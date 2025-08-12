# emulator_utils/gopher64_manager.py
# -*- coding: utf-8 -*-

import os
import platform
import logging

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


def get_gopher64_saves_path(executable_path: str | None = None) -> str | None:
    """
    Returns the standard saves directory for Gopher64.

    Notes:
    - On Windows, Gopher64 stores saves in %APPDATA%\gopher64\saves.
    - For Linux/macOS (best-effort), we guess ~/.config/gopher64/saves and
      ~/Library/Application Support/gopher64/saves respectively.
    - The executable_path hint is ignored because Gopher64 uses a fixed location.
    """
    current_os = platform.system()
    user_home = os.path.expanduser("~")

    try:
        if current_os == "Windows":
            appdata = os.getenv("APPDATA")
            if not appdata:
                log.error("APPDATA not found; cannot resolve Gopher64 saves path on Windows.")
                return None
            saves_dir = os.path.join(appdata, "gopher64", "saves")
            return saves_dir if os.path.isdir(saves_dir) else saves_dir  # Return even if missing; caller can handle

        if current_os == "Linux":
            saves_dir = os.path.join(user_home, ".config", "gopher64", "saves")
            return saves_dir if os.path.isdir(saves_dir) else saves_dir

        if current_os == "Darwin":
            saves_dir = os.path.join(user_home, "Library", "Application Support", "gopher64", "saves")
            return saves_dir if os.path.isdir(saves_dir) else saves_dir

        log.warning(f"Unsupported OS for Gopher64 path detection: {current_os}")
        return None
    except Exception as e:
        log.error(f"Unexpected error resolving Gopher64 saves path: {e}")
        return None


def _clean_gopher64_display_name(base_filename: str) -> str:
    """Cleans the display name by removing everything after the first dash ('-')."""
    try:
        if "-" in base_filename:
            return base_filename.split("-", 1)[0].strip()
        return base_filename.strip()
    except Exception:
        return base_filename


def find_gopher64_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Scans the fixed Gopher64 saves folder and returns one profile per save file.

    Returns a list of dicts like:
    { 'id': original_base_filename, 'name': cleaned_display_name, 'paths': [full_file_path] }

    If the standard folder cannot be determined, returns None to allow the UI
    to prompt the user (even though Gopher64 normally uses a fixed path).
    """
    saves_dir = get_gopher64_saves_path(executable_path)
    if not saves_dir:
        log.warning("Gopher64 saves directory could not be determined.")
        return None

    if not os.path.isdir(saves_dir):
        log.info(f"Gopher64 saves directory does not exist yet: {saves_dir}")
        # Return an empty list to indicate no profiles rather than None (path known but empty)
        return []

    profiles: list[dict] = []

    try:
        for entry in os.listdir(saves_dir):
            full_path = os.path.join(saves_dir, entry)
            if not os.path.isfile(full_path):
                continue

            base_name, _ext = os.path.splitext(entry)
            profile_id = base_name  # keep original (with trailing hash if present) to stay unique
            display_name = _clean_gopher64_display_name(base_name)

            profile = {
                "id": profile_id,
                "name": display_name if display_name else profile_id,
                "paths": [full_path],
            }
            profiles.append(profile)
            log.debug(f"Added Gopher64 profile: ID='{profile_id}', Name='{profile['name']}', Path='{full_path}'")

    except OSError as e:
        log.error(f"Error scanning Gopher64 saves directory '{saves_dir}': {e}")
        return []
    except Exception as e:
        log.error(f"Unexpected error while finding Gopher64 profiles: {e}")
        return []

    profiles.sort(key=lambda p: p.get("name", ""))
    log.info(f"Found {len(profiles)} Gopher64 profiles in '{saves_dir}'.")
    return profiles


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    found = find_gopher64_profiles()
    if found is None:
        print("Gopher64 saves path not found.")
    elif not found:
        print("No Gopher64 saves found.")
    else:
        for p in found:
            print(f"ID: {p['id']} | Name: {p['name']} | Path: {p['paths'][0]}")


