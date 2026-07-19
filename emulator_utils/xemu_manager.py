# emulator_utils/xemu_manager.py
# -*- coding: utf-8 -*-
"""Discovery profili xemu (config → HDD → Title ID su FATX).

Niente backup/restore qui: quello va in core / runner SaveState.
Quando sposti il file in SaveState, metti anche la cartella ``xemu_lab/``
accanto a questo manager (dentro ``emulator_utils/``).
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import platform
import re
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    tomllib = None  # type: ignore

try:
    from .obfuscation_utils import xor_bytes
except ImportError:  # pragma: no cover - fuori da SaveState / senza obfuscation
    try:
        from obfuscation_utils import xor_bytes  # type: ignore
    except ImportError:
        xor_bytes = None  # type: ignore

try:
    from .xemu_lab.titles import list_games_on_image
except ImportError:
    from xemu_lab.titles import list_games_on_image  # type: ignore


_title_map: dict[str, str] = {}
_title_map_loaded = False


def _manager_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _load_title_map() -> dict[str, str]:
    """Carica mappa Title ID → nome (JSON in dev, PKL obfuscato in release)."""

    global _title_map, _title_map_loaded
    if _title_map_loaded:
        return _title_map

    _title_map_loaded = True
    base = _manager_dir()
    json_path = os.path.join(base, "xbox_title_id_map.json")
    pkl_path = os.path.join(base, "xbox_title_id_map.pkl")

    try:
        with open(json_path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if isinstance(raw, dict):
            for tid, name in raw.items():
                if isinstance(tid, str) and isinstance(name, str):
                    _title_map[tid.strip().lower()] = name
            log.info("Loaded %s Xbox titles from xbox_title_id_map.json", len(_title_map))
            return _title_map
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.debug("Xbox title JSON not usable: %s", exc)

    try:
        with open(pkl_path, "rb") as handle:
            obf_map = pickle.load(handle)
        if not isinstance(obf_map, dict):
            return _title_map
        for tid, payload in obf_map.items():
            try:
                if xor_bytes is None:
                    if isinstance(payload, str):
                        _title_map[str(tid).strip().lower()] = payload
                    continue
                if isinstance(payload, bytes):
                    _title_map[str(tid).strip().lower()] = xor_bytes(payload).decode(
                        "utf-8"
                    )
                elif isinstance(payload, str):
                    _title_map[str(tid).strip().lower()] = payload
            except Exception:
                continue
        log.info("Loaded %s Xbox titles from xbox_title_id_map.pkl", len(_title_map))
    except FileNotFoundError:
        log.debug("No Xbox title map (json/pkl) next to xemu_manager.")
    except Exception as exc:
        log.debug("Xbox title PKL not usable: %s", exc)

    return _title_map


def _display_name(title_id: str) -> str:
    tid = title_id.strip().lower()
    names = _load_title_map()
    if tid in names:
        return names[tid]
    # Fallback piccolo di xemu_lab se la mappa non c'è.
    try:
        from .xemu_lab.titles import game_display_name
    except ImportError:
        try:
            from xemu_lab.titles import game_display_name  # type: ignore
        except ImportError:
            return f"Unknown ({tid})"
    return game_display_name(tid)


def _candidate_toml_paths(executable_path: str | None) -> list[str]:
    """Ordine: portable (accanto all'exe), poi path standard OS."""

    candidates: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        normalized = os.path.normcase(os.path.normpath(path))
        if normalized in seen:
            return
        seen.add(normalized)
        candidates.append(path)

    if executable_path:
        if os.path.isfile(executable_path):
            exe_dir = os.path.dirname(executable_path)
        elif os.path.isdir(executable_path):
            exe_dir = executable_path
        else:
            exe_dir = None
        if exe_dir:
            add(os.path.join(exe_dir, "xemu.toml"))

    system = platform.system()
    home = os.path.expanduser("~")

    if system == "Windows":
        appdata = os.getenv("APPDATA")
        if appdata:
            add(os.path.join(appdata, "xemu", "xemu", "xemu.toml"))
    elif system == "Linux":
        xdg_data = os.getenv("XDG_DATA_HOME", os.path.join(home, ".local", "share"))
        add(os.path.join(xdg_data, "xemu", "xemu", "xemu.toml"))
        add(
            os.path.join(
                home,
                ".var",
                "app",
                "app.xemu.xemu",
                "data",
                "xemu",
                "xemu",
                "xemu.toml",
            )
        )
        # Alcune build usano anche XDG_CONFIG.
        xdg_config = os.getenv("XDG_CONFIG_HOME", os.path.join(home, ".config"))
        add(os.path.join(xdg_config, "xemu", "xemu", "xemu.toml"))
    elif system == "Darwin":
        add(
            os.path.join(
                home,
                "Library",
                "Application Support",
                "xemu",
                "xemu",
                "xemu.toml",
            )
        )

    return candidates


def _parse_hdd_path_simple(text: str) -> str | None:
    """Fallback senza tomllib: cerca hdd_path sotto [sys.files]."""

    in_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line.lower() == "[sys.files]"
            continue
        if not in_section:
            continue
        match = re.match(
            r"^hdd_path\s*=\s*(['\"])(.*)\1\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(2).strip() or None
        # TOML senza quote (raro)
        match = re.match(r"^hdd_path\s*=\s*(.+)$", line, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip("\"'") or None
    return None


def _read_hdd_path_from_toml(toml_path: str) -> str | None:
    try:
        with open(toml_path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        log.debug("Cannot read %s: %s", toml_path, exc)
        return None

    hdd: str | None = None
    if tomllib is not None:
        try:
            data = tomllib.loads(raw.decode("utf-8"))
            files = data.get("sys", {}).get("files", {})
            if isinstance(files, dict):
                value = files.get("hdd_path")
                if isinstance(value, str) and value.strip():
                    hdd = value.strip()
        except Exception as exc:
            log.debug("tomllib failed on %s: %s — fallback line parse", toml_path, exc)

    if not hdd:
        try:
            hdd = _parse_hdd_path_simple(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            log.debug("Simple TOML parse failed on %s: %s", toml_path, exc)
            return None

    if not hdd:
        return None

    if not os.path.isabs(hdd):
        hdd = os.path.normpath(os.path.join(os.path.dirname(toml_path), hdd))
    return hdd


def find_xemu_toml(executable_path: str | None = None) -> str | None:
    """Restituisce il primo ``xemu.toml`` esistente (portable → standard)."""

    for path in _candidate_toml_paths(executable_path):
        if os.path.isfile(path):
            log.info("Found xemu.toml: %s", path)
            return path
    log.warning("xemu.toml not found (portable or standard locations).")
    return None


def get_xemu_hdd_path(executable_path: str | None = None) -> str | None:
    """Path assoluto dell'HDD QCOW2 in uso da xemu (da ``xemu.toml``)."""

    toml_path = find_xemu_toml(executable_path)
    if not toml_path:
        return None

    hdd = _read_hdd_path_from_toml(toml_path)
    if not hdd:
        log.error("hdd_path missing in %s", toml_path)
        return None
    if not os.path.isfile(hdd):
        log.error("HDD path from config does not exist: %s", hdd)
        return None

    log.info("xemu HDD in use: %s", hdd)
    return hdd


def find_xemu_profiles(executable_path: str | None = None) -> list[dict[str, Any]]:
    """Elenca i giochi (UDATA) sull'HDD live di xemu.

    Ogni profilo:
      - ``id``: Title ID (8 hex)
      - ``name``: nome display
      - ``paths``: ``[hdd_path]`` — stesso file per tutti i Title ID;
        il backup/restore chirurgico andrà gestito in core (non copiare
        l'intero QCOW2 come se fosse una cartella save).
      - ``title_id``: stesso di ``id`` (comodo per core)
      - ``hdd_path``: path assoluto HDD
      - ``area``: ``UDATA``
    """

    log.info("Attempting to find xemu profiles...")
    hdd_path = get_xemu_hdd_path(executable_path)
    if not hdd_path:
        log.error("Cannot find xemu profiles: HDD path unknown.")
        return []

    try:
        games = list_games_on_image(hdd_path, partition="E", areas=("UDATA",))
    except Exception as exc:
        log.error("Failed scanning xemu HDD '%s': %s", hdd_path, exc, exc_info=True)
        return []

    profiles: list[dict[str, Any]] = []
    for game in games:
        tid = game.title_id.lower()
        profiles.append(
            {
                "id": tid,
                "name": _display_name(tid),
                "paths": [hdd_path],
                "emulator": "xemu",
                "title_id": tid,
                "hdd_path": hdd_path,
                "area": game.area,
            }
        )

    log.info("Found %s xemu profiles on %s", len(profiles), hdd_path)
    return profiles


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    exe = None
    if os.path.isfile(r"D:\xemu\xemu.exe"):
        exe = r"D:\xemu\xemu.exe"
    for profile in find_xemu_profiles(exe):
        print(profile)
