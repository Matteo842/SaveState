# common/autostart_utils.py
# -*- coding: utf-8 -*-
"""Start SaveState on login (minimized to the system tray).

- Windows: per-user "Run" registry key. No admin rights needed; the entry
  also shows up in Task Manager > Startup apps.
- Linux: XDG autostart file (~/.config/autostart/SaveState.desktop), read
  by KDE, GNOME, XFCE, Cinnamon, etc. Not offered inside Flatpak/Snap.

Nothing is written unless the user enables the option.
"""
import logging
import os
import platform
import sys

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "SaveState"
DESKTOP_FILE_NAME = "SaveState.desktop"
MINIMIZED_ARG = "--minimized"


def is_supported() -> bool:
    """Autostart is implemented for Windows and regular Linux installs."""
    system = platform.system()
    if system == "Windows":
        return True
    if system == "Linux":
        from managers.update_manager import _is_flatpak, _is_snap
        return not (_is_flatpak() or _is_snap())
    return False


def checkbox_label() -> str:
    if platform.system() == "Windows":
        return "Start with Windows (minimized to tray)"
    return "Start on login (minimized to tray)"


def _command_parts() -> list:
    """Program and arguments the system will run at login."""
    from managers.update_manager import _is_frozen, _get_executable_path

    if _is_frozen():
        # On Linux this is the .AppImage path when running from an AppImage.
        exe = _get_executable_path() or sys.executable
        return [exe, MINIMIZED_ARG]

    # Running from source: on Windows prefer pythonw.exe so no console appears.
    interpreter = sys.executable
    if platform.system() == "Windows":
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.isfile(pythonw):
            interpreter = pythonw
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_script = os.path.join(project_root, "main.py")
    return [interpreter, main_script, MINIMIZED_ARG]


def build_command() -> str:
    """Windows command line for the Run key."""
    parts = _command_parts()
    return " ".join(p if p.startswith("--") else f'"{p}"' for p in parts)


def _desktop_exec_quote(arg: str) -> str:
    """Quote one argument for a .desktop Exec= line (freedesktop spec)."""
    arg = arg.replace("%", "%%")
    if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    for c in ('\\', '"', '`', '$'):
        arg = arg.replace(c, "\\" + c)
    return f'"{arg}"'


def _desktop_file_path() -> str:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(config_home, "autostart", DESKTOP_FILE_NAME)


def _desktop_file_content() -> str:
    exec_line = " ".join(_desktop_exec_quote(p) for p in _command_parts())
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=SaveState\n"
        "Comment=Start SaveState minimized to the system tray\n"
        f"Exec={exec_line}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def is_enabled() -> bool:
    """True if the SaveState autostart entry exists."""
    if not is_supported():
        return False
    if platform.system() == "Linux":
        return os.path.isfile(_desktop_file_path())
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logging.warning(f"Could not read autostart registry entry: {e}")
        return False


def _set_enabled_linux(enabled: bool) -> bool:
    path = _desktop_file_path()
    try:
        if enabled:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_desktop_file_content())
            logging.info(f"Start on login enabled: {path}")
        elif os.path.isfile(path):
            os.remove(path)
            logging.info("Start on login disabled.")
        return True
    except Exception as e:
        logging.error(f"Could not update autostart file '{path}': {e}")
        return False


def set_enabled(enabled: bool) -> bool:
    """Add or remove the autostart entry. Returns True on success."""
    if not is_supported():
        return False
    if platform.system() == "Linux":
        return _set_enabled_linux(enabled)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                command = build_command()
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
                logging.info(f"Start with Windows enabled: {command}")
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
                logging.info("Start with Windows disabled.")
        return True
    except Exception as e:
        logging.error(f"Could not update autostart registry entry: {e}")
        return False
