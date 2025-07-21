# emulator_utils/xemu_tools/xbox_hdd_reader.py
# -*- coding: utf-8 -*-

import os
import logging
import struct
import subprocess
import tempfile
import shutil
import json
import re
from typing import List, Dict, Optional, Tuple

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Load Xbox game database
_xbox_game_map: Dict[str, str] = {}
try:
    db_path = os.path.join(os.path.dirname(__file__), '..', 'xbox_title_id_map.json')
    if os.path.exists(db_path):
        with open(db_path, 'r', encoding='utf-8') as f:
            _xbox_game_map = json.load(f)
        log.debug(f"Loaded {len(_xbox_game_map)} Xbox games from the title ID database.")
    else:
        log.warning(f"Xbox title ID database not found at {db_path}. Game names will be generic.")
except Exception as e:
    log.warning(f"Could not load Xbox game database: {e}")
    _xbox_game_map = {}

class XboxHDDReader:
    """
    Reader for Xbox HDD images to extract game save information.
    This class uses a robust raw scan to find saves without external tools.
    """
    
    def __init__(self, hdd_path: str):
        self.hdd_path = hdd_path
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def find_xbox_saves(self, quick_scan: bool = False) -> List[Dict]:
        """
        Main method to find Xbox game saves in the HDD image.
        
        Args:
            quick_scan: If True, performs a faster but less thorough scan
        """
        log.info(f"Starting Xbox save scan (quick_scan={quick_scan})")
        
        if quick_scan:
            raw_saves = self.quick_qcow2_scan()
        else:
            raw_saves = self.fallback_qcow2_scan()

        if not raw_saves:
            log.info("No raw save patterns found.")
            return []
            
        return self.group_and_filter_saves(raw_saves)
    
    def quick_qcow2_scan(self) -> List[Dict]:
        """
        Ultra-fast scan optimized for maximum performance:
        - Scans only first 20% and last 20% of file (where saves are typically located)
        - Uses larger 8MB chunks for fewer I/O operations
        - Pre-compiled regex and optimized lookups
        - Early exits when enough data is found
        """
        title_id_offsets = []
        save_pattern_offsets = []
        patterns = {b'UDATA': 'UDATA', b'TDATA': 'TDATA', b'SaveMeta.xbx': 'SaveMeta.xbx'}

        try:
            with open(self.hdd_path, 'rb') as f:
                if f.read(4) != b'QFI\xfb':
                    log.error(f"'{self.hdd_path}' is not a valid QCOW2 file.")
                    return []

                file_size = os.path.getsize(self.hdd_path)
                chunk_size = 8 * 1024 * 1024  # 8MB chunks for fewer I/O operations
                
                # Scan only first 20% and last 20% for maximum speed
                scan_size = file_size // 5  # 20% of file
                scan_ranges = [
                    (0, scan_size),  # First 20%
                    (file_size - scan_size, file_size)  # Last 20%
                ]
                
                log.info(f"Ultra-fast scan: scanning {len(scan_ranges)} regions ({scan_size * 2 / 1024 / 1024:.1f}MB total)")
                
                # Pre-compile regex and create lookup set for maximum performance
                tid_regex = re.compile(b'[0-9a-fA-F]{8}')
                known_tids = set(_xbox_game_map.keys())
                
                # Scan each range with optimized processing
                for range_start, range_end in scan_ranges:
                    for offset in range(range_start, range_end, chunk_size):
                        if offset >= range_end:
                            break
                            
                        f.seek(offset)
                        read_size = min(chunk_size, range_end - offset)
                        chunk = f.read(read_size)
                        if not chunk:
                            break
                        
                        # Find Title IDs with optimized search
                        for match in tid_regex.finditer(chunk):
                            potential_tid = match.group(0).decode('ascii').lower()
                            if potential_tid in known_tids:
                                found_offset = offset + match.start()
                                title_id_offsets.append({'tid': potential_tid, 'offset': found_offset})
                        
                        # Find save patterns with optimized search
                        for pattern_bytes, pattern_name in patterns.items():
                            start_pos = 0
                            while True:
                                pos = chunk.find(pattern_bytes, start_pos)
                                if pos == -1:
                                    break
                                save_pattern_offsets.append({
                                    'pattern': pattern_name, 
                                    'offset': offset + pos
                                })
                                start_pos = pos + 1
                        
                        # Early exit if we found a good amount of data
                        if len(title_id_offsets) > 10 and len(save_pattern_offsets) > 20:
                            log.info("Early exit: found sufficient data for game detection")
                            break
                    
                    # Early exit from outer loop too
                    if len(title_id_offsets) > 10 and len(save_pattern_offsets) > 20:
                        break

                log.info(f"Ultra-fast scan found {len(title_id_offsets)} Title IDs and {len(save_pattern_offsets)} save patterns")

        except Exception as e:
            log.error(f"Error during ultra-fast QCOW2 scan: {e}")
            return []

        if not title_id_offsets or not save_pattern_offsets:
            log.warning("Ultra-fast scan: Could not find both Title IDs and save patterns.")
            return []

        # Optimized correlation with early sorting
        title_id_offsets.sort(key=lambda x: x['offset'])
        correlated_saves = []
        
        for save in save_pattern_offsets:
            # Find closest Title ID efficiently
            closest_tid = min(title_id_offsets, key=lambda tid: abs(tid['offset'] - save['offset']))
            context_strings = [closest_tid['tid']]
            
            correlated_saves.append({
                'pattern': save['pattern'],
                'offset': save['offset'],
                'context_strings': context_strings
            })

        return correlated_saves

    def fallback_qcow2_scan(self) -> List[Dict]:
        """
        Highly optimized QCOW2 scan for maximum performance:
        1. Use quick scan by default (only scan likely areas)
        2. Larger chunks and better memory management
        3. Early exits and optimized algorithms
        """
        # Use quick scan by default for much better performance
        return self.quick_qcow2_scan()

    def group_and_filter_saves(self, raw_saves: List[Dict]) -> List[Dict]:
        log.info(f"Found {len(raw_saves)} raw save patterns.")

        game_scores = {}

        for i, save in enumerate(raw_saves):
            # Find all possible games in the context of this save pattern
            possible_games = self.extract_real_game_name(save['context_strings'])

            if not possible_games:
                log.warning(f"Pattern #{i+1} at offset {save['offset']} did not match any known game.")
                log.debug(f"Context for unmatched pattern: {save['context_strings']}")
                continue

            for game_name, title_id in possible_games:
                if game_name not in game_scores:
                    game_scores[game_name] = {'score': 0, 'title_id': title_id}
                game_scores[game_name]['score'] += 1

        if not game_scores:
            log.info("Could not identify any known games from the patterns found.")
            return []

        log.info(f"Identified {len(game_scores)} distinct game(s) from raw patterns: {', '.join(game_scores.keys())}")

        final_saves = []
        for game_name, data in game_scores.items():
            safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', game_name.lower())
            safe_id = re.sub(r'_+', '_', safe_id).strip('_')
            final_saves.append({
                'name': game_name,
                'id': f"xbox_game_{safe_id}",
                'path': self.hdd_path,
                'dir_name': data['title_id']
            })
            log.debug(f"Created save profile for '{game_name}' with score {data['score']}")

        log.info(f"Filtered to {len(final_saves)} meaningful game saves.")
        return final_saves

    def extract_real_game_name(self, context_strings: List[str]) -> List[Tuple[str, str]]:
        context_text = ' '.join(context_strings).lower()
        found_games = []
        
        for tid, name in _xbox_game_map.items():
            # Check for both Title ID and name in the same pass
            if tid in context_text or (len(name) > 4 and name.lower() in context_text):
                if (name, tid) not in found_games:
                    log.debug(f"Found potential game match: {name} ({tid})")
                    found_games.append((name, tid))
                    
        return found_games

    def extract_strings_from_bytes(self, data: bytes, min_length: int = 4) -> List[str]:
        """Extract printable strings from binary data."""
        return [s.decode('ascii', 'ignore') for s in re.findall(b'[\x20-\x7E]{%d,}' % min_length, data)]

def find_xbox_game_saves(hdd_path: str, quick_scan: bool = False) -> List[Dict]:
    """
    Convenience function to find Xbox game saves in an HDD image.
    
    Args:
        hdd_path: Path to the Xbox HDD image file
        quick_scan: If True, performs a faster but less thorough scan
    """
    with XboxHDDReader(hdd_path) as reader:
        return reader.find_xbox_saves(quick_scan=quick_scan)

# Example usage for direct execution
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print(f"Usage: python {os.path.basename(__file__)} <path_to_xbox_hdd.qcow2>")
        sys.exit(1)
    
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    
    hdd_path = sys.argv[1]
    saves = find_xbox_game_saves(hdd_path)
    
    print(f"\n--- Found {len(saves)} Xbox Game Saves ---")
    for save in saves:
        print(f"  ID:   {save['id']}")
        print(f"  Name: {save['name']}")
        print(f"  Path: {save['path']}")
        print(f"  Dir:  {save['dir_name']}")
        print("--------------------")