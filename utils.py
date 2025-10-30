# utils.py
import os
import sys
import logging
import re

APP_NAME = "SaveState" # Same as in config.py, used for some utility functions if needed.

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # Not running in a PyInstaller bundle
        base_path = os.path.abspath(".")
    except Exception as e: # Catch any other exception during _MEIPASS access
        logging.error(f"Error accessing sys._MEIPASS: {e}. Falling back to os.path.abspath('.')")
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def sanitize_filename(filename):
    """
    Sanitizes a string to be safe for use as a filename or directory name.
    Removes or replaces characters that are typically invalid on most filesystems.
    """
    if not isinstance(filename, str):
        filename = str(filename) # Ensure it's a string

    # Define a set of illegal characters for Windows filenames/directories
    # (includes characters problematic on other OSes as well)
    # \ / : * ? " < > |
    # Additionally, control characters (0-31) are problematic.
    illegal_chars_pattern = r'[\\/:*?"<>|\x00-\x1F]'
    
    # Replace illegal characters with an underscore
    sanitized = re.sub(illegal_chars_pattern, '_', filename)
    
    # Remove leading/trailing whitespace and dots, as they can cause issues
    sanitized = sanitized.strip(' .')
    
    # Replace multiple underscores with a single one
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # If the filename becomes empty after sanitization, provide a default
    if not sanitized:
        return "sanitized_empty_name"
        
    return sanitized


def shorten_save_path(path, game_install_dir=None):
    """
    Shortens a save path by removing redundant or obvious parts.
    
    Examples:
        "E:\\Lies Of P (2023)\\Lies of P\\LiesofP\\Saved\\SaveGames"
        -> ("game folder\\Saved\\SaveGames", 11)  # 11 = length of "game folder"
        
        "C:\\Users\\Matteo842\\Documents\\Dolphin Emulator\\GC\\EUR\\Card A"
        -> ("Documents\\Dolphin Emulator\\GC\\EUR\\Card A", 9)  # 9 = length of "Documents"
        
        "/home/username/.local/share/Steam/steamapps/common/GameName/saves"
        -> ("~/.local/share/Steam/steamapps/common/GameName/saves", 1)  # 1 = length of "~"
    
    Args:
        path: The full path to shorten
        game_install_dir: Optional path to the game's installation directory. 
                         If provided, paths starting with this will be shortened to "game folder\..."
        
    Returns:
        tuple: (shortened_path, prefix_length) where prefix_length is the length of the shortened prefix
               Returns (original_path, 0) if no shortening was applied
    """
    if not path or not isinstance(path, str):
        return path, 0
    
    original_path = path
    path = os.path.normpath(path)
    
    # Platform detection
    is_windows = sys.platform.startswith('win')
    prefix_length = 0  # Track length of shortened prefix
    
    # --- Check if path starts with game_install_dir ---
    if game_install_dir:
        norm_install_dir = os.path.normpath(game_install_dir).lower()
        norm_path = os.path.normpath(path).lower()
        
        # Check if path starts with install dir
        if norm_path.startswith(norm_install_dir):
            # Get the part after the install dir
            remaining = path[len(game_install_dir):].lstrip(os.sep)
            if remaining:
                path = f"game folder{os.sep}{remaining}"
                prefix_length = len("game folder")
                return path, prefix_length
    
    # --- Windows-specific shortcuts ---
    if is_windows:
        # Check if this is a Users path first
        is_users_path = False
        users_pattern = re.compile(r'^[A-Za-z]:\\Users\\[^\\]+\\', re.IGNORECASE)
        match = users_pattern.match(path)
        if match:
            is_users_path = True
            path = path[len(match.group(0)):]
            # Find the first folder name (e.g., "Documents", "AppData")
            first_sep = path.find('\\')
            if first_sep > 0:
                prefix_length = first_sep
            else:
                prefix_length = len(path)
    
    # --- Linux/Unix-specific shortcuts ---
    else:
        # Replace /home/username with ~
        home_dir = os.path.expanduser('~')
        if path.startswith(home_dir):
            path = '~' + path[len(home_dir):]
            prefix_length = 1  # Length of "~"
    
    # If we shortened it too much (less than 10 chars), return original
    if len(path) < 10 and len(original_path) > 20:
        return original_path, 0
    
    return path, prefix_length
