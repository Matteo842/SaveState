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


def _expand(path_str: Optional[str], base: Optional[str], cfg_dir: Optional[str] = None) -> Optional[str]:
    """Expand user, env vars and RetroArch's ':' path macro.

    RetroArch writes relative paths in retroarch.cfg using a leading ':' to mean
    "the directory containing retroarch.cfg" (or the binary directory on portable
    installs). Examples seen in the wild:
        savefile_directory = ":\\saves"      (Windows)
        savefile_directory = ":/saves"       (Linux/macOS)
        savefile_directory = ":"              (the config dir itself)

    Without special handling, these produce invalid paths on disk and
    auto-detection silently fails.
    """
    if not path_str:
        return None
    try:
        s = path_str.strip().strip('"').strip("'")
        if not s:
            return None

        if s == ':' or s.startswith(':/') or s.startswith(':\\'):
            anchor = cfg_dir or base
            if anchor:
                remainder = s[1:]
                remainder = remainder.lstrip('/\\')
                s = os.path.join(anchor, remainder) if remainder else anchor

        expanded = os.path.expandvars(os.path.expanduser(s))
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
        # Some packaged builds ship the config one level up from the binary
        parent = os.path.dirname(ra_root)
        if parent and parent != ra_root:
            cfg_candidates.append(os.path.join(parent, 'retroarch.cfg'))
            cfg_candidates.append(os.path.join(parent, 'config', 'retroarch.cfg'))
    if platform.system() == 'Windows':
        appdata = os.getenv('APPDATA')
        if appdata:
            cfg_candidates.append(os.path.join(appdata, 'RetroArch', 'retroarch.cfg'))
        # RetroArch from the Microsoft Store / other packaged installs
        local_appdata = os.getenv('LOCALAPPDATA')
        if local_appdata:
            cfg_candidates.append(os.path.join(local_appdata, 'RetroArch', 'retroarch.cfg'))
            cfg_candidates.append(os.path.join(local_appdata, 'Packages', 'RetroArch', 'LocalState', 'retroarch.cfg'))
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
    cfg_dir = os.path.dirname(cfg_path) if cfg_path else None

    if cfg_path:
        log.info(f"RetroArch: using config file '{cfg_path}'")
    else:
        log.info(f"RetroArch: no retroarch.cfg found. Searched: {cfg_candidates}")

    # Resolve directories
    def _is_unset_dir_value(v: Optional[str]) -> bool:
        if v is None:
            return True
        v_stripped = v.strip().strip('"')
        return v_stripped == '' or v_stripped.lower() == 'default'

    explicit_saves: Optional[str] = None
    explicit_system: Optional[str] = None
    explicit_states: Optional[str] = None
    if cfg:
        saves_val = cfg.get('savefile_directory')
        system_val = cfg.get('system_directory')
        states_val = cfg.get('savestate_directory')
        if not _is_unset_dir_value(saves_val):
            explicit_saves = _expand(saves_val, ra_root, cfg_dir)
        if not _is_unset_dir_value(system_val):
            explicit_system = _expand(system_val, ra_root, cfg_dir)
        if not _is_unset_dir_value(states_val):
            explicit_states = _expand(states_val, ra_root, cfg_dir)
        log.debug(
            "RetroArch cfg paths: savefile=%s system=%s savestate=%s",
            explicit_saves, explicit_system, explicit_states
        )

    # Default directories by platform
    default_saves: Optional[str] = None
    default_system: Optional[str] = None
    default_states: Optional[str] = None
    sysname = platform.system()
    if sysname == 'Windows':
        default_saves = _get_saves_dir(ra_root)
        default_system = os.path.join(ra_root, 'system') if ra_root and os.path.isdir(os.path.join(ra_root, 'system')) else None
        default_states = os.path.join(ra_root, 'states') if ra_root and os.path.isdir(os.path.join(ra_root, 'states')) else None
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
        default_states = _first_existing_dir([
            os.path.join(ra_root, 'states') if ra_root else None,
            os.path.join(xdg_config, 'retroarch', 'states'),
            os.path.join(home, '.config', 'retroarch', 'states'),
            os.path.join(xdg_data, 'retroarch', 'states'),
            os.path.join(home, '.local', 'share', 'retroarch', 'states'),
            os.path.join(home, '.var', 'app', 'org.libretro.RetroArch', 'config', 'retroarch', 'states'),
            os.path.join(home, '.var', 'app', 'org.libretro.RetroArch', 'data', 'retroarch', 'states'),
            os.path.join(home, 'snap', 'retroarch', 'current', '.config', 'retroarch', 'states'),
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
        default_states = _first_existing_dir([
            os.path.join(ra_root, 'states') if ra_root else None,
            os.path.join(home, 'Library', 'Application Support', 'RetroArch', 'states'),
        ])

    saves_dir = explicit_saves if (explicit_saves and os.path.isdir(explicit_saves)) else default_saves
    system_dir = explicit_system if (explicit_system and os.path.isdir(explicit_system)) else default_system
    states_dir = explicit_states if (explicit_states and os.path.isdir(explicit_states)) else default_states

    log.info(
        "RetroArch resolved paths: ra_root=%s saves_dir=%s system_dir=%s states_dir=%s",
        ra_root, saves_dir, system_dir, states_dir
    )

    return {
        'ra_root': ra_root,
        'cfg_path': cfg_path,
        'saves_dir': saves_dir,
        'system_dir': system_dir,
        'states_dir': states_dir,
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
    Return cores from RetroArch 'saves' directory (and, as a supplement, 'states').

    Structure expected (default RetroArch layout, also used with custom paths):
      <saves_dir>/<CoreName>/<GameName>.<ext>
      <states_dir>/<CoreName>/<GameName>.state*

    When a user has configured custom save/savestate directories (e.g., on a
    microSD card shared across OSes), those directories are honored via
    retroarch.cfg. When per-core subfolders exist only under states (e.g.,
    'sort savestates by core' is enabled but 'sort savefiles by core' isn't),
    we still surface those cores so users can locate them.
    """
    paths = _resolve_ra_paths(executable_path_or_dir)
    saves_dir = paths.get('saves_dir')
    system_dir = paths.get('system_dir')
    states_dir = paths.get('states_dir')
    cores: List[CoreEntry] = []
    if not saves_dir and not states_dir:
        log.warning(
            "RetroArch: no saves/states directories found. "
            "Checked cfg '%s'. Consider setting 'savefile_directory' in retroarch.cfg "
            "to an absolute path (useful when saves live on a microSD or external drive).",
            paths.get('cfg_path')
        )
        return cores

    try:
        # Normal cores from saves/<CoreName>
        seen_ids: Dict[str, int] = {}
        if saves_dir and os.path.isdir(saves_dir):
            for entry in os.listdir(saves_dir):
                core_path = os.path.join(saves_dir, entry)
                if not os.path.isdir(core_path):
                    continue
                count = len(_iter_files_shallow(core_path))
                if count > 0:
                    seen_ids[entry] = seen_ids.get(entry, 0) + count

        # Supplement with cores found under states/<CoreName> (if per-core sorted)
        if states_dir and os.path.isdir(states_dir):
            for entry in os.listdir(states_dir):
                states_core_path = os.path.join(states_dir, entry)
                if not os.path.isdir(states_core_path):
                    continue
                count = len(_iter_files_shallow(states_core_path))
                if count > 0:
                    seen_ids[entry] = seen_ids.get(entry, 0) + count

        for core_id, count in seen_ids.items():
            cores.append({'id': core_id, 'name': core_id, 'count': count})

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
        log.error(f"Error listing cores (saves='{saves_dir}', states='{states_dir}'): {e}")
        return []

    cores.sort(key=lambda c: (c.get("name", "").lower()))
    if not cores:
        log.info(
            "RetroArch: cores listing is empty. saves_dir='%s' states_dir='%s'. "
            "Check that the directory contains per-core subfolders with save files.",
            saves_dir, states_dir
        )
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
    states_dir = paths.get('states_dir')
    if not saves_dir and not states_dir:
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

    core_dirs: List[str] = []
    if saves_dir:
        candidate = os.path.join(saves_dir, core_name)
        if os.path.isdir(candidate):
            core_dirs.append(candidate)
    if states_dir:
        candidate = os.path.join(states_dir, core_name)
        if os.path.isdir(candidate):
            core_dirs.append(candidate)

    if not core_dirs:
        return []

    profiles: List[ProfileEntry] = []
    seen: Dict[str, ProfileEntry] = {}

    try:
        for core_dir in core_dirs:
            for full in _iter_files_shallow(core_dir):
                entry = os.path.basename(full)
                base = os.path.splitext(entry)[0]
                display = re.sub(r"\s*\([A-Za-z]{2}(?:,[A-Za-z]{2})+\)$", "", base).strip() or base
                key = base.lower()
                if key in seen:
                    if full not in seen[key]['paths']:
                        seen[key]['paths'].append(full)
                else:
                    seen[key] = {'id': base, 'name': display, 'paths': [full]}
        profiles = list(seen.values())
    except Exception as e:
        log.error(f"Error scanning core directories {core_dirs}: {e}")
        return []

    return profiles


