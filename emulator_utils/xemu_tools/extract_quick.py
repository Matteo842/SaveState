#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick extraction for known games
"""

import os
import struct
import json

def extract_known_games(raw_path: str = None, output_dir: str = None, known_games: dict = None):
    """Extract saves for known games from XboxHDDReader."""
    
    if raw_path is None:
        raw_path = r'D:\GitHub\xemu_work_dir\xbox_hdd.raw'
    if output_dir is None:
        output_dir = r'D:\GitHub\xemu_work_dir\extracted_saves'
    
    print("🎮 Quick Xbox Save Extraction")
    print("=" * 40)
    
    if not os.path.exists(raw_path):
        print(f"❌ RAW file not found: {raw_path}")
        return
    
    file_size = os.path.getsize(raw_path)
    print(f"📁 File: {raw_path}")
    print(f"📊 Size: {file_size / (1024**3):.2f} GB")
    
    # Known games from XboxHDDReader (use provided or default)
    if known_games is None:
        known_games = {
            '4c410015': 'Mercenaries: Playground of Destruction',
            '5345000f': 'The House of the Dead III'
        }
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Read file in chunks to find saves
    chunk_size = 1024 * 1024  # 1MB chunks
    saves_found = 0
    
    with open(raw_path, 'rb') as f:
        for chunk_start in range(0, file_size, chunk_size):
            f.seek(chunk_start)
            data = f.read(min(chunk_size, file_size - chunk_start))
            
            # Look for known Title IDs
            for tid, game_name in known_games.items():
                tid_bytes = tid.encode('ascii')
                pos = data.find(tid_bytes)
                
                if pos != -1:
                    abs_pos = chunk_start + pos
                    print(f"🎯 Found {game_name} at 0x{abs_pos:x}")
                    
                    # Look for save patterns nearby
                    search_start = max(0, pos - 2048)
                    search_end = min(len(data), pos + 2048)
                    search_area = data[search_start:search_end]
                    
                    save_patterns = {
                        b'UDATA': 'UDATA',
                        b'TDATA': 'TDATA', 
                        b'SaveMeta.xbx': 'SaveMeta',
                        b'SaveGame': 'SaveGame'
                    }
                    
                    found_patterns = []
                    for pattern, name in save_patterns.items():
                        if pattern in search_area:
                            found_patterns.append(name)
                    
                    if found_patterns:
                        print(f"   📄 Save patterns: {', '.join(found_patterns)}")
                        
                        # Extract save data
                        extract_start = max(0, abs_pos - 8192)
                        extract_size = min(16384, file_size - extract_start)
                        
                        f.seek(extract_start)
                        save_data = f.read(extract_size)
                        
                        # Create game directory
                        game_dir = os.path.join(output_dir, f"{tid}_{game_name.replace(' ', '_')}")
                        os.makedirs(game_dir, exist_ok=True)
                        
                        # Save extracted data
                        save_file = os.path.join(game_dir, f"save_{abs_pos:x}.bin")
                        with open(save_file, 'wb') as out:
                            out.write(save_data)
                        
                        print(f"   💾 Saved: {save_file} ({len(save_data)} bytes)")
                        saves_found += 1
    
    print(f"\n✅ Extraction complete!")
    print(f"🎯 Found {saves_found} games with saves")
    print(f"📂 Output: {output_dir}")

def find_game_offset(raw_path: str, target_game_id: str, known_games: dict = None) -> dict:
    """
    Find offset for a specific Xbox game in RAW HDD image.
    Uses the same logic as extract_known_games but returns offset info.
    
    Args:
        raw_path: Path to RAW HDD image
        target_game_id: Specific game ID to find
        known_games: Dict of game_id -> game_name (optional)
        
    Returns:
        Dict with game info if found, empty dict if not found
    """
    if not os.path.exists(raw_path):
        return {}
    
    file_size = os.path.getsize(raw_path)
    
    # Use provided games or default
    if known_games is None:
        known_games = {
            '4c410015': 'Mercenaries: Playground of Destruction',
            '5345000f': 'The House of the Dead III'
        }
    
    # Only look for the target game
    if target_game_id not in known_games:
        return {}
    
    target_name = known_games[target_game_id]
    chunk_size = 1024 * 1024  # 1MB chunks
    
    with open(raw_path, 'rb') as f:
        for chunk_start in range(0, file_size, chunk_size):
            f.seek(chunk_start)
            data = f.read(min(chunk_size, file_size - chunk_start))
            
            # Look for the target Title ID (same logic as original)
            tid_bytes = target_game_id.encode('ascii')
            pos = data.find(tid_bytes)
            
            if pos != -1:
                abs_pos = chunk_start + pos
                
                # Look for save patterns nearby (same logic as original)
                search_start = max(0, pos - 2048)
                search_end = min(len(data), pos + 2048)
                search_area = data[search_start:search_end]
                
                save_patterns = {
                    b'UDATA': 'UDATA',
                    b'TDATA': 'TDATA', 
                    b'SaveMeta.xbx': 'SaveMeta',
                    b'SaveGame': 'SaveGame'
                }
                
                found_patterns = []
                for pattern, name in save_patterns.items():
                    if pattern in search_area:
                        found_patterns.append(name)
                
                # Return the game info even if no specific save patterns found
                # The presence of the game ID is already a good indicator
                return {
                    'id': target_game_id,
                    'name': target_name,
                    'offset': abs_pos,
                    'patterns': found_patterns if found_patterns else ['GameID']
                }
    
    return {}


if __name__ == "__main__":
    extract_known_games()