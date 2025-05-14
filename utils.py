# utils.py
import os
import sys
import logging

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
