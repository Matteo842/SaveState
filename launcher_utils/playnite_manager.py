# launcher_utils/playnite_manager.py
# -*- coding: utf-8 -*-

"""
Playnite launcher manager for SaveState.

Playnite stores its game library in a LiteDB database (games.db).
LiteDB uses BSON format which we need to parse to extract game information.

Key fields we need:
- Name: Game display name
- InstallDirectory: Path where the game is installed
- GameId: Unique identifier for the game
"""

import os
import logging
import platform
import struct
import json
import tempfile
import shutil
from typing import Optional, List, Dict

log = logging.getLogger(__name__)

# Blacklist of names that are NOT games (social media, launchers, websites, etc.)
# These entries appear in Playnite but should not be shown as games
NON_GAME_BLACKLIST = [
    # Social Media & Communication
    'discord', 'twitch', 'twitter', 'facebook', 'instagram', 'youtube',
    'bluesky', 'reddit', 'subreddit',
    # Launchers & Stores
    'steam', 'gog', 'epic games', 'ubisoft connect', 'origin', 'ea app',
    'battle.net', 'amazon games', 'xbox', 'playstation', 'nintendo',
    'google play', 'app store', 'app store (iphone)', 'app store (ipad)',
    # Websites & Resources
    'wikipedia', 'community wiki', 'official website',
    # Servers & Tools
    'dedicated server', 'palworld dedicated server',
]


def get_playnite_library_path(executable_path: str | None = None) -> str | None:
    """
    Determines the Playnite library database path.
    
    Checks:
    1. Portable installation: {exe_dir}/library/games.db
    2. Standard installation: %APPDATA%/Playnite/library/games.db
    
    Args:
        executable_path: Optional path to Playnite executable for portable check.
        
    Returns:
        Path to games.db if found, None otherwise.
    """
    log.debug(f"Determining Playnite library path. Executable: {executable_path}")
    
    paths_to_check = []
    
    # 1. Check portable installation (near executable)
    if executable_path:
        if os.path.isfile(executable_path):
            exe_dir = os.path.dirname(executable_path)
        elif os.path.isdir(executable_path):
            exe_dir = executable_path
        else:
            exe_dir = None
            
        if exe_dir:
            portable_db = os.path.join(exe_dir, "library", "games.db")
            if os.path.isfile(portable_db):
                log.info(f"Found portable Playnite library: {portable_db}")
                return portable_db
            paths_to_check.append(portable_db)
    
    # 2. Check standard installation
    if platform.system() == "Windows":
        appdata = os.getenv('APPDATA')
        if appdata:
            standard_db = os.path.join(appdata, "Playnite", "library", "games.db")
            if os.path.isfile(standard_db):
                log.info(f"Found standard Playnite library: {standard_db}")
                return standard_db
            paths_to_check.append(standard_db)
    
    # 3. Check LocalAppData for some installations
    if platform.system() == "Windows":
        localappdata = os.getenv('LOCALAPPDATA')
        if localappdata:
            local_db = os.path.join(localappdata, "Playnite", "library", "games.db")
            if os.path.isfile(local_db):
                log.info(f"Found Playnite library in LocalAppData: {local_db}")
                return local_db
            paths_to_check.append(local_db)
    
    log.warning(f"Could not find Playnite games.db. Checked: {paths_to_check}")
    return None


def _parse_bson_string(data: bytes, offset: int) -> tuple[str, int]:
    """Parse a BSON string at the given offset. Returns (string, new_offset)."""
    # BSON string: int32 length (including null), then bytes, then null terminator
    length = struct.unpack_from('<i', data, offset)[0]
    offset += 4
    # Decode string (excluding null terminator)
    string_value = data[offset:offset + length - 1].decode('utf-8', errors='replace')
    offset += length
    return string_value, offset


def _parse_bson_document(data: bytes, offset: int = 0) -> tuple[dict, int]:
    """
    Parse a BSON document starting at the given offset.
    Returns (parsed_dict, new_offset after document).
    
    This is a simplified parser that handles the types we need for Playnite:
    - 0x02: String
    - 0x03: Embedded document
    - 0x04: Array
    - 0x08: Boolean
    - 0x10: Int32
    - 0x12: Int64
    """
    result = {}
    
    # Document size
    doc_size = struct.unpack_from('<i', data, offset)[0]
    doc_end = offset + doc_size
    offset += 4
    
    while offset < doc_end - 1:  # -1 for null terminator
        # Element type
        elem_type = data[offset]
        offset += 1
        
        if elem_type == 0x00:  # End of document
            break
            
        # Element name (cstring)
        name_end = data.index(b'\x00', offset)
        name = data[offset:name_end].decode('utf-8', errors='replace')
        offset = name_end + 1
        
        # Parse value based on type
        if elem_type == 0x02:  # String
            value, offset = _parse_bson_string(data, offset)
            result[name] = value
            
        elif elem_type == 0x03:  # Embedded document
            value, offset = _parse_bson_document(data, offset)
            result[name] = value
            
        elif elem_type == 0x04:  # Array
            value, offset = _parse_bson_document(data, offset)
            # Convert dict with numeric keys to list
            result[name] = list(value.values())
            
        elif elem_type == 0x08:  # Boolean
            result[name] = data[offset] != 0
            offset += 1
            
        elif elem_type == 0x10:  # Int32
            result[name] = struct.unpack_from('<i', data, offset)[0]
            offset += 4
            
        elif elem_type == 0x12:  # Int64
            result[name] = struct.unpack_from('<q', data, offset)[0]
            offset += 8
            
        elif elem_type == 0x01:  # Double
            result[name] = struct.unpack_from('<d', data, offset)[0]
            offset += 8
            
        elif elem_type == 0x07:  # ObjectId (12 bytes)
            result[name] = data[offset:offset + 12].hex()
            offset += 12
            
        elif elem_type == 0x09:  # UTC datetime (int64)
            result[name] = struct.unpack_from('<q', data, offset)[0]
            offset += 8
            
        elif elem_type == 0x0A:  # Null
            result[name] = None
            
        elif elem_type == 0x05:  # Binary
            bin_len = struct.unpack_from('<i', data, offset)[0]
            offset += 4
            subtype = data[offset]
            offset += 1
            result[name] = data[offset:offset + bin_len]
            offset += bin_len
            
        else:
            # Unknown type, try to skip
            log.debug(f"Unknown BSON type {hex(elem_type)} for field '{name}'")
            break
    
    return result, doc_end


def read_games_db(db_path: str) -> List[Dict]:
    """
    Reads the Playnite games.db (LiteDB format) and extracts game information.
    
    LiteDB file format:
    - Header page at offset 0
    - Data pages containing BSON documents
    
    Note: LiteDB locks the file when Playnite is running. We copy the file to
    a temp location first to avoid permission errors.
    
    Args:
        db_path: Path to games.db file.
        
    Returns:
        List of game dictionaries with 'name', 'path', 'id' keys.
    """
    games = []
    temp_path = None
    
    try:
        # Copy the file to a temp location to avoid lock issues
        # This is needed because LiteDB locks the file when Playnite is running
        temp_fd, temp_path = tempfile.mkstemp(suffix='.db', prefix='playnite_temp_')
        os.close(temp_fd)  # Close the file descriptor, we'll use shutil.copy2
        
        try:
            shutil.copy2(db_path, temp_path)
            log.debug(f"Copied database to temp location: {temp_path}")
        except PermissionError:
            log.warning(f"Could not copy database file (Playnite may be running). Trying direct read...")
            # If copy fails, try reading directly (might work if file isn't locked)
            temp_path_for_read = db_path
        except Exception as e:
            log.warning(f"Error copying database: {e}. Trying direct read...")
            temp_path_for_read = db_path
        else:
            temp_path_for_read = temp_path
        
        with open(temp_path_for_read, 'rb') as f:
            data = f.read()
        
        log.debug(f"Read {len(data)} bytes from {temp_path_for_read}")
        
        # LiteDB v5 format detection
        # Look for BSON documents by searching for known field patterns
        # The 'Name' field in BSON would be: 0x02 (string type) + "Name\x00" + length + value
        
        # Search for game entries by looking for the pattern of 'Name' field
        offset = 0
        while offset < len(data) - 100:
            # Look for document start that might contain a game
            # We search for "Name" field indicator
            
            try:
                # Find potential BSON string field "Name"
                name_marker = data.find(b'\x02Name\x00', offset)
                
                if name_marker == -1:
                    break
                
                # Try to find the document start before this field
                # Look backwards for a reasonable document size marker
                doc_start = None
                for back_offset in range(max(0, name_marker - 1000), name_marker):
                    try:
                        potential_size = struct.unpack_from('<i', data, back_offset)[0]
                        # Check if this could be a valid document size
                        if 50 < potential_size < 50000:
                            doc_end_pos = back_offset + potential_size
                            # Verify it ends with null byte
                            if doc_end_pos <= len(data) and data[doc_end_pos - 1:doc_end_pos] == b'\x00':
                                doc_start = back_offset
                                break
                    except:
                        continue
                
                if doc_start is not None:
                    try:
                        game_doc, _ = _parse_bson_document(data, doc_start)
                        
                        # Extract the fields we need
                        game_name = game_doc.get('Name')
                        install_dir = game_doc.get('InstallDirectory')
                        game_id = game_doc.get('GameId') or game_doc.get('Id') or game_doc.get('_id')
                        
                        # Only add if we have a name
                        if game_name and isinstance(game_name, str) and len(game_name) > 0:
                            game_entry = {
                                'name': game_name,
                                'id': str(game_id) if game_id else game_name,
                                'path': install_dir if install_dir else '',
                            }
                            
                            # Avoid duplicates
                            if not any(g['name'] == game_name for g in games):
                                games.append(game_entry)
                                log.debug(f"Found game: {game_name}")
                        
                        offset = name_marker + 5
                        
                    except Exception as e:
                        log.debug(f"Failed to parse document at {doc_start}: {e}")
                        offset = name_marker + 5
                else:
                    offset = name_marker + 5
                    
            except Exception as e:
                log.debug(f"Error at offset {offset}: {e}")
                offset += 1
        
        log.info(f"Extracted {len(games)} games from Playnite database")
        
    except FileNotFoundError:
        log.error(f"Playnite database not found: {db_path}")
    except PermissionError:
        log.error(f"Permission denied reading Playnite database: {db_path}. Please close Playnite and try again.")
    except Exception as e:
        log.error(f"Error reading Playnite database: {e}", exc_info=True)
    finally:
        # Clean up temp file
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                log.debug(f"Cleaned up temp file: {temp_path}")
            except Exception as e:
                log.debug(f"Could not remove temp file {temp_path}: {e}")
    
    return games


def find_playnite_profiles(executable_path: str | None = None) -> List[Dict]:
    """
    Finds all games in the Playnite library.
    
    Filters out:
    - Entries without a valid InstallDirectory
    - Entries matching the NON_GAME_BLACKLIST (social media, launchers, etc.)
    
    Args:
        executable_path: Optional path to Playnite executable for portable detection.
        
    Returns:
        List of profile dictionaries with keys:
        - 'id': Game identifier
        - 'name': Game display name  
        - 'path': Installation directory (for save path detection)
        - 'paths': List containing the installation path
    """
    log.info("Attempting to find Playnite profiles...")
    log.debug(f"find_playnite_profiles received executable_path: {executable_path}")
    
    db_path = get_playnite_library_path(executable_path)
    
    if not db_path:
        log.error("Cannot find Playnite profiles: Library path is unknown.")
        return []
    
    log.info(f"Reading Playnite library from: {db_path}")
    games = read_games_db(db_path)
    
    # Convert to profile format expected by the UI, with filtering
    profiles = []
    filtered_count = 0
    
    for game in games:
        game_name = game['name']
        game_path = game.get('path', '')
        
        # Filter 1: Must have a valid install directory
        if not game_path or not os.path.isdir(game_path):
            log.debug(f"Filtered out '{game_name}': No valid install directory")
            filtered_count += 1
            continue
        
        # Filter 2: Must not be in the blacklist
        name_lower = game_name.lower().strip()
        is_blacklisted = False
        for blacklist_item in NON_GAME_BLACKLIST:
            if name_lower == blacklist_item or name_lower.startswith(blacklist_item + ' '):
                log.debug(f"Filtered out '{game_name}': Matches blacklist '{blacklist_item}'")
                is_blacklisted = True
                filtered_count += 1
                break
        
        if is_blacklisted:
            continue
        
        profile = {
            'id': game.get('id', game_name),
            'name': game_name,
            'path': game_path,
            'paths': [game_path],
        }
        profiles.append(profile)
    
    log.info(f"Found {len(profiles)} valid Playnite profiles ({filtered_count} filtered out).")
    return profiles
