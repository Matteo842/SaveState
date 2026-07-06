"""
process_watch_utils.py

Lightweight helpers to enumerate the names of the processes currently running on
the system. Used by the automatic backup feature to detect when a watched game
has been closed, and by the GUI process picker.

No subprocess is spawned for enumeration: native APIs are used in-process, which
keeps compatibility with single-file Nuitka builds.

- Windows: ctypes + Toolhelp32 snapshot (same style as controller_manager.py).
- Linux / SteamOS: read process names from the /proc filesystem.
- Other platforms: returns an empty set (the "backup on game close" mode is a
  no-op there).

All returned names are lowercased basenames (e.g. "game.exe", "ryujinx").
"""

import logging
import os
import platform
import re
import time
from dataclasses import dataclass

import psutil

import config

_SYSTEM = platform.system()
_PID_RE = re.compile(r"pid_(\d+)", re.IGNORECASE)


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
# Auto-backup process picker helpers
# ---------------------------------------------------------------------------

@dataclass
class _AggregatedProcessStats:
    name: str
    gpu_bytes: int = 0
    ram_bytes: int = 0
    cpu_percent: float = 0.0


def is_blacklisted_process_name(name: str) -> bool:
    """True if *name* should be hidden from the auto-backup process picker."""
    normalized = normalize_process_name(name)
    if not normalized:
        return True
    if normalized in config.AUTO_BACKUP_PROCESS_BLACKLIST_EXACT:
        return True
    return any(
        keyword in normalized
        for keyword in config.AUTO_BACKUP_PROCESS_BLACKLIST_KEYWORDS
    )


def _windows_gpu_bytes_by_pid() -> dict[int, int]:
    """Map PID -> dedicated GPU memory bytes (Windows only, best effort)."""
    if _SYSTEM != "Windows":
        return {}

    import ctypes
    from ctypes import wintypes

    pdh = ctypes.windll.PDH
    PDH_FMT_LARGE = 0x00000400
    PDH_MORE_DATA = ctypes.c_long(0x800007D2).value
    _ITEM_SIZE = 24  # QWORD name ptr, QWORD padding, QWORD value

    query = wintypes.HANDLE()
    counter = wintypes.HANDLE()
    counter_path = r"\GPU Process Memory(*)\Dedicated Usage"

    try:
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
            return {}
        if pdh.PdhAddCounterW(query, counter_path, 0, ctypes.byref(counter)) != 0:
            return {}
        if pdh.PdhCollectQueryData(query) != 0:
            return {}

        bufsize = wintypes.DWORD(0)
        itemcount = wintypes.DWORD(0)
        status = pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_LARGE, ctypes.byref(bufsize), ctypes.byref(itemcount), None
        )
        if status != PDH_MORE_DATA or not bufsize.value or not itemcount.value:
            return {}

        buf = (ctypes.c_byte * bufsize.value)()
        status = pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_LARGE, ctypes.byref(bufsize), ctypes.byref(itemcount), buf
        )
        if status != 0:
            return {}

        raw = bytes(buf)
        gpu_by_pid: dict[int, int] = {}
        for index in range(itemcount.value):
            offset = index * _ITEM_SIZE
            if offset + _ITEM_SIZE > len(raw):
                break
            name_ptr = int.from_bytes(raw[offset:offset + 8], "little", signed=False)
            value = int.from_bytes(raw[offset + 16:offset + 24], "little", signed=False)
            if value <= 0 or not name_ptr:
                continue
            try:
                instance_name = ctypes.wstring_at(name_ptr)
            except OSError:
                continue
            match = _PID_RE.search(instance_name)
            if not match:
                continue
            pid = int(match.group(1))
            gpu_by_pid[pid] = gpu_by_pid.get(pid, 0) + value
        return gpu_by_pid
    except Exception as e:
        logging.debug(f"process_watch_utils: GPU counter read failed: {e}")
        return {}
    finally:
        try:
            if counter.value:
                pdh.PdhRemoveCounter(counter)
            if query.value:
                pdh.PdhCloseQuery(query)
        except Exception:
            pass


def _aggregate_running_process_stats(cpu_sample_seconds: float = 0.1) -> dict[str, _AggregatedProcessStats]:
    """Collect per-process-name resource usage, aggregated across duplicate PIDs."""
    gpu_by_pid = _windows_gpu_bytes_by_pid()
    stats_by_name: dict[str, _AggregatedProcessStats] = {}
    proc_refs: list[psutil.Process] = []

    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            raw_name = proc.info.get("name")
            if not raw_name:
                continue
            name = normalize_process_name(raw_name)
            if not name or is_blacklisted_process_name(name):
                continue

            pid = proc.info.get("pid")
            mem = proc.info.get("memory_info")
            ram_bytes = int(getattr(mem, "rss", 0) or 0) if mem else 0
            gpu_bytes = int(gpu_by_pid.get(pid, 0)) if pid is not None else 0

            entry = stats_by_name.get(name)
            if entry is None:
                entry = _AggregatedProcessStats(name=name)
                stats_by_name[name] = entry
            entry.ram_bytes += ram_bytes
            entry.gpu_bytes += gpu_bytes
            proc_refs.append(proc)
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue

    if cpu_sample_seconds > 0 and proc_refs:
        time.sleep(cpu_sample_seconds)

    for proc in proc_refs:
        try:
            name = normalize_process_name(proc.name())
            if not name or name not in stats_by_name:
                continue
            stats_by_name[name].cpu_percent += float(proc.cpu_percent(interval=None) or 0.0)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue

    return stats_by_name


def list_running_processes_for_picker(cpu_sample_seconds: float = 0.1) -> list[str]:
    """Return running process names for the auto-backup picker.

    Processes are filtered via the auto-backup blacklist and sorted by resource
    usage: dedicated GPU memory first, then RAM, then CPU.
    """
    try:
        stats = _aggregate_running_process_stats(cpu_sample_seconds=cpu_sample_seconds)
        ordered = sorted(
            stats.values(),
            key=lambda item: (-item.gpu_bytes, -item.ram_bytes, -item.cpu_percent, item.name),
        )
        return [item.name for item in ordered]
    except Exception as e:
        logging.error(f"process_watch_utils: failed to build picker process list: {e}", exc_info=True)
        return sorted(
            name for name in list_running_process_names()
            if not is_blacklisted_process_name(name)
        )


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
