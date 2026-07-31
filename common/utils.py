# utils.py
import os
import sys
import logging
import re
import ntpath
import posixpath

APP_NAME = "SaveState" # Same as in config.py, used for some utility functions if needed.

# Keep the most specific Linux roots before their more general parents.  The
# display aliases are intentionally short: the full path remains available in
# the selection dialog's item data and tooltip.
LINUX_SAVE_PATH_SHORTCUTS = (
    ("~/.var/app/com.valvesoftware.Steam/.local/share/Steam", "Flatpak Steam"),
    ("~/.var/app/com.valvesoftware.Steam/data/Steam", "Flatpak Steam"),
    ("~/snap/steam/common/.local/share/Steam", "Snap Steam"),
    ("~/.steam/debian-installation", "Steam"),
    ("~/.local/share/Steam", "Steam"),
    ("~/.steam/steam", "Steam"),
    ("~/.steam/root", "Steam"),
    ("~/.godot/app_userdata", "Godot"),
    ("~/.local/share", "XDG data"),
    ("~/.config", "XDG config"),
    ("~/.var/app", "Flatpak"),
    ("~/.wine", "Wine prefix"),
    ("~/.renpy", "Ren'Py"),
    ("~/snap", "Snap"),
)

def _is_nuitka_compiled():
    """Detect Nuitka at runtime. __compiled__ is replaced with True by the Nuitka
    compiler; in CPython it raises NameError."""
    try:
        _ = __compiled__  # type: ignore[name-defined]
        return True
    except NameError:
        return False

def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev, PyInstaller, and Nuitka.
    
    Detection order:
    1. PyInstaller: Uses sys._MEIPASS for temporary extraction folder
    2. Nuitka: Uses directory containing the executable (sys.executable)
    3. Development: Uses the script's directory (__file__)
    4. Fallback: Uses current working directory
    """
    try:
        # 1. PyInstaller creates a temp folder and stores path in _MEIPASS
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
            logging.debug(f"resource_path: Using PyInstaller _MEIPASS: {base_path}")
        # 2. Nuitka or generic frozen: compiled executable
        #    __compiled__ is replaced with True by Nuitka at compile time;
        #    'in dir()' does NOT work inside a function, so we use try/except.
        #    In Nuitka onefile, __file__ already resolves to the temp extraction
        #    directory where data files are, so this branch is equivalent but explicit.
        elif getattr(sys, 'frozen', False) or _is_nuitka_compiled():
            base_path = os.path.dirname(sys.executable)
            logging.debug(f"resource_path: Using Nuitka/frozen executable dir: {base_path}")
        else:
            # 3. Development mode: Use the directory containing this script
            # This is more reliable than os.path.abspath(".") which uses CWD
            # common/utils.py lives one level below the project root
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            logging.debug(f"resource_path: Using project root: {base_path}")
    except Exception as e:
        # 4. Fallback to current working directory
        logging.error(f"resource_path: Error determining base path: {e}. Falling back to CWD.")
        base_path = os.path.abspath(".")
    
    full_path = os.path.join(base_path, relative_path)
    return full_path

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
        
        "/home/username/.local/share/Steam/userdata/123/456/remote"
        -> ("Steam/userdata/123/456/remote", 5)  # 5 = length of "Steam"

        "/home/username/.var/app/com.example.Game/data/saves"
        -> ("Flatpak/com.example.Game/data/saves", 7)  # 7 = length of "Flatpak"
    
    Args:
        path: The full path to shorten
        game_install_dir: Optional path to the game's installation directory.
                         If provided, paths starting with this will be shortened
                         to "game folder/..." (using the platform separator).
        
    Returns:
        tuple: (shortened_path, prefix_length) where prefix_length is the length of the shortened prefix
               Returns (original_path, 0) if no shortening was applied
    """
    if not path or not isinstance(path, str):
        return path, 0
    
    # Platform detection
    is_windows = sys.platform.startswith('win')
    path_module = ntpath if is_windows else posixpath

    original_path = path
    path = path_module.normpath(path)
    prefix_length = 0  # Track length of shortened prefix
    
    # --- Check if path starts with game_install_dir ---
    if game_install_dir:
        norm_install_dir = path_module.normpath(game_install_dir)
        norm_path = path_module.normpath(path)
        compare_install_dir = norm_install_dir.lower() if is_windows else norm_install_dir
        compare_path = norm_path.lower() if is_windows else norm_path
        
        # Check for the directory itself or one of its descendants.  A plain
        # startswith would incorrectly treat "/games/foo" as a child of
        # "/games/fo".
        install_prefix = compare_install_dir.rstrip(path_module.sep) + path_module.sep
        if compare_path == compare_install_dir or compare_path.startswith(install_prefix):
            # Get the part after the install dir
            remaining = path[len(norm_install_dir):].lstrip(path_module.sep)
            if remaining:
                path = f"game folder{path_module.sep}{remaining}"
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
        home_dir = posixpath.normpath(posixpath.expanduser("~"))
        linux_shortcuts = []

        # XDG roots may be customized outside the user's home, so include the
        # environment values in addition to the standard shortcut list.
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        if xdg_data_home:
            linux_shortcuts.append((posixpath.normpath(xdg_data_home), "XDG data"))
        if xdg_config_home:
            linux_shortcuts.append((posixpath.normpath(xdg_config_home), "XDG config"))

        for shortcut_path, alias in LINUX_SAVE_PATH_SHORTCUTS:
            expanded_path = shortcut_path
            if shortcut_path == "~" or shortcut_path.startswith("~/"):
                expanded_path = home_dir + shortcut_path[1:]
            linux_shortcuts.append((posixpath.normpath(expanded_path), alias))

        # Longest roots win, which also protects the Steam variants nested
        # inside Flatpak, Snap, and XDG data directories.
        for shortcut_path, alias in sorted(
            linux_shortcuts, key=lambda item: len(item[0]), reverse=True
        ):
            shortcut_prefix = shortcut_path.rstrip("/") + "/"
            if path == shortcut_path or path.startswith(shortcut_prefix):
                remaining = path[len(shortcut_path):].lstrip("/")
                path = alias if not remaining else f"{alias}/{remaining}"
                prefix_length = len(alias)
                break
        else:
            # Unknown home-relative locations still get the familiar "~/"
            # abbreviation, matching the fallback behavior used previously.
            home_prefix = home_dir.rstrip("/") + "/"
            if path == home_dir or path.startswith(home_prefix):
                path = "~" + path[len(home_dir):]
                prefix_length = 1  # Length of "~"
    
    # If we shortened it too much (less than 10 chars), return original
    if len(path) < 10 and len(original_path) > 20:
        return original_path, 0
    
    return path, prefix_length


def sanitize_profile_display_name(name):
    """
    Produce a clean, human-friendly display name for a game/profile.

    Heuristics:
    - Cut everything starting from the first bracket: '(', '[', or '{'.
      Example: "Game Title (Europe) (Rev A)" -> "Game Title"
    - Remove trailing CRC/similar hex tokens like ".980e42e38c995".
    - Collapse underscores/dots into spaces and normalize whitespace.
    - Trim trailing separators and punctuation.
    """
    try:
        if not isinstance(name, str):
            name = str(name)

        cleaned = name

        # 1) Trim at first bracket (any of (, [, {)
        cut_pos = len(cleaned)
        for ch in ('(', '[', '{'):
            p = cleaned.find(ch)
            if p != -1 and p < cut_pos:
                cut_pos = p
        if cut_pos != len(cleaned):
            cleaned = cleaned[:cut_pos]

        # 2) Remove trailing hex-like token after a dot (common CRC/hash suffixes)
        #    e.g., ".980e42e38c995"
        cleaned = re.sub(r"\.[0-9a-fA-F]{6,}$", "", cleaned)

        # 3) Replace underscores and isolated dots with spaces
        cleaned = cleaned.replace('_', ' ')
        # Avoid aggressively removing dots inside abbreviations; only compress repeated spaces later
        cleaned = cleaned.replace('·', ' ')

        # 4) Normalize whitespace and strip separators/punctuation
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip(" .-_/\\—–:;")

        # Fallback to original if result is empty
        return cleaned if cleaned else name.strip()
    except Exception:
        return name
