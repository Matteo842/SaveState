# emulator_utils/ymir_manager.py
# -*- coding: utf-8 -*-
r"""
Ymir Emulator Manager
Ymir is a Sega Saturn emulator by StrikerX3.

Supports two modes:
- Installed Mode: Saves to %APPDATA%\StrikerX3\Ymir\
- Portable Mode: Saves to the directory where the executable is located

Save files structure (based on source code analysis):
- <profile>/backup/           - Main backup memory images
- <profile>/backup/exported/  - Exported backup files

Backup RAM files:
- bup-int.bin     - Internal backup RAM (32 KiB) - Main save file
- bup-ext-*.bin   - External backup RAM cartridge (various sizes)

Exported save files:
- *.bup           - Standard Saturn backup format (Vmem magic)
- *.ymbup         - Ymir proprietary backup format (YmBP magic)
"""

import os
import logging
import platform
import re
import sys
from typing import Optional, List, Dict

# Handle import for both package and standalone execution
try:
    from utils import sanitize_profile_display_name
except ImportError:
    # Fallback for standalone execution
    def sanitize_profile_display_name(name: str) -> str:
        """Fallback sanitization function."""
        # Remove problematic characters and clean up
        result = re.sub(r'[<>:"/\\|?*]', '', name)
        result = re.sub(r'\s+', ' ', result).strip()
        return result if result else "Unknown"

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Ymir uses SDL_GetPrefPath with these values
YMIR_ORGANIZATION = "StrikerX3"
YMIR_APP_NAME = "Ymir"

# Saturn Backup RAM format constants
BACKUP_RAM_HEADER = b"BackUpRam Format"
INTERNAL_BLOCK_SIZE = 64  # 32 KiB internal backup uses 64-byte blocks


def parse_saturn_backup_ram(file_path: str) -> List[Dict[str, str]]:
    """
    Parse a Saturn Backup RAM file (bup-int.bin) to extract save entries.
    
    Saturn backup RAM format:
    - Block 0: Header ("BackUpRam Format" repeated)
    - Block 1: Empty (null block)
    - Block 2+: Save file entries
    
    Each save entry (at block start):
    - 0x00: Flag (0x80 = in use)
    - 0x04: Filename (11 bytes, null-terminated)
    - 0x0F: Language (1 byte)
    - 0x10: Comment (10 bytes, null-terminated)
    - 0x1A: Date (4 bytes, big-endian, minutes since 1980-01-01)
    - 0x1E: Data size (4 bytes, big-endian)
    
    Returns:
        List of save entries with 'filename', 'comment', 'size' keys
    """
    saves = []
    
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        log.error(f"Ymir: Unable to read backup RAM file '{file_path}': {e}")
        return saves
    
    file_size = len(data)
    
    # Determine block size based on file size
    # Internal: 32 KiB with 64-byte blocks
    # External: 512 KiB+ with 512-byte blocks (or 1024 for 4MB)
    if file_size == 32 * 1024:
        block_size = 64
    elif file_size == 512 * 1024:
        block_size = 512
    elif file_size == 1024 * 1024:
        block_size = 512
    elif file_size == 2 * 1024 * 1024:
        block_size = 512
    elif file_size == 4 * 1024 * 1024:
        block_size = 1024
    else:
        log.warning(f"Ymir: Unknown backup RAM size: {file_size} bytes")
        return saves
    
    total_blocks = file_size // block_size
    
    # Verify header (first block should be "BackUpRam Format" repeated)
    if len(data) < 16 or data[:16] != BACKUP_RAM_HEADER:
        log.warning(f"Ymir: Invalid backup RAM header in '{file_path}'")
        return saves
    
    # Scan blocks starting from block 2 (blocks 0 and 1 are header/null)
    for block_idx in range(2, total_blocks):
        offset = block_idx * block_size
        
        if offset + 0x22 > file_size:
            break
        
        # Check if block is in use (flag byte at offset 0x00 has bit 7 set)
        flag = data[offset]
        if (flag & 0x80) == 0:
            continue
        
        # Check padding bytes (0x01-0x03 should be 0x00)
        if data[offset + 1] != 0 or data[offset + 2] != 0 or data[offset + 3] != 0:
            continue
        
        # Read filename (11 bytes at offset 0x04)
        filename_bytes = data[offset + 0x04:offset + 0x04 + 11]
        try:
            # Try Shift-JIS first (Japanese games), then ASCII
            try:
                filename = filename_bytes.decode('shift_jis').rstrip('\x00 ')
            except UnicodeDecodeError:
                filename = filename_bytes.decode('latin-1').rstrip('\x00 ')
        except Exception:
            filename = filename_bytes.hex()
        
        if not filename:
            continue
        
        # Read comment (10 bytes at offset 0x10)
        comment_bytes = data[offset + 0x10:offset + 0x10 + 10]
        try:
            try:
                comment = comment_bytes.decode('shift_jis').rstrip('\x00 ')
            except UnicodeDecodeError:
                comment = comment_bytes.decode('latin-1').rstrip('\x00 ')
        except Exception:
            comment = ""
        
        # Debug: log raw bytes for analysis
        log.debug(f"Ymir: Raw save entry at block {block_idx}:")
        log.debug(f"  Filename bytes: {filename_bytes.hex()} -> '{filename}'")
        log.debug(f"  Comment bytes:  {comment_bytes.hex()} -> '{comment}'")
        
        # Read data size (4 bytes at offset 0x1E, big-endian)
        size_bytes = data[offset + 0x1E:offset + 0x1E + 4]
        if len(size_bytes) == 4:
            size = int.from_bytes(size_bytes, byteorder='big')
        else:
            size = 0
        
        # Validate size
        if size >= file_size - block_size * 2:
            continue
        
        saves.append({
            'filename': filename,
            'comment': comment,
            'size': size
        })
        
        log.debug(f"Ymir: Found save entry - filename='{filename}', comment='{comment}', size={size}")
    
    log.debug(f"Ymir: Parsed {len(saves)} save entries from '{file_path}'")
    return saves


def extract_saturn_save(backup_ram_path: str, game_id: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Extract a single game save from Saturn Backup RAM to a .bup file.
    
    The .bup format (standard Saturn backup format with "Vmem" magic):
    - 0x00-0x03: Magic "Vmem"
    - 0x04-0x07: Save ID (big-endian)
    - 0x08-0x0B: Function call counts (zeros)
    - 0x0C-0x0F: Padding
    - 0x10-0x1B: Filename (12 bytes, null-terminated)
    - 0x1C-0x26: Comment (11 bytes, null-terminated)
    - 0x27: Language
    - 0x28-0x2B: Date (big-endian, minutes since 1980-01-01)
    - 0x2C-0x2F: Data size (big-endian)
    - 0x30-0x31: Block size (big-endian)
    - 0x32-0x33: Padding
    - 0x34-0x37: Date again (big-endian)
    - 0x38-0x3F: Padding
    - 0x40+: Data
    
    Args:
        backup_ram_path: Path to the backup RAM file (bup-int.bin)
        game_id: The game save ID to extract (e.g., "SEGARALLY_0")
        output_path: Optional output path for the .bup file
        
    Returns:
        Path to the extracted .bup file, or None if extraction failed
    """
    log.info(f"Ymir: Extracting save '{game_id}' from '{backup_ram_path}'")
    
    try:
        with open(backup_ram_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        log.error(f"Ymir: Unable to read backup RAM file: {e}")
        return None
    
    file_size = len(data)
    
    # Determine block size
    if file_size == 32 * 1024:
        block_size = 64
    elif file_size == 512 * 1024:
        block_size = 512
    elif file_size == 1024 * 1024:
        block_size = 512
    elif file_size == 2 * 1024 * 1024:
        block_size = 512
    elif file_size == 4 * 1024 * 1024:
        block_size = 1024
    else:
        log.error(f"Ymir: Unknown backup RAM size: {file_size}")
        return None
    
    total_blocks = file_size // block_size
    
    # Find the save entry
    save_block = None
    save_filename = None
    save_comment = None
    save_language = 0
    save_date = 0
    save_size = 0
    
    for block_idx in range(2, total_blocks):
        offset = block_idx * block_size
        
        if offset + 0x22 > file_size:
            break
        
        # Check if block is in use
        flag = data[offset]
        if (flag & 0x80) == 0:
            continue
        
        # Check padding
        if data[offset + 1] != 0 or data[offset + 2] != 0 or data[offset + 3] != 0:
            continue
        
        # Read filename
        filename_bytes = data[offset + 0x04:offset + 0x04 + 11]
        try:
            filename = filename_bytes.decode('shift_jis').rstrip('\x00 ')
        except:
            filename = filename_bytes.decode('latin-1').rstrip('\x00 ')
        
        if filename == game_id:
            save_block = block_idx
            save_filename = filename
            
            # Read comment
            comment_bytes = data[offset + 0x10:offset + 0x10 + 10]
            try:
                save_comment = comment_bytes.decode('shift_jis').rstrip('\x00 ')
            except:
                save_comment = comment_bytes.decode('latin-1').rstrip('\x00 ')
            
            # Read language
            save_language = data[offset + 0x0F]
            
            # Read date (4 bytes big-endian at 0x1A)
            save_date = int.from_bytes(data[offset + 0x1A:offset + 0x1A + 4], byteorder='big')
            
            # Read size (4 bytes big-endian at 0x1E)
            save_size = int.from_bytes(data[offset + 0x1E:offset + 0x1E + 4], byteorder='big')
            
            log.debug(f"Ymir: Found save at block {block_idx}: filename='{filename}', size={save_size}")
            break
    
    if save_block is None:
        log.error(f"Ymir: Save '{game_id}' not found in backup RAM")
        return None
    
    # Read the block list to get all data blocks
    block_list = _read_block_list(data, save_block, block_size, total_blocks)
    log.debug(f"Ymir: Save uses {len(block_list)} blocks: {block_list}")
    
    # Extract the data from all blocks
    save_data = _extract_save_data(data, block_list, block_size, save_size)
    log.debug(f"Ymir: Extracted {len(save_data)} bytes of save data")
    
    # Generate output path if not provided
    if output_path is None:
        output_dir = os.path.dirname(backup_ram_path)
        output_path = os.path.join(output_dir, f"{game_id}.bup")
    
    # Write the .bup file
    try:
        with open(output_path, 'wb') as f:
            # Magic: "Vmem"
            f.write(b'Vmem')
            
            # Save ID (4 bytes) - just use 0
            f.write(b'\x00\x00\x00\x00')
            
            # Function call counts (4 bytes) - zeros
            f.write(b'\x00\x00\x00\x00')
            
            # Padding (4 bytes)
            f.write(b'\x00\x00\x00\x00')
            
            # Filename (12 bytes, null-terminated)
            filename_padded = save_filename.encode('latin-1')[:11].ljust(12, b'\x00')
            f.write(filename_padded)
            
            # Comment (11 bytes, null-terminated)
            comment_padded = (save_comment or '').encode('latin-1')[:10].ljust(11, b'\x00')
            f.write(comment_padded)
            
            # Language (1 byte)
            f.write(bytes([save_language]))
            
            # Date (4 bytes, big-endian)
            f.write(save_date.to_bytes(4, byteorder='big'))
            
            # Data size (4 bytes, big-endian)
            f.write(len(save_data).to_bytes(4, byteorder='big'))
            
            # Block size (2 bytes, big-endian) - number of blocks used
            f.write(len(block_list).to_bytes(2, byteorder='big'))
            
            # Padding (2 bytes)
            f.write(b'\x00\x00')
            
            # Date again (4 bytes, big-endian)
            f.write(save_date.to_bytes(4, byteorder='big'))
            
            # Padding (8 bytes)
            f.write(b'\x00\x00\x00\x00\x00\x00\x00\x00')
            
            # Data
            f.write(save_data)
        
        log.info(f"Ymir: Successfully exported save to '{output_path}'")
        return output_path
        
    except Exception as e:
        log.error(f"Ymir: Failed to write .bup file: {e}")
        return None


def import_saturn_save(backup_ram_path: str, bup_file_path: str, overwrite: bool = True) -> bool:
    """
    Import a .bup save file into Saturn Backup RAM.
    
    This function reads a .bup file (standard Saturn backup format with "Vmem" magic)
    and writes the save data into the backup RAM file (bup-int.bin or similar).
    
    Args:
        backup_ram_path: Path to the backup RAM file (bup-int.bin)
        bup_file_path: Path to the .bup file to import
        overwrite: If True, overwrite existing save with same filename
        
    Returns:
        True if import was successful, False otherwise
    """
    log.info(f"Ymir: Importing save from '{bup_file_path}' into '{backup_ram_path}'")
    
    # Read the .bup file
    try:
        with open(bup_file_path, 'rb') as f:
            bup_data = f.read()
    except Exception as e:
        log.error(f"Ymir: Unable to read .bup file: {e}")
        return False
    
    # Verify magic
    if len(bup_data) < 0x40 or bup_data[:4] != b'Vmem':
        log.error(f"Ymir: Invalid .bup file - missing 'Vmem' magic header")
        return False
    
    # Parse .bup header
    # 0x10-0x1B: Filename (12 bytes, null-terminated)
    filename_bytes = bup_data[0x10:0x1C]
    try:
        filename = filename_bytes.rstrip(b'\x00').decode('latin-1')
    except:
        filename = filename_bytes.rstrip(b'\x00').decode('shift_jis', errors='replace')
    
    # 0x1C-0x26: Comment (11 bytes, null-terminated)
    comment_bytes = bup_data[0x1C:0x27]
    try:
        comment = comment_bytes.rstrip(b'\x00').decode('latin-1')
    except:
        comment = comment_bytes.rstrip(b'\x00').decode('shift_jis', errors='replace')
    
    # 0x27: Language
    language = bup_data[0x27]
    
    # 0x28-0x2B: Date (big-endian)
    date = int.from_bytes(bup_data[0x28:0x2C], byteorder='big')
    
    # 0x2C-0x2F: Data size (big-endian)
    data_size = int.from_bytes(bup_data[0x2C:0x30], byteorder='big')
    
    # 0x40+: Data
    save_data = bup_data[0x40:0x40 + data_size]
    
    if len(save_data) < data_size:
        log.warning(f"Ymir: .bup file has less data than expected ({len(save_data)} < {data_size})")
        data_size = len(save_data)
    
    log.debug(f"Ymir: Parsed .bup file: filename='{filename}', comment='{comment}', size={data_size}")
    
    # Read the backup RAM file
    try:
        with open(backup_ram_path, 'rb') as f:
            ram_data = bytearray(f.read())
    except Exception as e:
        log.error(f"Ymir: Unable to read backup RAM file: {e}")
        return False
    
    file_size = len(ram_data)
    
    # Determine block size
    if file_size == 32 * 1024:
        block_size = 64
    elif file_size == 512 * 1024:
        block_size = 512
    elif file_size == 1024 * 1024:
        block_size = 512
    elif file_size == 2 * 1024 * 1024:
        block_size = 512
    elif file_size == 4 * 1024 * 1024:
        block_size = 1024
    else:
        log.error(f"Ymir: Unknown backup RAM size: {file_size}")
        return False
    
    total_blocks = file_size // block_size
    
    # Verify header
    if ram_data[:16] != BACKUP_RAM_HEADER:
        log.error(f"Ymir: Invalid backup RAM header")
        return False
    
    # Find existing save with same filename (if overwrite is enabled)
    existing_blocks = set()
    if overwrite:
        for block_idx in range(2, total_blocks):
            offset = block_idx * block_size
            if offset + 0x22 > file_size:
                break
            
            flag = ram_data[offset]
            if (flag & 0x80) == 0:
                continue
            
            # Check if padding bytes are correct
            if ram_data[offset + 1] != 0 or ram_data[offset + 2] != 0 or ram_data[offset + 3] != 0:
                continue
            
            # Read filename
            existing_filename_bytes = ram_data[offset + 0x04:offset + 0x04 + 11]
            try:
                existing_filename = existing_filename_bytes.decode('latin-1').rstrip('\x00 ')
            except:
                existing_filename = existing_filename_bytes.decode('shift_jis', errors='replace').rstrip('\x00 ')
            
            if existing_filename == filename:
                log.debug(f"Ymir: Found existing save '{filename}' at block {block_idx}, will overwrite")
                # Get all blocks used by this save
                block_list = _read_block_list(bytes(ram_data), block_idx, block_size, total_blocks)
                existing_blocks = set(block_list)
                
                # Clear all blocks used by this save
                for blk in block_list:
                    blk_offset = blk * block_size
                    ram_data[blk_offset] = 0x00  # Clear flag
                    # Clear the rest of the block (optional but cleaner)
                    for i in range(1, block_size):
                        ram_data[blk_offset + i] = 0x00
                
                log.debug(f"Ymir: Cleared {len(block_list)} blocks from existing save")
                break
    
    # Calculate required blocks
    # We need to fit: block_list (N blocks * 2 bytes + 2 bytes terminator) + save_data
    # First block: header (0x22 bytes) + block list/data
    # Other blocks: reserved (4 bytes) + block list/data
    usable_first_block = block_size - 0x22  # Space after header in first block
    usable_other_block = block_size - 4     # Space after reserved in other blocks
    
    # Iteratively calculate required blocks
    # Block list size depends on number of blocks, which creates a dependency
    estimated_blocks = 1
    while True:
        # Block list: (N-1) entries for other blocks + 1 terminator, each 2 bytes
        block_list_size = estimated_blocks * 2  # N-1 blocks + 1 terminator = N entries
        total_to_store = block_list_size + data_size
        
        # Calculate available space with this many blocks
        if estimated_blocks == 1:
            total_space = usable_first_block
        else:
            total_space = usable_first_block + (estimated_blocks - 1) * usable_other_block
        
        if total_space >= total_to_store:
            break
        
        estimated_blocks += 1
        if estimated_blocks > total_blocks - 2:
            log.error(f"Ymir: Not enough space in backup RAM for save data")
            return False
    
    required_blocks = estimated_blocks
    log.debug(f"Ymir: Save requires {required_blocks} blocks")
    
    # Find free blocks
    free_blocks = []
    for block_idx in range(2, total_blocks):
        offset = block_idx * block_size
        flag = ram_data[offset]
        
        # Block is free if flag doesn't have bit 7 set, OR it was cleared from existing save
        if (flag & 0x80) == 0 or block_idx in existing_blocks:
            free_blocks.append(block_idx)
        
        if len(free_blocks) >= required_blocks:
            break
    
    if len(free_blocks) < required_blocks:
        log.error(f"Ymir: Not enough free blocks. Need {required_blocks}, found {len(free_blocks)}")
        return False
    
    # Allocate blocks
    allocated_blocks = free_blocks[:required_blocks]
    log.debug(f"Ymir: Allocating blocks: {allocated_blocks}")
    
    # Write the save to backup RAM
    first_block = allocated_blocks[0]
    first_offset = first_block * block_size
    
    # Write first block header
    # 0x00: Flag (0x80 = in use)
    ram_data[first_offset] = 0x80
    
    # 0x01-0x03: Padding (zeros)
    ram_data[first_offset + 1] = 0x00
    ram_data[first_offset + 2] = 0x00
    ram_data[first_offset + 3] = 0x00
    
    # 0x04-0x0E: Filename (11 bytes)
    filename_padded = filename.encode('latin-1')[:11].ljust(11, b'\x00')
    ram_data[first_offset + 0x04:first_offset + 0x04 + 11] = filename_padded
    
    # 0x0F: Language
    ram_data[first_offset + 0x0F] = language
    
    # 0x10-0x19: Comment (10 bytes, space-padded to match Saturn format)
    comment_padded = comment.encode('latin-1')[:10].ljust(10, b' ')
    ram_data[first_offset + 0x10:first_offset + 0x10 + 10] = comment_padded
    
    # 0x1A-0x1D: Date (4 bytes, big-endian)
    ram_data[first_offset + 0x1A:first_offset + 0x1E] = date.to_bytes(4, byteorder='big')
    
    # 0x1E-0x21: Data size (4 bytes, big-endian)
    ram_data[first_offset + 0x1E:first_offset + 0x22] = data_size.to_bytes(4, byteorder='big')
    
    # Build the block list entries (all blocks after the first, then terminator)
    block_list_entries = []
    for blk in allocated_blocks[1:]:
        block_list_entries.append(blk.to_bytes(2, byteorder='big'))
    block_list_entries.append(b'\x00\x00')  # Terminator
    
    block_list_bytes = b''.join(block_list_entries)
    block_list_total_size = len(block_list_bytes)
    
    # Now we need to write block list + data across all allocated blocks
    # Block 0: header ends at 0x22, then block list and data
    # Block 1+: 4-byte header (0x00 x 4), then block list continuation or data
    
    # Create a combined buffer of block list + save data
    combined_data = block_list_bytes + save_data
    combined_offset = 0
    
    for i, blk in enumerate(allocated_blocks):
        blk_offset = blk * block_size
        
        if i == 0:
            # First block: already wrote header (0x00-0x21), now write from 0x22
            inner_start = 0x22
        else:
            # Continuation blocks: write 4-byte null header, then data from 0x04
            ram_data[blk_offset] = 0x00  # NOT 0x80 for continuation blocks!
            ram_data[blk_offset + 1] = 0x00
            ram_data[blk_offset + 2] = 0x00
            ram_data[blk_offset + 3] = 0x00
            inner_start = 0x04
        
        available = block_size - inner_start
        remaining = len(combined_data) - combined_offset
        to_write = min(available, remaining)
        
        if to_write > 0:
            write_offset = blk_offset + inner_start
            ram_data[write_offset:write_offset + to_write] = combined_data[combined_offset:combined_offset + to_write]
            combined_offset += to_write
        
        if combined_offset >= len(combined_data):
            break
    
    # Write the modified backup RAM back to file
    try:
        with open(backup_ram_path, 'wb') as f:
            f.write(ram_data)
        log.info(f"Ymir: Successfully imported save '{filename}' into '{backup_ram_path}'")
        return True
    except Exception as e:
        log.error(f"Ymir: Failed to write backup RAM file: {e}")
        return False


def _read_block_list(data: bytes, start_block: int, block_size: int, total_blocks: int) -> List[int]:
    """
    Read the block list (FAT chain) for a save entry.
    
    The block list starts at offset 0x22 in the first block and continues
    as 16-bit big-endian block indices until a 0x0000 terminator.
    """
    block_list = [start_block]
    
    # Start reading block list at offset 0x22 in the first block
    offset = start_block * block_size + 0x22
    list_index = 1
    
    while offset < len(data):
        # Read next block index (2 bytes, big-endian)
        if offset + 2 > len(data):
            break
            
        next_block = int.from_bytes(data[offset:offset + 2], byteorder='big')
        
        if next_block == 0:
            # End of list
            break
        
        if next_block >= total_blocks:
            # Invalid block index
            log.warning(f"Ymir: Invalid block index {next_block} in block list")
            offset += 2
            continue
        
        block_list.append(next_block)
        
        # Advance offset
        offset += 2
        
        # Check if we've reached the end of the current block
        if (offset % block_size) == 0:
            # Move to next block in the chain at offset 0x04
            if list_index < len(block_list):
                offset = block_list[list_index] * block_size + 4
                list_index += 1
    
    return block_list


def _extract_save_data(data: bytes, block_list: List[int], block_size: int, expected_size: int) -> bytes:
    """
    Extract the actual save data from the block chain.
    
    The data layout:
    - First block: 0x00-0x03 flag, 0x04-0x21 header, 0x22+ block list then data
    - Other blocks: 0x00-0x03 reserved, 0x04+ data
    """
    save_data = bytearray()
    block_list_size = len(block_list) * 2  # Each entry is 2 bytes
    
    block_list_remaining = block_list_size
    
    for i, block_idx in enumerate(block_list):
        block_offset = block_idx * block_size
        
        if i == 0:
            # First block: skip header (0x22 bytes)
            inner_offset = 0x22
        else:
            # Other blocks: skip reserved bytes (4 bytes)
            inner_offset = 0x04
        
        available_bytes = block_size - inner_offset
        
        # Skip remaining block list entries
        if block_list_remaining > 0:
            if block_list_remaining >= available_bytes:
                block_list_remaining -= available_bytes
                continue
            else:
                inner_offset += block_list_remaining
                available_bytes -= block_list_remaining
                block_list_remaining = 0
        
        # Read data
        remaining_to_read = expected_size - len(save_data)
        bytes_to_read = min(available_bytes, remaining_to_read)
        
        if bytes_to_read > 0:
            chunk = data[block_offset + inner_offset:block_offset + inner_offset + bytes_to_read]
            save_data.extend(chunk)
        
        if len(save_data) >= expected_size:
            break
    
    return bytes(save_data[:expected_size])


# Saturn game name database - maps save IDs to full game names
# This can be expanded over time
SATURN_GAME_NAMES: Dict[str, str] = {
    # Common games with known save IDs
    'SEGARALLY': 'Sega Rally Championship',
    'SONIC_R': 'Sonic R',
    'NIGHTS': 'NiGHTS into Dreams',
    'PANZER': 'Panzer Dragoon',
    'PANZERSAGA': 'Panzer Dragoon Saga',
    'VF2': 'Virtua Fighter 2',
    'DAYTONA': 'Daytona USA',
    'SAKURA': 'Sakura Taisen',
    'GRANDIA': 'Grandia',
    'SHINING': 'Shining Force III',
    'DRAGONFORCE': 'Dragon Force',
    'GUARDIAN': 'Guardian Heroes',
    'RADIANT': 'Radiant Silvergun',
    'DIEHARD': 'Die Hard Arcade',
    'HOUSEDEAD': 'House of the Dead',
    'VIRTUACOP': 'Virtua Cop',
    'BURNINGR': 'Burning Rangers',
    'CLOCKWORK': 'Clockwork Knight',
    'FIGHTERS': 'Fighters Megamix',
    'LASTBRONX': 'Last Bronx',
    'MARVEL': 'Marvel Super Heroes',
    'XMEN': 'X-Men vs Street Fighter',
    'STREETF': 'Street Fighter',
    'DARKSTALK': 'Darkstalkers',
    'SATBOMB': 'Saturn Bomberman',
    'BOMBERMAN': 'Bomberman',
    'DECATHLET': 'Decathlete',
    'WINTER': 'Winter Heat',
    'STEEP': 'Steep Slope Sliders',
    'SEGA': 'Sega Game',
    'VIRTUA': 'Virtua Game',
}


def _format_saturn_game_name(game_id: str, comment: str = "") -> str:
    """
    Format a Saturn save game ID into a readable name.
    
    Args:
        game_id: The raw save identifier (e.g., "SEGARALLY_0")
        comment: Optional comment from the save entry
        
    Returns:
        A formatted, human-readable game name
    """
    # Remove trailing numbers and underscores (e.g., "SEGARALLY_0" -> "SEGARALLY")
    base_id = re.sub(r'[_\-]\d+$', '', game_id).strip()
    
    # Try exact match first
    if base_id.upper() in SATURN_GAME_NAMES:
        return SATURN_GAME_NAMES[base_id.upper()]
    
    # Try partial match
    for key, name in SATURN_GAME_NAMES.items():
        if key in base_id.upper() or base_id.upper() in key:
            return name
    
    # No match found - format the ID nicely
    # "SEGARALLY" -> "Sega Rally"
    # "SONIC_R" -> "Sonic R"
    formatted = base_id.replace('_', ' ').replace('-', ' ')
    
    # Title case with some intelligence
    words = formatted.split()
    result_words = []
    for word in words:
        if len(word) <= 2:
            result_words.append(word.upper())  # Keep short words uppercase (R, II, etc.)
        else:
            result_words.append(word.capitalize())
    
    result = ' '.join(result_words)
    
    # If we have a useful comment, append it
    if comment and comment.strip() and comment.upper() != result.upper():
        # Don't append if comment is generic like "RECORDS", "DATA", "SAVE"
        if comment.upper() not in ['RECORDS', 'DATA', 'SAVE', 'BACKUP', 'SYSTEM']:
            result = f"{result} ({comment})"
    
    return sanitize_profile_display_name(result)

# Main backup RAM files (Internal backup is the primary save)
INTERNAL_BACKUP_FILE = "bup-int.bin"
EXTERNAL_BACKUP_FILES = [
    "bup-ext-4M.bin",
    "bup-ext-8M.bin", 
    "bup-ext-16M.bin",
    "bup-ext-32M.bin",
    "bup-ext.bin"  # Generic external backup
]

# All backup RAM extensions
# Native Ymir formats
BACKUP_IMAGE_EXTENSIONS = ('.bin', '.sav')
EXPORTED_BACKUP_EXTENSIONS = ('.bup', '.ymbup')

# Other Saturn emulator formats (SSF, Mednafen, etc.) that users might place here
OTHER_SATURN_SAVE_EXTENSIONS = (
    '.bcr',   # Backup Cartridge RAM (SSF, etc.)
    '.bkr',   # Backup RAM / Internal backup
    '.srm',   # SRAM (common format)
    '.smpc',  # SMPC state
    '.ram',   # RAM dump
)


def _parse_desktop_file(desktop_path: str) -> Optional[str]:
    """
    Parse a Linux .desktop file to extract the Exec path.
    
    Args:
        desktop_path: Path to the .desktop file
        
    Returns:
        The executable path from the Exec= line, or None if not found
    """
    try:
        with open(desktop_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('Exec='):
                    # Extract the command (may include arguments)
                    exec_value = line[5:].strip()
                    # Remove any arguments (take first part before space, unless quoted)
                    if exec_value.startswith('"'):
                        # Handle quoted path
                        end_quote = exec_value.find('"', 1)
                        if end_quote > 0:
                            exec_value = exec_value[1:end_quote]
                    else:
                        # Take first word (before any arguments)
                        exec_value = exec_value.split()[0] if exec_value else ""
                    
                    # Remove field codes like %f, %F, %u, %U
                    exec_value = re.sub(r'%[fFuUdDnNickvm]', '', exec_value).strip()
                    
                    if exec_value and os.path.isfile(exec_value):
                        log.debug(f"Ymir: Extracted executable from .desktop: {exec_value}")
                        return exec_value
                    elif exec_value:
                        log.debug(f"Ymir: .desktop Exec path not found as file: {exec_value}")
    except Exception as e:
        log.debug(f"Ymir: Failed to parse .desktop file: {e}")
    
    return None


def get_ymir_base_dirs(executable_path: Optional[str] = None) -> List[str]:
    """
    Returns a list of potential Ymir base directories to check.
    
    Resolution order:
    1. Portable mode: Directory of the executable (if provided)
    2. Installed mode: System-specific paths
    
    Args:
        executable_path: Optional path to the Ymir executable (or .desktop file on Linux)
        
    Returns:
        List of directory paths to check (in priority order)
    """
    potential_dirs = []
    system = platform.system()
    
    # 1. Portable mode - check executable directory first
    if executable_path:
        # Handle Linux .desktop files
        if executable_path.endswith('.desktop') and os.path.isfile(executable_path):
            real_exec = _parse_desktop_file(executable_path)
            if real_exec:
                exe_dir = os.path.dirname(real_exec)
                potential_dirs.append(exe_dir)
                log.debug(f"Ymir: Added portable path from .desktop: {exe_dir}")
        elif os.path.isfile(executable_path):
            exe_dir = os.path.dirname(executable_path)
            potential_dirs.append(exe_dir)
            log.debug(f"Ymir: Added portable path from executable: {exe_dir}")
        elif os.path.isdir(executable_path):
            potential_dirs.append(executable_path)
            log.debug(f"Ymir: Added portable path from directory: {executable_path}")
    
    # 2. Installed mode - system-specific paths
    # Ymir uses SDL_GetPrefPath("StrikerX3", "Ymir") which results in:
    # Windows: %APPDATA%\StrikerX3\Ymir\
    # Linux: ~/.local/share/StrikerX3/Ymir/ or ~/.local/share/Ymir/
    # macOS: ~/Library/Application Support/StrikerX3/Ymir/
    
    if system == "Windows":
        appdata_roaming = os.environ.get('APPDATA')
        if appdata_roaming:
            installed_path = os.path.join(appdata_roaming, YMIR_ORGANIZATION, YMIR_APP_NAME)
            potential_dirs.append(installed_path)
            log.debug(f"Ymir: Added Windows installed path: {installed_path}")
    
    elif system == "Linux":
        user_home = os.path.expanduser("~")
        # SDL uses XDG_DATA_HOME or ~/.local/share
        xdg_data_env = os.environ.get('XDG_DATA_HOME')
        xdg_data = xdg_data_env if xdg_data_env else os.path.join(user_home, ".local", "share")
        
        # Standard path based on user home (always add this first)
        standard_xdg = os.path.join(user_home, ".local", "share")
        
        # Primary path: ~/.local/share/StrikerX3/Ymir/
        linux_path_org = os.path.join(standard_xdg, YMIR_ORGANIZATION, YMIR_APP_NAME)
        potential_dirs.append(linux_path_org)
        log.debug(f"Ymir: Added Linux path (with org): {linux_path_org}")
        
        # Alternative path: ~/.local/share/Ymir/ (some installations)
        linux_path_alt = os.path.join(standard_xdg, YMIR_APP_NAME)
        potential_dirs.append(linux_path_alt)
        log.debug(f"Ymir: Added Linux path (alt): {linux_path_alt}")
        
        # If XDG_DATA_HOME is set and different from standard, also check there
        # (This handles Snap/Flatpak where XDG_DATA_HOME points to sandbox)
        if xdg_data_env and xdg_data != standard_xdg:
            sandbox_path_org = os.path.join(xdg_data, YMIR_ORGANIZATION, YMIR_APP_NAME)
            if sandbox_path_org not in potential_dirs:
                potential_dirs.append(sandbox_path_org)
                log.debug(f"Ymir: Added sandbox path (with org): {sandbox_path_org}")
            
            sandbox_path_alt = os.path.join(xdg_data, YMIR_APP_NAME)
            if sandbox_path_alt not in potential_dirs:
                potential_dirs.append(sandbox_path_alt)
                log.debug(f"Ymir: Added sandbox path (alt): {sandbox_path_alt}")
    
    elif system == "Darwin":  # macOS
        user_home = os.path.expanduser("~")
        macos_path = os.path.join(user_home, "Library", "Application Support", YMIR_ORGANIZATION, YMIR_APP_NAME)
        potential_dirs.append(macos_path)
        log.debug(f"Ymir: Added macOS path: {macos_path}")
    
    return potential_dirs


def get_ymir_backup_dirs(executable_path: Optional[str] = None) -> List[str]:
    """
    Determine all Ymir directories that contain backup/save files.
    
    Ymir can store saves in multiple locations:
    - <profile>/backup/     - Standard backup memory location
    - <profile>/state/      - Persistent state (also contains bup-int.bin in portable mode!)
    
    Args:
        executable_path: Optional path to the Ymir executable
        
    Returns:
        List of directories containing save files
    """
    base_dirs = get_ymir_base_dirs(executable_path)
    found_dirs: List[str] = []
    
    log.info(f"Ymir: Checking base directories: {base_dirs}")  # DEBUG TEMP
    
    all_extensions = BACKUP_IMAGE_EXTENSIONS + EXPORTED_BACKUP_EXTENSIONS + OTHER_SATURN_SAVE_EXTENSIONS
    
    for base_dir in base_dirs:
        if not os.path.isdir(base_dir):
            log.info(f"Ymir: Base directory does not exist: {base_dir}")  # DEBUG TEMP
            continue
        
        log.info(f"Ymir: Checking existing base directory: {base_dir}")  # DEBUG TEMP
        
        # Check for 'backup' subdirectory (Ymir's standard structure)
        backup_path = os.path.join(base_dir, "backup")
        if os.path.isdir(backup_path):
            # Verify it has save files
            try:
                for entry in os.listdir(backup_path):
                    if entry.lower().endswith(all_extensions):
                        log.debug(f"Ymir: Found backup directory with saves: {backup_path}")
                        found_dirs.append(backup_path)
                        break
            except OSError:
                pass
        
        # Check for 'state' subdirectory (portable mode stores bup-int.bin here!)
        state_path = os.path.join(base_dir, "state")
        log.info(f"Ymir: Checking state path: {state_path}, exists={os.path.isdir(state_path)}")  # DEBUG TEMP
        if os.path.isdir(state_path):
            # Check specifically for bup-int.bin or other backup files
            internal_backup = os.path.join(state_path, INTERNAL_BACKUP_FILE)
            log.info(f"Ymir: Checking bup-int.bin: {internal_backup}, exists={os.path.isfile(internal_backup)}")  # DEBUG TEMP
            if os.path.isfile(internal_backup):
                log.debug(f"Ymir: Found backup RAM in state directory: {state_path}")
                found_dirs.append(state_path)
            else:
                # Check for other save files
                try:
                    for entry in os.listdir(state_path):
                        if entry.lower().endswith(all_extensions):
                            log.debug(f"Ymir: Found save files in state directory: {state_path}")
                            found_dirs.append(state_path)
                            break
                except OSError:
                    pass
        
        # Check if backup files exist directly in base directory
        internal_backup = os.path.join(base_dir, INTERNAL_BACKUP_FILE)
        if os.path.isfile(internal_backup):
            log.debug(f"Ymir: Found backup files in base directory: {base_dir}")
            found_dirs.append(base_dir)
        else:
            # Check for other Saturn save formats in base directory
            try:
                for entry in os.listdir(base_dir):
                    if entry.lower().endswith(all_extensions):
                        log.debug(f"Ymir: Found Saturn save files in base directory: {base_dir}")
                        found_dirs.append(base_dir)
                        break
            except OSError:
                pass
    
    if not found_dirs:
        log.warning("Ymir: Could not find any backup directories")
    
    return found_dirs


def find_ymir_profiles(custom_path: Optional[str] = None) -> Optional[List[Dict[str, object]]]:
    """
    Find and list Ymir save profiles.
    
    Ymir stores saves in backup RAM images:
    - bup-int.bin: Internal backup RAM (main saves)
    - bup-ext-*.bin: External backup RAM cartridge
    
    Also checks for exported save files (.bup, .ymbup).
    
    Searches in multiple directories:
    - <profile>/backup/  - Standard backup location
    - <profile>/state/   - Persistent state (portable mode stores saves here!)
    
    Args:
        custom_path: Optional path to the Ymir executable or data directory
        
    Returns:
        List of profile dictionaries, or None if no backup directories found
    """
    log.info("Ymir: Scanning for save profiles...")
    
    backup_dirs = get_ymir_backup_dirs(custom_path)
    
    if not backup_dirs:
        log.warning("Ymir: No backup directories found. Cannot list profiles.")
        return None
    
    profiles: List[Dict[str, object]] = []
    
    # Collect all backup files from all directories
    backup_files: List[str] = []
    
    # All recognized save extensions
    all_save_extensions = (
        BACKUP_IMAGE_EXTENSIONS + 
        EXPORTED_BACKUP_EXTENSIONS + 
        OTHER_SATURN_SAVE_EXTENSIONS
    )
    
    for backup_dir in backup_dirs:
        try:
            # Check this backup directory
            for entry in os.listdir(backup_dir):
                full_path = os.path.join(backup_dir, entry)
                if os.path.isfile(full_path):
                    # Check for any recognized save file
                    if entry.lower().endswith(all_save_extensions):
                        if full_path not in backup_files:  # Avoid duplicates
                            backup_files.append(full_path)
            
            # Check exported subdirectory if it exists
            exported_dir = os.path.join(backup_dir, "exported")
            if os.path.isdir(exported_dir):
                for entry in os.listdir(exported_dir):
                    full_path = os.path.join(exported_dir, entry)
                    if os.path.isfile(full_path) and entry.lower().endswith(all_save_extensions):
                        if full_path not in backup_files:
                            backup_files.append(full_path)
                        
        except OSError as e:
            log.error(f"Ymir: Unable to list directory '{backup_dir}': {e}")
            continue
    
    if not backup_files:
        log.debug(f"Ymir: No backup files found in directory: {backup_dir}")
        return []
    
    # Group files by type
    internal_backup_path = None
    external_backup_paths: List[str] = []
    exported_paths: List[str] = []
    other_saturn_saves: List[str] = []
    
    for file_path in backup_files:
        filename = os.path.basename(file_path).lower()
        
        if filename == INTERNAL_BACKUP_FILE.lower():
            internal_backup_path = file_path
        elif any(filename == ext.lower() for ext in EXTERNAL_BACKUP_FILES):
            external_backup_paths.append(file_path)
        elif filename.startswith("bup-ext"):
            external_backup_paths.append(file_path)
        elif filename.endswith(EXPORTED_BACKUP_EXTENSIONS):
            exported_paths.append(file_path)
        elif filename.endswith(OTHER_SATURN_SAVE_EXTENSIONS):
            other_saturn_saves.append(file_path)
        elif filename.endswith(BACKUP_IMAGE_EXTENSIONS):
            external_backup_paths.append(file_path)
    
    # Parse backup RAM files to extract individual game saves
    # Each game save is stored with its source file path
    parsed_games: Dict[str, Dict] = {}  # game_id -> {comment, size, source, source_path}
    
    if internal_backup_path:
        # Parse the internal backup RAM to find individual game saves
        save_entries = parse_saturn_backup_ram(internal_backup_path)
        for entry in save_entries:
            game_id = entry['filename']
            if game_id not in parsed_games:
                parsed_games[game_id] = {
                    'comment': entry['comment'],
                    'size': entry['size'],
                    'source': 'internal',
                    'source_path': internal_backup_path  # Store the specific file path
                }
    
    # Also parse external backup paths
    for ext_path in sorted(external_backup_paths):
        save_entries = parse_saturn_backup_ram(ext_path)
        for entry in save_entries:
            game_id = entry['filename']
            if game_id not in parsed_games:
                parsed_games[game_id] = {
                    'comment': entry['comment'],
                    'size': entry['size'],
                    'source': 'external',
                    'source_path': ext_path  # Store the specific file path
                }
    
    # Create profiles based on parsed games
    if parsed_games:
        # Create individual profiles for each game found in backup RAM
        for game_id, game_info in parsed_games.items():
            comment = game_info['comment']
            source_path = game_info['source_path']
            
            # Use the directory containing the backup RAM file, not the file itself
            # This is required because SaveState validates paths as directories
            source_dir = os.path.dirname(source_path)
            
            # Use filename (game_id) as primary name - it's usually more descriptive
            # Format: "SEGARALLY_0" -> "Sega Rally 0" or lookup in database
            display_name = _format_saturn_game_name(game_id, comment)
            
            profile_id = f"ymir_{re.sub(r'[^a-zA-Z0-9_]', '_', game_id.lower())}"
            
            profiles.append({
                'id': profile_id,
                'name': display_name,
                'paths': [source_dir],  # Directory containing the backup RAM file
                'emulator': 'Ymir',
                'saturn_save_id': game_id  # Store original ID for reference
            })
            log.debug(f"Ymir: Found game '{display_name}' (ID: {game_id}, source: {source_dir})")
    
    elif internal_backup_path:
        # Fallback: couldn't parse, just show generic backup RAM profile
        # Use directory containing the backup RAM file
        backup_dir = os.path.dirname(internal_backup_path)
        profiles.append({
            'id': 'ymir_backup_ram',
            'name': 'Saturn Backup RAM',
            'paths': [backup_dir],
            'emulator': 'Ymir'
        })
        log.debug(f"Ymir: Fallback - showing generic Backup RAM profile at {backup_dir}")
    
    # Group other Saturn saves by game name (from filename stem)
    if other_saturn_saves:
        grouped_saves: Dict[str, List[str]] = {}
        for file_path in other_saturn_saves:
            filename = os.path.basename(file_path)
            stem = os.path.splitext(filename)[0]
            grouped_saves.setdefault(stem, []).append(file_path)
        
        for game_name, file_paths in grouped_saves.items():
            display_name = sanitize_profile_display_name(game_name)
            profile_id = f"ymir_saturn_{re.sub(r'[^a-zA-Z0-9_]', '_', game_name.lower())}"
            
            # Get unique directories containing the save files
            save_dirs = sorted(set(os.path.dirname(fp) for fp in file_paths))
            
            profiles.append({
                'id': profile_id,
                'name': display_name,
                'paths': save_dirs,
                'emulator': 'Ymir'
            })
            log.debug(f"Ymir: Found Saturn save '{display_name}' in {len(save_dirs)} directory(ies)")
    
    # Create profiles for exported saves (individual game saves)
    # Group by directory to avoid creating multiple profiles for same location
    exported_dirs: Dict[str, List[str]] = {}
    for exported_path in exported_paths:
        export_dir = os.path.dirname(exported_path)
        exported_dirs.setdefault(export_dir, []).append(exported_path)
    
    for export_dir, files in exported_dirs.items():
        # Use the first file's name for the profile name
        first_file = sorted(files)[0]
        filename = os.path.basename(first_file)
        stem = os.path.splitext(filename)[0]
        
        # Extract game name from filename (format: GAMENAME_YYYYMMDD_HHMM.bup)
        display_name = stem
        # Try to extract just the game identifier
        parts = stem.rsplit('_', 2)
        if len(parts) >= 3:
            # Remove date/time parts
            display_name = parts[0]
        
        display_name = sanitize_profile_display_name(display_name)
        profile_id = f"ymir_exported_{re.sub(r'[^a-zA-Z0-9_]', '_', os.path.basename(export_dir).lower())}"
        
        profiles.append({
            'id': profile_id,
            'name': f"{display_name} (Exported)",
            'paths': [export_dir],
            'emulator': 'Ymir'
        })
        log.debug(f"Ymir: Found exported saves in '{export_dir}' ({len(files)} file(s))")
    
    log.info(f"Ymir: Built {len(profiles)} profile(s) from {len(backup_dirs)} directory(ies)")
    return profiles


# For testing this module directly
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    print("=" * 60)
    print("YMIR MANAGER TEST")
    print("=" * 60)
    print()
    
    # Check command line arguments for extraction test
    if len(sys.argv) > 1 and sys.argv[1] == "--extract":
        # Test extraction mode
        if len(sys.argv) < 4:
            print("Usage: python ymir_manager.py --extract <backup_ram_path> <game_id>")
            print("Example: python ymir_manager.py --extract D:\\ymir\\state\\bup-int.bin SEGARALLY_0")
            sys.exit(1)
        
        backup_path = sys.argv[2]
        game_id = sys.argv[3]
        
        print(f"Extracting save '{game_id}' from '{backup_path}'...")
        result = extract_saturn_save(backup_path, game_id)
        
        if result:
            print(f"\n[OK] SUCCESS! Extracted to: {result}")
            print(f"     File size: {os.path.getsize(result)} bytes")
        else:
            print("\n[FAIL] FAILED! Check logs above for details.")
        
        sys.exit(0 if result else 1)
    
    # Check command line arguments for import test
    if len(sys.argv) > 1 and sys.argv[1] == "--import":
        # Test import mode
        if len(sys.argv) < 4:
            print("Usage: python ymir_manager.py --import <backup_ram_path> <bup_file_path>")
            print("Example: python ymir_manager.py --import D:\\ymir\\state\\bup-int.bin D:\\ymir\\state\\SEGARALLY_0.bup")
            sys.exit(1)
        
        backup_path = sys.argv[2]
        bup_path = sys.argv[3]
        
        print(f"Importing save from '{bup_path}' into '{backup_path}'...")
        result = import_saturn_save(backup_path, bup_path)
        
        if result:
            print(f"\n[OK] SUCCESS! Save imported successfully.")
        else:
            print("\n[FAIL] FAILED! Check logs above for details.")
        
        sys.exit(0 if result else 1)
    
    # Check for optional custom path argument
    custom_path = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        custom_path = sys.argv[1]
        print(f"Using custom path: {custom_path}")
        print()
    
    print(f"Organization: {YMIR_ORGANIZATION}")
    print(f"App Name: {YMIR_APP_NAME}")
    print()
    
    # Show expected paths
    print("Expected paths to check:")
    for path in get_ymir_base_dirs(custom_path):
        exists = "EXISTS" if os.path.isdir(path) else "NOT FOUND"
        print(f"  [{exists}] {path}")
    print()
    
    # Test with provided path or default paths
    found = find_ymir_profiles(custom_path)
    
    if found is None:
        print("Ymir backup directory not found automatically.")
        print("This could mean:")
        print("  - Ymir is not installed")
        print("  - Ymir has not created any saves yet")
        print("  - Ymir uses a non-standard path")
    elif not found:
        print("No Ymir saves detected in the found directory.")
    else:
        print(f"Found {len(found)} Ymir profile(s):")
        for p in found:
            paths = p.get('paths', [])
            saturn_id = p.get('saturn_save_id', 'N/A')
            print(f"  - {p['name']}")
            print(f"    Saturn Save ID: {saturn_id}")
            print(f"    Profile ID: {p['id']}")
            print(f"    Files: {len(paths)}")
            for path in paths:
                print(f"      - {os.path.basename(path)}")
        
        # Offer extraction test
        print()
        print("=" * 60)
        print("EXTRACTION TEST")
        print("=" * 60)
        print()
        
        # Find the backup RAM file
        backup_ram_file = None
        for p in found:
            for path in p.get('paths', []):
                if os.path.basename(path).lower() == 'bup-int.bin':
                    backup_ram_file = path
                    break
            if backup_ram_file:
                break
        
        if backup_ram_file:
            print(f"Found backup RAM: {backup_ram_file}")
            print()
            
            # Extract all saves
            for p in found:
                saturn_id = p.get('saturn_save_id')
                if saturn_id:
                    print(f"Extracting '{saturn_id}'...")
                    output_path = extract_saturn_save(backup_ram_file, saturn_id)
                    if output_path:
                        print(f"  [OK] Success: {output_path} ({os.path.getsize(output_path)} bytes)")
                    else:
                        print(f"  [FAIL] Failed!")
        else:
            print("No backup RAM file found for extraction test.")
        
        print()
        print("To test extraction manually:")
        print(f"  python ymir_manager.py --extract <path_to_bup-int.bin> <GAME_ID>")
