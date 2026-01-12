# gui_components/icon_extractor.py
# -*- coding: utf-8 -*-
"""
Module for extracting and caching game icons from executables and shortcuts.
Uses Windows API (icoextract/PIL) or shell32 to extract icons.
"""
import logging
import os
import hashlib
import platform
from typing import Optional

from PySide6.QtGui import QIcon, QPixmap, QImage
from PySide6.QtCore import QSize, Qt

import config

logger = logging.getLogger(__name__)

# --- Constants ---
ICON_CACHE_FOLDER = ".icon_cache"
DEFAULT_ICON_SIZE = 32  # Size for icons in profile list (increased from 32 for better quality)

# Module-level cache for icon cache directory
_cached_icon_cache_dir = None


def get_icon_cache_dir() -> str:
    """Get the directory for cached icons. Caches the result to avoid repeated settings lookups."""
    global _cached_icon_cache_dir
    
    if _cached_icon_cache_dir is not None:
        return _cached_icon_cache_dir
    
    try:
        import settings_manager
        backup_base = settings_manager.load_settings()[0].get("backup_base_dir", config.BACKUP_BASE_DIR)
    except Exception:
        backup_base = getattr(config, "BACKUP_BASE_DIR", None)
    
    if not backup_base:
        # Fallback to app data folder
        backup_base = config.get_app_data_folder()
    
    cache_dir = os.path.join(backup_base, ".savestate", ICON_CACHE_FOLDER)
    os.makedirs(cache_dir, exist_ok=True)
    
    _cached_icon_cache_dir = cache_dir
    return cache_dir


def _get_cache_filename(exe_path: str) -> str:
    """Generate a unique cache filename for an executable path."""
    # Use hash of path for unique filename
    path_hash = hashlib.md5(exe_path.encode('utf-8')).hexdigest()[:16]
    # Also include filename for readability
    base_name = os.path.splitext(os.path.basename(exe_path))[0]
    safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in base_name)[:30]
    return f"{safe_name}_{path_hash}.png"


def _resolve_shortcut_target(shortcut_path: str) -> Optional[str]:
    """Resolve a .lnk shortcut to its target path."""
    if platform.system() != "Windows":
        return None
    
    try:
        import winshell
        shortcut = winshell.shortcut(shortcut_path)
        target = shortcut.path
        if target and os.path.exists(target):
            return target
    except Exception as e:
        logger.debug(f"Error resolving shortcut '{shortcut_path}': {e}")
    
    return None


def _extract_icon_windows(exe_path: str, output_path: str, size: int = DEFAULT_ICON_SIZE) -> bool:
    """Extract icon from Windows executable using shell32 and convert with ctypes/PIL."""
    try:
        from PIL import Image
        import ctypes
        from ctypes import wintypes
        
        # Use ExtractIconExW to get the icon handle
        shell32 = ctypes.windll.shell32
        
        # First, get the number of icons
        num_icons = shell32.ExtractIconExW(exe_path, -1, None, None, 0)
        
        if num_icons <= 0:
            logger.debug(f"No icons found in '{exe_path}'")
            return False
        
        # Extract the first large icon
        large_icon = ctypes.c_void_p()
        small_icon = ctypes.c_void_p()
        
        result = shell32.ExtractIconExW(
            exe_path, 
            0,  # Index of first icon
            ctypes.byref(large_icon), 
            ctypes.byref(small_icon), 
            1
        )
        
        if result == 0 or not large_icon.value:
            logger.debug(f"Failed to extract icon from '{exe_path}'")
            return False
        
        hicon = large_icon.value
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        
        try:
            # Get icon info to determine size
            class ICONINFO(ctypes.Structure):
                _fields_ = [
                    ('fIcon', wintypes.BOOL),
                    ('xHotspot', wintypes.DWORD),
                    ('yHotspot', wintypes.DWORD),
                    ('hbmMask', wintypes.HBITMAP),
                    ('hbmColor', wintypes.HBITMAP),
                ]
            
            icon_info = ICONINFO()
            if not user32.GetIconInfo(hicon, ctypes.byref(icon_info)):
                logger.debug(f"GetIconInfo failed for '{exe_path}'")
                user32.DestroyIcon(hicon)
                if small_icon.value:
                    user32.DestroyIcon(small_icon)
                return False
            
            # Get bitmap info
            class BITMAP(ctypes.Structure):
                _fields_ = [
                    ('bmType', wintypes.LONG),
                    ('bmWidth', wintypes.LONG),
                    ('bmHeight', wintypes.LONG),
                    ('bmWidthBytes', wintypes.LONG),
                    ('bmPlanes', wintypes.WORD),
                    ('bmBitsPixel', wintypes.WORD),
                    ('bmBits', ctypes.c_void_p),
                ]
            
            bmp = BITMAP()
            if icon_info.hbmColor:
                gdi32.GetObjectW(icon_info.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bmp))
                width, height = bmp.bmWidth, bmp.bmHeight
            else:
                # Fallback size
                width, height = 32, 32
            
            # Create a device context and bitmap to draw the icon
            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            
            # Create a 32-bit RGBA bitmap
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', wintypes.DWORD),
                    ('biWidth', wintypes.LONG),
                    ('biHeight', wintypes.LONG),
                    ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD),
                    ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD),
                    ('biXPelsPerMeter', wintypes.LONG),
                    ('biYPelsPerMeter', wintypes.LONG),
                    ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD),
                ]
            
            class BITMAPINFO(ctypes.Structure):
                _fields_ = [
                    ('bmiHeader', BITMAPINFOHEADER),
                    ('bmiColors', wintypes.DWORD * 3),
                ]
            
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height  # Top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0  # BI_RGB
            
            bits = ctypes.c_void_p()
            hbm = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            
            if not hbm:
                logger.debug(f"CreateDIBSection failed for '{exe_path}'")
                gdi32.DeleteDC(hdc_mem)
                user32.ReleaseDC(0, hdc_screen)
                if icon_info.hbmMask:
                    gdi32.DeleteObject(icon_info.hbmMask)
                if icon_info.hbmColor:
                    gdi32.DeleteObject(icon_info.hbmColor)
                user32.DestroyIcon(hicon)
                if small_icon.value:
                    user32.DestroyIcon(small_icon)
                return False
            
            old_bm = gdi32.SelectObject(hdc_mem, hbm)
            
            # Fill with transparent background
            gdi32.PatBlt(hdc_mem, 0, 0, width, height, 0x00000042)  # BLACKNESS
            
            # Draw the icon
            user32.DrawIconEx(hdc_mem, 0, 0, hicon, width, height, 0, 0, 0x0003)  # DI_NORMAL
            
            # Copy pixels
            buffer_size = width * height * 4
            buffer = (ctypes.c_ubyte * buffer_size)()
            ctypes.memmove(buffer, bits, buffer_size)
            
            # Create PIL Image
            image = Image.frombuffer('RGBA', (width, height), bytes(buffer), 'raw', 'BGRA', 0, 1)
            
            # Resize to target size
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            image.save(output_path, 'PNG')
            
            # Cleanup
            gdi32.SelectObject(hdc_mem, old_bm)
            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)
            if icon_info.hbmMask:
                gdi32.DeleteObject(icon_info.hbmMask)
            if icon_info.hbmColor:
                gdi32.DeleteObject(icon_info.hbmColor)
            user32.DestroyIcon(hicon)
            if small_icon.value:
                user32.DestroyIcon(small_icon)
            
            return True
            
        except Exception as e_convert:
            logger.debug(f"Icon conversion failed for '{exe_path}': {e_convert}")
            # Cleanup on error
            user32.DestroyIcon(hicon)
            if small_icon.value:
                user32.DestroyIcon(small_icon)
            
    except Exception as e:
        logger.debug(f"shell32 extraction failed for '{exe_path}': {e}")
    
    return False


def _extract_icon_icoextract(exe_path: str, output_path: str, size: int = DEFAULT_ICON_SIZE) -> bool:
    """Extract icon using icoextract library (if available)."""
    try:
        import icoextract
        from PIL import Image
        import io
        
        extractor = icoextract.IconExtractor(exe_path)
        
        # Get the best icon
        icon_data = extractor.get_icon()
        
        if icon_data:
            # Load with PIL and save as PNG
            image = Image.open(io.BytesIO(icon_data))
            # Get the largest frame if it's an ICO with multiple sizes
            if hasattr(image, 'n_frames') and image.n_frames > 1:
                # ICO files can have multiple images, find the largest
                best_size = 0
                best_frame = 0
                for frame_idx in range(image.n_frames):
                    image.seek(frame_idx)
                    current_size = max(image.size)
                    if current_size > best_size:
                        best_size = current_size
                        best_frame = frame_idx
                image.seek(best_frame)
            
            # Resize to target size
            image = image.convert('RGBA')
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            image.save(output_path, 'PNG')
            return True
            
    except ImportError:
        logger.debug("icoextract library not available")
    except Exception as e:
        logger.debug(f"icoextract failed for '{exe_path}': {e}")
    
    return False


def _extract_icon_pillow_ico(exe_path: str, output_path: str, size: int = DEFAULT_ICON_SIZE) -> bool:
    """Try to extract icon directly if it's an .ico file."""
    try:
        from PIL import Image
        
        if exe_path.lower().endswith('.ico'):
            image = Image.open(exe_path)
            image = image.convert('RGBA')
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            image.save(output_path, 'PNG')
            return True
    except Exception as e:
        logger.debug(f"PIL ICO loading failed for '{exe_path}': {e}")
    
    return False


def _extract_icon_exe_pe(exe_path: str, output_path: str, size: int = DEFAULT_ICON_SIZE) -> bool:
    """Extract icon from PE executable using pefile library."""
    try:
        import pefile
        from PIL import Image
        import io
        
        pe = pefile.PE(exe_path, fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']
        ])
        
        if not hasattr(pe, 'DIRECTORY_ENTRY_RESOURCE'):
            return False
        
        # Look for RT_GROUP_ICON resources
        RT_ICON = 3
        RT_GROUP_ICON = 14
        
        icon_data = None
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if entry.id == RT_ICON:
                for icon_entry in entry.directory.entries:
                    for icon_lang in icon_entry.directory.entries:
                        data_rva = icon_lang.data.struct.OffsetToData
                        data_size = icon_lang.data.struct.Size
                        icon_data = pe.get_memory_mapped_image()[data_rva:data_rva + data_size]
                        break
                    if icon_data:
                        break
            if icon_data:
                break
        
        if icon_data:
            # Create a simple ICO header
            ico_header = bytearray([0, 0, 1, 0, 1, 0])  # ICO magic, type, count
            # Icon entry: width, height, colors, reserved, planes, bpp, size, offset
            ico_entry = bytearray([32, 32, 0, 0, 1, 0, 32, 0])
            ico_entry.extend(len(icon_data).to_bytes(4, 'little'))
            ico_entry.extend((22).to_bytes(4, 'little'))  # Offset after header
            
            full_ico = bytes(ico_header) + bytes(ico_entry) + icon_data
            
            image = Image.open(io.BytesIO(full_ico))
            image = image.convert('RGBA')
            image = image.resize((size, size), Image.Resampling.LANCZOS)
            image.save(output_path, 'PNG')
            pe.close()
            return True
        
        pe.close()
        
    except ImportError:
        logger.debug("pefile library not available")
    except Exception as e:
        logger.debug(f"pefile extraction failed for '{exe_path}': {e}")
    
    return False


def extract_icon_from_executable(exe_path: str, size: int = DEFAULT_ICON_SIZE) -> Optional[str]:
    """
    Extract icon from an executable or shortcut and cache it.
    
    Args:
        exe_path: Path to the executable (.exe) or shortcut (.lnk)
        size: Desired icon size in pixels
        
    Returns:
        Path to the cached PNG icon, or None if extraction failed
    """
    if not exe_path or not os.path.exists(exe_path):
        return None
    
    # Resolve shortcuts to their targets
    original_path = exe_path
    if exe_path.lower().endswith('.lnk'):
        resolved = _resolve_shortcut_target(exe_path)
        if resolved:
            exe_path = resolved
        else:
            logger.debug(f"Could not resolve shortcut: {original_path}")
            return None
    
    # Check cache first
    cache_dir = get_icon_cache_dir()
    cache_filename = _get_cache_filename(exe_path)
    cache_path = os.path.join(cache_dir, cache_filename)
    
    if os.path.exists(cache_path):
        logger.debug(f"Using cached icon: {cache_path}")
        return cache_path
    
    # Try extraction methods in order of preference
    extracted = False
    
    if platform.system() == "Windows":
        # Try Windows-specific extraction first
        extracted = _extract_icon_windows(exe_path, cache_path, size)
    
    if not extracted:
        # Try icoextract (cross-platform PE extraction)
        extracted = _extract_icon_icoextract(exe_path, cache_path, size)
    
    if not extracted:
        # Try pefile-based extraction
        extracted = _extract_icon_exe_pe(exe_path, cache_path, size)
    
    if not extracted:
        # Try direct ICO loading
        extracted = _extract_icon_pillow_ico(exe_path, cache_path, size)
    
    if extracted and os.path.exists(cache_path):
        logger.info(f"Icon extracted and cached: {cache_path}")
        return cache_path
    
    logger.debug(f"Failed to extract icon from: {exe_path}")
    return None


def _find_main_executable_in_dir(install_dir: str) -> Optional[str]:
    """
    Try to find the main game executable in an installation directory.
    Useful for Steam games where we only know the install folder.
    
    Args:
        install_dir: Path to game installation directory
        
    Returns:
        Path to the most likely main executable, or None
    """
    if not install_dir or not os.path.isdir(install_dir):
        return None
    
    try:
        # Look for .exe files in the root of the install dir
        all_exe_files = []
        preferred_exe_files = []  # Exes that are likely the main game
        
        for item in os.listdir(install_dir):
            item_path = os.path.join(install_dir, item)
            if os.path.isfile(item_path) and item.lower().endswith('.exe'):
                all_exe_files.append(item_path)
                
                # Check if this is likely NOT the main game exe
                lower_name = item.lower()
                is_utility = any(skip in lower_name for skip in [
                    'uninstall', 'crash', 'update', 'setup',
                    'redist', 'vcredist', 'dxsetup', 'directx', 'dotnet',
                    'ue4prereq', 'easyanticheat', 'battleye', 'eac_'
                ])
                # Note: Removed 'launcher' from strict skip list - many games have launcher as main exe
                
                if not is_utility:
                    preferred_exe_files.append(item_path)
        
        # Use preferred list if available, otherwise fall back to all exes
        exe_files = preferred_exe_files if preferred_exe_files else all_exe_files
        
        if not exe_files:
            return None
        
        # If only one exe, use it
        if len(exe_files) == 1:
            return exe_files[0]
        
        # Try to find the main game exe by matching folder name
        folder_name = os.path.basename(install_dir).lower()
        for exe_path in exe_files:
            exe_name = os.path.splitext(os.path.basename(exe_path))[0].lower()
            # Check for similarity with folder name
            if exe_name in folder_name or folder_name in exe_name:
                return exe_path
        
        # Return the largest exe file (usually the main game)
        exe_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
        return exe_files[0]
        
    except Exception as e:
        logger.debug(f"Error finding exe in '{install_dir}': {e}")
    
    return None


def get_profile_icon(profile_data: dict, profile_name: str, size: int = DEFAULT_ICON_SIZE) -> Optional[QIcon]:
    """
    Get the icon for a profile based on its game_executable field.
    Falls back to searching in game_install_dir for Steam games,
    or emulator_executable for emulator profiles.
    
    Args:
        profile_data: The profile dictionary
        profile_name: Name of the profile (for logging)
        size: Desired icon size
        
    Returns:
        QIcon if icon could be extracted, None otherwise
    """
    if not isinstance(profile_data, dict):
        return None
    
    # Check for game_executable in profile
    exe_path = profile_data.get('game_executable')
    
    # If no executable stored, try to find one in game_install_dir (for Steam games)
    if not exe_path:
        install_dir = profile_data.get('game_install_dir')
        if install_dir:
            exe_path = _find_main_executable_in_dir(install_dir)
            if exe_path:
                logger.debug(f"Found exe in install dir for '{profile_name}': {exe_path}")
    
    # If still no executable, check for emulator_executable (for emulator profiles)
    if not exe_path:
        emulator_exe = profile_data.get('emulator_executable')
        if emulator_exe and os.path.exists(emulator_exe):
            exe_path = emulator_exe
            logger.debug(f"Using emulator_executable for '{profile_name}': {exe_path}")
    
    if not exe_path:
        # No executable found
        return None
    
    # Extract/get cached icon
    icon_path = extract_icon_from_executable(exe_path, size)
    
    if icon_path and os.path.exists(icon_path):
        icon = QIcon(icon_path)
        if not icon.isNull():
            return icon
    
    return None


def clear_icon_cache():
    """Clear all cached icons."""
    try:
        cache_dir = get_icon_cache_dir()
        if os.path.exists(cache_dir):
            for filename in os.listdir(cache_dir):
                if filename.endswith('.png'):
                    try:
                        os.remove(os.path.join(cache_dir, filename))
                    except Exception:
                        pass
            logger.info(f"Icon cache cleared: {cache_dir}")
    except Exception as e:
        logger.error(f"Error clearing icon cache: {e}")


def delete_profile_icon(profile_data: dict, all_profiles: dict = None, deleting_profile_name: str = None) -> bool:
    """
    Delete the cached icon for a specific profile.
    Call this when a profile is deleted.
    
    Only deletes the icon if no other profile uses the same executable/icon.
    
    Args:
        profile_data: The profile dictionary (needs 'game_executable', 'game_install_dir', or 'emulator_executable')
        all_profiles: Optional dict of all profiles to check if icon is shared
        deleting_profile_name: Optional name of the profile being deleted (to exclude from check)
        
    Returns:
        True if icon was deleted, False otherwise
    """
    if not isinstance(profile_data, dict):
        return False
    
    # Try to find the executable path
    exe_path = profile_data.get('game_executable')
    
    if not exe_path:
        # Try to find from install dir
        install_dir = profile_data.get('game_install_dir')
        if install_dir:
            exe_path = _find_main_executable_in_dir(install_dir)
    
    if not exe_path:
        # Try emulator_executable for emulator profiles
        exe_path = profile_data.get('emulator_executable')
    
    if not exe_path:
        return False
    
    # Resolve shortcut if needed
    if exe_path.lower().endswith('.lnk'):
        resolved = _resolve_shortcut_target(exe_path)
        if resolved:
            exe_path = resolved
    
    # Check if other profiles use the same icon before deleting
    if all_profiles:
        cache_filename = _get_cache_filename(exe_path)
        
        for other_name, other_data in all_profiles.items():
            # Skip the profile we're deleting
            if other_name == deleting_profile_name:
                continue
            
            if not isinstance(other_data, dict):
                continue
            
            # Check all possible exe sources for the other profile
            other_exe = other_data.get('game_executable')
            if not other_exe:
                other_install_dir = other_data.get('game_install_dir')
                if other_install_dir:
                    other_exe = _find_main_executable_in_dir(other_install_dir)
            if not other_exe:
                other_exe = other_data.get('emulator_executable')
            
            if other_exe:
                # Resolve shortcut if needed
                if other_exe.lower().endswith('.lnk'):
                    resolved = _resolve_shortcut_target(other_exe)
                    if resolved:
                        other_exe = resolved
                
                # Check if they would use the same cached icon
                other_cache_filename = _get_cache_filename(other_exe)
                if other_cache_filename == cache_filename:
                    logger.debug(f"Icon '{cache_filename}' still used by profile '{other_name}', not deleting")
                    return False
    
    # Get cache filename and delete
    try:
        cache_dir = get_icon_cache_dir()
        cache_filename = _get_cache_filename(exe_path)
        cache_path = os.path.join(cache_dir, cache_filename)
        
        if os.path.exists(cache_path):
            os.remove(cache_path)
            logger.info(f"Deleted cached icon: {cache_path}")
            return True
    except Exception as e:
        logger.debug(f"Error deleting cached icon: {e}")
    
    return False


def cleanup_orphaned_icons(profiles: dict) -> int:
    """
    Remove cached icons that don't belong to any existing profile.
    Call this periodically or at startup to clean up stale icons.
    
    Args:
        profiles: Dictionary of all current profiles
        
    Returns:
        Number of orphaned icons deleted
    """
    deleted_count = 0
    
    try:
        cache_dir = get_icon_cache_dir()
        if not os.path.exists(cache_dir):
            return 0
        
        # Build set of valid cache filenames from current profiles
        valid_filenames = set()
        for profile_name, profile_data in profiles.items():
            if not isinstance(profile_data, dict):
                continue
            
            exe_path = profile_data.get('game_executable')
            if not exe_path:
                install_dir = profile_data.get('game_install_dir')
                if install_dir:
                    exe_path = _find_main_executable_in_dir(install_dir)
            
            if not exe_path:
                # Check for emulator_executable
                exe_path = profile_data.get('emulator_executable')
            
            if exe_path:
                # Resolve shortcut if needed
                if exe_path.lower().endswith('.lnk'):
                    resolved = _resolve_shortcut_target(exe_path)
                    if resolved:
                        exe_path = resolved
                
                valid_filenames.add(_get_cache_filename(exe_path))
        
        # Delete icons not in valid set
        for filename in os.listdir(cache_dir):
            if filename.endswith('.png') and filename not in valid_filenames:
                try:
                    os.remove(os.path.join(cache_dir, filename))
                    deleted_count += 1
                    logger.debug(f"Deleted orphaned icon: {filename}")
                except Exception:
                    pass
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} orphaned icon(s) from cache")
    
    except Exception as e:
        logger.error(f"Error cleaning up orphaned icons: {e}")
    
    return deleted_count
