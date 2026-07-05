"""
process_watch_utils.py

Lightweight, dependency-free helpers to enumerate the names of the processes
currently running on the system. Used by the automatic backup feature to detect
when a watched game has been closed.

No subprocess is spawned: enumeration happens entirely in-process via native
APIs, which keeps it compatible with single-file Nuitka builds.

- Windows: ctypes + Toolhelp32 snapshot (same style as controller_manager.py).
- Linux / SteamOS: read process names from the /proc filesystem.
- Other platforms: returns an empty set (the "backup on game close" mode is a
  no-op there).

All returned names are lowercased basenames (e.g. "game.exe", "ryujinx").
"""

import logging
import os
import platform

_SYSTEM = platform.system()


# ---------------------------------------------------------------------------
# Windows backend (ctypes / Toolhelp32)
# ---------------------------------------------------------------------------

def _list_windows() -> set[str]:
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * MAX_PATH),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    names: set[str] = set()
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        logging.debug("process_watch_utils: CreateToolhelp32Snapshot failed.")
        return names

    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return names
        while True:
            exe = entry.szExeFile
            if exe:
                names.add(exe.lower())
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)

    return names


# ---------------------------------------------------------------------------
# Linux / SteamOS backend (/proc)
# ---------------------------------------------------------------------------

def _list_linux() -> set[str]:
    names: set[str] = set()
    try:
        proc_entries = os.listdir("/proc")
    except OSError as e:
        logging.debug(f"process_watch_utils: unable to list /proc: {e}")
        return names

    for pid in proc_entries:
        if not pid.isdigit():
            continue
        # /proc/<pid>/comm holds the (possibly truncated) process name.
        added = False
        try:
            with open(f"/proc/{pid}/comm", "r", encoding="utf-8", errors="ignore") as f:
                comm = f.read().strip()
            if comm:
                names.add(comm.lower())
                added = True
        except OSError:
            pass

        # Also include the executable basename from cmdline so users can match
        # either the short comm name or the full executable name.
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read()
            if raw:
                first = raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
                if first:
                    names.add(os.path.basename(first).lower())
                    added = True
        except OSError:
            pass

        if not added:
            continue

    return names


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_running_process_names() -> set[str]:
    """Return the set of lowercased names of currently running processes.

    Returns an empty set on unsupported platforms or on error (callers should
    treat an empty result as "could not determine", not as "nothing running").
    """
    try:
        if _SYSTEM == "Windows":
            return _list_windows()
        if _SYSTEM == "Linux":
            return _list_linux()
    except Exception as e:
        logging.error(f"process_watch_utils: failed to enumerate processes: {e}", exc_info=True)
    return set()


def is_process_watching_supported() -> bool:
    """True if the current platform supports process enumeration."""
    return _SYSTEM in ("Windows", "Linux")


def normalize_process_name(name: str) -> str:
    """Normalize a user-entered process name for matching (basename, lowercased)."""
    if not isinstance(name, str):
        return ""
    return os.path.basename(name.strip()).lower()
