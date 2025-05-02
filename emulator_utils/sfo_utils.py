# d:\GitHub\SaveState\emulator_utils\sfo_utils.py
import os
import struct
import logging

log = logging.getLogger(__name__)

def parse_param_sfo(sfo_path):
    """Parses a PARAM.SFO file to extract the game title.

    Args:
        sfo_path (str): The absolute path to the PARAM.SFO file.

    Returns:
        str | None: The extracted game title, or None if parsing fails or title not found.
    """
    try:
        with open(sfo_path, 'rb') as f:
            # Read the entire file content
            data = f.read()

        # Basic SFO structure validation (Magic number, version)
        if data[0:4] != b'\x00PSF' or data[4:8] != b'\x01\x01\x00\x00':
            log.warning(f"Invalid SFO magic number or version in {sfo_path}")
            return None

        key_table_start = struct.unpack('<I', data[8:12])[0]
        data_table_start = struct.unpack('<I', data[12:16])[0]
        num_entries = struct.unpack('<I', data[16:20])[0]

        # Iterate through index table entries
        index_table_offset = 20
        for i in range(num_entries):
            entry_offset = index_table_offset + (i * 16)

            key_offset = struct.unpack('<H', data[entry_offset:entry_offset + 2])[0]
            # data_fmt = struct.unpack('<H', data[entry_offset + 2:entry_offset + 4])[0]
            data_len = struct.unpack('<I', data[entry_offset + 4:entry_offset + 8])[0]
            data_max_len = struct.unpack('<I', data[entry_offset + 8:entry_offset + 12])[0]
            data_offset = struct.unpack('<I', data[entry_offset + 12:entry_offset + 16])[0]

            # Read the key string
            key_start = key_table_start + key_offset
            key_end = data.find(b'\x00', key_start)
            key = data[key_start:key_end].decode('utf-8', errors='ignore')

            # Check if this is the TITLE key
            if key == 'TITLE':
                # Read the title data (UTF-8 string)
                value_start = data_table_start + data_offset
                # Read up to data_len, ensuring we don't exceed buffer, stop at null terminator
                value_end = value_start + data_len
                raw_value = data[value_start:value_end]
                # Find the actual null terminator within the read data
                null_term_pos = raw_value.find(b'\x00')
                if null_term_pos != -1:
                    title = raw_value[:null_term_pos].decode('utf-8', errors='ignore').strip()
                else:
                    # If no null terminator found within data_len, decode the whole chunk
                    title = raw_value.decode('utf-8', errors='ignore').strip()

                log.debug(f"Extracted Title '{title}' from {sfo_path}")
                return title

        log.warning(f"'TITLE' key not found in {sfo_path}")
        return None

    except FileNotFoundError:
        log.error(f"PARAM.SFO file not found at: {sfo_path}")
        return None
    except Exception as e:
        log.error(f"Error parsing {sfo_path}: {e}", exc_info=True)
        return None
