#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Final extraction script for Xbox saves
"""

import os
import struct
import json

def extract_xbox_saves_final(raw_path: str = None, output_dir: str = None, game_positions: list = None):
    """Extract Xbox saves using known offsets."""
    
    if raw_path is None:
        raw_path = r'D:\GitHub\xemu_work_dir\xbox_hdd.raw'
    if output_dir is None:
        output_dir = r'D:\GitHub\xemu_work_dir\extracted_saves_final'
    
    print("🎮 Xbox Save Final Extraction")
    print("=" * 40)
    
    if not os.path.exists(raw_path):
        print(f"❌ RAW file not found: {raw_path}")
        return
    
    file_size = os.path.getsize(raw_path)
    print(f"📁 File: {raw_path}")
    print(f"📊 Size: {file_size / (1024**3):.2f} GB")
    
    # Known game positions from previous scan (use provided or default)
    if game_positions is None:
        game_positions = [
            {'tid': '4c410015', 'name': 'Mercenaries', 'offset': 0xabfb7002},
            {'tid': '5345000f', 'name': 'HouseOfTheDead3', 'offset': 0xabfb7042}
        ]
    
    os.makedirs(output_dir, exist_ok=True)
    
    saves_found = 0
    
    with open(raw_path, 'rb') as f:
        for game in game_positions:
            print(f"\n🎯 Processing {game['name']}...")
            
            # Read a larger chunk around the Title ID
            read_start = max(0, game['offset'] - 0x10000)  # 64KB before
            read_size = min(0x20000, file_size - read_start)  # 128KB total
            
            f.seek(read_start)
            data = f.read(read_size)
            
            # Look for save patterns
            save_patterns = {
                b'UDATA': 'UDATA',
                b'TDATA': 'TDATA', 
                b'SaveMeta.xbx': 'SaveMeta',
                b'SaveGame': 'SaveGame',
                b'XBXS': 'XboxSave'
            }
            
            found_patterns = []
            for pattern, name in save_patterns.items():
                pos = data.find(pattern)
                if pos != -1:
                    abs_pos = read_start + pos
                    found_patterns.append((name, abs_pos))
            
            if found_patterns:
                print(f"   📄 Found {len(found_patterns)} save patterns")
                
                # Create game directory
                game_dir = os.path.join(output_dir, f"{game['tid']}_{game['name']}")
                os.makedirs(game_dir, exist_ok=True)
                
                # Extract the entire save area
                extract_start = read_start
                extract_size = read_size
                
                f.seek(extract_start)
                save_data = f.read(extract_size)
                
                # Save the data
                save_file = os.path.join(game_dir, f"save_area_{extract_start:x}.bin")
                with open(save_file, 'wb') as out:
                    out.write(save_data)
                
                print(f"   💾 Saved: {save_file} ({len(save_data)} bytes)")
                
                # Also extract individual patterns
                for pattern_name, pattern_offset in found_patterns:
                    # Extract pattern context
                    context_start = max(0, pattern_offset - 0x1000)
                    context_size = min(0x2000, file_size - context_start)
                    
                    f.seek(context_start)
                    context_data = f.read(context_size)
                    
                    pattern_file = os.path.join(game_dir, f"{pattern_name}_{pattern_offset:x}.bin")
                    with open(pattern_file, 'wb') as out:
                        out.write(context_data)
                    
                    print(f"   📄 {pattern_name}: {pattern_file}")
                
                saves_found += 1
    
    print(f"\n✅ Final extraction complete!")
    print(f"🎯 Found {saves_found} games with saves")
    print(f"📂 Output: {output_dir}")

if __name__ == "__main__":
    extract_xbox_saves_final()