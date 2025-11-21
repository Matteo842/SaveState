# emulator_utils/melonds_manager.py
# -*- coding: utf-8 -*-

import os
import re
import platform
import logging
import configparser
from typing import Iterable
try:
    from PySide6.QtCore import QThread, Signal
except Exception:
    QThread = None
    Signal = None

# Import banned folder list from config
try:
    from config import BANNED_FOLDER_NAMES_LOWER
except ImportError:
    # Fallback se config non è disponibile
    BANNED_FOLDER_NAMES_LOWER = {
        ".git", ".svn", ".hg", "node_modules", "__pycache__", "venv", "env", ".cache",
        "Windows", "Program Files", "Program Files (x86)", "$Recycle.Bin", "System Volume Information",
    }

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


def _unique_existing_paths(paths: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for p in paths:
        if not p:
            continue
        try:
            full = os.path.abspath(os.path.expanduser(p))
        except Exception:
            continue
        if full in seen:
            continue
        if os.path.exists(full):
            seen.add(full)
            result.append(full)
    return result


def _normalize_dir(path_str: str) -> str | None:
    try:
        if not path_str:
            return None
        p = os.path.abspath(os.path.expanduser(path_str))
        if os.path.isfile(p):
            return os.path.dirname(p)
        return p
    except Exception:
        return None


def _is_subpath(child: str, parent: str) -> bool:
    try:
        child_abs = os.path.abspath(child)
        parent_abs = os.path.abspath(parent)
        common = os.path.commonpath([child_abs, parent_abs])
        return common == parent_abs
    except Exception:
        return False


def _read_melonds_config_dirs(executable_path: str | None) -> list[str]:
    """
    Attempts to read melonDS configuration to infer ROM locations (recent files or configured dirs).
    It looks for melonDS.ini in portable, OS-specific, and Flatpak locations.
    Returns candidate directories that likely contain ROMs (thus .sav files nearby).
    """
    candidate_ini_paths: list[str] = []

    # Portable near executable
    if executable_path:
        try:
            exe_dir = os.path.dirname(executable_path) if os.path.isfile(executable_path) else executable_path
            if exe_dir and os.path.isdir(exe_dir):
                candidate_ini_paths.append(os.path.join(exe_dir, "melonDS.ini"))
        except Exception as e:
            log.debug(f"Error deriving portable config path from '{executable_path}': {e}")

    user_home = os.path.expanduser("~")
    system = platform.system()

    if system == "Windows":
        appdata = os.getenv("APPDATA")  # Roaming
        localappdata = os.getenv("LOCALAPPDATA")
        if appdata:
            candidate_ini_paths.append(os.path.join(appdata, "melonDS", "melonDS.ini"))
        if localappdata:
            candidate_ini_paths.append(os.path.join(localappdata, "melonDS", "melonDS.ini"))
    elif system == "Linux":
        candidate_ini_paths.append(os.path.join(user_home, ".config", "melonDS", "melonDS.ini"))
        # Flatpak (known ID)
        candidate_ini_paths.append(os.path.join(user_home, ".var", "app", "net.kuribo64.melonDS", "config", "melonDS", "melonDS.ini"))
    elif system == "Darwin":
        candidate_ini_paths.append(os.path.join(user_home, "Library", "Application Support", "melonDS", "melonDS.ini"))

    dirs_from_ini: list[str] = []
    for ini_path in candidate_ini_paths:
        if not os.path.isfile(ini_path):
            continue
        try:
            parser = configparser.ConfigParser()
            parser.read(ini_path, encoding="utf-8")
            log.debug(f"Parsing melonDS config: {ini_path}")

            for section in parser.sections():
                for key, value in parser.items(section):
                    v = value.strip().strip('"')
                    # Collect directories from values that look like file paths or ROM roots
                    if os.path.isfile(v):
                        dirs_from_ini.append(os.path.dirname(v))
                        continue
                    if os.path.isdir(v):
                        dirs_from_ini.append(v)
                        continue
                    # Heuristic: values pointing to ROM-like files
                    if re.search(r"\.(nds|zip|7z|rar)$", v, re.IGNORECASE):
                        dirs_from_ini.append(os.path.dirname(v))
                        continue
                    # Heuristic: keys that usually carry ROM paths or recents
                    if re.search(r"recent.*rom|rom.*dir|rom.*path|lastrom|rom\d+", key, re.IGNORECASE):
                        if v:
                            # If it looks like a path fragment, use as-is
                            dirs_from_ini.append(v)
        except Exception as e:
            log.debug(f"Failed reading melonDS ini '{ini_path}': {e}")

    # Normalize and filter to existing unique dirs
    dirs_from_ini = [d for d in dirs_from_ini if isinstance(d, str)]
    return _unique_existing_paths(dirs_from_ini)


def _guess_common_rom_dirs(executable_path: str | None) -> list[str]:
    """
    Builds a curated set of likely ROM roots to scan based on platform conventions and common user layouts.
    This is intentionally conservative to remain fast.
    """
    user_home = os.path.expanduser("~")
    system = platform.system()

    likely_roots: list[str] = []

    # Near the emulator (portable setups)
    exe_dir: str | None = None
    try:
        if executable_path:
            if os.path.isfile(executable_path):
                exe_dir = os.path.dirname(executable_path)
            elif os.path.isdir(executable_path):
                exe_dir = executable_path
    except Exception:
        exe_dir = None

    if exe_dir and os.path.isdir(exe_dir):
        likely_roots.append(exe_dir)
        parent = os.path.dirname(exe_dir)
        siblings = [
            os.path.join(parent, n) for n in [
                "Roms", "ROMs", "roms", "ROM", "Games", "games", "Emulation", "Emulators", "RetroArch",
            ]
        ]
        likely_roots.extend([p for p in siblings if os.path.isdir(p)])

    # User folders
    user_candidates = [
        os.path.join(user_home, "Roms"), os.path.join(user_home, "ROMs"), os.path.join(user_home, "roms"),
        os.path.join(user_home, "Games"), os.path.join(user_home, "games"),
        os.path.join(user_home, "Emulation"), os.path.join(user_home, "Emulators"),
        os.path.join(user_home, "RetroArch"), os.path.join(user_home, "LaunchBox"),
        os.path.join(user_home, "EmulationStation"),
        os.path.join(user_home, "Desktop"),  # Desktop diretto dell'utente
        # Evitiamo esplicitamente Documents/Downloads per ridurre i falsi positivi
        # OneDrive/Documents rimosso per performance (troppo pesante da scansionare)
    ]

    likely_roots.extend([p for p in user_candidates if os.path.isdir(p)])

    # Prebuild some explicit DS combos commonly used by frontends
    def combos(base: str) -> list[str]:
        names = []
        for parts in [
            ("roms", "nds"),
            ("Roms", "nds"),
            ("ROMs", "nds"),
            ("roms", "NDS"),
            ("roms", "Nintendo DS"),
            ("roms", "Nintendo_DS"),
            ("Emulation", "roms", "nds"),
            ("emulation", "roms", "nds"),
            ("RetroArch", "downloads"),
            ("LaunchBox", "Games", "Nintendo DS"),
            ("EmulationStation", "roms", "nds"),
            ("Emulators", "melonDS", "roms"),
            ("Emulators", "melonDS", "Roms"),
            ("Emulators", "melonDS", "ROMs"),
        ]:
            names.append(os.path.join(base, *parts))
        return names

    explicit_candidates: list[str] = []
    for base in list(likely_roots):
        for path in combos(base):
            if os.path.isdir(path):
                explicit_candidates.append(path)
    if explicit_candidates:
        likely_roots.extend(explicit_candidates)

    # On Windows, also probe other fixed-letter drives for common top-level dirs
    def _safe_listdir(path: str) -> list[str]:
        try:
            return [d for d in os.listdir(path)]
        except Exception:
            return []

    def _is_network_drive(drive_letter: str) -> bool:
        """Check if a Windows drive is a network/remote drive (to skip it for performance)."""
        try:
            import ctypes
            drive_path = f"{drive_letter}:\\"
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
            # DRIVE_REMOTE = 4 (network drive)
            # DRIVE_FIXED = 3 (local hard disk)
            # DRIVE_REMOVABLE = 2 (USB, floppy)
            # DRIVE_CDROM = 5 (CD/DVD)
            # DRIVE_NO_ROOT_DIR = 1 (invalid)
            return drive_type == 4  # Only exclude network drives
        except Exception:
            # Se ctypes fallisce, assumiamo che non sia di rete
            return False

    if system == "Windows":
        # Cartelle da bannare a livello root dei drive (troppo pesanti o irrilevanti)
        BANNED_DRIVE_ROOT_FOLDERS = {
            "windows", "program files", "program files (x86)", "programdata", 
            "users", "perflogs", "$recycle.bin", "system volume information",
            "windows.old", "intel", "amd", "nvidia", "msocache",
            "$windows.~bt", "$windows.~ws",  # Windows update temp folders
            "programdata", "recovery", "boot", "efi",
        }
        
        discovered_windows_roots: list[str] = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if not os.path.isdir(root):
                continue
            
            # Skip network drives (slow and unlikely to contain local ROMs)
            if _is_network_drive(letter):
                log.debug(f"Skipping network drive: {root}")
                continue
            
            # Known top-level names
            for name in ["Roms", "ROMs", "roms", "ROM", "Games", "games", "Emulation", "Emulators", "RetroArch"]:
                candidate = os.path.join(root, name)
                if os.path.isdir(candidate):
                    likely_roots.append(candidate)
                    discovered_windows_roots.append(candidate)

            # Generic pattern matches at drive root (cheap): anything containing 'rom' or 'game'
            for entry in _safe_listdir(root):
                # Skip banned root-level folders (system/heavy folders)
                if entry.lower() in BANNED_DRIVE_ROOT_FOLDERS:
                    continue
                
                entry_path = os.path.join(root, entry)
                if not os.path.isdir(entry_path):
                    continue
                lower = entry.lower()
                if any(token in lower for token in ["rom", "game", "emul", "retro"]):
                    likely_roots.append(entry_path)
                    discovered_windows_roots.append(entry_path)

        if discovered_windows_roots:
            log.debug(f"Windows drive root candidates discovered: {discovered_windows_roots}")

        # Also probe common DS subfolders directly under discovered roots
        ds_root_patterns = [
            ("roms", "nds"), ("ROMs", "nds"), ("Roms", "nds"),
            ("Games", "Nintendo DS"), ("games", "Nintendo DS"),
            ("Emulation", "roms", "nds"), ("emulation", "roms", "nds"),
            ("Emulators", "melonDS", "roms"), ("Emulators", "melonDS", "Roms"), ("Emulators", "melonDS", "ROMs"),
        ]
        for base in list(likely_roots):
            for parts in ds_root_patterns:
                p = os.path.join(base, *parts)
                if os.path.isdir(p):
                    likely_roots.append(p)

    # DS-specific subfolders we should prioritize/deepen
    ds_subfolders = [
        "nds", "NDS", "Nintendo DS", "Nintendo_DS", "nintendo-ds",
        "ds", "dsi", "ds roms", "nds roms", "ds_games", "melonds", "melon",
    ]
    ds_dirs: list[str] = []
    for r in likely_roots:
        for sub in ds_subfolders:
            p = os.path.join(r, sub)
            if os.path.isdir(p):
                ds_dirs.append(p)

    combined = _unique_existing_paths([*likely_roots, *ds_dirs])
    return combined


def _iter_sav_files(root_dir: str, deep_priority_names: set[str], max_depth: int = 3) -> Iterable[str]:
    """
    Yields .sav files under root_dir, pruning common heavy/irrelevant folders and limiting depth
    unless the path is within DS-focused folder names (e.g., 'nds', 'Nintendo DS').
    """
    # Use comprehensive banned folder list from config.py for maximum performance
    # This includes browser folders, dev tools, system folders, launchers, etc.
    skip_dir_names = BANNED_FOLDER_NAMES_LOWER

    root_dir_abs = os.path.abspath(root_dir)
    for current_root, dirnames, filenames in os.walk(root_dir_abs):
        # Depth pruning
        rel = os.path.relpath(current_root, root_dir_abs)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        # Allow unlimited depth if we are inside a DS-named directory
        inside_deep = any(name.lower() in deep_priority_names for name in current_root.split(os.sep))
        if not inside_deep and depth > max_depth:
            # Prune children
            dirnames[:] = []
            continue

        # Prune heavy/irrelevant folders (case-insensitive comparison)
        dirnames[:] = [d for d in dirnames if d.lower() not in skip_dir_names]

        for fn in filenames:
            if fn.lower().endswith(".sav"):
                yield os.path.join(current_root, fn)


def _clean_game_name_from_filename(filename: str) -> tuple[str, str]:
    base = os.path.splitext(os.path.basename(filename))[0]
    profile_id = base
    # Remove common region/language tags like in DeSmuME manager
    name = re.sub(r"\s*\((USA|Europe|Japan|World|[A-Za-z]{2}(?:,[A-Za-z]{2})*)\)$", "", base, flags=re.IGNORECASE).strip()
    if not name or name == base:
        name = re.sub(r"\s*\((En|Fr|De|Es|It|Ja|Nl|Pt)\)$", "", base, flags=re.IGNORECASE).strip()
    if not name:
        name = base
    return profile_id, name


ROM_EXTS = (".nds", ".srl", ".zip", ".7z", ".rar")


def _has_neighbor_rom(save_path: str) -> bool:
    """Checks if a ROM with the same basename as the .sav exists in the same folder."""
    try:
        directory = os.path.dirname(save_path)
        base = os.path.splitext(os.path.basename(save_path))[0]
        for ext in ROM_EXTS:
            if os.path.isfile(os.path.join(directory, base + ext)):
                return True
        return False
    except Exception:
        return False


def _is_likely_ds_dir(path: str, max_probe_depth: int = 2) -> bool:
    """
    Quick heuristic to decide if a directory likely contains DS ROMs.
    True if the path has DS-related segment names or contains at least one ROM_EXTS file within depth.
    """
    try:
        segments = {seg.lower() for seg in path.split(os.sep)}
        ds_markers = {"nds", "nintendo ds", "nintendo_ds", "ds"}
        if segments & ds_markers:
            return True

        root_abs = os.path.abspath(path)
        for current_root, dirnames, filenames in os.walk(root_abs):
            rel = os.path.relpath(current_root, root_abs)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > max_probe_depth:
                dirnames[:] = []
                continue
            for fn in filenames:
                lower = fn.lower()
                for ext in ROM_EXTS:
                    if lower.endswith(ext):
                        return True
        return False
    except Exception:
        return False


def _contains_sav_quick(path: str, max_probe_depth: int = 2) -> bool:
    """True if the directory contains any .sav within a shallow depth."""
    try:
        root_abs = os.path.abspath(path)
        for current_root, dirnames, filenames in os.walk(root_abs):
            rel = os.path.relpath(current_root, root_abs)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > max_probe_depth:
                dirnames[:] = []
                continue
            for fn in filenames:
                if fn.lower().endswith(".sav"):
                    return True
        return False
    except Exception:
        return False


def _collect_profile_banned_dirs() -> list[str]:
    """
    Builds a list of directories to skip by reading existing profiles and
    extracting paths that likely belong to other emulator ROM folders.
    We avoid banning DS-related directories.
    """
    try:
        import core_logic  # Local import to avoid potential circular issues
    except Exception as e:
        log.debug(f"Unable to import core_logic for profile-based bans: {e}")
        return []

    try:
        profiles = core_logic.load_profiles()
    except Exception as e:
        log.debug(f"Unable to load profiles for profile-based bans: {e}")
        return []

    emulator_markers = {
        # Common emulator names/ids (non-DS)
        "rpcs3", "yuzu", "ryujinx", "dolphin", "duckstation", "mgba", "snes9x",
        "cemu", "flycast", "shadps4", "sameboy", "xenia", "pcsx2", "xemu",
        "ppsspp", "citra", "azahar", "vita3k", "aethersx2", "mame", "retroarch",
        "xqemu", "simple64", "mupen64plus", "melonds",
    }
    ds_markers = {"nds", "nintendo ds", "nintendo_ds", "nintendo-ds", "ds", "desmume", "melonds"}
    rom_like_tokens = {"rom", "roms", "games", "isos", "iso", "titles", "wbfs", "wad"}

    banned: set[str] = set()

    for _, pdata in profiles.items():
        try:
            if not isinstance(pdata, dict):
                continue
            emulator_value = str(pdata.get("emulator", "")).lower()
            if emulator_value in {"melonds", "desmume"}:
                continue  # don't ban DS-related explicit profiles

            # Gather candidate paths
            raw_paths: list[str] = []
            if isinstance(pdata.get("paths"), list):
                raw_paths.extend([p for p in pdata.get("paths") if isinstance(p, str)])
            if isinstance(pdata.get("path"), str):
                raw_paths.append(pdata.get("path"))

            for p in raw_paths:
                norm_dir = _normalize_dir(p)
                if not norm_dir or not os.path.isdir(norm_dir):
                    continue
                lower = norm_dir.lower()

                # Skip obvious user/system areas (not useful for ROMs)
                skip_tokens = {"appdata", "program files", "program files (x86)", "windows", "users\\public"}
                if any(tok in lower for tok in skip_tokens):
                    continue

                segments = set(lower.split(os.sep))
                contains_emulator_marker = any(m in lower for m in emulator_markers)
                contains_rom_token = any(t in segments or t in lower for t in rom_like_tokens)
                contains_ds_marker = any(d in lower for d in ds_markers)

                # Ban if looks like other emulator content (not DS) and rom-ish
                if contains_emulator_marker and not contains_ds_marker:
                    if contains_rom_token or emulator_value:
                        banned.add(norm_dir)
        except Exception:
            continue

    return list(banned)


def get_melonds_rom_dir(executable_path: str | None = None) -> str | None:
    """
    Returns a best-guess ROM directory for melonDS using the same heuristics
    used by the profile finder, but without scanning. Useful for seeding a
    user prompt default path.
    """
    try:
        config_dirs: list[str] = _read_melonds_config_dirs(executable_path)
    except Exception as e:
        log.debug(f"get_melonds_rom_dir: error reading config dirs: {e}")
        config_dirs = []

    try:
        guessed_dirs: list[str] = _guess_common_rom_dirs(executable_path)
    except Exception as e:
        log.debug(f"get_melonds_rom_dir: error building guessed dirs: {e}")
        guessed_dirs = []

    filtered_guessed_dirs = [d for d in guessed_dirs if _is_likely_ds_dir(d) or _contains_sav_quick(d)]
    candidate_dirs: list[str] = _unique_existing_paths([*config_dirs, *filtered_guessed_dirs])

    # Apply profile-based bans
    profile_banned_dirs = _collect_profile_banned_dirs()
    if profile_banned_dirs:
        candidate_dirs = [d for d in candidate_dirs if not any(_is_subpath(d, b) for b in profile_banned_dirs)]

    # Prefer directories that already contain .sav quickly
    for d in candidate_dirs:
        if _contains_sav_quick(d):
            return d
    # Otherwise return the first DS-likely directory if present
    for d in candidate_dirs:
        if _is_likely_ds_dir(d):
            return d
    # Fallback: first candidate if any
    return candidate_dirs[0] if candidate_dirs else None


def find_melonds_profiles(executable_path: str | None = None) -> list[dict] | None:
    """
    Finds melonDS save files (.sav). Since melonDS stores saves next to ROMs by default,
    this function infers likely ROM directories and scans for .sav files efficiently.

    Returns a list of profiles: [{ 'id': str, 'name': str, 'paths': [str] }, ...]
    """
    log.info(
        f"Attempting to find melonDS profiles... Executable path: {executable_path if executable_path else 'Not provided'}"
    )

    # Collect config-derived and guessed dirs separately for better filtering/logging
    config_dirs: list[str] = []
    try:
        config_dirs = _read_melonds_config_dirs(executable_path)
    except Exception as e:
        log.debug(f"Error reading melonDS config dirs: {e}")

    guessed_dirs: list[str] = []
    try:
        guessed_dirs = _guess_common_rom_dirs(executable_path)
    except Exception as e:
        log.debug(f"Error building common ROM dirs: {e}")

    # Filter guessed dirs to those that look like DS folders OR contain .sav quickly; keep useful general roots
    filtered_guessed_dirs = [d for d in guessed_dirs if _is_likely_ds_dir(d) or _contains_sav_quick(d)]

    candidate_dirs: list[str] = _unique_existing_paths([*config_dirs, *filtered_guessed_dirs])

    # Profile-based bans (from other emulator profiles)
    profile_banned_dirs = _collect_profile_banned_dirs()
    if profile_banned_dirs:
        before = len(candidate_dirs)
        candidate_dirs = [d for d in candidate_dirs if not any(_is_subpath(d, b) for b in profile_banned_dirs)]
        log.debug(f"Profile-based banned dirs: {profile_banned_dirs}")
        log.debug(f"Filtered candidate dirs by profiles: {before} -> {len(candidate_dirs)}")

    log.debug(f"melonDS candidate dirs (config): {config_dirs}")
    log.debug(f"melonDS candidate dirs (guessed, pre-filter): {guessed_dirs}")
    log.debug(f"melonDS candidate dirs (guessed, filtered): {filtered_guessed_dirs}")
    log.debug(f"melonDS candidate dirs (final): {candidate_dirs}")

    if not candidate_dirs:
        log.warning("No plausible ROM directories found for melonDS; cannot scan for .sav files.")
        return None

    deep_priority_names = {"nds", "nintendo ds", "nintendo_ds", "ds"}

    # Optional: name hints support (local file only, no network). If present, used as a fallback.
    def _normalize_title(s: str) -> str:
        s = s.lower()
        s = re.sub(r"[^a-z0-9]+", "", s)
        return s

    def _load_name_hints() -> set[str]:
        hints: set[str] = set()
        try:
            # Primary: within repository if provided
            repo_file = os.path.join(os.path.dirname(__file__), "ds_game_names.txt")
            user_home = os.path.expanduser("~")
            # Secondary: user-writable location
            appdata = os.getenv("APPDATA") or os.path.join(user_home, ".config")
            user_file = os.path.join(appdata, "SaveState", "ds_game_names.txt")
            for path in (repo_file, user_file):
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            name = line.strip()
                            if not name or name.startswith("#"):
                                continue
                            hints.add(_normalize_title(name))
        except Exception as e:
            log.debug(f"Error loading DS name hints: {e}")
        return hints

    name_hints = _load_name_hints()
    if name_hints:
        log.debug(f"Loaded {len(name_hints)} DS name hints for melonDS fallback matching.")

    profiles: list[dict] = []
    seen_files: set[str] = set()
    total_sav_seen = 0
    total_sav_matched_rom = 0

    for root in candidate_dirs:
        try:
            dir_count = 0
            matched_here = 0
            for file_path in _iter_sav_files(root, deep_priority_names=deep_priority_names, max_depth=3):
                try:
                    total_sav_seen += 1
                    dir_count += 1
                    real_file = os.path.realpath(file_path)
                    if real_file in seen_files:
                        continue
                    seen_files.add(real_file)
                    accept = False
                    if _has_neighbor_rom(file_path):
                        accept = True
                    elif name_hints:
                        # Fallback: accept if filename (cleaned) matches known DS titles
                        _, cleaned = _clean_game_name_from_filename(file_path)
                        if _normalize_title(cleaned) in name_hints:
                            accept = True
                    if accept:
                        total_sav_matched_rom += 1
                        matched_here += 1
                        profile_id, profile_name = _clean_game_name_from_filename(file_path)
                        profiles.append({
                            "id": profile_id,
                            "name": profile_name,
                            "paths": [file_path],
                        })
                    else:
                        log.debug(f"Skipping .sav (no neighbor ROM and no name-hint match): {file_path}")
                except Exception as e:
                    log.debug(f"Skipping file due to error '{file_path}': {e}")
            log.debug(f"Scanned '{root}': sav_found={dir_count}, matched_rom={matched_here}")
        except Exception as e:
            log.debug(f"Failed scanning directory '{root}': {e}")

    if profiles:
        log.info(
            f"Found {len(profiles)} melonDS profiles (.sav) across {len(candidate_dirs)} candidate dirs; "
            f"total_sav_seen={total_sav_seen}, matched_with_rom={total_sav_matched_rom}"
        )
        profiles.sort(key=lambda p: p.get("name", ""))
        return profiles
    else:
        log.info(
            f"No melonDS profiles found across {len(candidate_dirs)} candidate dirs; "
            f"total_sav_seen={total_sav_seen}, matched_with_rom={total_sav_matched_rom}. Signalling for user prompt."
        )
        return None


# --- Async worker (Qt) to run melonDS scan without blocking the UI ---
class MelonDSProfilesWorker(QThread):
    """
    Qt worker thread that runs find_melonds_profiles in background.
    Usage:
        worker = MelonDSProfilesWorker(executable_path)
        worker.finished.connect(lambda profiles: ...)
        worker.start()
    """
    if Signal is not None:
        finished = Signal(object)  # Emits profiles list or None

    def __init__(self, executable_path: str | None):
        if QThread is None:
            raise RuntimeError("Qt (PySide6) not available; MelonDSProfilesWorker cannot be used.")
        super().__init__()
        self._executable_path = executable_path

    def run(self) -> None:
        try:
            profiles = find_melonds_profiles(self._executable_path)
        except Exception as e:
            logging.error(f"MelonDSProfilesWorker error: {e}")
            profiles = None
        # Emit result
        try:
            self.finished.emit(profiles)
        except Exception:
            # If no Qt signal available or disconnected
            pass


def start_melonds_profile_search_async(executable_path: str | None):
    """
    Convenience helper to start the async search.
    Returns the started QThread instance (caller should keep a reference).
    """
    if QThread is None:
        raise RuntimeError("Qt (PySide6) not available; cannot start async melonDS search.")
    worker = MelonDSProfilesWorker(executable_path)
    worker.start()
    return worker

# Example usage (optional)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    dummy_exe = None
    found = find_melonds_profiles(dummy_exe)
    print(f"Found {len(found)} melonDS profiles:")
    for p in found[:20]:
        print(f"  ID: {p['id']} | Name: {p['name']} | Path: {p['paths'][0]}")


