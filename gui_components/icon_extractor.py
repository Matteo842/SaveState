# gui_components/icon_extractor.py
# -*- coding: utf-8 -*-
"""
Module for extracting and caching game icons from executables and shortcuts.
Uses Windows API (icoextract/PIL) or shell32 to extract icons on Windows.
Uses .desktop files, XDG icon directories, and AppImage extraction on Linux.
"""
import logging
import os
import hashlib
import platform
import re
import subprocess
import shutil
from typing import Optional

from PySide6.QtGui import QIcon, QPixmap, QImage
from PySide6.QtCore import QSize, Qt

import config

logger = logging.getLogger(__name__)

# --- Constants ---
ICON_CACHE_FOLDER = ".icon_cache"
DEFAULT_ICON_SIZE = 32  # Size for icons in profile list

# Linux icon search paths (in order of preference)
LINUX_ICON_DIRS = [
    "~/.local/share/icons",
    "~/.icons",
    "/usr/share/icons",
    "/usr/local/share/icons",
    "/usr/share/pixmaps",
    "/usr/local/share/pixmaps",
    # Flatpak icon locations
    "~/.local/share/flatpak/exports/share/icons",
    "/var/lib/flatpak/exports/share/icons",
    # Steam Deck specific paths
    "/home/deck/.local/share/icons",
    "/home/deck/.icons",
]

# Icon themes to search (in order of preference)
LINUX_ICON_THEMES = [
    "hicolor",        # Standard fallback theme (always check first)
    "breeze",         # KDE/Steam Deck default theme
    "breeze-dark",    # KDE dark variant (Steam Deck gaming mode)
    "Adwaita",        # GNOME default theme
    "Yaru",           # Ubuntu default theme
    "gnome",
    "oxygen",         # KDE alternative theme
    "Papirus",        # Popular third-party theme
    "elementary",     # Elementary OS theme
    "Humanity",       # Older Ubuntu theme
    "ubuntu-mono-dark",
    "ubuntu-mono-light",
]

# Preferred icon sizes (in order of preference - larger first for better quality)
LINUX_ICON_SIZES = ["256x256", "128x128", "96x96", "64x64", "48x48", "32x32", "scalable"]

# Icon categories to search
LINUX_ICON_CATEGORIES = ["apps", "applications", "mimetypes", "places", "devices", "actions", "categories"]

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
    """Resolve a .lnk shortcut (Windows) or .desktop file (Linux) to its target path."""
    
    # Handle Windows .lnk shortcuts
    if shortcut_path.lower().endswith('.lnk'):
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
    
    # Handle Linux .desktop files
    if shortcut_path.lower().endswith('.desktop'):
        desktop_data = _parse_desktop_file(shortcut_path)
        if not desktop_data:
            return None
        
        # Get the Exec field
        exec_field = desktop_data.get('Exec', '')
        if not exec_field:
            exec_field = desktop_data.get('TryExec', '')
        
        if not exec_field:
            return None
        
        # Parse the Exec field - remove arguments and field codes
        # Exec can contain things like: /path/to/app %U or env VAR=value /path/to/app
        exec_parts = exec_field.split()
        exe_path = None
        
        for part in exec_parts:
            # Skip environment variable assignments
            if '=' in part and not os.path.exists(part):
                continue
            # Skip field codes (%f, %F, %u, %U, etc.)
            if part.startswith('%'):
                continue
            # Skip common prefixes
            if part in ('env', 'nice', 'ionice', 'primusrun', 'optirun', 'gamemoderun'):
                continue
            
            # This might be the executable
            expanded = os.path.expanduser(part)
            if os.path.isabs(expanded):
                if os.path.exists(expanded):
                    exe_path = expanded
                    break
            else:
                # Try to find it in PATH
                found = shutil.which(part)
                if found:
                    exe_path = found
                    break
        
        return exe_path
    
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


# =============================================================================
# LINUX-SPECIFIC ICON EXTRACTION
# =============================================================================

def _parse_desktop_file(desktop_path: str) -> Optional[dict]:
    """
    Parse a .desktop file and extract key fields.
    
    Args:
        desktop_path: Path to the .desktop file
        
    Returns:
        Dictionary with 'Icon', 'Exec', 'Name' fields, or None if parsing fails
    """
    if not os.path.isfile(desktop_path):
        logger.debug(f"_parse_desktop_file: File does not exist: {desktop_path}")
        return None
    
    logger.debug(f"_parse_desktop_file: Parsing '{desktop_path}'")
    
    try:
        result = {}
        in_desktop_entry = False
        
        with open(desktop_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                
                if line == '[Desktop Entry]':
                    in_desktop_entry = True
                    logger.debug("_parse_desktop_file: Found [Desktop Entry] section")
                    continue
                elif line.startswith('[') and line.endswith(']'):
                    # New section - stop parsing Desktop Entry
                    if in_desktop_entry:
                        logger.debug(f"_parse_desktop_file: Reached new section '{line}', stopping")
                        break
                    continue
                
                if in_desktop_entry and '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip()
                    
                    if key in ('Icon', 'Exec', 'Name', 'TryExec'):
                        result[key] = value
                        logger.debug(f"_parse_desktop_file: Found {key}={value}")
        
        logger.debug(f"_parse_desktop_file: Parsed result: {result}")
        return result if result else None
        
    except Exception as e:
        logger.error(f"Error parsing desktop file '{desktop_path}': {e}")
        return None


def _find_icon_in_theme(icon_name: str, theme_path: str, size: int = DEFAULT_ICON_SIZE) -> Optional[str]:
    """
    Search for an icon within a specific theme directory.
    
    Args:
        icon_name: Name of the icon (without extension)
        theme_path: Path to the theme directory
        size: Desired icon size
        
    Returns:
        Path to the icon file, or None if not found
    """
    if not os.path.isdir(theme_path):
        return None
    
    extensions = ['.png', '.svg', '.xpm']
    
    # Method 1: Search in preferred sizes first (standard structure: theme/size/category/)
    for size_dir in LINUX_ICON_SIZES:
        for category in LINUX_ICON_CATEGORIES:
            search_dir = os.path.join(theme_path, size_dir, category)
            if not os.path.isdir(search_dir):
                continue
            
            # Try different extensions
            for ext in extensions:
                icon_path = os.path.join(search_dir, icon_name + ext)
                if os.path.isfile(icon_path):
                    return icon_path
    
    # Method 2: Some themes use category/size structure (theme/category/size/)
    for category in LINUX_ICON_CATEGORIES:
        for size_dir in LINUX_ICON_SIZES:
            search_dir = os.path.join(theme_path, category, size_dir)
            if not os.path.isdir(search_dir):
                continue
            
            for ext in extensions:
                icon_path = os.path.join(search_dir, icon_name + ext)
                if os.path.isfile(icon_path):
                    return icon_path
    
    # Method 3: Search directly in theme root (some themes have flat structure)
    for ext in extensions:
        icon_path = os.path.join(theme_path, icon_name + ext)
        if os.path.isfile(icon_path):
            return icon_path
    
    # Method 4: Search all subdirectories recursively (limited depth)
    try:
        for root, dirs, files in os.walk(theme_path):
            # Limit depth to avoid too deep searches
            depth = root.replace(theme_path, '').count(os.sep)
            if depth > 3:
                continue
            
            for ext in extensions:
                target_file = icon_name + ext
                if target_file in files:
                    return os.path.join(root, target_file)
    except (OSError, PermissionError):
        pass
    
    return None


def _find_icon_by_name(icon_name: str, size: int = DEFAULT_ICON_SIZE) -> Optional[str]:
    """
    Search for an icon by name in standard Linux icon directories.
    
    Args:
        icon_name: Name of the icon (can be a path or just a name)
        size: Desired icon size
        
    Returns:
        Path to the icon file, or None if not found
    """
    if not icon_name:
        logger.debug("_find_icon_by_name: icon_name is empty")
        return None
    
    logger.debug(f"_find_icon_by_name: Searching for icon '{icon_name}'")
    
    # If it's already an absolute path, return it if it exists
    if os.path.isabs(icon_name):
        if os.path.isfile(icon_name):
            logger.debug(f"_find_icon_by_name: Found absolute path: {icon_name}")
            return icon_name
        # Try adding extensions
        for ext in ['.png', '.svg', '.xpm', '.ico']:
            test_path = icon_name + ext
            if os.path.isfile(test_path):
                logger.debug(f"_find_icon_by_name: Found with extension: {test_path}")
                return test_path
        logger.debug(f"_find_icon_by_name: Absolute path not found: {icon_name}")
        return None
    
    # If it has an extension and is a relative path, try to find it
    if '.' in icon_name and '/' in icon_name:
        expanded = os.path.expanduser(icon_name)
        if os.path.isfile(expanded):
            logger.debug(f"_find_icon_by_name: Found expanded path: {expanded}")
            return expanded
    
    # Strip extension if present for searching
    base_name = icon_name
    if '.' in os.path.basename(icon_name):
        base_name = os.path.splitext(icon_name)[0]
    
    logger.debug(f"_find_icon_by_name: Searching for base_name '{base_name}' in icon directories")
    
    # Search in icon directories
    for icon_dir_template in LINUX_ICON_DIRS:
        icon_dir = os.path.expanduser(icon_dir_template)
        if not os.path.isdir(icon_dir):
            continue
        
        # Search in themes
        for theme in LINUX_ICON_THEMES:
            theme_path = os.path.join(icon_dir, theme)
            if not os.path.isdir(theme_path):
                continue
            found = _find_icon_in_theme(base_name, theme_path, size)
            if found:
                logger.debug(f"_find_icon_by_name: Found in theme '{theme}': {found}")
                return found
        
        # Also check pixmaps directly (no theme structure)
        if 'pixmaps' in icon_dir:
            for ext in ['.png', '.svg', '.xpm', '.ico']:
                icon_path = os.path.join(icon_dir, base_name + ext)
                if os.path.isfile(icon_path):
                    logger.debug(f"_find_icon_by_name: Found in pixmaps: {icon_path}")
                    return icon_path
    
    logger.debug(f"_find_icon_by_name: Icon '{icon_name}' not found in any location")
    return None


def _resolve_desktop_file_icon(desktop_path: str) -> Optional[str]:
    """
    Resolve the icon from a .desktop file.
    
    Args:
        desktop_path: Path to the .desktop file
        
    Returns:
        Path to the icon file, or None if not found
    """
    logger.debug(f"_resolve_desktop_file_icon: Resolving icon for '{desktop_path}'")
    
    desktop_data = _parse_desktop_file(desktop_path)
    if not desktop_data:
        logger.debug("_resolve_desktop_file_icon: Failed to parse desktop file")
        return None
    
    if 'Icon' not in desktop_data:
        logger.debug(f"_resolve_desktop_file_icon: No 'Icon' field found. Available fields: {list(desktop_data.keys())}")
        return None
    
    icon_name = desktop_data['Icon']
    logger.debug(f"_resolve_desktop_file_icon: Icon name from .desktop file: '{icon_name}'")
    
    # First, try to find the icon by name in standard locations
    icon_path = _find_icon_by_name(icon_name)
    if icon_path:
        logger.debug(f"_resolve_desktop_file_icon: Found icon at: {icon_path}")
        return icon_path
    
    # If not found, try relative to the desktop file's directory
    desktop_dir = os.path.dirname(desktop_path)
    for ext in ['', '.png', '.svg', '.xpm', '.ico']:
        test_path = os.path.join(desktop_dir, icon_name + ext)
        if os.path.isfile(test_path):
            logger.debug(f"_resolve_desktop_file_icon: Found icon relative to desktop file: {test_path}")
            return test_path
    
    logger.debug(f"_resolve_desktop_file_icon: Could not find icon '{icon_name}' anywhere")
    return None


def _find_desktop_file_for_executable(exe_path: str) -> Optional[str]:
    """
    Find a .desktop file that references the given executable.
    
    Args:
        exe_path: Path to the executable
        
    Returns:
        Path to the .desktop file, or None if not found
    """
    if not exe_path:
        return None
    
    exe_name = os.path.basename(exe_path).lower()
    exe_name_no_ext = os.path.splitext(exe_name)[0]
    
    # Search directories for .desktop files
    desktop_dirs = [
        os.path.expanduser("~/.local/share/applications"),
        "/usr/share/applications",
        "/usr/local/share/applications",
        # Flatpak applications
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        "/var/lib/flatpak/exports/share/applications",
        # Steam Deck specific (deck user)
        "/home/deck/.local/share/applications",
        # Snap applications (if present)
        "/var/lib/snapd/desktop/applications",
    ]
    
    for desktop_dir in desktop_dirs:
        if not os.path.isdir(desktop_dir):
            continue
        
        try:
            for filename in os.listdir(desktop_dir):
                if not filename.endswith('.desktop'):
                    continue
                
                desktop_path = os.path.join(desktop_dir, filename)
                desktop_data = _parse_desktop_file(desktop_path)
                
                if not desktop_data:
                    continue
                
                # Check if the Exec field matches our executable
                exec_field = desktop_data.get('Exec', '')
                if exe_path in exec_field or exe_name in exec_field.lower():
                    return desktop_path
                
                # Check if desktop file name matches executable name
                desktop_name = os.path.splitext(filename)[0].lower()
                if exe_name_no_ext == desktop_name or exe_name_no_ext in desktop_name:
                    return desktop_path
                    
        except (OSError, PermissionError) as e:
            logger.debug(f"Error scanning desktop dir '{desktop_dir}': {e}")
    
    return None


def _extract_icon_from_appimage(appimage_path: str, output_path: str, size: int = DEFAULT_ICON_SIZE) -> bool:
    """
    Extract icon from an AppImage file.
    
    Args:
        appimage_path: Path to the AppImage file
        output_path: Path to save the extracted icon
        size: Desired icon size
        
    Returns:
        True if extraction succeeded, False otherwise
    """
    if not appimage_path.lower().endswith('.appimage'):
        return False
    
    try:
        import tempfile
        from PIL import Image
        
        # Create a temporary directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            # Try to extract using --appimage-extract
            try:
                result = subprocess.run(
                    [appimage_path, '--appimage-extract'],
                    cwd=temp_dir,
                    capture_output=True,
                    timeout=30
                )
            except (subprocess.TimeoutExpired, PermissionError, FileNotFoundError):
                logger.debug(f"Failed to extract AppImage: {appimage_path}")
                return False
            
            squashfs_root = os.path.join(temp_dir, 'squashfs-root')
            if not os.path.isdir(squashfs_root):
                return False
            
            # Look for icons in the extracted AppImage
            icon_candidates = []
            
            # Check for .DirIcon (standard AppImage icon)
            dir_icon = os.path.join(squashfs_root, '.DirIcon')
            if os.path.isfile(dir_icon):
                icon_candidates.append(dir_icon)
            
            # Check for icons in standard locations
            for icon_dir in ['usr/share/icons', 'usr/share/pixmaps', '']:
                search_path = os.path.join(squashfs_root, icon_dir) if icon_dir else squashfs_root
                if not os.path.isdir(search_path):
                    continue
                
                for root, dirs, files in os.walk(search_path):
                    for filename in files:
                        if filename.endswith(('.png', '.svg', '.xpm')):
                            icon_candidates.append(os.path.join(root, filename))
            
            # Find the best icon (prefer larger sizes)
            best_icon = None
            best_size = 0
            
            for icon_path in icon_candidates:
                try:
                    if icon_path.endswith('.svg'):
                        # SVG files are scalable, prioritize them
                        best_icon = icon_path
                        best_size = 9999
                        break
                    
                    with Image.open(icon_path) as img:
                        current_size = max(img.size)
                        if current_size > best_size:
                            best_size = current_size
                            best_icon = icon_path
                except Exception:
                    continue
            
            if best_icon:
                return _convert_icon_to_png(best_icon, output_path, size)
    
    except ImportError:
        logger.debug("PIL not available for AppImage icon extraction")
    except Exception as e:
        logger.debug(f"Error extracting AppImage icon: {e}")
    
    return False


def _convert_icon_to_png(icon_path: str, output_path: str, size: int = DEFAULT_ICON_SIZE) -> bool:
    """
    Convert an icon file (PNG, SVG, XPM) to PNG at the specified size.
    
    Args:
        icon_path: Path to the source icon
        output_path: Path to save the converted PNG
        size: Desired icon size
        
    Returns:
        True if conversion succeeded, False otherwise
    """
    logger.debug(f"_convert_icon_to_png: Converting '{icon_path}' to '{output_path}' (size={size})")
    
    if not os.path.isfile(icon_path):
        logger.debug(f"_convert_icon_to_png: Source file does not exist: {icon_path}")
        return False
    
    try:
        from PIL import Image
        
        if icon_path.lower().endswith('.svg'):
            logger.debug("_convert_icon_to_png: Handling SVG file")
            # Try to convert SVG using cairosvg if available
            try:
                import cairosvg
                cairosvg.svg2png(url=icon_path, write_to=output_path, 
                               output_width=size, output_height=size)
                logger.debug("_convert_icon_to_png: SVG converted using cairosvg")
                return True
            except ImportError:
                logger.debug("_convert_icon_to_png: cairosvg not available, trying alternatives")
            except Exception as e:
                logger.debug(f"_convert_icon_to_png: cairosvg failed: {e}")
            
            # Fall back to rsvg-convert if available
            if shutil.which('rsvg-convert'):
                try:
                    result = subprocess.run(
                        ['rsvg-convert', '-w', str(size), '-h', str(size), 
                         icon_path, '-o', output_path],
                        capture_output=True,
                        timeout=10
                    )
                    if os.path.isfile(output_path):
                        logger.debug("_convert_icon_to_png: SVG converted using rsvg-convert")
                        return True
                    logger.debug(f"_convert_icon_to_png: rsvg-convert failed: {result.stderr.decode()}")
                except Exception as e:
                    logger.debug(f"_convert_icon_to_png: rsvg-convert exception: {e}")
            
            # Try using Inkscape if available
            if shutil.which('inkscape'):
                try:
                    result = subprocess.run(
                        ['inkscape', '--export-type=png', 
                         f'--export-filename={output_path}',
                         f'-w', str(size), f'-h', str(size), icon_path],
                        capture_output=True,
                        timeout=30
                    )
                    if os.path.isfile(output_path):
                        logger.debug("_convert_icon_to_png: SVG converted using inkscape")
                        return True
                    logger.debug(f"_convert_icon_to_png: inkscape failed: {result.stderr.decode()}")
                except Exception as e:
                    logger.debug(f"_convert_icon_to_png: inkscape exception: {e}")
            
            logger.debug(f"_convert_icon_to_png: No SVG converter available for '{icon_path}'")
            return False
        
        # Handle PNG, XPM, JPG and other formats with PIL
        logger.debug(f"_convert_icon_to_png: Opening image with PIL")
        with Image.open(icon_path) as img:
            img = img.convert('RGBA')
            img = img.resize((size, size), Image.Resampling.LANCZOS)
            img.save(output_path, 'PNG')
            logger.debug(f"_convert_icon_to_png: Successfully saved to {output_path}")
            return True
            
    except ImportError:
        logger.error("_convert_icon_to_png: PIL/Pillow is not installed!")
    except Exception as e:
        logger.debug(f"_convert_icon_to_png: Error converting icon '{icon_path}': {e}")
    
    return False


def _find_icon_near_executable(exe_path: str) -> Optional[str]:
    """
    Look for icon files in the same directory or nearby the executable.
    
    Args:
        exe_path: Path to the executable
        
    Returns:
        Path to an icon file, or None if not found
    """
    if not exe_path or not os.path.exists(exe_path):
        return None
    
    exe_dir = os.path.dirname(exe_path)
    exe_name = os.path.splitext(os.path.basename(exe_path))[0].lower()
    
    # Patterns to search for
    icon_patterns = [
        f"{exe_name}.png",
        f"{exe_name}.ico",
        f"{exe_name}.svg",
        "icon.png",
        "icon.ico",
        "icon.svg",
        "game.png",
        "game.ico",
        "app.png",
        "app.ico",
    ]
    
    # Search in the executable's directory
    for pattern in icon_patterns:
        icon_path = os.path.join(exe_dir, pattern)
        if os.path.isfile(icon_path):
            return icon_path
        
        # Also try case-insensitive match
        try:
            for filename in os.listdir(exe_dir):
                if filename.lower() == pattern:
                    return os.path.join(exe_dir, filename)
        except OSError:
            pass
    
    # Check common subdirectories
    for subdir in ['icons', 'resources', 'assets', 'data', 'share']:
        subdir_path = os.path.join(exe_dir, subdir)
        if os.path.isdir(subdir_path):
            for pattern in icon_patterns:
                icon_path = os.path.join(subdir_path, pattern)
                if os.path.isfile(icon_path):
                    return icon_path
    
    return None


def _extract_icon_linux(exe_path: str, output_path: str, size: int = DEFAULT_ICON_SIZE) -> bool:
    """
    Extract icon from a Linux executable or related files.
    
    Tries multiple methods:
    1. Find and use icon from .desktop file
    2. Look for icon files near the executable
    3. Extract from AppImage
    4. Use icoextract for Windows executables running under Wine/Proton
    
    Args:
        exe_path: Path to the executable
        output_path: Path to save the extracted icon
        size: Desired icon size
        
    Returns:
        True if extraction succeeded, False otherwise
    """
    # Method 1: Try to find a .desktop file for this executable
    desktop_file = _find_desktop_file_for_executable(exe_path)
    if desktop_file:
        icon_path = _resolve_desktop_file_icon(desktop_file)
        if icon_path:
            if _convert_icon_to_png(icon_path, output_path, size):
                logger.debug(f"Extracted icon from desktop file: {desktop_file}")
                return True
    
    # Method 2: Look for icon files near the executable
    nearby_icon = _find_icon_near_executable(exe_path)
    if nearby_icon:
        if _convert_icon_to_png(nearby_icon, output_path, size):
            logger.debug(f"Found icon near executable: {nearby_icon}")
            return True
    
    # Method 3: Try AppImage extraction
    if exe_path.lower().endswith('.appimage'):
        if _extract_icon_from_appimage(exe_path, output_path, size):
            return True
    
    # Method 4: For .exe files (Wine/Proton), try icoextract or pefile
    if exe_path.lower().endswith('.exe'):
        if _extract_icon_icoextract(exe_path, output_path, size):
            return True
        if _extract_icon_exe_pe(exe_path, output_path, size):
            return True
    
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
        exe_path: Path to the executable (.exe, .lnk, .desktop, .AppImage, or Linux binary)
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
    
    # For .desktop files on Linux, extract the icon directly
    if exe_path.lower().endswith('.desktop'):
        logger.debug(f"extract_icon_from_executable: Processing .desktop file: {exe_path}")
        icon_path = _resolve_desktop_file_icon(exe_path)
        if icon_path:
            logger.debug(f"extract_icon_from_executable: Found icon path: {icon_path}")
            # Use the .desktop file path for caching, not the resolved icon
            cache_dir = get_icon_cache_dir()
            cache_filename = _get_cache_filename(exe_path)
            cache_path = os.path.join(cache_dir, cache_filename)
            
            if os.path.exists(cache_path):
                logger.debug(f"extract_icon_from_executable: Using cached icon: {cache_path}")
                return cache_path
            
            if _convert_icon_to_png(icon_path, cache_path, size):
                logger.info(f"Icon extracted from .desktop file and cached: {cache_path}")
                return cache_path
            else:
                logger.debug(f"extract_icon_from_executable: Failed to convert icon: {icon_path}")
        else:
            logger.debug(f"extract_icon_from_executable: Could not resolve icon from .desktop file")
        return None
    
    # Check cache first
    cache_dir = get_icon_cache_dir()
    cache_filename = _get_cache_filename(exe_path)
    cache_path = os.path.join(cache_dir, cache_filename)
    
    if os.path.exists(cache_path):
        logger.debug(f"Using cached icon: {cache_path}")
        return cache_path
    
    # Try extraction methods based on platform
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
    
    else:
        # Linux/macOS: Use Linux-specific extraction methods
        extracted = _extract_icon_linux(exe_path, cache_path, size)
        
        if not extracted:
            # Try icoextract for Windows executables (Wine/Proton)
            extracted = _extract_icon_icoextract(exe_path, cache_path, size)
        
        if not extracted:
            # Try pefile-based extraction for Windows executables
            extracted = _extract_icon_exe_pe(exe_path, cache_path, size)
        
        if not extracted:
            # Try direct ICO loading
            extracted = _extract_icon_pillow_ico(exe_path, cache_path, size)
    
    if extracted and os.path.exists(cache_path):
        logger.info(f"Icon extracted and cached: {cache_path}")
        return cache_path
    
    logger.debug(f"Failed to extract icon from: {exe_path}")
    return None


def _is_linux_executable(file_path: str) -> bool:
    """
    Check if a file is an executable on Linux.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if the file is executable, False otherwise
    """
    if not os.path.isfile(file_path):
        return False
    
    # Check if file has execute permission
    if not os.access(file_path, os.X_OK):
        return False
    
    # Check for known executable extensions
    lower_name = file_path.lower()
    if lower_name.endswith(('.appimage', '.sh', '.py', '.run')):
        return True
    
    # Check if it's an ELF binary or script
    try:
        with open(file_path, 'rb') as f:
            header = f.read(4)
            # ELF magic number
            if header == b'\x7fELF':
                return True
            # Check for shebang (script)
            if header[:2] == b'#!':
                return True
    except Exception:
        pass
    
    return False


def _find_main_executable_in_dir(install_dir: str) -> Optional[str]:
    """
    Try to find the main game executable in an installation directory.
    Useful for Steam games where we only know the install folder.
    Works on both Windows and Linux.
    
    Args:
        install_dir: Path to game installation directory
        
    Returns:
        Path to the most likely main executable, or None
    """
    if not install_dir or not os.path.isdir(install_dir):
        return None
    
    is_linux = platform.system() != "Windows"
    
    try:
        # Look for executable files in the root of the install dir
        all_exe_files = []
        preferred_exe_files = []  # Executables that are likely the main game
        
        # Skip patterns for utility files
        skip_patterns = [
            'uninstall', 'crash', 'update', 'setup',
            'redist', 'vcredist', 'dxsetup', 'directx', 'dotnet',
            'ue4prereq', 'easyanticheat', 'battleye', 'eac_'
        ]
        
        for item in os.listdir(install_dir):
            item_path = os.path.join(install_dir, item)
            
            if not os.path.isfile(item_path):
                continue
            
            lower_name = item.lower()
            is_executable = False
            
            if is_linux:
                # On Linux, check for AppImage, .sh, or ELF binaries
                if lower_name.endswith('.appimage'):
                    is_executable = True
                elif lower_name.endswith('.sh'):
                    is_executable = True
                elif lower_name.endswith('.exe'):
                    # Windows executables (for Wine/Proton)
                    is_executable = True
                elif _is_linux_executable(item_path):
                    is_executable = True
            else:
                # On Windows, check for .exe files
                if lower_name.endswith('.exe'):
                    is_executable = True
            
            if is_executable:
                all_exe_files.append(item_path)
                
                # Check if this is likely NOT the main game exe
                is_utility = any(skip in lower_name for skip in skip_patterns)
                
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
            exe_name = os.path.basename(exe_path).lower()
            # Remove common extensions for comparison
            for ext in ['.exe', '.appimage', '.sh', '.run']:
                if exe_name.endswith(ext):
                    exe_name = exe_name[:-len(ext)]
                    break
            
            # Check for similarity with folder name
            if exe_name in folder_name or folder_name in exe_name:
                return exe_path
        
        # Prefer .AppImage files on Linux (they usually have icons)
        if is_linux:
            appimages = [f for f in exe_files if f.lower().endswith('.appimage')]
            if appimages:
                appimages.sort(key=lambda x: os.path.getsize(x), reverse=True)
                return appimages[0]
        
        # Return the largest exe file (usually the main game)
        exe_files.sort(key=lambda x: os.path.getsize(x), reverse=True)
        return exe_files[0]
        
    except Exception as e:
        logger.debug(f"Error finding exe in '{install_dir}': {e}")
    
    return None


def _find_icon_by_game_name(game_name: str, size: int = DEFAULT_ICON_SIZE) -> Optional[str]:
    """
    Try to find an icon by searching for the game name in icon directories.
    This is useful on Linux where game icons might be installed system-wide.
    
    Args:
        game_name: Name of the game
        size: Desired icon size
        
    Returns:
        Path to an icon file, or None if not found
    """
    if not game_name or platform.system() == "Windows":
        return None
    
    # Clean up game name for searching
    # Remove special characters and convert to lowercase
    clean_name = re.sub(r'[^\w\s-]', '', game_name).lower()
    clean_name = re.sub(r'\s+', '-', clean_name)
    
    # Also try variations
    variations = [
        clean_name,
        clean_name.replace('-', ''),
        clean_name.replace('-', '_'),
        game_name.lower().replace(' ', '-'),
        game_name.lower().replace(' ', ''),
    ]
    
    for name in variations:
        if not name:
            continue
        
        icon_path = _find_icon_by_name(name, size)
        if icon_path:
            return icon_path
    
    return None


def _find_steam_grid_icon(appid: str, size: int = DEFAULT_ICON_SIZE) -> Optional[str]:
    """
    Try to find a Steam grid/library icon for a game.
    Steam stores game icons in the userdata folder.
    
    Args:
        appid: Steam App ID
        size: Desired icon size
        
    Returns:
        Path to an icon file, or None if not found
    """
    if not appid or platform.system() == "Windows":
        return None
    
    try:
        home = os.path.expanduser("~")
        
        # Common Steam installation paths on Linux (including Steam Deck)
        steam_paths = [
            os.path.join(home, ".steam", "steam"),
            os.path.join(home, ".local", "share", "Steam"),
            # Flatpak Steam
            os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
            # Steam Deck specific paths
            "/home/deck/.steam/steam",
            "/home/deck/.local/share/Steam",
        ]
        
        for steam_path in steam_paths:
            if not os.path.isdir(steam_path):
                continue
            
            # Check librarycache for icons
            cache_path = os.path.join(steam_path, "appcache", "librarycache")
            if os.path.isdir(cache_path):
                # Steam uses various naming conventions
                icon_patterns = [
                    f"{appid}_icon.jpg",
                    f"{appid}_icon.png",
                    f"{appid}_library_600x900.jpg",
                    f"{appid}_library_600x900.png",
                    f"{appid}_logo.png",
                    f"{appid}_header.jpg",
                    f"{appid}_header.png",
                    f"{appid}_library_hero.jpg",
                    f"{appid}_library_hero.png",
                ]
                
                for pattern in icon_patterns:
                    icon_path = os.path.join(cache_path, pattern)
                    if os.path.isfile(icon_path):
                        return icon_path
        
    except Exception as e:
        logger.debug(f"Error finding Steam grid icon: {e}")
    
    return None


def get_profile_icon(profile_data: dict, profile_name: str, size: int = DEFAULT_ICON_SIZE) -> Optional[QIcon]:
    """
    Get the icon for a profile based on its game_executable field.
    Falls back to searching in game_install_dir for Steam games,
    or emulator_executable for emulator profiles.
    On Linux, also searches for .desktop files and icon directories.
    
    Args:
        profile_data: The profile dictionary
        profile_name: Name of the profile (for logging)
        size: Desired icon size
        
    Returns:
        QIcon if icon could be extracted, None otherwise
    """
    if not isinstance(profile_data, dict):
        return None
    
    is_linux = platform.system() != "Windows"
    
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
    
    icon_path = None
    
    # Try to extract icon from executable
    if exe_path:
        icon_path = extract_icon_from_executable(exe_path, size)
    
    # On Linux, try additional methods if executable extraction failed
    if not icon_path and is_linux:
        # Try to find Steam library icon by AppID
        steam_appid = profile_data.get('steam_appid') or profile_data.get('appid')
        if steam_appid:
            steam_icon = _find_steam_grid_icon(str(steam_appid), size)
            if steam_icon:
                # Convert and cache it
                cache_dir = get_icon_cache_dir()
                cache_filename = f"steam_{steam_appid}.png"
                cache_path = os.path.join(cache_dir, cache_filename)
                
                if os.path.exists(cache_path):
                    icon_path = cache_path
                elif _convert_icon_to_png(steam_icon, cache_path, size):
                    icon_path = cache_path
                    logger.debug(f"Using Steam library icon for '{profile_name}'")
        
        # Try to find icon by game name
        if not icon_path:
            game_name = profile_data.get('game_name') or profile_name
            name_icon = _find_icon_by_game_name(game_name, size)
            if name_icon:
                # Convert and cache it
                cache_dir = get_icon_cache_dir()
                cache_filename = _get_cache_filename(f"name_{game_name}")
                cache_path = os.path.join(cache_dir, cache_filename)
                
                if os.path.exists(cache_path):
                    icon_path = cache_path
                elif _convert_icon_to_png(name_icon, cache_path, size):
                    icon_path = cache_path
                    logger.debug(f"Found icon by game name for '{profile_name}'")
    
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
    
    # Resolve shortcut if needed (.lnk on Windows, .desktop on Linux)
    if exe_path.lower().endswith('.lnk') or exe_path.lower().endswith('.desktop'):
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
                # Resolve shortcut if needed (.lnk on Windows, .desktop on Linux)
                if other_exe.lower().endswith('.lnk') or other_exe.lower().endswith('.desktop'):
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
                # Resolve shortcut if needed (.lnk on Windows, .desktop on Linux)
                if exe_path.lower().endswith('.lnk') or exe_path.lower().endswith('.desktop'):
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
