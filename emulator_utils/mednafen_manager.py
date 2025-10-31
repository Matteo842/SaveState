# emulator_utils/mednafen_manager.py
# -*- coding: utf-8 -*-

import os
import re
import logging
from typing import Optional, List, Dict
from utils import sanitize_profile_display_name

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


def _expand_and_normalize_path(raw_path: str, base_dir: Optional[str]) -> str:
    """Expand env vars and user, resolve relative to base_dir when not absolute."""
    try:
        expanded = os.path.expandvars(os.path.expanduser(raw_path.strip().strip('"').strip("'")))
        if not os.path.isabs(expanded) and base_dir:
            expanded = os.path.normpath(os.path.join(base_dir, expanded))
        return os.path.normpath(expanded)
    except Exception as e:
        log.warning(f"Failed to expand/normalize path '{raw_path}': {e}")
        return raw_path


def _parse_cfg_for_sav_dir(cfg_path: str, base_dir: Optional[str]) -> Optional[str]:
    """Parse mednafen.cfg (or similar) to extract filesys.path_sav directory."""
    if not os.path.isfile(cfg_path):
        return None
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(cfg_path, 'r', encoding='latin-1') as f:
                content = f.read()
        except Exception as e2:
            log.error(f"Unable to read config file '{cfg_path}': {e2}")
            return None
    except Exception as e:
        log.error(f"Unable to read config file '{cfg_path}': {e}")
        return None

    # Remove full-line comments starting with ';' or '#'
    lines: List[str] = []
    for line in content.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith(';') or stripped.startswith('#'):
            continue
        lines.append(line)

    pattern = re.compile(r"^\s*filesys\.path_sav\s+(.+?)\s*(?:[;#].*)?$", re.IGNORECASE)
    for line in lines:
        m = pattern.match(line)
        if m:
            raw_value = m.group(1)
            path_val = _expand_and_normalize_path(raw_value, base_dir)
            if os.path.isdir(path_val):
                log.info(f"mednafen.cfg: Using save directory from filesys.path_sav: {path_val}")
                return path_val
            else:
                log.warning(f"filesys.path_sav in config points to non-existent directory: {path_val}")
                # Still return the expanded value so caller can try fallback existence checks
                return path_val
    return None


def get_mednafen_saves_dir(custom_path: Optional[str] = None) -> Optional[str]:
    """Determine the Mednafen 'sav' directory.

    Resolution order:
    - If custom_path is a file, use its directory as base_dir.
    - If custom_path is a directory, use it directly as base_dir.
    - Parse mednafen.cfg (or mednafen-09x.cfg) for filesys.path_sav.
    - Fallback to base_dir / 'sav' if it exists.
    """
    base_dir: Optional[str] = None
    if custom_path:
        try:
            if os.path.isfile(custom_path):
                base_dir = os.path.dirname(custom_path)
            elif os.path.isdir(custom_path):
                base_dir = custom_path
        except Exception as e:
            log.warning(f"Error inspecting custom_path '{custom_path}': {e}")

    # Try configs in base_dir
    if base_dir:
        for cfg_name in ("mednafen.cfg", "mednafen-09x.cfg"):
            cfg_path = os.path.join(base_dir, cfg_name)
            sav_dir = _parse_cfg_for_sav_dir(cfg_path, base_dir)
            if sav_dir and os.path.isdir(sav_dir):
                return sav_dir
            # If value was parsed but not existing, keep checking fallback below

        # Fallback: base_dir/sav
        fallback = os.path.join(base_dir, "sav")
        if os.path.isdir(fallback):
            log.info(f"Using default 'sav' directory under base dir: {fallback}")
            return fallback

    # If we reach here, we couldn't determine a directory reliably
    log.warning("Mednafen save directory not found via provided path or default 'sav'.")
    return None


def find_mednafen_profiles(custom_path: Optional[str] = None) -> Optional[List[Dict[str, object]]]:
    """Find and group Mednafen saves in the 'sav' directory.

    Groups files by base filename (without extension) and returns one profile per game
    with a list of all related save files in 'paths'.
    """
    sav_dir = get_mednafen_saves_dir(custom_path)
    if not sav_dir:
        # Signal to caller that we couldn't auto-detect; UI can prompt for path
        return None

    try:
        entries = [f for f in os.listdir(sav_dir) if os.path.isfile(os.path.join(sav_dir, f))]
    except Exception as e:
        log.error(f"Unable to list Mednafen save directory '{sav_dir}': {e}")
        return None

    if not entries:
        log.info(f"No save files found in Mednafen directory: {sav_dir}")
        return []

    # Group by stem (filename without extension)
    grouped: Dict[str, List[str]] = {}
    for filename in entries:
        stem, _ext = os.path.splitext(filename)
        full_path = os.path.join(sav_dir, filename)
        grouped.setdefault(stem, []).append(full_path)

    profiles: List[Dict[str, object]] = []
    for stem, file_list in grouped.items():
        display_name = sanitize_profile_display_name(stem)
        profile_id = f"mednafen_{stem.lower()}"
        # Sort paths for deterministic order (use filename)
        file_list_sorted = sorted(file_list, key=lambda p: os.path.basename(p).lower())
        profiles.append({
            'id': profile_id,
            'name': display_name,
            'paths': file_list_sorted,
        })

    log.info(f"Mednafen profiles built: {len(profiles)} from directory '{sav_dir}'")
    return profiles


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    found = find_mednafen_profiles()
    if found is None:
        print("Mednafen saves dir not found automatically.")
    elif not found:
        print("No Mednafen saves detected.")
    else:
        print(f"Found {len(found)} Mednafen profiles:")
        for p in found:
            print(f"- {p['name']} ({len(p['paths'])} files)")


