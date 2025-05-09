import logging
import os

# Configure basic logging for the test script
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- IMPORTANT: Set this path to one of your .bin VMU dump files ---
# Using the path from your previous logs as a placeholder.
VMU_BIN_FILE_PATH = r"D:\flycast\data\vmu_save_A1.bin" 
# Example: VMU_BIN_FILE_PATH = r"D:\path\to\your\vmu_save_A1.bin"

log.info(f"Attempting to parse VMU file: {VMU_BIN_FILE_PATH}")

if not os.path.exists(VMU_BIN_FILE_PATH):
    log.error(f"VMU file not found at: {VMU_BIN_FILE_PATH}")
    log.error("Please update VMU_BIN_FILE_PATH in this script to a valid .bin file.")
    exit()

try:
    log.info("Attempting to import 'vmut' library...")
    import vmut
    log.info("'vmut' library imported successfully.")
except ImportError as e:
    log.error(f"Failed to import 'vmut' library: {e}")
    log.error("Please ensure 'vmut' (from vmu-tools by slurmking) is installed correctly.")
    exit()

# --- Test 1: Using vmut.vms.load_vms() --- 
log.info("\n--- Test 1: Attempting to load with vmut.vms.load_vms() ---")
try:
    # The example.py for vmut shows vmut.vms.load_vms for .VMS files.
    # Let's see what it does with a .bin (full dump).
    vms_object_from_load = vmut.vms.load_vms(VMU_BIN_FILE_PATH)
    log.info(f"Object type from vmut.vms.load_vms(): {type(vms_object_from_load)}")
    log.info(f"Attributes/methods of object from load_vms(): {dir(vms_object_from_load)}")
    
    if hasattr(vms_object_from_load, 'info'):
        log.info(f"vms_object_from_load.info: {vms_object_from_load.info}")
        if 'description' in vms_object_from_load.info:
            log.info(f"  Description from .info: '{vms_object_from_load.info['description']}'")
    
    # Check for a '.files' attribute or similar that might hold multiple entries
    if hasattr(vms_object_from_load, 'files'):
        log.info("Found a '.files' attribute! Iterating through entries:")
        if vms_object_from_load.files:
            for i, entry in enumerate(vms_object_from_load.files):
                log.info(f"  Entry {i}: {type(entry)}")
                log.info(f"    dir(entry): {dir(entry)}")
                if hasattr(entry, 'header') and entry.header and hasattr(entry.header, 'description'):
                    log.info(f"      Entry description: '{entry.header.description.strip()}'")
                elif hasattr(entry, 'info') and entry.info and 'description' in entry.info:
                     log.info(f"      Entry description (from info): '{entry.info['description'].strip()}'")
                else:
                    log.info("      Entry does not have a clear 'description' field.")
        else:
            log.info("  '.files' attribute is empty or None.")
    else:
        log.info("Object from load_vms() does not have a '.files' attribute.")

except Exception as e:
    log.error(f"Error during Test 1 (vmut.vms.load_vms()): {e}", exc_info=True)

# --- Test 2: Using vmut.Vms_file() --- (As in your flycast_manager.py)
log.info("\n--- Test 2: Attempting to load with vmut.Vms_file() ---")
try:
    # This is what you used in flycast_manager.py, likely from vmut.vms.Vms_file
    # Assuming Vms_file is accessible directly under vmut or vmut.vms
    vms_file_instance = None
    if hasattr(vmut, 'Vms_file'):
        vms_file_instance = vmut.Vms_file(file=VMU_BIN_FILE_PATH)
    elif hasattr(vmut, 'vms') and hasattr(vmut.vms, 'Vms_file'):
        vms_file_instance = vmut.vms.Vms_file(file=VMU_BIN_FILE_PATH)
    else:
        log.warning("Could not find Vms_file class directly under vmut or vmut.vms")

    if vms_file_instance:
        log.info(f"Object type from Vms_file(): {type(vms_file_instance)}")
        log.info(f"Attributes/methods of Vms_file object: {dir(vms_file_instance)}")

        if hasattr(vms_file_instance, 'info'):
            log.info(f"vms_file_instance.info: {vms_file_instance.info}")
            if 'description' in vms_file_instance.info:
                log.info(f"  Description from .info: '{vms_file_instance.info['description']}'")
        
        if hasattr(vms_file_instance, 'files'):
            log.info("Found a '.files' attribute on Vms_file object! Iterating:")
            if vms_file_instance.files:
                for i, entry in enumerate(vms_file_instance.files):
                    log.info(f"  Entry {i}: {type(entry)}")
                    log.info(f"    dir(entry): {dir(entry)}")
                    if hasattr(entry, 'header') and entry.header and hasattr(entry.header, 'description'):
                        log.info(f"      Entry description: '{entry.header.description.strip()}'")
                    elif hasattr(entry, 'info') and entry.info and 'description' in entry.info:
                        log.info(f"      Entry description (from info): '{entry.info['description'].strip()}'")
            else:
                log.info("  '.files' attribute is empty or None.")
        else:
            log.info("Vms_file object does not have a '.files' attribute.")

except Exception as e:
    log.error(f"Error during Test 2 (Vms_file()): {e}", exc_info=True)


# --- Test 3: Speculatively trying to find and use a 'Vmu' class for full dumps ---
# The original vmu-tools by slurmking (source of vmut) has a vmu_tools/vmu.py with a Vmu class.
# This class is designed for full dumps. Let's see if it's accessible via `vmut`.
log.info("\n--- Test 3: Speculatively looking for a 'Vmu' class for full dumps ---")
try:
    VmuDumpClass = None
    if hasattr(vmut, 'Vmu'): # Direct access: vmut.Vmu
        VmuDumpClass = vmut.Vmu
        log.info("Found 'vmut.Vmu'")
    elif hasattr(vmut, 'vmu') and hasattr(vmut.vmu, 'Vmu'): # Access via submodule: vmut.vmu.Vmu
        VmuDumpClass = vmut.vmu.Vmu
        log.info("Found 'vmut.vmu.Vmu'")
    else:
        log.info("Did not find a 'Vmu' class under 'vmut' or 'vmut.vmu'.")

    if VmuDumpClass:
        log.info(f"Attempting to load dump with {VmuDumpClass.__name__}...")
        vmu_dump = VmuDumpClass(filename=VMU_BIN_FILE_PATH)
        log.info(f"Object type from {VmuDumpClass.__name__}: {type(vmu_dump)}")
        log.info(f"Attributes/methods of {VmuDumpClass.__name__} object: {dir(vmu_dump)}")

        if hasattr(vmu_dump, 'files') and vmu_dump.files:
            log.info("VMU Dump object has a '.files' attribute. Iterating through save entries:")
            for i, file_entry in enumerate(vmu_dump.files):
                log.info(f"  File Entry {i}: Type - {type(file_entry)}")
                # The file_entry here should be an instance similar to what Vms_file or load_vms returns for a single VMS
                # It should have a header with game title information.
                log.info(f"    dir(file_entry): {dir(file_entry)}")
                title = "Unknown"
                if hasattr(file_entry, 'header') and file_entry.header:
                    # Common field for game title in VMS header
                    if hasattr(file_entry.header, 'description') and file_entry.header.description:
                        title = file_entry.header.description.strip()
                        log.info(f"      Title (from header.description): '{title}'")
                    elif hasattr(file_entry.header, 'vms_filename') and file_entry.header.vms_filename:
                        # Fallback to VMS filename if description is empty
                        title = file_entry.header.vms_filename.strip()
                        log.info(f"      Title (from header.vms_filename): '{title}'")
                    else:
                        log.warning("      header.description and header.vms_filename are empty or not found.")
                elif hasattr(file_entry, 'info') and file_entry.info:
                     if 'description' in file_entry.info and file_entry.info['description']:
                        title = file_entry.info['description'].strip()
                        log.info(f"      Title (from info['description']): '{title}'")
                     elif 'vms_filename' in file_entry.info and file_entry.info['vms_filename']:
                        title = file_entry.info['vms_filename'].strip()
                        log.info(f"      Title (from info['vms_filename']): '{title}'")
                     else:
                        log.warning("      info['description'] and info['vms_filename'] are empty or not found.")
                else:
                    log.warning("      Could not find .header or .info on file_entry to extract title.")
                log.info(f"      ---> Game Title for entry {i}: {title}")
        elif hasattr(vmu_dump, 'get_files'): # Some libraries use a method
            log.info("VMU Dump object has a '.get_files()' method. Calling it...")
            files_list = vmu_dump.get_files()
            if files_list:
                # Process files_list similar to the .files attribute above
                log.info(f"Iterating through {len(files_list)} entries from get_files():")
                # (Add similar iteration logic as for .files here if needed)
                pass # Placeholder for brevity
            else:
                log.info("'.get_files()' returned an empty list or None.")
        else:
            log.info("VMU Dump object does not seem to have a '.files' attribute or '.get_files()' method for listing entries.")
except Exception as e:
    log.error(f"Error during Test 3 (speculative Vmu class): {e}", exc_info=True)

log.info("\n--- Test Script Finished ---")
log.info("Review the logs above. If a 'Vmu' class was found and it listed file entries with titles, that's the solution!")
log.info("If Test 1 or 2 showed a '.files' attribute with populated entries and titles, that's also a good sign.")
log.info("If all tests fail to list individual game titles from the .bin, the 'vmut' library might not expose this functionality for full dumps easily.")
