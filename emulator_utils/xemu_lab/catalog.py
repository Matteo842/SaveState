"""Catalogo read-only degli scenari HDD del laboratorio."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .qcow2 import QCOW2BlockDevice, QCOW2Error


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "hdd_backups.json"
DEFAULT_XEMU_TOML = (
    Path.home() / "AppData" / "Roaming" / "xemu" / "xemu" / "xemu.toml"
)


class CatalogError(Exception):
    """Configurazione del catalogo assente o non valida."""


@dataclass(frozen=True)
class RegisteredScenario:
    scenario_id: str
    filename: str
    description: str
    games: Tuple[str, ...]
    checkpoint: Optional[int]


@dataclass(frozen=True)
class CatalogConfig:
    xemu_root: Path
    backup_folder: Path
    target_hdd: str
    scenarios: Tuple[RegisteredScenario, ...]

    @property
    def target_path(self) -> Path:
        return self.xemu_root / self.target_hdd


@dataclass(frozen=True)
class QCOW2Metadata:
    version: int
    guest_size: int
    cluster_size: int
    host_size: int
    dirty: bool


@dataclass(frozen=True)
class CatalogEntry:
    scenario_id: Optional[str]
    configured_filename: Optional[str]
    actual_path: Path
    description: str
    games: Tuple[str, ...]
    checkpoint: Optional[int]
    registered: bool
    exists: bool
    filename_case_mismatch: bool
    host_size: Optional[int]
    modified_at: Optional[datetime]
    qcow2: Optional[QCOW2Metadata]
    error: Optional[str]

    @property
    def display_id(self) -> str:
        return self.scenario_id if self.scenario_id is not None else "?"


class HDDCatalog:
    """Legge il registro e l'archivio senza scrivere metadati o sidecar."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        self.config_path = Path(config_path)
        self.config = load_config(self.config_path)

    def entries(self, include_unregistered: bool = True) -> List[CatalogEntry]:
        actual_files = self._actual_qcow2_files()
        consumed: set[str] = set()
        entries: List[CatalogEntry] = []

        for scenario in self.config.scenarios:
            key = scenario.filename.casefold()
            actual = actual_files.get(key)
            if actual is not None:
                consumed.add(key)
                entries.append(
                    self._build_entry(
                        actual,
                        scenario=scenario,
                        registered=True,
                        exists=True,
                    )
                )
            else:
                expected = self.config.backup_folder / scenario.filename
                entries.append(
                    CatalogEntry(
                        scenario_id=scenario.scenario_id,
                        configured_filename=scenario.filename,
                        actual_path=expected,
                        description=scenario.description,
                        games=scenario.games,
                        checkpoint=scenario.checkpoint,
                        registered=True,
                        exists=False,
                        filename_case_mismatch=False,
                        host_size=None,
                        modified_at=None,
                        qcow2=None,
                        error="File non trovato",
                    )
                )

        if include_unregistered:
            for key, path in sorted(
                actual_files.items(),
                key=lambda item: item[1].name.casefold(),
            ):
                if key in consumed:
                    continue
                entries.append(
                    self._build_entry(
                        path,
                        scenario=None,
                        registered=False,
                        exists=True,
                    )
                )
        return entries

    def find(self, identifier: str) -> CatalogEntry:
        folded = identifier.strip().casefold()
        for entry in self.entries(include_unregistered=True):
            candidates = {
                entry.actual_path.name.casefold(),
                entry.actual_path.stem.casefold(),
            }
            if entry.scenario_id is not None:
                candidates.add(entry.scenario_id.casefold())
            if entry.configured_filename is not None:
                candidates.add(entry.configured_filename.casefold())
            if folded in candidates:
                return entry
        raise KeyError(f"Scenario o file non trovato: {identifier}")

    def inspect_path(self, path: Path) -> CatalogEntry:
        candidate = Path(path)
        return self._build_entry(
            candidate,
            scenario=None,
            registered=False,
            exists=candidate.is_file(),
        )

    def _actual_qcow2_files(self) -> Dict[str, Path]:
        folder = self.config.backup_folder
        if not folder.is_dir():
            return {}
        return {
            path.name.casefold(): path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.casefold() == ".qcow2"
        }

    def _build_entry(
        self,
        path: Path,
        scenario: Optional[RegisteredScenario],
        registered: bool,
        exists: bool,
    ) -> CatalogEntry:
        if scenario is None:
            scenario_id = None
            configured_filename = None
            description = "Non catalogato; significato non dedotto"
            games: Tuple[str, ...] = ()
            checkpoint = None
        else:
            scenario_id = scenario.scenario_id
            configured_filename = scenario.filename
            description = scenario.description
            games = scenario.games
            checkpoint = scenario.checkpoint

        if not exists:
            return CatalogEntry(
                scenario_id=scenario_id,
                configured_filename=configured_filename,
                actual_path=path,
                description=description,
                games=games,
                checkpoint=checkpoint,
                registered=registered,
                exists=False,
                filename_case_mismatch=False,
                host_size=None,
                modified_at=None,
                qcow2=None,
                error="File non trovato",
            )

        stat = path.stat()
        metadata: Optional[QCOW2Metadata] = None
        error: Optional[str] = None
        try:
            with QCOW2BlockDevice(path) as device:
                metadata = QCOW2Metadata(
                    version=device.header.version,
                    guest_size=device.size,
                    cluster_size=device.cluster_size,
                    host_size=device.host_size,
                    dirty=device.header.is_dirty,
                )
        except (OSError, QCOW2Error, ValueError) as exc:
            error = str(exc)

        return CatalogEntry(
            scenario_id=scenario_id,
            configured_filename=configured_filename,
            actual_path=path,
            description=description,
            games=games,
            checkpoint=checkpoint,
            registered=registered,
            exists=True,
            filename_case_mismatch=bool(
                configured_filename
                and configured_filename != path.name
            ),
            host_size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            qcow2=metadata,
            error=error,
        )


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> CatalogConfig:
    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(
            f"Impossibile leggere {config_path}: {exc}"
        ) from exc

    required = ("xemu_root", "backup_folder", "target_hdd", "backups")
    missing = [key for key in required if key not in raw]
    if missing:
        raise CatalogError(
            "Chiavi mancanti nel catalogo: " + ", ".join(missing)
        )
    if not isinstance(raw["backups"], list):
        raise CatalogError("'backups' deve essere una lista")

    scenarios: List[RegisteredScenario] = []
    seen_ids: set[str] = set()
    for item in raw["backups"]:
        if not isinstance(item, dict):
            raise CatalogError("Scenario catalogo non valido")
        try:
            scenario_id = str(item["id"])
            filename = str(item["filename"])
            description = str(item["description"])
        except KeyError as exc:
            raise CatalogError(
                f"Campo scenario mancante: {exc.args[0]}"
            ) from exc

        folded_id = scenario_id.casefold()
        if folded_id in seen_ids:
            raise CatalogError(f"ID scenario duplicato: {scenario_id}")
        seen_ids.add(folded_id)

        games_value = item.get("games", [])
        if not isinstance(games_value, list):
            raise CatalogError(
                f"Lista giochi non valida per scenario {scenario_id}"
            )
        checkpoint_value = item.get("checkpoint")
        checkpoint = (
            int(checkpoint_value)
            if checkpoint_value is not None
            else None
        )
        scenarios.append(
            RegisteredScenario(
                scenario_id=scenario_id,
                filename=filename,
                description=description,
                games=tuple(str(game) for game in games_value),
                checkpoint=checkpoint,
            )
        )

    return CatalogConfig(
        xemu_root=Path(str(raw["xemu_root"])),
        backup_folder=Path(str(raw["backup_folder"])),
        target_hdd=str(raw["target_hdd"]),
        scenarios=tuple(scenarios),
    )


def read_xemu_hdd_path(path: Path = DEFAULT_XEMU_TOML) -> Optional[Path]:
    """Legge solo `sys.files.hdd_path` dal TOML senza modificarlo."""

    config_path = Path(path)
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    in_sys_files = False
    section_pattern = re.compile(r"^\s*\[([^\]]+)\]\s*$")
    hdd_pattern = re.compile(
        r"""^\s*hdd_path\s*=\s*(['"])(.*?)\1\s*$"""
    )
    for line in lines:
        section = section_pattern.match(line)
        if section:
            in_sys_files = section.group(1).strip() == "sys.files"
            continue
        if not in_sys_files:
            continue
        match = hdd_pattern.match(line)
        if match:
            return Path(match.group(2))
    return None


def cataloged_paths(entries: Iterable[CatalogEntry]) -> Tuple[Path, ...]:
    return tuple(entry.actual_path for entry in entries if entry.exists)
