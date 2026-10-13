# emulator_utils/kytyps5_manager.py
# -*- coding: utf-8 -*-

import os
import re
import sys
import logging

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# KytyPS5 is portable-only: saves are written to a "_SaveData" folder relative to the
# working directory, which the launcher sets to the folder containing kyty_emulator(.exe).
# Layout (from KytyPS5 src/libs/libSaveData.cpp):
#   _SaveData/<TITLE_ID>/<dir_name>/sce_sys/param.bin
#   _SaveData/<TITLE_ID>/sce_sdmemory/<user_id>/param.bin + memory.dat
SAVE_DATA_DIR = "_SaveData"

# param.bin is a raw SaveDataParam struct (not a PARAM.SFO):
# title[128], sub_title[128], detail[1024], user_param, pad, mtime, reserved[32]
PARAM_BIN_SIZE = 1328
PARAM_TITLE_SIZE = 128

# PS5 (PPSA01234) and PS4 (CUSA01234) style title IDs
TITLE_ID_PATTERN = re.compile(r'^[A-Z]{4}\d{5}$')


def get_kytyps5_savedata_path(executable_path: str | None = None) -> str | None:
    """
    Returns the KytyPS5 _SaveData directory.

    The launcher looks for kyty_emulator next to itself or one folder up,
    and runs it with the working directory set to the emulator's folder.
    So we check the given folder first, then its parent.
    """
    if not executable_path:
        log.info("KytyPS5 path not provided. Cannot locate _SaveData (portable-only emulator).")
        return None

    if os.path.isfile(executable_path):
        base_dir = os.path.dirname(executable_path)
    elif os.path.isdir(executable_path):
        base_dir = executable_path
    else:
        log.warning(f"KytyPS5 path is neither a file nor a directory: {executable_path}")
        return None

    for candidate_dir in (base_dir, os.path.dirname(base_dir)):
        savedata_path = os.path.join(candidate_dir, SAVE_DATA_DIR)
        if os.path.isdir(savedata_path):
            log.info(f"Found KytyPS5 save directory: {savedata_path}")
            return savedata_path

    log.warning(f"KytyPS5 '{SAVE_DATA_DIR}' folder not found in '{base_dir}' or its parent.")
    return None


def read_param_bin_title(param_path: str) -> str | None:
    """Reads the save title (first 128 bytes, UTF-8, null-terminated) from a KytyPS5 param.bin."""
    try:
        with open(param_path, 'rb') as f:
            data = f.read(PARAM_BIN_SIZE + 1)
    except OSError as e:
        log.debug(f"Could not read {param_path}: {e}")
        return None

    if len(data) != PARAM_BIN_SIZE:
        log.debug(f"Unexpected param.bin size ({len(data)} bytes) at {param_path}")
        return None

    title = data[:PARAM_TITLE_SIZE].split(b'\x00', 1)[0].decode('utf-8', errors='ignore').strip()
    return title or None


def get_game_title(title_dir: str) -> str | None:
    """Looks through a game's save folders and returns the first save title found."""
    try:
        entries = sorted(os.listdir(title_dir))
    except OSError as e:
        log.debug(f"Could not list {title_dir}: {e}")
        return None

    for entry in entries:
        entry_path = os.path.join(title_dir, entry)
        if not os.path.isdir(entry_path):
            continue

        # Regular save: <dir_name>/sce_sys/param.bin
        param_paths = [os.path.join(entry_path, "sce_sys", "param.bin")]

        # Memory save: sce_sdmemory/<user_id>/param.bin
        if entry.startswith("sce_sdmemory"):
            try:
                for user_id in sorted(os.listdir(entry_path)):
                    param_paths.append(os.path.join(entry_path, user_id, "param.bin"))
            except OSError as e:
                log.debug(f"Could not list {entry_path}: {e}")

        for param_path in param_paths:
            if os.path.isfile(param_path):
                title = read_param_bin_title(param_path)
                if title:
                    return title

    return None


def find_kytyps5_profiles(executable_path: str | None = None) -> list[dict]:
    """
    Finds KytyPS5 game save profiles.

    One profile per game: the whole _SaveData/<TITLE_ID> folder is backed up,
    so every save slot and memory save of that game is included.

    Returns:
        List of profile dicts: [{'id': TITLE_ID, 'name': GameName, 'paths': [title_dir]}, ...]
    """
    log.info("Attempting to find KytyPS5 profiles...")
    savedata_dir = get_kytyps5_savedata_path(executable_path)
    if not savedata_dir:
        return []

    profiles = []
    try:
        for title_id in sorted(os.listdir(savedata_dir)):
            title_dir = os.path.join(savedata_dir, title_id)
            if not os.path.isdir(title_dir):
                continue

            # Skips "UNKNOWN" (game without a TITLE_ID) and anything else that is not a title ID
            if not TITLE_ID_PATTERN.match(title_id):
                log.debug(f"Skipping non-standard folder in {SAVE_DATA_DIR}: {title_id}")
                continue

            game_title = get_game_title(title_dir)
            if not game_title:
                log.debug(f"No save title found for {title_id}. Using the title ID as name.")
                game_title = title_id

            profiles.append({
                'id': title_id,
                'name': game_title,
                'paths': [title_dir]
            })
            log.debug(f"Added KytyPS5 profile: ID='{title_id}', Name='{game_title}', Path='{title_dir}'")

    except OSError as e:
        log.error(f"Error scanning KytyPS5 save directory '{savedata_dir}': {e}")
        return []

    log.info(f"Found {len(profiles)} KytyPS5 profiles.")
    profiles.sort(key=lambda p: p.get('name', '').lower())
    return profiles


# Example Usage (Optional): python -m emulator_utils.kytyps5_manager "D:\path\to\KytyPS5"
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_path = sys.argv[1] if len(sys.argv) > 1 else None
    found_profiles = find_kytyps5_profiles(test_path)
    if found_profiles:
        print(f"Found {len(found_profiles)} KytyPS5 Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print("No KytyPS5 profiles found.")
