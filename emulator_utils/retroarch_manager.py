# emulator_utils/retroarch_manager.py
# -*- coding: utf-8 -*-

import os
import logging
import platform
import re
from typing import Dict, List, Optional, Tuple, TypedDict

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


class CoreEntry(TypedDict):
    id: str
    name: str
    count: int


class ProfileEntry(TypedDict):
    id: str
    name: str
    paths: List[str]


def _get_ra_root(executable_path_or_dir: Optional[str]) -> Optional[str]:
    """Given a RetroArch exe path or a directory, return the RetroArch root directory.
    - If a file is provided, returns its directory
    - If a directory is provided, returns it
    - Otherwise, returns None
    """
    if not executable_path_or_dir:
        return None
    try:
        if os.path.isfile(executable_path_or_dir):
            return os.path.dirname(executable_path_or_dir)
        if os.path.isdir(executable_path_or_dir):
            return executable_path_or_dir
    except Exception:
        return None
    return None


def _get_saves_dir(ra_root: Optional[str]) -> Optional[str]:
    """Return the RetroArch saves directory under the given root (root/saves)."""
    if not ra_root:
        return None
    saves = os.path.join(ra_root, "saves")
    return saves if os.path.isdir(saves) else None


def _parse_simple_cfg_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse a simple retroarch.cfg line of the form key = "value".
    - Strips inline comments outside quotes (e.g., ... "value"  # comment)
    - Returns (key, value) or None if not parseable
    """
    def _strip_inline_comment(s: str) -> str:
        in_quotes = False
        escaped = False
        out_chars: List[str] = []
        for ch in s:
            if ch == '"' and not escaped:
                in_quotes = not in_quotes
            if ch == '#' and not in_quotes:
                break
            out_chars.append(ch)
            escaped = (ch == '\\' and not escaped)
        return ''.join(out_chars)

    s = _strip_inline_comment(line).strip()
    if not s or s.startswith('#'):
        return None
    if '=' not in s:
        return None
    k, v = s.split('=', 1)
    key = k.strip()
    value = v.strip().strip('"')
    if not key:
        return None
    return key, value


def _read_retroarch_cfg(cfg_path: Optional[str]) -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    if not cfg_path or not os.path.isfile(cfg_path):
        return cfg
    try:
        with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
            for raw in f:
                parsed = _parse_simple_cfg_line(raw)
                if parsed:
                    k, v = parsed
                    cfg[k] = v
    except Exception as e:
        log.warning(f"Error reading retroarch.cfg '{cfg_path}': {e}")
    return cfg


def _expand(path_str: Optional[str], base: Optional[str]) -> Optional[str]:
    if not path_str:
        return None
    try:
        expanded = os.path.expandvars(os.path.expanduser(path_str))
        if not os.path.isabs(expanded) and base:
            expanded = os.path.join(base, expanded)
        return os.path.abspath(expanded)
    except Exception:
        return path_str


def _first_existing_dir(candidates: List[Optional[str]]) -> Optional[str]:
    for p in candidates:
        if p and os.path.isdir(p):
            return p
    return None


def _resolve_ra_paths(executable_path_or_dir: Optional[str]) -> Dict[str, Optional[str]]:
    """Resolve RetroArch root, saves directory and system directory using both root and retroarch.cfg.
    Preference: explicit directories in retroarch.cfg > root defaults.
    """
    ra_root = _get_ra_root(executable_path_or_dir)

    # retroarch.cfg candidates
    cfg_candidates: List[str] = []
    if ra_root:
        cfg_candidates.append(os.path.join(ra_root, 'retroarch.cfg'))
        # Portable/packaged layouts
        cfg_candidates.append(os.path.join(ra_root, 'config', 'retroarch.cfg'))
        cfg_candidates.append(os.path.join(ra_root, 'config', 'retroarch', 'retroarch.cfg'))
    if platform.system() == 'Windows':
        appdata = os.getenv('APPDATA')
        if appdata:
            cfg_candidates.append(os.path.join(appdata, 'RetroArch', 'retroarch.cfg'))
    elif platform.system() == 'Linux':
        home = os.path.expanduser('~')
        # XDG_CONFIG_HOME
        xdg_config = os.getenv('XDG_CONFIG_HOME')
        if xdg_config:
            cfg_candidates.append(os.path.join(xdg_config, 'retroarch', 'retroarch.cfg'))
        # Standard config location
        cfg_candidates.append(os.path.join(home, '.config', 'retroarch', 'retroarch.cfg'))
        # Flatpak
        cfg_candidates.append(os.path.join(home, '.var', 'app', 'org.libretro.RetroArch', 'config', 'retroarch', 'retroarch.cfg'))
        # Snap (less common, but seen in the wild)
        cfg_candidates.append(os.path.join(home, 'snap', 'retroarch', 'current', '.config', 'retroarch', 'retroarch.cfg'))
    elif platform.system() == 'Darwin':
        home = os.path.expanduser('~')
        cfg_candidates.append(os.path.join(home, 'Library', 'Application Support', 'RetroArch', 'retroarch.cfg'))

    cfg_path = next((p for p in cfg_candidates if p and os.path.isfile(p)), None)
    cfg = _read_retroarch_cfg(cfg_path)

    # Resolve directories
    def _is_unset_dir_value(v: Optional[str]) -> bool:
        if v is None:
            return True
        v_stripped = v.strip().strip('"')
        return v_stripped == '' or v_stripped.lower() == 'default'

    explicit_saves = None
    explicit_system = None
    if cfg:
        saves_val = cfg.get('savefile_directory')
        system_val = cfg.get('system_directory')
        if not _is_unset_dir_value(saves_val):
            explicit_saves = _expand(saves_val, ra_root)
        if not _is_unset_dir_value(system_val):
            explicit_system = _expand(system_val, ra_root)

    # Default directories by platform
    default_saves: Optional[str] = None
    default_system: Optional[str] = None
    sysname = platform.system()
    if sysname == 'Windows':
        default_saves = _get_saves_dir(ra_root)
        default_system = os.path.join(ra_root, 'system') if ra_root and os.path.isdir(os.path.join(ra_root, 'system')) else None
    elif sysname == 'Linux':
        home = os.path.expanduser('~')
        xdg_config = os.getenv('XDG_CONFIG_HOME') or os.path.join(home, '.config')
        xdg_data = os.getenv('XDG_DATA_HOME') or os.path.join(home, '.local', 'share')
        default_saves = _first_existing_dir([
            _get_saves_dir(ra_root),
            os.path.join(xdg_config, 'retroarch', 'saves'),
            os.path.join(home, '.config', 'retroarch', 'saves'),
            os.path.join(xdg_data, 'retroarch', 'saves'),
            os.path.join(home, '.local', 'share', 'retroarch', 'saves'),
            os.path.join(home, '.var', 'app', 'org.libretro.RetroArch', 'config', 'retroarch', 'saves'),
            os.path.join(home, '.var', 'app', 'org.libretro.RetroArch', 'data', 'retroarch', 'saves'),
            os.path.join(home, 'snap', 'retroarch', 'current', '.config', 'retroarch', 'saves'),
        ])
        default_system = _first_existing_dir([
            os.path.join(ra_root, 'system') if ra_root else None,
            os.path.join(xdg_config, 'retroarch', 'system') if xdg_config else None,
            os.path.join(home, '.config', 'retroarch', 'system'),
            os.path.join(xdg_data, 'retroarch', 'system') if xdg_data else None,
            os.path.join(home, '.local', 'share', 'retroarch', 'system'),
            os.path.join(home, '.var', 'app', 'org.libretro.RetroArch', 'config', 'retroarch', 'system'),
            os.path.join(home, '.var', 'app', 'org.libretro.RetroArch', 'data', 'retroarch', 'system'),
            os.path.join(home, 'snap', 'retroarch', 'current', '.config', 'retroarch', 'system'),
        ])
    elif sysname == 'Darwin':
        home = os.path.expanduser('~')
        default_saves = _first_existing_dir([
            _get_saves_dir(ra_root),
            os.path.join(home, 'Library', 'Application Support', 'RetroArch', 'saves'),
        ])
        default_system = _first_existing_dir([
            os.path.join(ra_root, 'system') if ra_root else None,
            os.path.join(home, 'Library', 'Application Support', 'RetroArch', 'system'),
        ])

    saves_dir = explicit_saves if (explicit_saves and os.path.isdir(explicit_saves)) else default_saves
    system_dir = explicit_system if (explicit_system and os.path.isdir(explicit_system)) else default_system

    return {
        'ra_root': ra_root,
        'cfg_path': cfg_path,
        'saves_dir': saves_dir,
        'system_dir': system_dir,
    }


def _iter_files_shallow(root_dir: str) -> List[str]:
    """Return list of files (non-recursive) inside root_dir."""
    out: List[str] = []
    try:
        for entry in os.listdir(root_dir):
            full = os.path.join(root_dir, entry)
            if os.path.isfile(full):
                out.append(full)
    except Exception as e:
        log.warning(f"Error walking directory '{root_dir}': {e}")
    return out


def _find_dir_with_ext(roots: List[Optional[str]], ext: str, max_depth: int = 3) -> Tuple[Optional[str], int]:
    """Find the first directory (DFS shallow) under any root that contains files with given ext.
    Returns (dir_path, count). Scans up to max_depth levels.
    """
    visited = set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        root_abs = os.path.abspath(root)
        for current_root, dirnames, filenames in os.walk(root_abs):
            # depth control
            rel = os.path.relpath(current_root, root_abs)
            depth = 0 if rel == '.' else rel.count(os.sep) + 1
            if depth > max_depth:
                # prune
                dirnames[:] = []
                continue
            if current_root in visited:
                continue
            visited.add(current_root)
            files_here = [f for f in filenames if os.path.splitext(f)[1].lower() == ext.lower()]
            if files_here:
                return current_root, len(files_here)
    return None, 0


def _count_files_with_extensions(root_dir: Optional[str], extensions: List[str]) -> int:
    if not root_dir or not os.path.isdir(root_dir):
        return 0
    count = 0
    try:
        for entry in os.listdir(root_dir):
            full = os.path.join(root_dir, entry)
            if os.path.isfile(full):
                ext = os.path.splitext(entry)[1].lower()
                if ext in extensions:
                    count += 1
            elif os.path.isdir(full):
                # shallow scan in subfolders
                for sub in os.listdir(full):
                    sub_full = os.path.join(full, sub)
                    if os.path.isfile(sub_full):
                        ext = os.path.splitext(sub)[1].lower()
                        if ext in extensions:
                            count += 1
    except Exception as e:
        log.warning(f"Error counting files in '{root_dir}': {e}")
    return count


def list_retroarch_cores(executable_path_or_dir: Optional[str] = None) -> List[CoreEntry]:
    """
    Return cores from RetroArch root 'saves' directory.
    Structure expected:
      <RA_ROOT>/saves/<CoreName>/<GameName>.<ext>
    We only care about saves (no savestates/system).
    """
    paths = _resolve_ra_paths(executable_path_or_dir)
    saves_dir = paths.get('saves_dir')
    system_dir = paths.get('system_dir')
    cores: List[CoreEntry] = []
    if not saves_dir:
        log.info("RetroArch saves directory not found under the provided root.")
        return cores

    try:
        # normal cores from saves/<CoreName>
        for entry in os.listdir(saves_dir):
            core_path = os.path.join(saves_dir, entry)
            if not os.path.isdir(core_path):
                continue
            count = len(_iter_files_shallow(core_path))
            if count > 0:
                cores.append({'id': entry, 'name': entry, 'count': count})

        # PS2: any directory containing .ps2 under system or saves
        ps2_dir, ps2_count = _find_dir_with_ext([system_dir, saves_dir], '.ps2', max_depth=3)
        if ps2_dir and ps2_count > 0:
            # Ensure unique entry by name
            if not any(c.get('id', '').lower() == 'pcsx2' for c in cores):
                cores.append({'id': 'PCSX2', 'name': 'PCSX2', 'count': ps2_count})

        # PS1: any directory containing .mcd under system or saves
        ps1_dir, ps1_count = _find_dir_with_ext([system_dir, saves_dir], '.mcd', max_depth=3)
        if ps1_dir and ps1_count > 0:
            if not any(c.get('id', '').lower() == 'duckstation' for c in cores):
                cores.append({'id': 'DuckStation', 'name': 'DuckStation', 'count': ps1_count})

        # Flycast: VMU containers (.bin, .vmu, .vms) under system or saves
        flycast_count_total = 0
        for ext in ('.bin', '.vmu', '.vms'):
            fc_dir, fc_count = _find_dir_with_ext([system_dir, saves_dir], ext, max_depth=3)
            flycast_count_total += fc_count
        if flycast_count_total > 0 and not any(c.get('id', '').lower() == 'flycast' for c in cores):
            cores.append({'id': 'Flycast', 'name': 'Flycast', 'count': flycast_count_total})
    except Exception as e:
        log.error(f"Error listing cores in saves directory '{saves_dir}': {e}")
        return []

    cores.sort(key=lambda c: (c.get("name", "").lower()))
    return cores


def find_retroarch_profiles(selected_core: str, executable_path_or_dir: Optional[str] = None) -> Optional[List[ProfileEntry]]:
    """Return file-based profiles for the given core from <RA_ROOT>/saves/<CoreName>/.
    Each profile: {'id': base_filename, 'name': cleaned_display_name, 'paths': [full_file_path]}
    """
    core_name = (selected_core or '').strip()
    if not core_name:
        return []

    paths = _resolve_ra_paths(executable_path_or_dir)
    ra_root = paths.get('ra_root')
    saves_dir = paths.get('saves_dir')
    system_dir = paths.get('system_dir')
    if not saves_dir:
        return []

    # Special handling for PCSX2: find any dir with .ps2 and reuse PCSX2 manager
    if core_name.upper() == 'PCSX2':
        memcards_dir, _ = _find_dir_with_ext([system_dir, saves_dir], '.ps2', max_depth=3)
        if not memcards_dir:
            return []
        try:
            from .pcsx2_manager import find_pcsx2_profiles
            return find_pcsx2_profiles(memcards_dir) or []
        except Exception as e:
            log.error(f"Error reading PCSX2 memcards from '{memcards_dir}': {e}")
            return []

    # Special handling for PS1 (DuckStation): list .mcd files as profiles
    if core_name.lower() == 'duckstation':
        ps1_dir, _ = _find_dir_with_ext([system_dir, saves_dir], '.mcd', max_depth=3)
        if not ps1_dir:
            return []
        profiles: List[ProfileEntry] = []
        for f in _iter_files_shallow(ps1_dir):
            if os.path.splitext(f)[1].lower() != '.mcd':
                continue
            base = os.path.splitext(os.path.basename(f))[0]
            display = re.sub(r"\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$", "", base).strip() or base
            profiles.append({'id': base, 'name': display, 'paths': [f]})
        return profiles

    # Special handling for Flycast: reuse flycast_manager to parse VMU/VMs for titles when possible
    if core_name.lower() == 'flycast':
        try:
            from .flycast_manager import find_flycast_profiles
            # Pass RA root as hint so manager can locate saves (saves/flycast or system/dc)
            return find_flycast_profiles(ra_root) or []
        except Exception as e:
            log.error(f"Error building Flycast profiles from RA root '{ra_root}': {e}")
            # Fallback: simple file listing for container files
            fc_dir_bin, _ = _find_dir_with_ext([system_dir, saves_dir], '.bin', max_depth=3)
            fc_dir_vmu, _ = _find_dir_with_ext([system_dir, saves_dir], '.vmu', max_depth=3)
            fc_dir_vms, _ = _find_dir_with_ext([system_dir, saves_dir], '.vms', max_depth=3)
            chosen = next((d for d in [fc_dir_bin, fc_dir_vmu, fc_dir_vms] if d), None)
            if not chosen:
                return []
            profiles: List[ProfileEntry] = []
            for f in _iter_files_shallow(chosen):
                ext = os.path.splitext(f)[1].lower()
                if ext not in ('.bin', '.vmu', '.vms'):
                    continue
                base = os.path.splitext(os.path.basename(f))[0]
                display = re.sub(r"\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$", "", base).strip() or base
                profiles.append({'id': base, 'name': display, 'paths': [f]})
            return profiles

    core_dir = os.path.join(saves_dir, core_name)
    if not os.path.isdir(core_dir):
        return []

    profiles: List[ProfileEntry] = []

    try:
        for full in _iter_files_shallow(core_dir):
            entry = os.path.basename(full)
            base = os.path.splitext(entry)[0]
            display = re.sub(r"\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$", "", base).strip() or base
            profiles.append({'id': base, 'name': display, 'paths': [full]})
    except Exception as e:
        log.error(f"Error scanning core directory '{core_dir}': {e}")
        return []

    return profiles


