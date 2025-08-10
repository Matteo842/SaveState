# emulator_utils/snes9x_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import glob
import re
import platform

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler()) # Avoid 'No handler found' warnings

def _get_snes9x_save_dirs(executable_path: str | None = None) -> list[str]:
    """
    Determines potential Snes9x save directories.
    Checks portable (near executable), Linux, and macOS standard locations.
    """
    potential_dirs = []
    user_home = os.path.expanduser("~")
    system = platform.system()

    # 1. Portable check
    actual_emulator_dir = None
    if executable_path:
        if os.path.isfile(executable_path):
            actual_emulator_dir = os.path.dirname(executable_path)
            log.debug(f"executable_path ('{executable_path}') is a file, using parent dir: {actual_emulator_dir} for portable check.")
        elif os.path.isdir(executable_path):
            actual_emulator_dir = executable_path # Assume it's the emulator's root directory
            log.debug(f"executable_path ('{executable_path}') is a directory, using it directly for portable check.")
        else:
            log.debug(f"executable_path ('{executable_path}') is neither a file nor a directory, skipping portable check based on it.")
    
    if actual_emulator_dir:
        for portable_subdir_name in ["Saves", "saves"]:
            portable_path = os.path.join(actual_emulator_dir, portable_subdir_name)
            if os.path.isdir(portable_path):
                log.debug(f"Found potential Snes9x portable save directory: {portable_path}")
                if portable_path not in potential_dirs:
                    potential_dirs.append(portable_path)
    else:
        log.debug("No valid executable_path provided or determined for portable check.")

    # 2. Standard OS-specific paths
    if system == "Linux":
        linux_paths = [
            os.path.join(user_home, ".local", "share", "snes9x", "Saves"),
            os.path.join(user_home, ".local", "share", "snes9x", "saves"),
            os.path.join(user_home, ".config", "snes9x", "Saves"),
            os.path.join(user_home, ".config", "snes9x", "saves"),
            os.path.join(user_home, ".var", "app", "com.snes9x.Snes9x", "data", "snes9x", "Saves"),
            os.path.join(user_home, ".var", "app", "com.snes9x.Snes9x", "data", "snes9x", "saves"),
        ]
        for path in linux_paths:
            if os.path.isdir(path):
                log.debug(f"Found potential Snes9x Linux save directory: {path}")
                if path not in potential_dirs:
                    potential_dirs.append(path)
    elif system == "Darwin": # macOS
        macos_paths = [
            os.path.join(user_home, "Library", "Application Support", "Snes9x", "Saves"),
            os.path.join(user_home, "Library", "Application Support", "Snes9x", "saves"),
            # Meno comune, ma possibile
            os.path.join(user_home, ".config", "snes9x", "Saves"),
            os.path.join(user_home, ".config", "snes9x", "saves"),
        ]
        for path in macos_paths:
            if os.path.isdir(path):
                log.debug(f"Found potential Snes9x macOS save directory: {path}")
                if path not in potential_dirs:
                    potential_dirs.append(path)
    elif system == "Windows":
        # Per Windows, abbiamo già controllato il percorso portatile
        # Controlliamo anche in AppData come fallback
        appdata_path = os.getenv("APPDATA")
        if appdata_path:
            win_paths = [
                os.path.join(appdata_path, "Snes9x", "Saves"),
                os.path.join(appdata_path, "Snes9x", "saves"),
            ]
            for path in win_paths:
                if os.path.isdir(path):
                    log.debug(f"Found potential Snes9x Windows AppData save directory: {path}")
                    if path not in potential_dirs:
                        potential_dirs.append(path)

    if not potential_dirs:
        log.warning("Could not find any potential Snes9x save directories (portable or standard).")
    return potential_dirs

def find_snes9x_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Finds Snes9x save files (.srm) by checking various locations.
    Locations include portable (near executable) and standard OS paths.

    Args:
        executable_path: Optional. The full path to the Snes9x executable.
                         If provided, portable paths are checked.

    Returns:
        List of profile dicts: [{'id': 'save_name', 'name': 'save_name', 'paths': [full_path]}, ...]
    """
    profiles: list[dict] = []
    log.info(f"Attempting to find Snes9x profiles... Executable path: {executable_path if executable_path else 'Not provided'}")

    save_dirs_to_check = _get_snes9x_save_dirs(executable_path)

    if not save_dirs_to_check:
        log.warning("No Snes9x save directories found to scan. Signalling for user prompt.")
        return None

    all_found_files = {} # Per gestire duplicati da più percorsi che puntano allo stesso file

    for saves_dir in save_dirs_to_check:
        log.info(f"Searching for .srm files in: {saves_dir}")
        try:
            # Look for .srm files (standard SRAM saves)
            search_pattern = os.path.join(saves_dir, "*.srm")
            save_files = glob.glob(search_pattern)

            log.debug(f"Found {len(save_files)} .srm files in {saves_dir}")

            for file_path in save_files:
                if os.path.isfile(file_path):
                    # Risolve il percorso reale per evitare duplicati da symlink ecc.
                    real_file_path = os.path.realpath(file_path)
                    if real_file_path in all_found_files:
                        log.debug(f"Skipping duplicate file (already processed): {file_path}")
                        continue
                    all_found_files[real_file_path] = True

                    # Use the filename without extension as both ID and Name initially
                    base_name = os.path.splitext(os.path.basename(file_path))[0]
                    profile_id = base_name # Keep full name for ID

                    # Clean the name for display by removing trailing language codes like (En,Fr,De,...)
                    profile_name = re.sub(r'\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$', '', base_name).strip()
                    # If cleaning didn't change anything, use original
                    if not profile_name:
                        profile_name = base_name

                    profile = {
                        'id': profile_id,
                        'name': profile_name, # Use the cleaned name for display
                        'paths': [file_path] # IMPORTANT: List contains only the single .srm file path
                    }
                    profiles.append(profile)
                    log.debug(f"  Added Snes9x profile: ID='{profile_id}', Name='{profile_name}', Path='{file_path}'")

        except OSError as e:
            log.error(f"Error accessing Snes9x saves directory '{saves_dir}': {e}")
        except Exception as e:
            log.error(f"Unexpected error finding Snes9x profiles in '{saves_dir}': {e}", exc_info=True)

    if profiles:
        log.info(f"Found {len(profiles)} unique Snes9x profiles (.srm) across all checked directories.")
        profiles.sort(key=lambda p: p.get('name', '')) # Sort for consistent output
        return profiles
    else:
        log.info("No Snes9x profiles found. Signalling for user prompt.")
        return None

# Example Usage (Optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # Provide a dummy path for testing - replace with actual if needed
    # Example: dummy_exe = "D:\\Emulators\\Snes9x\\snes9x-x64.exe"
    # dummy_exe = "snes9x-dummy.exe" # Test without a valid exe (should use standard paths)
    dummy_exe = None # Test with no exe path

    # To test properly with a dummy exe:
    # 1. Create a directory for the dummy exe: temp_snes9x_portable/
    # 2. Put a dummy snes9x-dummy.exe in it.
    # 3. Create subdirectories: temp_snes9x_portable/Saves/ or temp_snes9x_portable/saves/
    # 4. Create dummy files: temp_snes9x_portable/Saves/MyGame.srm
    # 5. Set dummy_exe = "temp_snes9x_portable/snes9x-dummy.exe"

    # To test standard paths (e.g., Linux):
    # 1. Create: ~/.local/share/snes9x/Saves/ or ~/.config/snes9x/Saves/
    # 2. Put dummy .srm files there: ~/.local/share/snes9x/Saves/AnotherGame.srm
    # 3. Run with dummy_exe = None

    print(f"--- Testing Snes9x Profile Finder with exe: {dummy_exe if dummy_exe else 'None (standard paths only)'} ---")
    found_profiles = find_snes9x_profiles(dummy_exe)
    if found_profiles:
        print("Found Snes9x Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['paths'][0]}")
    else:
        print(f"No Snes9x profiles found (exe path: '{dummy_exe if dummy_exe else 'None'}').")

