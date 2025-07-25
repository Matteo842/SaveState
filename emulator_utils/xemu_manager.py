# emulator_utils/xemu_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json
import struct
import tempfile
import shutil
from typing import Dict, List, Optional, Tuple
from .xemu_tools.xbox_hdd_reader import find_xbox_game_saves
from .xemu_tools.qemu_converter import get_qemu_converter

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

def get_xemu_data_path(executable_path: str | None = None) -> str | None:
    """
    Determines the xemu data directory for save files and EEPROM.
    Checks portable mode first (data folder alongside exe), then standard OS-specific locations.
    """
    # Portable check: look for data folder alongside exe OR HDD directly in exe dir
    if executable_path:
        exe_dir = None
        if os.path.isfile(executable_path):
            exe_dir = os.path.dirname(executable_path)
        elif os.path.isdir(executable_path):
            exe_dir = executable_path
        
        if exe_dir:
            # Check for data folder alongside executable (standard portable installation)
            data_dir = os.path.join(exe_dir, "data")
            if os.path.isdir(data_dir):
                log.debug(f"Using executable-relative xemu data directory: {data_dir}")
                return data_dir
            
            # Check for HDD directly in executable directory (custom portable setup)
            hdd_in_exe_dir = os.path.join(exe_dir, "xbox_hdd.qcow2")
            if os.path.isfile(hdd_in_exe_dir):
                log.debug(f"Found HDD in executable directory, using as data dir: {exe_dir}")
                return exe_dir
            
            # Check if xemu.log exists in exe directory (indicates this is the data dir)
            log_in_exe_dir = os.path.join(exe_dir, "xemu.log")
            if os.path.isfile(log_in_exe_dir):
                log.debug(f"Found xemu.log in executable directory, using as data dir: {exe_dir}")
                return exe_dir

    # Standard locations based on OS
    system = platform.system()
    user_home = os.path.expanduser("~")
    
    if system == "Windows":
        # Windows: %APPDATA%\xemu
        appdata = os.getenv("APPDATA")
        if appdata:
            data_dir = os.path.join(appdata, "xemu")
            if os.path.isdir(data_dir):
                log.debug(f"Using Windows AppData xemu data directory: {data_dir}")
                return data_dir
    elif system == "Linux":
        # Linux: ~/.local/share/xemu
        xdg_data = os.getenv("XDG_DATA_HOME", os.path.join(user_home, ".local", "share"))
        data_dir = os.path.join(xdg_data, "xemu")
        if os.path.isdir(data_dir):
            log.debug(f"Using Linux XDG data xemu directory: {data_dir}")
            return data_dir
    elif system == "Darwin":  # macOS
        # macOS: ~/Library/Application Support/xemu
        data_dir = os.path.join(user_home, "Library", "Application Support", "xemu")
        if os.path.isdir(data_dir):
            log.debug(f"Using macOS Application Support xemu directory: {data_dir}")
            return data_dir

    log.warning("Could not determine xemu data directory.")
    return None


def get_xemu_hdd_path(data_dir: str) -> str | None:
    """
    Gets the path to the xemu HDD image file where game saves are stored.
    First tries to find it from xemu.log, then falls back to standard locations.
    """
    if not data_dir:
        return None
    
    # Method 1: Try to find HDD path from xemu.log
    log_path = os.path.join(data_dir, "xemu.log")
    if os.path.isfile(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read the last 1000 lines to find the most recent launch
                lines = f.readlines()
                for line in reversed(lines[-1000:]):  # Check last 1000 lines
                    if "media=disk,file=" in line:
                        # Extract HDD path from log line
                        # Example: -drive index=0,media=disk,file=D:\xemu\xbox_hdd.qcow2,locked=on
                        import re
                        match = re.search(r'media=disk,file=([^,\s]+)', line)
                        if match:
                            hdd_path_from_log = match.group(1)
                            if os.path.isfile(hdd_path_from_log):
                                log.info(f"Found xemu HDD image from log: {hdd_path_from_log}")
                                return hdd_path_from_log
                            else:
                                log.warning(f"HDD path from log exists but file not found: {hdd_path_from_log}")
        except Exception as e:
            log.warning(f"Error reading xemu.log: {e}")
    
    # Method 2: Standard HDD image filename used by xemu
    hdd_path = os.path.join(data_dir, "xbox_hdd.qcow2")
    if os.path.isfile(hdd_path):
        log.debug(f"Found xemu HDD image: {hdd_path}")
        return hdd_path
    
    # Method 3: Alternative filename
    hdd_path_alt = os.path.join(data_dir, "hdd.qcow2")
    if os.path.isfile(hdd_path_alt):
        log.debug(f"Found xemu HDD image (alternative name): {hdd_path_alt}")
        return hdd_path_alt
    
    log.warning(f"Could not find xemu HDD image in data directory: {data_dir}")
    return None


def get_xemu_eeprom_path(data_dir: str) -> str | None:
    """
    Gets the path to the xemu EEPROM file.
    """
    if not data_dir:
        return None
    
    eeprom_path = os.path.join(data_dir, "eeprom.bin")
    if os.path.isfile(eeprom_path):
        log.debug(f"Found xemu EEPROM file: {eeprom_path}")
        return eeprom_path
    
    log.warning(f"Could not find xemu EEPROM file in data directory: {data_dir}")
    return None


def clean_save_file_name(file_name: str) -> str:
    """
    Clean up save file names for better display.
    """
    if not file_name:
        return "Xbox Save File"
    
    # Handle EEPROM files
    if 'eeprom' in file_name.lower():
        # Extract date if present
        import re
        date_match = re.search(r'(\d{4}_\d{2}_\d{2})', file_name)
        if date_match:
            date_str = date_match.group(1).replace('_', '-')
            return f"Xbox EEPROM ({date_str})"
        else:
            return "Xbox EEPROM (System Settings)"
    
    # Handle other save files
    if any(ext in file_name.lower() for ext in ['.sav', '.save', '.dat']):
        clean_name = file_name.replace('_', ' ').title()
        return f"Xbox Save: {clean_name}"
    
    # Default cleanup
    clean_name = file_name.replace('_', ' ').title()
    return f"Xbox File: {clean_name}"


def scan_for_game_saves(data_dir: str) -> List[Dict[str, str]]:
    """
    Scans for individual game save files in the xemu data directory.
    Some games might store saves as individual files outside the HDD image.
    """
    saves = []
    if not data_dir or not os.path.isdir(data_dir):
        return saves
    
    try:
        for item in os.listdir(data_dir):
            item_path = os.path.join(data_dir, item)
            
            # Skip known system files
            if item.lower() in ['xbox_hdd.qcow2', 'hdd.qcow2', 'eeprom.bin', 'bios.bin', 'mcpx_1.0.bin']:
                continue
            
            # Look for save-related files and directories
            if os.path.isfile(item_path):
                # Check for common save file extensions
                if any(item.lower().endswith(ext) for ext in ['.sav', '.save', '.dat', '.bin']):
                    saves.append({
                        'name': os.path.splitext(item)[0],
                        'path': item_path,
                        'type': 'file'
                    })
            elif os.path.isdir(item_path):
                # Check for directories that might contain saves
                if any(keyword in item.lower() for keyword in ['save', 'data', 'profile']):
                    saves.append({
                        'name': item,
                        'path': item_path,
                        'type': 'directory'
                    })
    
    except OSError as e:
        log.error(f"Error scanning xemu data directory '{data_dir}': {e}")
    
    return saves


def find_xemu_profiles(executable_path: str | None = None) -> List[Dict[str, str]]:
    """
    Finds xemu save profiles by scanning the data directory and HDD image.
    Returns a list of dicts: {'id': ..., 'name': ..., 'paths': [...]}.
    
    Optimized version with faster HDD scanning.
    """
    data_dir = get_xemu_data_path(executable_path)
    if not data_dir:
        log.error("Cannot find xemu save profiles: data directory unknown.")
        return []

    profiles = []
    
    try:
        # 1. Check for HDD image and extract game saves from it (OPTIMIZED)
        hdd_path = get_xemu_hdd_path(data_dir)
        if hdd_path:
            log.info(f"Found Xbox HDD image, scanning for game saves: {hdd_path}")
            try:
                # Use QUICK SCAN for much better performance
                xbox_saves = find_xbox_game_saves(hdd_path, quick_scan=True)
                log.info(f"Found {len(xbox_saves)} game saves in HDD image")
                
                for save in xbox_saves:
                    profiles.append({
                        'id': save['id'],
                        'name': save['name'],
                        'paths': [hdd_path],  # All saves are in the HDD image
                        'type': 'xbox_game_save',
                        'emulator': 'xemu',  # Add emulator field for consistency
                        'save_info': save  # Store additional save information
                    })
                    
            except Exception as e:
                log.error(f"Error scanning Xbox HDD image: {e}")
                # Fallback: include the HDD image as a single profile
                profiles.append({
                    'id': 'xbox_hdd',
                    'name': 'Xbox HDD Image (Game Saves)',
                    'paths': [hdd_path],
                    'type': 'hdd_image',
                    'emulator': 'xemu'
                })
        
        # 2. Check for EEPROM (system settings and some saves)
        eeprom_path = get_xemu_eeprom_path(data_dir)
        if eeprom_path:
            profiles.append({
                'id': 'xbox_eeprom',
                'name': 'Xbox EEPROM (System Settings)',
                'paths': [eeprom_path],
                'type': 'eeprom',
                'emulator': 'xemu'
            })
        
        # 3. If no specific saves found, include the entire data directory
        if not profiles:
            profiles.append({
                'id': 'xemu_data',
                'name': 'xemu Data Directory',
                'paths': [data_dir],
                'type': 'directory',
                'emulator': 'xemu'
            })
    
    except Exception as e:
        log.error(f"Error scanning xemu data directory '{data_dir}': {e}", exc_info=True)
        return []

    log.info(f"Found {len(profiles)} xemu profiles.")
    return profiles


def backup_xbox_save(profile_id: str, backup_dir: str, executable_path: str | None = None) -> tuple[bool, str]:
    """
    Backup a specific Xbox save using the integrated extraction pipeline.
    
    Args:
        profile_id: ID of the profile/game to backup
        backup_dir: Directory to save the backup
        executable_path: Path to xemu executable
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        data_dir = get_xemu_data_path(executable_path)
        if not data_dir:
            msg = "Cannot backup Xbox save: data directory unknown."
            log.error(msg)
            return False, msg
        
        hdd_path = get_xemu_hdd_path(data_dir)
        if not hdd_path:
            msg = "Cannot backup Xbox save: HDD image not found."
            log.error(msg)
            return False, msg
        
        # Create backup directory
        os.makedirs(backup_dir, exist_ok=True)
        
        # Handle different profile types
        if profile_id == 'xbox_eeprom':
            # Simple file copy for EEPROM
            eeprom_path = get_xemu_eeprom_path(data_dir)
            if eeprom_path:
                backup_file = os.path.join(backup_dir, 'eeprom.bin')
                shutil.copy2(eeprom_path, backup_file)
                msg = f"EEPROM backup completed successfully"
                log.info(f"EEPROM backed up to: {backup_file}")
                return True, msg
            return False, "EEPROM file not found"
        
        elif profile_id == 'xbox_hdd':
            # Full HDD backup
            backup_file = os.path.join(backup_dir, 'xbox_hdd.qcow2')
            shutil.copy2(hdd_path, backup_file)
            msg = f"Full HDD backup completed successfully"
            log.info(f"Full HDD backed up to: {backup_file}")
            return True, msg
        
        else:
            # Individual game save extraction
            success = _extract_game_save(profile_id, hdd_path, backup_dir)
            if success:
                return True, f"Xbox game save backup completed successfully"
            else:
                return False, f"Failed to extract game save for {profile_id}"
    
    except Exception as e:
        msg = f"Error backing up Xbox save '{profile_id}': {e}"
        log.error(msg, exc_info=True)
        return False, msg


def restore_xbox_save(profile_id: str, backup_dir: str, executable_path: str | None = None) -> bool:
    """
    Restore a specific Xbox save.
    
    Args:
        profile_id: ID of the profile/game to restore
        backup_dir: Directory containing the backup
        executable_path: Path to xemu executable
        
    Returns:
        True if restore successful, False otherwise
    """
    try:
        data_dir = get_xemu_data_path(executable_path)
        if not data_dir:
            log.error("Cannot restore Xbox save: data directory unknown.")
            return False
        
        # Handle different profile types
        if profile_id == 'xbox_eeprom':
            # Simple file copy for EEPROM
            backup_file = os.path.join(backup_dir, 'eeprom.bin')
            if os.path.isfile(backup_file):
                eeprom_path = get_xemu_eeprom_path(data_dir)
                if eeprom_path:
                    shutil.copy2(backup_file, eeprom_path)
                    log.info(f"EEPROM restored from: {backup_file}")
                    return True
            return False
        
        elif profile_id == 'xbox_hdd':
            # Full HDD restore
            backup_file = os.path.join(backup_dir, 'xbox_hdd.qcow2')
            if os.path.isfile(backup_file):
                hdd_path = get_xemu_hdd_path(data_dir)
                if hdd_path:
                    shutil.copy2(backup_file, hdd_path)
                    log.info(f"Full HDD restored from: {backup_file}")
                    return True
            return False
        
        else:
            # Individual game save restore (more complex - would need HDD injection)
            log.warning(f"Individual game save restore not yet implemented for: {profile_id}")
            return False
    
    except Exception as e:
        log.error(f"Error restoring Xbox save '{profile_id}': {e}", exc_info=True)
        return False


def _extract_game_save(game_id: str, hdd_path: str, output_dir: str) -> bool:
    """
    Extract a specific game save using the integrated pipeline.
    
    Args:
        game_id: Game ID to extract
        hdd_path: Path to HDD image
        output_dir: Output directory for extracted save
        
    Returns:
        True if extraction successful
    """
    temp_raw_path = None
    
    try:
        # Step 1: Convert QCOW2 to RAW using QEMU converter
        converter = get_qemu_converter()
        if not converter.is_qemu_available():
            log.error("QEMU tools not available for save extraction")
            return False
        
        # Create temporary directory for conversion
        temp_dir = tempfile.mkdtemp(prefix="xemu_extract_")
        temp_raw_path = converter.convert_qcow2_to_raw(hdd_path, temp_dir)
        
        if not temp_raw_path:
            log.error("Failed to convert QCOW2 to RAW for extraction")
            return False
        
        # Step 2: Use extract_quick to find the game offset
        from .xemu_tools.extract_quick import find_game_offset
        
        # Load the title map to get game names
        title_map = {}
        try:
            title_map_path = os.path.join(os.path.dirname(__file__), 'xbox_title_id_map.json')
            with open(title_map_path, 'r', encoding='utf-8') as f:
                title_map = json.load(f)
        except Exception as e:
            log.warning(f"Could not load title map: {e}")
        
        # Find offset for the specific game
        game_info = find_game_offset(temp_raw_path, game_id, title_map)
        
        if not game_info:
            log.error(f"No save patterns found for game ID: {game_id}")
            return False
        
        game_offset = game_info['offset']
        game_name = game_info['name']
        
        log.info(f"Found {game_name} at offset 0x{game_offset:x}")
        
        # Step 3: Use extract_final to extract the save at the found offset
        from .xemu_tools.extract_final import extract_xbox_saves_final
        
        # Sanitize game name for directory creation (remove invalid characters)
        import re
        safe_game_name = re.sub(r'[<>:"/\\|?*]', '_', game_name)
        safe_game_name = safe_game_name.replace(' ', '_')
        
        # Prepare game positions for extract_final
        game_positions = [{
            'tid': game_id,
            'name': safe_game_name,
            'offset': game_offset
        }]
        
        # Extract the save
        extract_xbox_saves_final(temp_raw_path, output_dir, game_positions)
        
        # Check if extraction was successful
        game_dir = os.path.join(output_dir, f"{game_id}_{safe_game_name}")
        if os.path.isdir(game_dir) and os.listdir(game_dir):
            log.info(f"Successfully extracted save for game {game_id} to {output_dir}")
            return True
        else:
            log.error(f"Failed to extract save for game {game_id}")
            return False
    
    except Exception as e:
        log.error(f"Error extracting game save {game_id}: {e}", exc_info=True)
        return False
    
    finally:
        # Cleanup temporary files
        if temp_raw_path and os.path.isfile(temp_raw_path):
            try:
                os.remove(temp_raw_path)
                temp_dir = os.path.dirname(temp_raw_path)
                if os.path.isdir(temp_dir):
                    shutil.rmtree(temp_dir)
                log.info(f"Cleaned up temporary RAW file: {temp_raw_path}")
            except Exception as e:
                log.warning(f"Failed to cleanup temporary files: {e}")


# Example usage (optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Testing xemu manager...")
    profiles = find_xemu_profiles()
    for profile in profiles:
        print(f"ID: {profile['id']}")
        print(f"Name: {profile['name']}")
        print(f"Paths: {profile['paths']}")
        print(f"Type: {profile.get('type', 'unknown')}")
        print("-" * 40)