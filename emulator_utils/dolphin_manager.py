# emulator_utils/dolphin_manager.py
# -*- coding: utf-8 -*-

import os
import platform
import logging
import re
import struct # Necessario per leggere dati binari
import codecs # Needed for Wii banner parsing

log = logging.getLogger(__name__)


def _normalize_path(path: str | None) -> str | None:
    """Expand environment/user variables and normalize a filesystem path."""
    if not path:
        return None
    value = str(path).strip().strip('"')
    if not value:
        return None
    return os.path.normpath(os.path.expandvars(os.path.expanduser(value)))


def _append_existing_dir(paths: list[str], candidate: str | None, source: str) -> None:
    """Add an existing directory to *paths* once, with useful logging."""
    normalized = _normalize_path(candidate)
    if not normalized:
        return

    if os.path.isdir(normalized):
        # normcase prevents duplicates on Windows with different path casing.
        existing = {os.path.normcase(os.path.abspath(p)) for p in paths}
        key = os.path.normcase(os.path.abspath(normalized))
        if key not in existing:
            log.info(f"Found Dolphin user directory ({source}): {normalized}")
            paths.append(normalized)
    else:
        log.debug(f"Dolphin user directory candidate does not exist ({source}): {normalized}")


def _get_windows_documents_dir() -> str:
    """Return the real Windows Documents known-folder path, including redirection."""
    fallback = os.path.join(os.path.expanduser("~"), "Documents")
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            documents, _ = winreg.QueryValueEx(key, "Personal")
        return _normalize_path(documents) or fallback
    except (OSError, ImportError, TypeError, ValueError) as exc:
        log.debug(f"Could not resolve redirected Windows Documents folder: {exc}")
        return fallback


def _get_windows_dolphin_registry_settings() -> tuple[str | None, bool]:
    """Read Dolphin's global-user-directory settings from HKCU on Windows."""
    user_config_path = None
    local_user_config = False

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Dolphin Emulator") as key:
            try:
                value, _ = winreg.QueryValueEx(key, "UserConfigPath")
                user_config_path = _normalize_path(value)
            except OSError:
                pass

            try:
                value, _ = winreg.QueryValueEx(key, "LocalUserConfig")
                local_user_config = str(value).strip().lower() in {"1", "true", "yes"}
            except OSError:
                pass
    except (OSError, ImportError) as exc:
        log.debug(f"Dolphin registry settings not available: {exc}")

    return user_config_path, local_user_config


def get_dolphin_user_dirs(executable_path: str | None = None) -> list[str]:
    """
    Return existing Dolphin Global User Directory candidates.

    On Windows this includes portable/local installs, Dolphin's registry-configured
    UserConfigPath, the modern AppData location, and the real (possibly redirected)
    Documents known folder used by older installations.
    """
    potential_bases: list[str] = []
    system = platform.system()
    user_home = os.path.expanduser("~")

    exe_dir = None
    if executable_path and os.path.isfile(executable_path):
        exe_dir = os.path.dirname(os.path.abspath(executable_path))
        local_user_dir = os.path.join(exe_dir, "User")
        portable_marker = os.path.join(exe_dir, "portable.txt")

        # Dolphin uses <exe>\User when portable.txt is present. We also accept an
        # already-existing User folder because older/local builds may use it.
        if os.path.isfile(portable_marker):
            log.debug(f"Dolphin portable.txt detected next to executable: {portable_marker}")
        _append_existing_dir(potential_bases, local_user_dir, "local/portable install")

    if system == "Windows":
        registry_user_path, registry_local = _get_windows_dolphin_registry_settings()

        # LocalUserConfig=1 forces the local User directory for all Dolphin builds.
        if registry_local and exe_dir:
            _append_existing_dir(
                potential_bases,
                os.path.join(exe_dir, "User"),
                "registry LocalUserConfig",
            )

        # This is the important case for users who moved Dolphin's User directory
        # to another drive (for example G:\...).
        _append_existing_dir(
            potential_bases,
            registry_user_path,
            "registry UserConfigPath",
        )

        appdata = os.environ.get("APPDATA", os.path.join(user_home, "AppData", "Roaming"))
        _append_existing_dir(
            potential_bases,
            os.path.join(appdata, "Dolphin Emulator"),
            "Windows AppData default",
        )

        documents_dir = _get_windows_documents_dir()
        _append_existing_dir(
            potential_bases,
            os.path.join(documents_dir, "Dolphin Emulator"),
            "Windows Documents default",
        )

        # Keep the naive path as a compatibility fallback in case the Known Folder
        # registry entry is missing or damaged.
        naive_documents = os.path.join(user_home, "Documents", "Dolphin Emulator")
        if os.path.normcase(os.path.abspath(naive_documents)) != os.path.normcase(
            os.path.abspath(os.path.join(documents_dir, "Dolphin Emulator"))
        ):
            _append_existing_dir(
                potential_bases,
                naive_documents,
                "Windows Documents fallback",
            )

    elif system == "Linux":
        # Dolphin supports DOLPHIN_EMU_USERPATH for a custom user directory.
        _append_existing_dir(
            potential_bases,
            os.environ.get("DOLPHIN_EMU_USERPATH"),
            "DOLPHIN_EMU_USERPATH",
        )
        for candidate in [
            os.path.join(user_home, ".local", "share", "dolphin-emu"),
            os.path.join(user_home, ".var", "app", "org.DolphinEmu.dolphin-emu", "data", "dolphin-emu"),
            os.path.join(user_home, ".dolphin-emu"),
        ]:
            _append_existing_dir(potential_bases, candidate, "Linux default")

    elif system == "Darwin":
        _append_existing_dir(
            potential_bases,
            os.environ.get("DOLPHIN_EMU_USERPATH"),
            "DOLPHIN_EMU_USERPATH",
        )
        _append_existing_dir(
            potential_bases,
            os.path.join(user_home, "Library", "Application Support", "Dolphin"),
            "macOS default",
        )

    if not potential_bases:
        log.warning("Could not find any Dolphin Global User Directory (portable, configured, or standard).")

    return potential_bases


def _get_dolphin_save_dirs_from_user_dirs(user_dirs: list[str]) -> list[str]:
    """Return existing GC and Wii save roots from known Dolphin user directories."""
    save_dirs: list[str] = []

    for base_dir in user_dirs:
        log.debug(f"Checking for save subdirectories in Dolphin user directory: {base_dir}")
        gc_path = os.path.join(base_dir, "GC")
        wii_path = os.path.join(base_dir, "Wii", "title")

        if os.path.isdir(gc_path):
            log.info(f"Found Dolphin GC save directory: {gc_path}")
            if gc_path not in save_dirs:
                save_dirs.append(gc_path)
        else:
            log.debug(f"GC save directory not found in base: {base_dir}")

        if os.path.isdir(wii_path):
            log.info(f"Found Dolphin Wii save directory: {wii_path}")
            if wii_path not in save_dirs:
                save_dirs.append(wii_path)
        else:
            log.debug(f"Wii save directory ('{os.path.join('Wii', 'title')}') not found in base: {base_dir}")

    if user_dirs and not save_dirs:
        log.warning("Found Dolphin Global User Directory(ies) but no GC or Wii save subdirectories within them.")

    return save_dirs


def get_dolphin_save_dirs(executable_path: str | None = None) -> list[str]:
    """
    Determine existing Dolphin GC and Wii save directories.

    Unlike the old implementation, this respects Dolphin's configured Windows
    UserConfigPath and redirected Documents folder instead of assuming the default user profile Documents path.
    """
    return _get_dolphin_save_dirs_from_user_dirs(get_dolphin_user_dirs(executable_path))


def _state_prefixes_for_profile(profile: dict) -> list[str]:
    """Return filename prefixes used by Dolphin StateSaves for a detected profile."""
    profile_id = str(profile.get("id", "")).strip()
    profile_type = str(profile.get("type", "")).upper()
    prefixes: list[str] = []

    if not profile_id:
        return prefixes

    if profile_type == "GC":
        # Standard GC profile IDs are 6-char game IDs. GCI-card grouping may only
        # provide the first 4 chars; that is still useful as a conservative prefix.
        prefixes.append(profile_id)

    elif profile_type == "WII":
        # Wii save folders are low title IDs such as 524d4750 -> ASCII "RMGP".
        # Savestates use the normal game ID (e.g. RMGP01.s01), so the decoded
        # 4-char title code is the common prefix we can reliably derive here.
        try:
            decoded = bytes.fromhex(profile_id).decode("ascii")
            if len(decoded) == 4 and decoded.isprintable():
                prefixes.append(decoded)
        except (ValueError, UnicodeDecodeError):
            pass

    return [p.lower() for p in prefixes if p]


def _attach_dolphin_state_saves(profiles: list[dict], user_dirs: list[str]) -> None:
    """Attach matching files from StateSaves to each detected game profile."""
    state_files: list[str] = []

    for base_dir in user_dirs:
        state_dir = os.path.join(base_dir, "StateSaves")
        if not os.path.isdir(state_dir):
            continue
        try:
            for entry in os.scandir(state_dir):
                if entry.is_file():
                    state_files.append(entry.path)
        except OSError as exc:
            log.error(f"Error scanning Dolphin StateSaves directory '{state_dir}': {exc}")

    if not state_files:
        return

    for profile in profiles:
        prefixes = _state_prefixes_for_profile(profile)
        if not prefixes:
            continue

        paths = profile.setdefault("paths", [])
        existing = {os.path.normcase(os.path.abspath(p)) for p in paths}

        for state_path in state_files:
            filename = os.path.basename(state_path).lower()
            if any(filename.startswith(prefix) for prefix in prefixes):
                key = os.path.normcase(os.path.abspath(state_path))
                if key not in existing:
                    paths.append(state_path)
                    existing.add(key)
                    log.debug(
                        f"Attached Dolphin savestate '{state_path}' to profile "
                        f"'{profile.get('name', profile.get('id', 'unknown'))}'"
                    )


def _merge_duplicate_profiles(profiles: list[dict]) -> list[dict]:
    """Merge duplicate IDs found in multiple Dolphin user-directory candidates."""
    merged: dict[tuple[str, str], dict] = {}

    for profile in profiles:
        key = (str(profile.get("type", "")), str(profile.get("id", "")))
        if key not in merged:
            merged[key] = {
                **profile,
                "paths": list(profile.get("paths", [])),
            }
            continue

        target = merged[key]
        target_paths = target.setdefault("paths", [])
        known = {os.path.normcase(os.path.abspath(p)) for p in target_paths}
        for path in profile.get("paths", []):
            norm = os.path.normcase(os.path.abspath(path))
            if norm not in known:
                target_paths.append(path)
                known.add(norm)

        # Prefer a parsed human-readable name over a raw ID when available.
        if target.get("name") == target.get("id") and profile.get("name") != profile.get("id"):
            target["name"] = profile.get("name")

    return list(merged.values())

def _parse_gc_banner_bin(banner_path: str) -> str | None:
    """
    Parses a GC banner.bin file to extract the game title.
    Tries common encodings. Returns None if unable to parse.
    """
    try:
        with open(banner_path, 'rb') as f:
            # Basic check: Read magic bytes (BNR1/BNR2) - optional but good practice
            magic = f.read(4)
            if magic not in (b'BNR1', b'BNR2'):
                log.warning(f"Invalid magic bytes in banner.bin: {banner_path} ({magic!r})")
                # Continue anyway, might still work for some variants

            # Game titles often start around offset 0x20.
            # Let's read a block that should contain multiple titles.
            # Example structure might have:
            # 0x20: Short Title (32 bytes)
            # 0x40: Short Maker (32 bytes)
            # 0x60: Long Title (64 bytes)
            # 0xA0: Long Maker (64 bytes)
            # 0xE0: Description (128 bytes)
            # We'll try reading the Long Title first, then Short Title.

            # Try Long Title (Offset 0x60, Length 64)
            f.seek(0x60)
            long_title_bytes = f.read(64).split(b'\x00', 1)[0] # Read until null terminator

            # Try Short Title (Offset 0x20, Length 32) if Long Title empty
            if not long_title_bytes:
                 f.seek(0x20)
                 long_title_bytes = f.read(32).split(b'\x00', 1)[0] # Use same variable

            if not long_title_bytes:
                 log.debug(f"No title data found at expected offsets in banner.bin: {banner_path}")
                 return None

            # Attempt decoding (try common encodings)
            encodings_to_try = ['utf-8', 'shift_jis', 'latin_1'] # Add others if needed
            title = None
            for enc in encodings_to_try:
                try:
                    title = long_title_bytes.decode(enc).strip()
                    if title: # Stop if we get a non-empty title
                         log.debug(f"Decoded title '{title}' using {enc} from {banner_path}")
                         return title
                except UnicodeDecodeError:
                    continue # Try next encoding
                except Exception as decode_err: # Catch other potential decoding issues
                     log.warning(f"Error decoding title bytes with {enc} from {banner_path}: {decode_err}")
                     continue

            if not title:
                 log.warning(f"Could not decode title from banner.bin: {banner_path} (Bytes: {long_title_bytes!r})")
            return None # Return None if all decoding attempts fail

    except FileNotFoundError:
        log.error(f"banner.bin not found at expected path: {banner_path}")
        return None
    except OSError as e:
        log.error(f"OS Error reading banner.bin {banner_path}: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error parsing banner.bin {banner_path}: {e}", exc_info=True)
        return None


# --- Add Wii Banner Parsing Function (basic structure) ---
def _parse_wii_banner_bin(banner_path: str) -> str | None:
    """Parses the banner.bin file for Wii titles to extract the game name.

    Wii banner.bin often stores the title at offset 0x20, encoded in UTF-16BE.
    """
    expected_size = 0x480 # Standard Wii banner size, adjust if needed
    title_offset = 0x20
    # Max title length isn't strictly defined, read a reasonable amount
    max_read_bytes = 256

    try:
        if not os.path.exists(banner_path):
            log.debug(f"Wii banner.bin not found at {banner_path}")
            return None

        file_size = os.path.getsize(banner_path)
        if file_size < title_offset + 2: # Need at least offset + 2 bytes for a char
            log.warning(f"Wii banner.bin too small: {banner_path} ({file_size} bytes)")
            return None

        with open(banner_path, 'rb') as f:
            f.seek(title_offset)
            raw_title_bytes = f.read(max_read_bytes)

        # Decode using UTF-16 Big Endian
        try:
            # Find the first double null byte (0x0000) which terminates the string
            null_terminator_pos = -1
            for i in range(0, len(raw_title_bytes) - 1, 2):
                if raw_title_bytes[i] == 0x00 and raw_title_bytes[i+1] == 0x00:
                    null_terminator_pos = i
                    break

            if null_terminator_pos != -1:
                title_bytes = raw_title_bytes[:null_terminator_pos]
            else:
                # No null terminator found within read range, use all bytes read
                title_bytes = raw_title_bytes
                log.debug("Wii banner name wasn't null-terminated within read bytes")

            # Check for empty title after trimming
            if not title_bytes:
                 log.debug("Wii banner name section is empty after processing nulls")
                 return None

            title = title_bytes.decode('utf-16-be').strip()
            log.debug(f"Decoded Wii title (UTF-16BE): '{title}'")
            # Basic sanity check - reject if too short or looks like garbage?
            if title and len(title) > 1:
                 return title
            else:
                 log.warning(f"Parsed Wii title seems invalid: '{title}'")
                 return None

        except UnicodeDecodeError:
            log.warning(f"Could not decode Wii banner title as UTF-16BE: {banner_path}", exc_info=True)
            # Add fallbacks to other encodings if necessary here (e.g., Shift_JIS for JP games?)
            return None
        except Exception as e:
            log.error(f"Error reading/decoding Wii banner title section: {e}", exc_info=True)
            return None

    except OSError as e:
        log.error(f"OS Error accessing Wii banner.bin '{banner_path}': {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error parsing Wii banner.bin '{banner_path}': {e}", exc_info=True)
        return None

# ------------------------------------------------------


def find_dolphin_profiles(executable_path: str | None = None) -> list[dict]:
    """
    Finds Dolphin game save profiles by scanning determined save directories.
    Attempts to parse banner.bin for GC game names. Uses directory names as fallback/for Wii.
    """
    log.info("Attempting to find Dolphin profiles...")
    user_dirs = get_dolphin_user_dirs(executable_path)
    save_dirs = _get_dolphin_save_dirs_from_user_dirs(user_dirs)
    profiles = []

    if not save_dirs:
        log.error("Cannot find Dolphin profiles: Save directory locations are unknown.")
        return []

    for save_dir in save_dirs:
        log.info(f"Scanning Dolphin save directory: {save_dir}")

        # --- CORRECTED TYPE DETECTION ---
        # Determine type based on the save_dir path itself
        current_scan_type = None
        base_name = os.path.basename(save_dir).lower()
        parent_base_name = os.path.basename(os.path.dirname(save_dir)).lower()

        if base_name == 'gc':
             current_scan_type = 'GC'
        elif base_name == 'title' and parent_base_name == 'wii':
             current_scan_type = 'Wii'
        else:
            log.warning(f"Unexpected save directory structure, cannot determine type: {save_dir}")
            continue # Skip this directory

        log.debug(f"Determined scan type for '{save_dir}' as: {current_scan_type}")
        # ---------------------------------

        try:
            # --- MODIFIED GC LOGIC --- 
            if current_scan_type == 'GC':
                region_folders = os.listdir(save_dir)
                log.debug(f"  Regions/Items found in GC dir '{save_dir}': {region_folders}")
                for region_name in region_folders:
                    region_path = os.path.join(save_dir, region_name)
                    # Check if it's a directory and a known region
                    if os.path.isdir(region_path) and region_name.upper() in ['USA', 'EUR', 'JAP']:
                        log.debug(f"    Scanning GC Region Folder: {region_path}")
                        try:
                            game_id_folders = os.listdir(region_path)
                            log.debug(f"      Game IDs/Items found in region '{region_name}': {game_id_folders}")

                            # 1) Handle standard per-title folders (6-char alnum)
                            for game_id_name in game_id_folders:
                                game_id_path = os.path.join(region_path, game_id_name)

                                if os.path.isdir(game_id_path) and len(game_id_name) == 6 and game_id_name.isalnum():
                                    log.debug(f"        Found potential GC Game ID folder: {game_id_name}")
                                    profile_id = game_id_name
                                    profile_name = game_id_name
                                    profile_type = 'GC'

                                    banner_file = os.path.join(game_id_path, 'banner.bin')
                                    if os.path.isfile(banner_file):
                                        log.debug(f"          Found banner.bin, attempting parse: {banner_file}")
                                        parsed_name = _parse_gc_banner_bin(banner_file)
                                        if parsed_name:
                                            profile_name = parsed_name
                                            log.info(f"          Successfully parsed GC game name: '{profile_name}' (ID: {profile_id})")
                                        else:
                                            log.warning(f"          Failed to parse banner.bin for {profile_id}, using ID as name.")
                                    else:
                                        log.debug(f"          banner.bin not found in {game_id_path}, using ID as name.")

                                    profiles.append({
                                        'id': profile_id,
                                        'name': profile_name,
                                        'paths': [game_id_path],
                                        'type': profile_type
                                    })

                            # 2) Handle Memory Card folders (Card A / Card B) containing .gci files
                            for card_folder in ['Card A', 'Card B']:
                                card_path = os.path.join(region_path, card_folder)
                                if not os.path.isdir(card_path):
                                    continue
                                try:
                                    gci_files = [f for f in os.listdir(card_path) if f.lower().endswith('.gci')]
                                except OSError as e:
                                    log.error(f"      Error listing files in memory card folder '{card_path}': {e}")
                                    gci_files = []

                                if not gci_files:
                                    continue

                                # Group .gci files by the internal 4-char game code in filename if present
                                # Expected pattern example: '01-GMSP-super_mario_sunshine.gci'
                                groups: dict[str, list[str]] = {}
                                for filename in gci_files:
                                    base = os.path.splitext(filename)[0]
                                    # Try to extract 4-char code between first '-' and next '-'
                                    # Accept both with or without leading slot index prefix
                                    # Patterns: '01-GMSP-title', 'GMSP-title', fallback: whole base
                                    code_match = re.search(r'^(?:\d{2}-)?([A-Za-z0-9]{4})-', base)
                                    if code_match:
                                        game_code = code_match.group(1)
                                        display_name = re.sub(r'^(?:\d{2}-)?[A-Za-z0-9]{4}-', '', base)
                                    else:
                                        # Fallback: use base as code and display
                                        game_code = base[:6] if len(base) >= 6 else base
                                        display_name = base

                                    display_name = display_name.replace('_', ' ').strip() or game_code
                                    key = f"{game_code}"
                                    groups.setdefault(key, [])
                                    groups[key].append(os.path.join(card_path, filename))

                                # Create one profile per group
                                for game_code, file_paths in groups.items():
                                    # Try to get a nicer name from any filename in the group
                                    sample_name = os.path.splitext(os.path.basename(file_paths[0]))[0]
                                    name_part = re.sub(r'^(?:\d{2}-)?[A-Za-z0-9]{4}-', '', sample_name)
                                    display = name_part.replace('_', ' ').strip() or game_code

                                    profile_id = game_code
                                    profile_name = display
                                    profile_type = 'GC'

                                    profiles.append({
                                        'id': profile_id,
                                        'name': profile_name,
                                        'paths': file_paths,
                                        'type': profile_type
                                    })
                        except OSError as region_e:
                            log.error(f"      Error scanning GC region directory '{region_path}': {region_e}")
                    else:
                         log.debug(f"    Skipping item in GC dir (not dir or not known region): {region_name}")
            # --- END MODIFIED GC LOGIC ---

            # --- MODIFIED Wii Logic --- 
            elif current_scan_type == 'Wii':
                high_tid_folders = os.listdir(save_dir) # e.g., ['00000001', '00010000']
                log.debug(f"  High-Level Title ID folders found in Wii dir '{save_dir}': {high_tid_folders}")
                for high_tid_name in high_tid_folders:
                    high_tid_path = os.path.join(save_dir, high_tid_name)
                    # --- Refined Check: Only look in game title folders (00010000) ---
                    if os.path.isdir(high_tid_path) and high_tid_name.startswith('00010000'):
                    # ---------------------------------------------------------------
                        log.debug(f"    Scanning High-Level TID Folder: {high_tid_path}")
                        try:
                            low_tid_folders = os.listdir(high_tid_path) # e.g., ['524d4750']
                            log.debug(f"      Low-Level Title ID folders found in '{high_tid_name}': {low_tid_folders}")
                            for low_tid_name in low_tid_folders:
                                low_tid_path = os.path.join(high_tid_path, low_tid_name)
                                # Check if it's a directory and has the 8-char length of low TID
                                if os.path.isdir(low_tid_path) and len(low_tid_name) == 8:
                                    log.debug(f"        Found potential Wii Game Title ID folder: {low_tid_name}")
                                    profile_id = low_tid_name # Use the 8-char Low TID
                                    profile_name = low_tid_name # Default name is ID
                                    profile_type = 'Wii'

                                    # --- Try to get name from Wii banner.bin --- 
                                    # Look in the folder itself or in a 'data' subfolder
                                    banner_path_direct = os.path.join(low_tid_path, "banner.bin")
                                    banner_path_data = os.path.join(low_tid_path, "data", "banner.bin")
                                    
                                    banner_to_parse = None
                                    if os.path.isfile(banner_path_direct):
                                        banner_to_parse = banner_path_direct
                                    elif os.path.isfile(banner_path_data):
                                        banner_to_parse = banner_path_data

                                    if banner_to_parse:
                                        log.debug(f"          Found Wii banner.bin, attempting parse: {banner_to_parse}")
                                        parsed_name = _parse_wii_banner_bin(banner_to_parse)
                                        if parsed_name:
                                            profile_name = parsed_name # Use parsed name!
                                            log.info(f"          Successfully parsed Wii game name: '{profile_name}' (ID: {profile_id})")
                                        else:
                                            log.warning(f"          Failed to parse Wii banner.bin for {profile_id}, using ID as name.")
                                    else:
                                        log.debug(f"          Wii banner.bin not found in {low_tid_path} or its data subdir, using ID as name.")
                                    # -------------------------------------------

                                    # *** Add the profile to the list ***
                                    profiles.append({
                                        'id': profile_id,
                                        'name': profile_name,
                                        'paths': [low_tid_path], # Use list and 'paths'
                                        'type': profile_type
                                    })
                                else:
                                    log.debug(f"        Skipping item in high TID '{high_tid_name}' (not dir or not 8 chars): {low_tid_name}")
                        except OSError as low_tid_e:
                            log.error(f"      Error scanning Wii low TID directory '{high_tid_path}': {low_tid_e}")
                    else:
                        log.debug(f"    Skipping item in Wii title dir (not dir or not known high TID prefix): {high_tid_name}")
            # --- END MODIFIED Wii Logic ---

        except FileNotFoundError:
             log.error(f"Save directory not found during scan (was it deleted?): '{save_dir}'")
        except OSError as e:
            log.error(f"Error scanning Dolphin save directory '{save_dir}': {e}")
        except Exception as e:
            log.error(f"Unexpected error scanning Dolphin directory '{save_dir}': {e}", exc_info=True)

    profiles = _merge_duplicate_profiles(profiles)
    _attach_dolphin_state_saves(profiles, user_dirs)

    log.info(f"Found {len(profiles)} Dolphin profiles (GC named via banner.bin where possible).")
    profiles.sort(key=lambda p: p.get('name', ''))
    return profiles


# --- Example Usage ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    # Try finding saves without assuming an executable path (checks standard locations)
    print("--- Finding Dolphin Profiles (Standard Paths) ---")
    standard_profiles = find_dolphin_profiles()
    for p in standard_profiles:
        print(p)

    # Example: Simulate finding a portable install (replace with actual path if needed)
    # print("\n--- Finding Dolphin Profiles (Simulated Portable Path) ---")
    # portable_exe_path = "C:\\path\\to\\Dolphin\\Dolphin.exe" # CHANGE THIS
    # portable_profiles = find_dolphin_profiles(portable_exe_path)
    # for p in portable_profiles:
    #      print(p)
