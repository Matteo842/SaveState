# emulator_utils/xenia_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

_title_map: dict = {}
try:
    map_file = os.path.join(os.path.dirname(__file__), 'xenia_title_map.json')
    with open(map_file, 'r', encoding='utf-8') as mf:
        _title_map = json.load(mf)
except Exception as e:
    log.debug(f"Could not load Xenia title map: {e}")

def get_xenia_content_path(executable_path: str | None = None) -> str | None:
    """
    Determines the Xenia content directory for savedata.
    Checks portable mode (content/ folder alongside exe when portable.txt exists),
    then standard OS-specific locations.
    """
    # Portable check: look for content folder alongside exe
    if executable_path:
        exe_dir = None
        if os.path.isfile(executable_path):
            exe_dir = os.path.dirname(executable_path)
        elif os.path.isdir(executable_path):
            exe_dir = executable_path
        if exe_dir:
            # Check for content folder alongside executable (portable installation)
            content_dir = os.path.join(exe_dir, "content")
            if os.path.isdir(content_dir):
                log.debug(f"Using executable-relative Xenia content directory: {content_dir}")
                return content_dir

    # Standard locations
    system = platform.system()
    user_home = os.path.expanduser("~")
    if system == "Windows":
        appdata = os.getenv("APPDATA")
        if appdata:
            content_dir = os.path.join(appdata, "Xenia", "content")
            if os.path.isdir(content_dir):
                log.debug(f"Using Windows AppData Xenia content directory: {content_dir}")
                return content_dir
    elif system in ("Linux", "Darwin"):
        xdg = os.getenv("XDG_CONFIG_HOME", os.path.join(user_home, ".config"))
        content_dir = os.path.join(xdg, "xenia", "content")
        if os.path.isdir(content_dir):
            log.debug(f"Using XDG config Xenia content directory: {content_dir}")
            return content_dir

    log.warning("Could not determine Xenia content directory.")
    return None


def find_xenia_profiles(executable_path: str | None = None) -> list[dict]:
    """
    Finds Xenia savedata profiles by scanning the content directory.
    Returns a list of dicts: {'id': ..., 'name': ..., 'paths': [...]}.
    """
    content_dir = get_xenia_content_path(executable_path)
    if not content_dir:
        log.error("Cannot find Xenia save profiles: content directory unknown.")
        return []

    profiles: list[dict] = []
    try:
        for pkg in os.listdir(content_dir):
            # Skip default/global content package to avoid duplicate entries
            if pkg == '0000000000000000':
                continue
            pkg_dir = os.path.join(content_dir, pkg)
            if not os.path.isdir(pkg_dir):
                continue
            for game_id in os.listdir(pkg_dir):
                game_dir = os.path.join(pkg_dir, game_id)
                if not os.path.isdir(game_dir):
                    continue
                for slot in os.listdir(game_dir):
                    # Skip metadata directories (e.g., headers, marketplace)
                    if slot.lower() in ('headers', 'marketplace'):
                        continue
                    slot_dir = os.path.join(game_dir, slot)
                    if not os.path.isdir(slot_dir):
                        continue
                    subdirs = [d for d in os.listdir(slot_dir) if os.path.isdir(os.path.join(slot_dir, d))]
                    if subdirs:
                        for sub in subdirs:
                            # Exclude headers, marketplace, and pkg folder
                            if sub.lower() in ('headers','marketplace') or sub == pkg:
                                continue
                            profile_dir = os.path.join(slot_dir, sub)
                            profiles.append({
                                'id': f"{game_id}_{slot}_{sub}",
                                'name': _title_map.get(game_id, game_id),
                                'paths': [profile_dir]
                            })
                    else:
                        # Direct slot directory as profile
                        profiles.append({
                            'id': f"{game_id}_{slot}",
                            'name': _title_map.get(game_id, game_id),
                            'paths': [slot_dir]
                        })
    except Exception as e:
        log.error(f"Error scanning Xenia content directory '{content_dir}': {e}", exc_info=True)
        return []

    log.info(f"Found {len(profiles)} Xenia profiles.")
    return profiles

# Example usage (optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print(find_xenia_profiles())
