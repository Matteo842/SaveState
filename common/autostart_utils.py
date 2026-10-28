# common/autostart_utils.py
# -*- coding: utf-8 -*-
"""Start SaveState with Windows (minimized to the system tray).

Uses the per-user "Run" registry key, so no admin rights are needed and
the entry shows up in Task Manager > Startup apps, where the user can
also turn it off. Nothing is written unless the user enables the option.
"""
import logging
import os
import platform
import sys

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "SaveState"
MINIMIZED_ARG = "--minimized"


def is_supported() -> bool:
    """Autostart is only implemented for Windows."""
    return platform.system() == "Windows"


def build_command() -> str:
    """Command line Windows will run at login."""
    from managers.update_manager import _is_frozen, _get_executable_path

    if _is_frozen():
        exe = _get_executable_path() or sys.executable
        return f'"{exe}" {MINIMIZED_ARG}'

    # Running from source: prefer pythonw.exe so no console window appears.
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    interpreter = pythonw if os.path.isfile(pythonw) else sys.executable
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_script = os.path.join(project_root, "main.py")
    return f'"{interpreter}" "{main_script}" {MINIMIZED_ARG}'


def is_enabled() -> bool:
    """True if the SaveState entry exists in the Run key."""
    if not is_supported():
        return False
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


def set_enabled(enabled: bool) -> bool:
    """Add or remove the Run entry. Returns True on success."""
    if not is_supported():
        return False
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
