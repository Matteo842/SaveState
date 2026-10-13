# emulator_utils/kytyps5_manager.py
# -*- coding: utf-8 -*-

import os
import re
import sys
import json
import logging
import platform

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

# The save title is chosen by the game and is often not the game name
# (e.g. 'GoW_SoS_Save_Data_999'). This strips a trailing 'Save Data 999' / 'Save 01' / 'Slot 2'.
SAVE_SUFFIX_PATTERN = re.compile(r'[\s\-:#]*\b(save\s*data|savedata|save|slot)[\s\-:#]*\d*$', re.IGNORECASE)

# Safety limit when searching the launcher's game folders for installed games
MAX_GAME_SCAN_DEPTH = 6


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


def clean_save_title(title: str) -> str | None:
    """'GoW_SoS_Save_Data_999' -> 'GoW SoS'. Returns None if nothing is left."""
    cleaned = ' '.join(title.replace('_', ' ').split())
    cleaned = SAVE_SUFFIX_PATTERN.sub('', cleaned).strip()
    return cleaned or None


def get_kyty_ini_path(install_dir: str) -> str | None:
    """
    Returns the KytyPS5 launcher settings file (Kyty.ini).

    The launcher uses Kyty.ini next to itself if it exists, otherwise
    %PROGRAMDATA%/Kyty/Kyty.ini on Windows and ~/.config/Kyty/Kyty.ini on Linux.
    """
    candidates = [os.path.join(install_dir, "Kyty.ini")]
    if platform.system() == "Windows":
        programdata = os.getenv('PROGRAMDATA')
        if programdata:
            candidates.append(os.path.join(programdata, "Kyty", "Kyty.ini"))
    else:
        config_home = os.getenv('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser("~"), ".config")
        candidates.append(os.path.join(config_home, "Kyty", "Kyty.ini"))

    for ini_path in candidates:
        if os.path.isfile(ini_path):
            log.debug(f"Found KytyPS5 settings file: {ini_path}")
            return ini_path
    return None


def _parse_qt_ini_list(value: str) -> list[str]:
    """Splits a Qt INI string list ('a, "b,c", d') into items, undoing Qt's escaping."""
    items = []
    current = ''
    in_quotes = False
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == '\\' and i + 1 < len(value):
            i += 1
            next_ch = value[i]
            if next_ch == 'x':
                hex_digits = re.match(r'[0-9a-fA-F]{1,4}', value[i + 1:])
                if hex_digits:
                    current += chr(int(hex_digits.group(), 16))
                    i += len(hex_digits.group())
            else:
                current += {'n': '\n', 't': '\t', 'r': '\r', '0': '\0'}.get(next_ch, next_ch)
        elif ch == ',' and not in_quotes:
            items.append(current.strip())
            current = ''
        else:
            current += ch
        i += 1
    items.append(current.strip())
    return [item for item in items if item]


def read_kyty_game_dirs(ini_path: str) -> list[str]:
    """Reads the game folders configured in the KytyPS5 launcher ([Launcher] game_dirs)."""
    section = None
    values = {}
    try:
        with open(ini_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    section = line[1:-1]
                elif section == 'Launcher' and '=' in line:
                    key, value = line.split('=', 1)
                    values[key.strip()] = value.strip()
    except OSError as e:
        log.debug(f"Could not read {ini_path}: {e}")
        return []

    # 'game_dir' is the older single-folder setting
    raw_value = values.get('game_dirs') or values.get('game_dir') or ''
    return [os.path.normpath(d) for d in _parse_qt_ini_list(raw_value)]


def read_param_json_title(param_json_path: str) -> tuple[str | None, str | None]:
    """
    Reads (titleId, titleName) from a PS5 game's sce_sys/param.json.
    Language order is the same as the KytyPS5 launcher: default language, en-US, then any.
    """
    try:
        with open(param_json_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log.debug(f"Could not read {param_json_path}: {e}")
        return None, None
    if not isinstance(data, dict):
        return None, None

    title_id = str(data.get('titleId', '')).strip() or None
    localized = data.get('localizedParameters')
    if not isinstance(localized, dict):
        return title_id, None

    def title_for(language):
        entry = localized.get(language)
        return str(entry.get('titleName', '')).strip() if isinstance(entry, dict) else ''

    title_name = title_for(localized.get('defaultLanguage', '')) or title_for('en-US')
    if not title_name:
        for language in localized:
            title_name = title_for(language)
            if title_name:
                break
    return title_id, title_name or None


def find_installed_game_titles(game_dirs: list[str], wanted_ids: list[str]) -> dict[str, str]:
    """
    Maps TITLE_ID -> game name for installed games, reading sce_sys/param.json of each
    game folder (a folder with eboot.bin) inside the launcher's game folders.
    .zar archives are not read: those games fall back to the save title.
    """
    titles = {}
    wanted = set(wanted_ids)
    for game_dir in game_dirs:
        if not os.path.isdir(game_dir):
            continue
        base_depth = game_dir.rstrip(os.sep).count(os.sep)
        for root, dirnames, filenames in os.walk(game_dir):
            if any(name.lower() == 'eboot.bin' for name in filenames):
                dirnames[:] = []  # game folder found: no need to go deeper
                title_id, title_name = read_param_json_title(os.path.join(root, "sce_sys", "param.json"))
                if title_id in wanted and title_name and title_id not in titles:
                    titles[title_id] = title_name
                    log.debug(f"KytyPS5 installed game: {title_id} = '{title_name}' ({root})")
                    if wanted.issubset(titles):
                        return titles
            elif root.count(os.sep) - base_depth >= MAX_GAME_SCAN_DEPTH:
                dirnames[:] = []
    return titles


def get_save_title(title_dir: str) -> str | None:
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

    title_ids = []
    try:
        for title_id in sorted(os.listdir(savedata_dir)):
            if not os.path.isdir(os.path.join(savedata_dir, title_id)):
                continue

            # Skips "UNKNOWN" (game without a TITLE_ID) and anything else that is not a title ID
            if not TITLE_ID_PATTERN.match(title_id):
                log.debug(f"Skipping non-standard folder in {SAVE_DATA_DIR}: {title_id}")
                continue
            title_ids.append(title_id)
    except OSError as e:
        log.error(f"Error scanning KytyPS5 save directory '{savedata_dir}': {e}")
        return []

    # Real game names come from the games installed in the launcher's game folders
    installed_titles = {}
    ini_path = get_kyty_ini_path(os.path.dirname(savedata_dir)) if title_ids else None
    if ini_path:
        installed_titles = find_installed_game_titles(read_kyty_game_dirs(ini_path), title_ids)

    profiles = []
    for title_id in title_ids:
        title_dir = os.path.join(savedata_dir, title_id)

        # Name order: installed game name, cleaned save title, title ID
        game_title = installed_titles.get(title_id)
        if not game_title:
            save_title = get_save_title(title_dir)
            game_title = clean_save_title(save_title) if save_title else None
        if not game_title:
            log.debug(f"No game name found for {title_id}. Using the title ID as name.")
            game_title = title_id

        profiles.append({
            'id': title_id,
            'name': game_title,
            'paths': [title_dir]
        })
        log.debug(f"Added KytyPS5 profile: ID='{title_id}', Name='{game_title}', Path='{title_dir}'")

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
