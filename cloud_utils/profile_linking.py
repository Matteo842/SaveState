"""Bind a downloaded backup folder to a device-local save path."""

import os
import json
import zipfile

from core.core_logic import get_backup_folder_name, is_group_profile


class ProfileLinkError(ValueError):
    """The requested binding would be invalid or hide existing backups."""


def valid_backup_folder_name(folder_name):
    return (
        isinstance(folder_name, str)
        and bool(folder_name)
        and folder_name not in ('.', '..')
        and os.path.basename(folder_name) == folder_name
        and '/' not in folder_name
        and '\\' not in folder_name
        and ':' not in folder_name
    )


def latest_backup_manifest(backup_folder):
    """Read only the small manifest from the latest named backup ZIP.

    SaveState names backups with a sortable timestamp. Reading a ZIP's central
    directory and manifest does not decompress the save payload.
    """
    try:
        with os.scandir(backup_folder) as entries:
            archives = [
                entry.path for entry in entries
                if entry.is_file(follow_symlinks=False)
                and entry.name.lower().endswith('.zip')
            ]
        if not archives:
            return None
        archive = max(archives, key=lambda path: os.path.basename(path))
        with zipfile.ZipFile(archive) as zipf:
            info = zipf.getinfo('savestate/manifest.json')
            if info.file_size > 65536:
                return None
            with zipf.open(info) as source:
                manifest = json.loads(source.read(65537))
        if not isinstance(manifest, dict):
            return None
        paths = manifest.get('paths')
        if isinstance(paths, list) and len(paths) > 64:
            return None
        return manifest
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError):
        return None


def prepare_profile_link(
    profiles, backup_base_dir, folder_name, profile_name, save_path=None, *, create_new=False
):
    """Return an updated profile mapping without changing the input mapping.

    For an existing profile its configured save path is retained unless a new
    one is supplied. Its backup folder can only change when the old folder is empty.
    """
    if not valid_backup_folder_name(folder_name):
        raise ProfileLinkError("The selected backup folder has an invalid name.")
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ProfileLinkError("Enter a profile name.")
    profile_name = profile_name.strip()
    if create_new and any(name.casefold() == profile_name.casefold() for name in profiles):
        raise ProfileLinkError("A profile with this name already exists. Select it from the list instead.")

    backup_folder = os.path.join(backup_base_dir, folder_name)
    backup_root_real = os.path.normcase(os.path.realpath(backup_base_dir))
    backup_folder_real = os.path.normcase(os.path.realpath(backup_folder))
    if os.path.dirname(backup_folder_real) != backup_root_real:
        raise ProfileLinkError("The selected backup folder is outside the backup directory.")
    if not os.path.isdir(backup_folder) or not any(
        entry.lower().endswith('.zip') and os.path.isfile(os.path.join(backup_folder, entry))
        for entry in os.listdir(backup_folder)
    ):
        raise ProfileLinkError("Download a backup for this game before linking it.")

    for other_name, other_data in profiles.items():
        if other_name == profile_name or is_group_profile(other_data):
            continue
        if get_backup_folder_name(other_name, other_data).casefold() == folder_name.casefold():
            raise ProfileLinkError(f"This backup folder is already linked to '{other_name}'.")

    updated = dict(profiles)
    if profile_name in profiles:
        old_data = profiles[profile_name]
        if not isinstance(old_data, dict) or is_group_profile(old_data):
            raise ProfileLinkError("A group cannot be linked to one backup folder.")
        old_folder = get_backup_folder_name(profile_name, old_data)
        if old_folder != folder_name:
            old_folder_path = os.path.join(backup_base_dir, old_folder)
            if os.path.isdir(old_folder_path) and os.listdir(old_folder_path):
                raise ProfileLinkError(
                    f"'{profile_name}' already has backups in '{old_folder}'. "
                    "Move or merge those backups before linking this folder. Nothing was changed."
                )
        new_data = dict(old_data)
        if save_path is not None:
            normalized = _normalize_save_paths(save_path, backup_base_dir)
            if isinstance(normalized, list):
                new_data['paths'] = normalized
                new_data.pop('path', None)
            else:
                new_data['path'] = normalized
                new_data.pop('paths', None)
        configured_paths = new_data.get('paths') or new_data.get('path')
        if isinstance(configured_paths, list):
            paths = configured_paths
        else:
            paths = [configured_paths]
        if not paths or any(not _valid_save_path(path, backup_base_dir) for path in paths):
            raise ProfileLinkError(
                "This profile has no valid local Save Path. Edit its path before linking."
            )
    else:
        if any(name.casefold() == profile_name.casefold() for name in profiles):
            raise ProfileLinkError("A profile with this name already exists.")
        normalized = _normalize_save_paths(save_path, backup_base_dir)
        new_data = {'paths': normalized} if isinstance(normalized, list) else {'path': normalized}

    new_data['backup_folder_name'] = folder_name
    updated[profile_name] = new_data
    return updated


def _normalize_save_paths(save_path, backup_base_dir):
    paths = save_path if isinstance(save_path, list) else [save_path]
    if not paths or any(not _valid_save_path(path, backup_base_dir) for path in paths):
        raise ProfileLinkError(
            "Choose existing local save files or folders outside the backup directory."
        )
    normalized = [os.path.normpath(path.strip()) for path in paths]
    return normalized if isinstance(save_path, list) else normalized[0]


def profile_has_local_save_paths(profile_data, backup_base_dir):
    if not isinstance(profile_data, dict) or is_group_profile(profile_data):
        return False
    paths = profile_data.get('paths') or [profile_data.get('path')]
    return isinstance(paths, list) and bool(paths) and all(
        _valid_save_path(path, backup_base_dir) for path in paths
    )


def profile_matches_manifest_shape(profile_data, manifest):
    """Check whether restore destinations match the archive's path count and layout."""
    if not isinstance(profile_data, dict):
        return False
    if not isinstance(manifest, dict) or not isinstance(manifest.get('paths'), list):
        return True  # An already configured profile is authoritative for legacy ZIPs.
    source_paths = manifest['paths']
    if not source_paths:
        return True  # Specialized backup formats do not use generic path mapping.
    local_multi = bool(profile_data.get('paths'))
    local_paths = profile_data.get('paths') if local_multi else [profile_data.get('path')]
    archive_multi = bool(manifest.get('multiple_paths')) or len(source_paths) > 1
    return len(local_paths) == len(source_paths) and local_multi == archive_multi


def _valid_save_path(path, backup_base_dir):
    if not isinstance(path, str) or not path.strip():
        return False
    path = path.strip()
    if not (os.path.isfile(path) or os.path.isdir(path)):
        return False
    target = os.path.normcase(os.path.realpath(path))
    backup_root = os.path.normcase(os.path.realpath(backup_base_dir))
    if os.path.dirname(target) == target:
        return False
    try:
        common = os.path.commonpath((target, backup_root))
        if common == backup_root or common == target:
            return False
    except ValueError:
        pass  # Different drives cannot contain one another.
    return True
