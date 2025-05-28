# emulator_utils/pcsx2_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
from typing import List, Dict, Optional
from .pcsx2_mymc.ps2mc import ps2mc
from .pcsx2_mymc.ps2mc_dir import mode_is_file, mode_is_dir, DF_DIR, DF_EXISTS, DF_FILE, DF_RWX, DF_0400
from .pcsx2_mymc.ps2iconsys import IconSys
import configparser  # to read PCSX2 config for memcard paths
import unicodedata  # for normalization of fullwidth characters

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


def get_pcsx2_memcard_path(custom_path: Optional[str] = None) -> Optional[str]:
    """Determine PCSX2 memcard directory or use custom path."""
    if custom_path:
        ext = os.path.splitext(custom_path)[1].lower()
        # custom_path is a memcard file
        if ext == '.ps2' and os.path.isfile(custom_path):
            return os.path.dirname(custom_path)
        # custom_path is a memcard directory
        if os.path.isdir(custom_path) and any(f.lower().endswith('.ps2') for f in os.listdir(custom_path)):
            return custom_path
    home = os.path.expanduser("~")
    # Try reading PCSX2 config for memcard location
    docs = os.path.join(home, "Documents", "PCSX2")
    cfg = os.path.join(docs, "inis", "PCSX2_ui.ini")
    if os.path.isfile(cfg):
        config = configparser.ConfigParser()
        try:
            config.read(cfg)
            for section in config.sections():
                for key in ("MemoryCardA", "MemoryCardB"):
                    if config.has_option(section, key):
                        mcard = config.get(section, key)
                        mcard = os.path.expandvars(os.path.expanduser(mcard))
                        dir0 = os.path.dirname(mcard)
                        if os.path.isdir(dir0):
                            log.info(f"Using PCSX2 memcards dir from config: {dir0}")
                            return dir0
        except Exception as e:
            log.warning(f"Error reading PCSX2 config {cfg}: {e}")
    system = platform.system()
    if system == "Windows":
        default = os.path.join(home, "Documents", "PCSX2", "memcards")
    elif system == "Linux":
        default = os.path.join(home, ".config", "PCSX2", "memcards")
    else:
        default = None
    if default and os.path.isdir(default):
        log.info(f"Using default PCSX2 memcards dir: {default}")
        return default
    log.error("PCSX2 memcards directory not found.")
    return None


def list_pcsx2_memcards(custom_path: Optional[str] = None) -> List[str]:
    """Return list of .ps2 files from custom_path or detected memcard dir."""
    cards: List[str] = []
    # direct file path
    if custom_path and custom_path.lower().endswith('.ps2') and os.path.isfile(custom_path):
        return [custom_path]
    memdir = get_pcsx2_memcard_path(custom_path)
    if memdir:
        cards = [os.path.join(memdir, f) for f in os.listdir(memdir) if f.lower().endswith('.ps2')]
    return cards


def find_pcsx2_profiles(custom_path: Optional[str] = None) -> Optional[List[Dict[str, str]]]:
    """Find PCSX2 memory card saves and return profiles."""
    profiles: List[Dict[str, str]] = []
    # find memcard files
    cards = list_pcsx2_memcards(custom_path)
    if not cards:
        log.error("No PCSX2 memory card files found.")
        return None
    for path in cards:
        f = None
        mc = None
        try:
            f = open(path, 'rb')
            mc = ps2mc(f, ignore_ecc=True)
        except Exception as e:
            log.error(f"Failed to open memcard {path}: {e}")
            if f:
                f.close()
            continue
        try:
            dirs = mc.glob("*/")
            for d in dirs:
                raw = mc.get_icon_sys(d)
                if raw:
                    icon = IconSys(raw)
                    title1, title2 = icon.get_title("unicode")
                    name = f"{title1} {title2}".strip()
                else:
                    name = d.strip("/")
                profile_id = f"pcsx2_{os.path.splitext(os.path.basename(path))[0]}_{d.strip('/').lower()}"
                profiles.append({
                    'id': profile_id,
                    'name': name,
                    'paths': [path],
                    'save_dir': d
                })
        finally:
            if mc:
                mc.close()
            elif f and not f.closed:
                f.close()
    # Normalize profile names to convert fullwidth characters to ASCII
    for p in profiles:
        p['name'] = unicodedata.normalize("NFKC", p['name'])
    return profiles if profiles else None


# --- Recursive helper for extracting PS2 save directory contents ---
def _recursive_extract_ps2_save_dir(mc_instance: ps2mc, mc_current_dir_path: str, fs_target_dir_path: str):
    """
    Recursively extracts contents of a directory from PS2 memory card to filesystem.
    mc_instance: ps2mc instance.
    mc_current_dir_path: Current directory path on MC to extract (e.g., "SAVEDIR/" or "SAVEDIR/SUBDIR/").
                         Must end with a '/'.
    fs_target_dir_path: Corresponding directory path on filesystem to extract to.
    """
    log.debug(f"Recursively extracting MC path '{mc_current_dir_path}' to FS path '{fs_target_dir_path}'")
    os.makedirs(fs_target_dir_path, exist_ok=True)

    glob_pattern = f"{mc_current_dir_path}*"

    log.debug(f"Globbing with pattern: '{glob_pattern}'")

    mc_entries_paths = []
    try:
        mc_entries_paths = mc_instance.glob(glob_pattern) # Returns list of path strings
    except Exception as e_glob:
        log.error(f"Error globbing MC path '{glob_pattern}': {e_glob}", exc_info=True)
        return

    for mc_entry_path in mc_entries_paths: # mc_entry_path is a string
        mc_entry_name = os.path.basename(mc_entry_path.rstrip('/')) # Get name from path

        # Skip parent and current directory entries if they appear
        if mc_entry_name in ['.', '..']:
            continue

        fs_entry_full_path = os.path.join(fs_target_dir_path, mc_entry_name)

        try:
            current_mode = mc_instance.get_mode(mc_entry_path)
            if current_mode is None:
                log.warning(f"Could not get mode for MC entry '{mc_entry_path}', skipping.")
                continue

            # Use current_mode to determine if it's a directory
            if (current_mode & (DF_DIR | DF_EXISTS)) == (DF_DIR | DF_EXISTS): # Check if it's a directory
                log.debug(f"MC Directory: '{mc_entry_path}'. Creating FS dir: '{fs_entry_full_path}' and recursing.")
                # For recursion, the new "current_dir_path" on MC is mc_entry_path
                _recursive_extract_ps2_save_dir(mc_instance, mc_entry_path, fs_entry_full_path)
            else: # It's a file
                log.debug(f"MC File: '{mc_entry_path}'. Copying to FS: '{fs_entry_full_path}'")
                with open(fs_entry_full_path, 'wb') as f:
                    mc_file = None # Initialize to ensure it's defined for finally block
                    try:
                        mc_file = mc_instance.open(mc_entry_path, "rb")
                        while True:
                            chunk = mc_file.read(4096) # Read in 4KB chunks
                            if not chunk:
                                break
                            f.write(chunk)
                    finally:
                        if mc_file:
                            mc_file.close()
        except Exception as e:
            log.error(f"Error processing MC entry '{mc_entry_path}': {e}", exc_info=True)


# --- Recursive helper for injecting filesystem directory contents into PS2 MC ---
def _recursive_inject_fs_dir_to_mc(mc_instance: ps2mc, 
                                   fs_source_root_dir: str, 
                                   mc_target_root_dir_on_card: str):
    """
    Recursively copies contents of a local filesystem directory into a PS2 memory card directory.

    mc_instance: ps2mc instance (opened in r+b mode).
    fs_source_root_dir: The root directory on the local filesystem whose contents will be mirrored.
                        (e.g., "C:/temp_extract/SLUS12345")
    mc_target_root_dir_on_card: The base directory on the memory card where the structure from 
                                fs_source_root_dir will be created. Must end with '/'.
                                (e.g., "SLUS12345/")
    """
    log.debug(f"Recursively injecting FS dir '{fs_source_root_dir}' into MC dir '{mc_target_root_dir_on_card}'")

    if not mc_target_root_dir_on_card.endswith('/'):
        mc_target_root_dir_on_card += '/' # Ensure it ends with a slash
        log.warning(f"mc_target_root_dir_on_card did not end with '/'. Appended: '{mc_target_root_dir_on_card}'")

    # Ensure the base MC target directory structure exists (e.g., "PARENT/SAVEDIR/")
    try:
        path_parts = [part for part in mc_target_root_dir_on_card.strip('/').split('/') if part]
        current_parent_dirloc = mc_instance.path_search(".")[0] # dirloc of MC root
        current_mc_path_being_built = ""
        for i, part_name in enumerate(path_parts):
            path_to_check_for_part = current_mc_path_being_built + part_name + "/"
            path_info = mc_instance.path_search(path_to_check_for_part)
            
            if not path_info[1]: # Directory part_name does not exist at this level
                log.debug(f"Creating intermediate MC directory: {path_to_check_for_part}")
                created_dirloc_ent = mc_instance.create_dir_entry(
                    current_parent_dirloc, 
                    part_name, 
                    DF_DIR | DF_RWX | DF_0400 | DF_EXISTS
                )
                current_parent_dirloc = created_dirloc_ent[0] # This is the dirloc of the newly created directory part_name
            elif not path_info[2]: # Exists, but not a directory
                log.error(f"MC path '{path_to_check_for_part}' exists but is not a directory. Injection aborted.")
                return
            else: # Exists and is a directory
                current_parent_dirloc = path_info[0] # The dirloc of the existing directory part_name
            current_mc_path_being_built = path_to_check_for_part
        log.info(f"Ensured base MC directory '{mc_target_root_dir_on_card}' exists.")
    except Exception as e_create_base:
        log.error(f"Failed to create or ensure base MC directory '{mc_target_root_dir_on_card}': {e_create_base}", exc_info=True)
        return

    for fs_current_walk_dir, fs_subdirs, fs_filenames in os.walk(fs_source_root_dir):
        fs_relative_path = os.path.relpath(fs_current_walk_dir, fs_source_root_dir)
        
        mc_current_processing_dir_on_card: str
        if fs_relative_path == '.':
            mc_current_processing_dir_on_card = mc_target_root_dir_on_card
        else:
            mc_rel_segment = fs_relative_path.replace(os.sep, '/')
            mc_current_processing_dir_on_card = mc_target_root_dir_on_card + mc_rel_segment + '/'

        # Get the dirloc of the current directory we are processing on the MC.
        # This directory must exist due to the pre-processing step or previous iterations.
        current_mc_dir_info = mc_instance.path_search(mc_current_processing_dir_on_card)
        if not current_mc_dir_info[1] or not current_mc_dir_info[2]: # ent is None or not a dir
            log.error(f"Critical: MC directory '{mc_current_processing_dir_on_card}' for processing should exist but not found or not a dir. Skipping items within.")
            continue
        
        parent_dirloc_for_children = current_mc_dir_info[0] # dirloc of mc_current_processing_dir_on_card

        # Create subdirectories on MC if they don't exist
        for subdir_name in fs_subdirs:
            mc_path_for_subdir = mc_current_processing_dir_on_card + subdir_name + "/"
            log.debug(f"  Checking/Creating MC subdirectory: {mc_path_for_subdir}")
            try:
                subdir_info = mc_instance.path_search(mc_path_for_subdir)
                if not subdir_info[1]: # Subdirectory does not exist
                    mc_instance.create_dir_entry(
                        parent_dirloc_for_children, 
                        subdir_name, 
                        DF_DIR | DF_RWX | DF_0400 | DF_EXISTS
                    )
                    log.debug(f"    Created MC subdirectory: {mc_path_for_subdir}")
                elif not subdir_info[2]: # Path exists but is not a directory
                    log.warning(f"    MC path {mc_path_for_subdir} exists but is not a directory. Cannot create subdir.")
                else:
                    log.debug(f"    MC subdirectory {mc_path_for_subdir} already exists.")
            except Exception as e_mkdir_loop:
                log.warning(f"    Could not create or check MC subdirectory {mc_path_for_subdir}: {e_mkdir_loop}", exc_info=True)

        # Copy files to MC
        for file_name in fs_filenames:
            local_file_full_path = os.path.join(fs_current_walk_dir, file_name)
            mc_file_full_path_on_card = mc_current_processing_dir_on_card + file_name # Files don't end with /
            
            log.debug(f"  Attempting to copy FS file '{local_file_full_path}' to MC path '{mc_file_full_path_on_card}'")
            mc_file_to_write = None
            try:
                with open(local_file_full_path, 'rb') as local_f:
                    # mc_instance.open will use create_dir_entry internally if file doesn't exist
                    # and its parent directory (parent_dirloc_for_children) is known to exist.
                    mc_file_to_write = mc_instance.open(mc_file_full_path_on_card, 'wb')
                    while True:
                        chunk = local_f.read(4096) # Read in 4KB chunks
                        if not chunk:
                            break
                        mc_file_to_write.write(chunk)
                log.debug(f"    Copied FS file: {local_file_full_path} -> {mc_file_full_path_on_card}")
            except Exception as e_cp_file:
                log.error(f"    Failed to copy FS file '{local_file_full_path}' to MC '{mc_file_full_path_on_card}': {e_cp_file}", exc_info=True)
            finally:
                if mc_file_to_write:
                    try:
                        mc_file_to_write.close()
                    except Exception as e_close:
                        log.error(f"Error closing MC file '{mc_file_full_path_on_card}': {e_close}", exc_info=True)


# --- Selective backup for PS2 profiles ---
def backup_pcsx2_save(profile_name: str, memcard_path: str, save_dir: str, # save_dir is like "SLUS12345/"
                      backup_base_dir: str, max_backups: int, 
                      max_source_size_mb: int, compression_mode: str) -> tuple[bool, str]:
    import os
    import tempfile
    from core_logic import perform_backup

    log.info(f"Starting selective PCSX2 backup for profile '{profile_name}', save_dir '{save_dir}' from '{memcard_path}'")

    # Ensure save_dir ends with a '/' for consistent path construction with the helper
    if not save_dir.endswith('/'):
        log.warning(f"Save directory '{save_dir}' for PCSX2 backup does not end with '/'. Appending.")
        save_dir += '/'

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir_name_on_fs = save_dir.strip('/') 
            fs_extraction_root_for_save = os.path.join(tmpdir, save_dir_name_on_fs)
            
            log.debug(f"Temporary directory for extraction: {tmpdir}")
            log.debug(f"Filesystem extraction root for save '{save_dir_name_on_fs}': {fs_extraction_root_for_save}")

            with open(memcard_path, 'rb') as f_mc:
                mc = ps2mc(f_mc, ignore_ecc=True)
                try:
                    _recursive_extract_ps2_save_dir(mc, save_dir, fs_extraction_root_for_save)
                except Exception as e_extract:
                    log.error(f"Error during recursive extraction from MC: {e_extract}", exc_info=True)
                    # mc.close() will be called in finally
                    return False, f"ERROR during PS2 save extraction: {e_extract}"
                finally:
                    if hasattr(mc, 'f') and mc.f and not mc.f.closed:
                         mc.close()

            log.info(f"Extraction to temporary directory completed. Source for backup: {fs_extraction_root_for_save}")
            
            success, message = perform_backup(
                profile_name, 
                [fs_extraction_root_for_save], 
                backup_base_dir, 
                max_backups, 
                max_source_size_mb, 
                compression_mode
            )
            if success:
                log.info(f"Selective PCSX2 backup successful for '{profile_name}'.")
            else:
                log.error(f"Selective PCSX2 backup failed for '{profile_name}': {message}")
            return success, message
            
    except Exception as e:
        log.error(f"General ERROR during PS2 backup for profile '{profile_name}': {e}", exc_info=True)
        return False, f"General ERROR during PS2 backup: {e}"


# --- Selective restore for PS2 profiles ---
def restore_pcsx2_save(profile_name: str, 
                       memcard_path: str, 
                       local_backup_source_dir: str, # Path to the local FOLDER containing the save (e.g. "temp/SLUS12345")
                       mc_target_save_dir_name: str    # Name of the save dir on MC (e.g. "SLUS12345")
                       ) -> tuple[bool, str]:
    import os
    log.info(f"Starting selective PCSX2 restore for profile '{profile_name}', target MC dir '{mc_target_save_dir_name}' to '{memcard_path}' from '{local_backup_source_dir}'")

    # Ensure mc_target_save_dir_name is just the directory name, no slashes initially for rmdir/mkdir
    mc_target_save_dir_name_cleaned = mc_target_save_dir_name.strip('/')
    if not mc_target_save_dir_name_cleaned:
        msg = "Target save directory name on MC cannot be empty or root."
        log.error(msg)
        return False, msg

    mc_instance = None
    try:
        # Open memory card in read-write binary mode
        with open(memcard_path, 'r+b') as f_mc_rw:
            mc_instance = ps2mc(f_mc_rw, ignore_ecc=True) # ignore_ecc for robustness, ECC handled on write by default
            
            # 1. Attempt to remove existing directory on MC to prevent conflicts / ensure clean state
            #    mc.rmdir is recursive.
            try:
                log.debug(f"Attempting to remove existing MC directory: '{mc_target_save_dir_name_cleaned}'")
                mc_instance.rmdir(mc_target_save_dir_name_cleaned)
                log.info(f"Successfully removed existing MC directory: '{mc_target_save_dir_name_cleaned}'")
            except Exception as e_rmdir:
                # Common case: directory doesn't exist, which is fine.
                # Check if it's specifically a 'path not found' or 'dir not found' type error if ps2mc raises specific ones.
                # For now, log as warning if not a critical error.
                log.warning(f"Could not remove MC directory '{mc_target_save_dir_name_cleaned}' (may not exist or other issue): {e_rmdir}")

            # 2. Create the top-level target directory on MC
            #    mc.mkdir creates parent directories if they don't exist, but here we expect to be at root or similar.
            try:
                log.debug(f"Attempting to create target MC directory: '{mc_target_save_dir_name_cleaned}'")
                mc_instance.mkdir(mc_target_save_dir_name_cleaned)
                log.info(f"Successfully created target MC directory: '{mc_target_save_dir_name_cleaned}'")
            except Exception as e_mkdir_root:
                msg = f"Failed to create target directory '{mc_target_save_dir_name_cleaned}' on MC: {e_mkdir_root}"
                log.error(msg, exc_info=True)
                if mc_instance and hasattr(mc_instance, 'f') and mc_instance.f and not mc_instance.f.closed: mc_instance.close()
                return False, msg

            # 3. Recursively inject the contents from local_backup_source_dir into the newly created mc_target_save_dir_name
            #    The mc_target_root_dir_on_card for the helper needs to end with a '/'
            mc_base_path_for_injection = mc_target_save_dir_name_cleaned + '/'
            _recursive_inject_fs_dir_to_mc(mc_instance, local_backup_source_dir, mc_base_path_for_injection)
            
            log.info(f"Recursive injection completed for '{mc_target_save_dir_name_cleaned}'. Flushing changes.")
            # Changes are flushed on mc_instance.close()

        log.info(f"Selective PCSX2 restore successful for profile '{profile_name}' to MC dir '{mc_target_save_dir_name_cleaned}'.")
        return True, f"Restore successful for {profile_name} to {mc_target_save_dir_name_cleaned}."

    except Exception as e:
        msg = f"General ERROR during PS2 restore for profile '{profile_name}': {e}"
        log.error(msg, exc_info=True)
        return False, msg
    finally:
        if mc_instance and hasattr(mc_instance, 'f') and mc_instance.f and not mc_instance.f.closed:
            log.debug("Ensuring MC instance is closed in finally block.")
            mc_instance.close()
