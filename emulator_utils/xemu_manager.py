# emulator_utils/xemu_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import json
import struct
from typing import Dict, List, Optional
from .xemu_tools.xbox_hdd_reader import find_xbox_game_saves

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
    """
    if not data_dir:
        return None
    
    # Standard HDD image filename used by xemu
    hdd_path = os.path.join(data_dir, "xbox_hdd.qcow2")
    if os.path.isfile(hdd_path):
        log.debug(f"Found xemu HDD image: {hdd_path}")
        return hdd_path
    
    # Alternative filename
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
                        'save_info': save  # Store additional save information
                    })
                    
            except Exception as e:
                log.error(f"Error scanning Xbox HDD image: {e}")
                # Fallback: include the HDD image as a single profile
                profiles.append({
                    'id': 'xbox_hdd',
                    'name': 'Xbox HDD Image (Game Saves)',
                    'paths': [hdd_path],
                    'type': 'hdd_image'
                })
        
        # 2. Check for EEPROM (system settings and some saves)
        eeprom_path = get_xemu_eeprom_path(data_dir)
        if eeprom_path:
            profiles.append({
                'id': 'xbox_eeprom',
                'name': 'Xbox EEPROM (System Settings)',
                'paths': [eeprom_path],
                'type': 'eeprom'
            })
        
        # 3. If no specific saves found, include the entire data directory
        if not profiles:
            profiles.append({
                'id': 'xemu_data',
                'name': 'xemu Data Directory',
                'paths': [data_dir],
                'type': 'directory'
            })
    
    except Exception as e:
        log.error(f"Error scanning xemu data directory '{data_dir}': {e}", exc_info=True)
        return []

    log.info(f"Found {len(profiles)} xemu profiles.")
    return profiles


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