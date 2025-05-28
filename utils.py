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
