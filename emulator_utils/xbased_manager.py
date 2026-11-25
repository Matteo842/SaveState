# emulator_utils/xbased_manager.py
# -*- coding: utf-8 -*-
r"""
xbased profile discovery (original Xbox emulator by crazyriddler).
https://github.com/crazyriddler/xbased

Unlike xemu, xbased keeps the Xbox hard disk as plain folders, so saves are
normal files and the standard folder backup/restore works on them.

Save layout (from xbased native/app/ui/dash_memory.c):
    <hdd>/Partition1/UDATA/<TITLE ID>/              one folder per game (E:\UDATA)
    <hdd>/Partition1/UDATA/<TITLE ID>/TitleMeta.xbx  game name (UTF-16LE "TitleName=...")
    <hdd>/Partition1/UDATA/<TITLE ID>/<save>/       one folder per save

Where <hdd> is (from native/app/ui/config.c and native/app/win_main.c):
    - the 'hdd=' line in xbased.ini, if set
    - otherwise '<data dir>/hdd'

And <data dir> is:
    - Windows: the folder of xbased.exe (portable, the default),
      or %APPDATA%\xbased\ when that folder cannot be written
    - Linux:   ~/.local/share/xbased/ (or the executable's folder when a
      'portable.txt' file is next to it)

xbased signs saves with the hard disk key of its EEPROM (<hdd>/eeprom.bin).
Every new install gets the same default key, so a save restored into another
xbased install is accepted by the game.
"""

import os
import re
import logging
import platform

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Name used by xbased with SDL_GetPrefPath("", "xbased")
XBASED_APP_NAME = "xbased"
XBASED_INI_NAME = "xbased.ini"

# Xbox Title IDs are 8 hex digits (e.g. 4D530004)
TITLE_ID_PATTERN = re.compile(r'^[0-9A-Fa-f]{8}$')


def _get_default_data_dir() -> str | None:
    """Returns the data folder xbased uses when it is not portable."""
    system = platform.system()
    if system == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            return os.path.join(appdata, XBASED_APP_NAME)
        return None
    if system == "Linux":
        data_home = os.getenv('XDG_DATA_HOME') or os.path.join(os.path.expanduser("~"), ".local", "share")
        return os.path.join(data_home, XBASED_APP_NAME)
    if system == "Darwin":
        # xbased has no macOS build today; this is the SDL default, kept for completeness
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", XBASED_APP_NAME)
    return None


def _get_candidate_data_dirs(executable_path: str | None) -> list[str]:
    """Data folders to check: the executable's folder first (portable), then the default one."""
    candidates = []

    if executable_path:
        if os.path.isfile(executable_path):
            candidates.append(os.path.dirname(executable_path))
        elif os.path.isdir(executable_path):
            candidates.append(executable_path)

    default_dir = _get_default_data_dir()
    if default_dir:
        candidates.append(default_dir)

    # Remove duplicates, keep order
    unique = []
    seen = set()
    for folder in candidates:
        key = os.path.normcase(os.path.normpath(folder))
        if key not in seen:
            seen.add(key)
            unique.append(folder)
    return unique


def _read_hdd_option(ini_path: str) -> str | None:
    """
    Reads the 'hdd' option from an xbased.ini file.

    The file has one option per line ('key=value'), '#' starts a comment,
    and the last line with the same key wins.
    """
    hdd_value = None
    try:
        with open(ini_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                if key.strip() == 'hdd':
                    hdd_value = value.strip() or None
    except OSError as e:
        log.debug(f"xbased: could not read {ini_path}: {e}")
        return None
    return hdd_value


def get_xbased_hdd_path(data_dir: str) -> str:
    """Returns the hard disk folder of an xbased data folder ('hdd=' in xbased.ini, else '<data dir>/hdd')."""
    ini_path = os.getenv('XBASED_CONFIG') or os.path.join(data_dir, XBASED_INI_NAME)
    hdd_value = _read_hdd_option(ini_path) if os.path.isfile(ini_path) else None

    if hdd_value:
        if not os.path.isabs(hdd_value):
            hdd_value = os.path.join(data_dir, hdd_value)
        log.debug(f"xbased: custom hdd folder from {ini_path}: {hdd_value}")
        return os.path.normpath(hdd_value)

    return os.path.join(data_dir, "hdd")


def get_xbased_udata_path(executable_path: str | None = None) -> str | None:
    """
    Returns the folder with the game saves (<hdd>/Partition1/UDATA).

    Args:
        executable_path: path of xbased.exe (or its folder). Optional.

    Returns:
        The UDATA folder, or None if not found.
    """
    for data_dir in _get_candidate_data_dirs(executable_path):
        hdd_path = get_xbased_hdd_path(data_dir)
        udata_path = os.path.join(hdd_path, "Partition1", "UDATA")
        if os.path.isdir(udata_path):
            log.info(f"Found xbased save folder: {udata_path}")
            return udata_path
        log.debug(f"xbased: no save folder at {udata_path}")

    log.warning("xbased save folder (hdd/Partition1/UDATA) not found.")
    return None


def read_title_name(title_dir: str) -> str | None:
    """Reads 'TitleName' from TitleMeta.xbx (UTF-16LE 'Key=Value' lines) in a game's save folder."""
    meta_path = os.path.join(title_dir, "TitleMeta.xbx")
    try:
        with open(meta_path, 'rb') as f:
            data = f.read(64 * 1024)
    except OSError:
        return None

    try:
        text = data.decode('utf-16-le', errors='ignore').lstrip('\ufeff')
    except Exception:
        return None

    for line in text.splitlines():
        if line.startswith('TitleName='):
            name = line[len('TitleName='):].strip().strip('\x00').strip()
            return name or None
    return None


def _get_known_title_name(title_id: str) -> str | None:
    """Looks up the game name in the Xbox title database used for xemu, if available."""
    try:
        from .xemu_manager import _display_name
    except ImportError:
        try:
            from xemu_manager import _display_name  # type: ignore
        except ImportError:
            return None

    try:
        name = _display_name(title_id)
    except Exception as e:
        log.debug(f"xbased: title lookup failed for {title_id}: {e}")
        return None

    # The lookup returns 'Unknown (...)' when the Title ID is not in the database
    if not name or name.startswith("Unknown ("):
        return None
    return name


def find_xbased_profiles(executable_path: str | None = None) -> list[dict]:
    """
    Finds the games with saves in xbased.

    Args:
        executable_path: path of xbased.exe (or its folder). Optional.

    Returns:
        List of profile dicts: [{'id': TITLE_ID, 'name': GameName, 'paths': [title_dir]}, ...]
    """
    log.info("Attempting to find xbased profiles...")
    udata_path = get_xbased_udata_path(executable_path)
    if not udata_path:
        return []

    try:
        entries = sorted(os.listdir(udata_path))
    except OSError as e:
        log.error(f"xbased: cannot list {udata_path}: {e}")
        return []

    profiles = []
    for entry in entries:
        title_dir = os.path.join(udata_path, entry)
        if not TITLE_ID_PATTERN.match(entry) or not os.path.isdir(title_dir):
            continue

        title_id = entry.upper()
        game_name = (read_title_name(title_dir)
                     or _get_known_title_name(title_id)
                     or f"Unknown ({title_id})")

        profiles.append({
            'id': title_id,
            'name': game_name,
            'paths': [title_dir],
        })
        log.debug(f"xbased: found {title_id} '{game_name}' at {title_dir}")

    profiles.sort(key=lambda p: p.get('name', '').lower())
    log.info(f"Found {len(profiles)} xbased profiles in {udata_path}")
    return profiles


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
    exe = sys.argv[1] if len(sys.argv) > 1 else None
    found = find_xbased_profiles(exe)
    print(f"\nFound {len(found)} xbased profile(s):")
    for p in found:
        print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
