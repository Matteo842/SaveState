"""Backup chirurgico guest-aware di un Title ID FATX (XBSV v6/v7)."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple, Union

from .fatx import DirectoryEntry, FATXVolume
from .qcow2 import BlockDevice, QCOW2BlockDevice
from .titles import game_display_name


PathLike = Union[str, Path]

XBSV_MAGIC = b"XBSV"
XBSV_VERSION = 7
XBSV_MIN_READ_VERSION = 6
DEFAULT_BACKUP_DIR = Path(__file__).resolve().parent.parent / "surgical_backups_v6"


class BackupError(Exception):
    """Errore durante l'estrazione o la serializzazione del backup."""


@dataclass
class GameBackup:
    title_id: str
    partition: str
    source_path: Path
    source_sha256: str
    created_at: datetime
    fat_entry_size: int
    fatx_cluster_size: int
    directory_entries: List[Tuple[int, bytes]] = field(default_factory=list)
    fat_runs: List[Tuple[int, int, bytes]] = field(default_factory=list)
    # (first_cluster, guest_offset, blob)
    data_chunks: List[Tuple[int, int, bytes]] = field(default_factory=list)
    # (fatx_cluster, guest_offset, payload)
    qcow2_envelopes: List[Tuple[int, bytes]] = field(default_factory=list)
    # (qcow2_guest_cluster, full_cluster_bytes)
    qcow2_cluster_size: int = 0
    format_version: int = XBSV_VERSION

    @property
    def cluster_count(self) -> int:
        return len(self.data_chunks)

    @property
    def directory_entry_count(self) -> int:
        return len(self.directory_entries)

    @property
    def has_qcow2_envelopes(self) -> bool:
        return bool(self.qcow2_envelopes)


def backup_title_id(
    device: BlockDevice,
    title_id: str,
    source_path: PathLike,
    partition: str = "E",
    areas: Sequence[str] = ("UDATA",),
) -> GameBackup:
    """Estrae directory entries, FAT, cluster dati e envelope QCOW2."""

    normalized = title_id.strip().lower()
    if len(normalized) != 8:
        raise BackupError(f"Title ID non valido: {title_id}")

    volume = FATXVolume.open_partition(device, partition)
    directory_entries: List[Tuple[int, bytes]] = []
    clusters: Set[int] = set()
    seen_entry_offsets: Set[int] = set()

    root = volume.header.root_dir_first_cluster
    found_any = False

    for area_name in areas:
        area_entry = volume.find_child(root, area_name)
        if area_entry is None or not area_entry.is_directory:
            continue
        game_entry = volume.find_child(area_entry.first_cluster, normalized)
        if game_entry is None:
            # Title ID sul disco può essere mixed-case.
            game_entry = volume.find_child(area_entry.first_cluster, title_id)
        if game_entry is None or not game_entry.is_directory:
            continue

        found_any = True
        _add_directory_entry(directory_entries, seen_entry_offsets, game_entry)
        clusters.update(volume.get_chain(game_entry.first_cluster))

        for item in volume.walk(
            first_cluster=game_entry.first_cluster,
            base_path=f"{area_name.upper()}\\{normalized}",
        ):
            _add_directory_entry(directory_entries, seen_entry_offsets, item.entry)
            if item.entry.first_cluster > 0:
                clusters.update(volume.get_chain(item.entry.first_cluster))

    if not found_any:
        raise BackupError(
            f"Title ID {normalized} non trovato in "
            f"{partition}:\\{'/'.join(areas)}"
        )
    if not clusters:
        raise BackupError(f"Nessun cluster dati per {normalized}")

    sorted_clusters = sorted(clusters)
    fat_runs = _build_fat_runs(volume, sorted_clusters)
    data_chunks: List[Tuple[int, int, bytes]] = []
    for cluster in sorted_clusters:
        guest_offset = volume.cluster_offset(cluster)
        data_chunks.append(
            (
                cluster,
                guest_offset,
                volume.read_cluster(cluster),
            )
        )

    ranges: List[Tuple[int, int]] = []
    for guest_offset, raw in directory_entries:
        ranges.append((guest_offset, len(raw)))
    for _first, guest_offset, blob in fat_runs:
        ranges.append((guest_offset, len(blob)))
    for _cluster, guest_offset, payload in data_chunks:
        ranges.append((guest_offset, len(payload)))

    qcow2_cluster_size = int(getattr(device, "cluster_size", 0) or 0)
    envelopes: List[Tuple[int, bytes]] = []
    if qcow2_cluster_size > 0:
        envelopes = _collect_qcow2_envelopes(device, ranges, qcow2_cluster_size)

    source = Path(source_path)
    return GameBackup(
        title_id=normalized,
        partition=partition.upper(),
        source_path=source,
        source_sha256=_sha256_file(source) if source.is_file() else "",
        created_at=datetime.now(timezone.utc),
        fat_entry_size=volume.header.fat_entry_size,
        fatx_cluster_size=volume.header.cluster_size,
        directory_entries=directory_entries,
        fat_runs=fat_runs,
        data_chunks=data_chunks,
        qcow2_envelopes=envelopes,
        qcow2_cluster_size=qcow2_cluster_size,
        format_version=XBSV_VERSION,
    )


def backup_title_id_from_path(
    image_path: PathLike,
    title_id: str,
    partition: str = "E",
    areas: Sequence[str] = ("UDATA",),
) -> GameBackup:
    path = Path(image_path)
    with QCOW2BlockDevice(path) as device:
        return backup_title_id(
            device,
            title_id,
            source_path=path,
            partition=partition,
            areas=areas,
        )


def save_backup(
    backup: GameBackup,
    output_dir: PathLike = DEFAULT_BACKUP_DIR,
) -> Tuple[Path, Path]:
    """Serializza XBSV + sidecar JSON. Restituisce (bin_path, json_path)."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    game_name = game_display_name(backup.title_id)
    stem = _backup_filename_stem(game_name, backup.created_at, backup.title_id)
    bin_path = _unique_path(out / f"{stem}.bin")
    json_path = bin_path.with_suffix(".json")

    payload = serialize_backup(backup)
    digest = hashlib.sha256(payload).hexdigest()
    bin_path.write_bytes(payload)

    meta = {
        "format": "XBSV",
        "version": backup.format_version,
        "title_id": backup.title_id,
        "game_name": game_name,
        "partition": backup.partition,
        "source_path": str(backup.source_path),
        "source_sha256": backup.source_sha256,
        "created_at": backup.created_at.isoformat(),
        "fat_entry_size": backup.fat_entry_size,
        "fatx_cluster_size": backup.fatx_cluster_size,
        "directory_entries": backup.directory_entry_count,
        "fat_runs": len(backup.fat_runs),
        "data_clusters": backup.cluster_count,
        "qcow2_envelopes": len(backup.qcow2_envelopes),
        "qcow2_cluster_size": backup.qcow2_cluster_size,
        "bin_file": bin_path.name,
        "sha256": digest,
        "guest_offsets_only": True,
        "qemu": False,
    }
    json_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return bin_path, json_path


def serialize_backup(backup: GameBackup) -> bytes:
    version = backup.format_version or XBSV_VERSION
    if backup.qcow2_envelopes and version < 7:
        version = 7
    if version < 7:
        version = 6

    header = bytearray()
    header.extend(XBSV_MAGIC)
    header.extend(struct.pack("<I", version))
    title = backup.title_id.encode("ascii")
    if len(title) != 8:
        raise BackupError("Title ID deve essere ASCII da 8 caratteri")
    header.extend(title)
    header.extend(backup.partition.encode("ascii")[:1].ljust(1, b"E"))
    header.extend(struct.pack("<I", backup.fat_entry_size))
    header.extend(struct.pack("<I", backup.fatx_cluster_size))
    created = int(backup.created_at.timestamp())
    header.extend(struct.pack("<Q", created))
    source_hash = bytes.fromhex(backup.source_sha256) if backup.source_sha256 else bytes(32)
    if len(source_hash) != 32:
        raise BackupError("source_sha256 non valido")
    header.extend(source_hash)

    header.extend(struct.pack("<I", len(backup.directory_entries)))
    for guest_offset, raw in backup.directory_entries:
        if len(raw) != 64:
            raise BackupError("Directory entry deve essere da 64 byte")
        header.extend(struct.pack("<Q", guest_offset))
        header.extend(raw)

    header.extend(struct.pack("<I", len(backup.fat_runs)))
    for first_cluster, guest_offset, blob in backup.fat_runs:
        header.extend(struct.pack("<I", first_cluster))
        header.extend(struct.pack("<Q", guest_offset))
        header.extend(struct.pack("<I", len(blob)))
        header.extend(blob)

    header.extend(struct.pack("<I", len(backup.data_chunks)))
    for cluster, guest_offset, payload in backup.data_chunks:
        header.extend(struct.pack("<I", cluster))
        header.extend(struct.pack("<Q", guest_offset))
        header.extend(struct.pack("<I", len(payload)))
        header.extend(payload)

    if version >= 7:
        header.extend(struct.pack("<I", backup.qcow2_cluster_size))
        header.extend(struct.pack("<I", len(backup.qcow2_envelopes)))
        for guest_cluster, payload in backup.qcow2_envelopes:
            if backup.qcow2_cluster_size and len(payload) != backup.qcow2_cluster_size:
                raise BackupError(
                    "Envelope QCOW2 con dimensione non coerente"
                )
            header.extend(struct.pack("<I", guest_cluster))
            header.extend(struct.pack("<I", len(payload)))
            header.extend(payload)

    return bytes(header)


def load_backup(bin_path: PathLike, json_path: Optional[PathLike] = None) -> GameBackup:
    path = Path(bin_path)
    payload = path.read_bytes()
    if json_path is not None:
        meta = json.loads(Path(json_path).read_text(encoding="utf-8"))
        expected = meta.get("sha256")
        if expected:
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected:
                raise BackupError(
                    f"Hash backup non corrispondente: {actual} != {expected}"
                )

    return deserialize_backup(payload, source_hint=path)


def deserialize_backup(
    payload: bytes,
    source_hint: Optional[Path] = None,
) -> GameBackup:
    if len(payload) < 61:
        raise BackupError("Backup troncato")
    if payload[:4] != XBSV_MAGIC:
        raise BackupError("Magic XBSV assente")
    version = struct.unpack_from("<I", payload, 4)[0]
    if version < XBSV_MIN_READ_VERSION or version > XBSV_VERSION:
        raise BackupError(f"Versione backup non supportata: {version}")

    title_id = payload[8:16].decode("ascii")
    partition = chr(payload[16])
    fat_entry_size, fatx_cluster_size = struct.unpack_from("<II", payload, 17)
    created = struct.unpack_from("<Q", payload, 25)[0]
    source_hash = payload[33:65].hex()
    cursor = 65

    def need(size: int) -> None:
        nonlocal cursor
        if cursor + size > len(payload):
            raise BackupError("Backup troncato durante il parse")

    need(4)
    dir_count = struct.unpack_from("<I", payload, cursor)[0]
    cursor += 4
    directory_entries: List[Tuple[int, bytes]] = []
    for _ in range(dir_count):
        need(8 + 64)
        guest_offset = struct.unpack_from("<Q", payload, cursor)[0]
        cursor += 8
        raw = payload[cursor : cursor + 64]
        cursor += 64
        directory_entries.append((guest_offset, raw))

    need(4)
    fat_run_count = struct.unpack_from("<I", payload, cursor)[0]
    cursor += 4
    fat_runs: List[Tuple[int, int, bytes]] = []
    for _ in range(fat_run_count):
        need(4 + 8 + 4)
        first_cluster = struct.unpack_from("<I", payload, cursor)[0]
        cursor += 4
        guest_offset = struct.unpack_from("<Q", payload, cursor)[0]
        cursor += 8
        blob_size = struct.unpack_from("<I", payload, cursor)[0]
        cursor += 4
        need(blob_size)
        blob = payload[cursor : cursor + blob_size]
        cursor += blob_size
        fat_runs.append((first_cluster, guest_offset, blob))

    need(4)
    chunk_count = struct.unpack_from("<I", payload, cursor)[0]
    cursor += 4
    data_chunks: List[Tuple[int, int, bytes]] = []
    for _ in range(chunk_count):
        need(4 + 8 + 4)
        cluster = struct.unpack_from("<I", payload, cursor)[0]
        cursor += 4
        guest_offset = struct.unpack_from("<Q", payload, cursor)[0]
        cursor += 8
        size = struct.unpack_from("<I", payload, cursor)[0]
        cursor += 4
        need(size)
        data = payload[cursor : cursor + size]
        cursor += size
        data_chunks.append((cluster, guest_offset, data))

    qcow2_cluster_size = 0
    envelopes: List[Tuple[int, bytes]] = []
    if version >= 7:
        need(8)
        qcow2_cluster_size = struct.unpack_from("<I", payload, cursor)[0]
        cursor += 4
        env_count = struct.unpack_from("<I", payload, cursor)[0]
        cursor += 4
        for _ in range(env_count):
            need(8)
            guest_cluster = struct.unpack_from("<I", payload, cursor)[0]
            cursor += 4
            size = struct.unpack_from("<I", payload, cursor)[0]
            cursor += 4
            need(size)
            blob = payload[cursor : cursor + size]
            cursor += size
            envelopes.append((guest_cluster, blob))

    if cursor != len(payload):
        raise BackupError(
            f"Byte residui nel backup: {len(payload) - cursor}"
        )

    return GameBackup(
        title_id=title_id,
        partition=partition,
        source_path=source_hint or Path("."),
        source_sha256=source_hash,
        created_at=datetime.fromtimestamp(created, tz=timezone.utc),
        fat_entry_size=fat_entry_size,
        fatx_cluster_size=fatx_cluster_size,
        directory_entries=directory_entries,
        fat_runs=fat_runs,
        data_chunks=data_chunks,
        qcow2_envelopes=envelopes,
        qcow2_cluster_size=qcow2_cluster_size,
        format_version=version,
    )


def list_backups(directory: PathLike = DEFAULT_BACKUP_DIR) -> List[Path]:
    """Elenca i sidecar JSON XBSV v6/v7."""

    folder = Path(directory)
    if not folder.is_dir():
        return []
    results: List[Path] = []
    for path in folder.glob("*.json"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("format") != "XBSV":
            continue
        version = int(meta.get("version", 0))
        if XBSV_MIN_READ_VERSION <= version <= XBSV_VERSION:
            results.append(path)
    return sorted(results, key=lambda p: p.stat().st_mtime)


def backup_display_label(json_path: PathLike) -> str:
    """Etichetta menu: 'Mercenaries (18/07/26 08:49)'."""

    path = Path(json_path)
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path.name

    title_id = str(meta.get("title_id", ""))
    name = str(meta.get("game_name") or game_display_name(title_id) or path.stem)
    created_raw = meta.get("created_at")
    stamp = ""
    if created_raw:
        try:
            created = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            stamp = created.astimezone().strftime("%d/%m/%y %H:%M")
        except ValueError:
            stamp = ""
    version = meta.get("version")
    suffix = f" v{version}" if version else ""
    if stamp:
        return f"{name} ({stamp}){suffix}"
    return f"{name}{suffix}"


def _collect_qcow2_envelopes(
    device: BlockDevice,
    ranges: Sequence[Tuple[int, int]],
    cluster_size: int,
) -> List[Tuple[int, bytes]]:
    """Copia i cluster QCOW2 interi toccati dai range chirurgici."""

    touched: Set[int] = set()
    for offset, size in ranges:
        if size <= 0:
            continue
        start = offset // cluster_size
        end = (offset + size - 1) // cluster_size
        touched.update(range(start, end + 1))

    envelopes: List[Tuple[int, bytes]] = []
    for guest_cluster in sorted(touched):
        guest_offset = guest_cluster * cluster_size
        payload = device.read_at(guest_offset, cluster_size)
        if len(payload) != cluster_size:
            raise BackupError(
                f"Lettura envelope QCOW2 {guest_cluster} incompleta"
            )
        envelopes.append((guest_cluster, payload))
    return envelopes


def _backup_filename_stem(
    game_name: str,
    created_at: datetime,
    title_id: str,
) -> str:
    """Nome file Windows-safe: 'Mercenaries (18-07-26 08-49)'."""

    safe_name = re.sub(r'[<>:"/\\|?*]', "-", game_name).strip() or title_id
    safe_name = re.sub(r"\s+", " ", safe_name)
    if created_at.tzinfo is None:
        local = created_at.replace(tzinfo=timezone.utc).astimezone()
    else:
        local = created_at.astimezone()
    stamp = local.strftime("%d-%m-%y %H-%M")
    return f"{safe_name} ({stamp})"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem} #{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise BackupError(f"Impossibile creare nome unico per {path.name}")


def _add_directory_entry(
    entries: List[Tuple[int, bytes]],
    seen: Set[int],
    entry: DirectoryEntry,
) -> None:
    if entry.guest_offset in seen:
        return
    seen.add(entry.guest_offset)
    entries.append((entry.guest_offset, entry.raw))


def _build_fat_runs(
    volume: FATXVolume,
    clusters: Sequence[int],
) -> List[Tuple[int, int, bytes]]:
    """Costruisce run FAT contigui solo sui cluster del gioco."""

    if not clusters:
        return []

    sorted_unique = sorted(set(clusters))
    runs: List[Tuple[int, int, bytes]] = []
    run_start = sorted_unique[0]
    previous = sorted_unique[0]
    run_values = [volume.read_fat_entry(previous)]

    def flush() -> None:
        nonlocal run_start, run_values
        blob = b"".join(
            value.to_bytes(volume.header.fat_entry_size, "little")
            for value in run_values
        )
        guest_offset = (
            volume.header.fat_offset
            + run_start * volume.header.fat_entry_size
        )
        runs.append((run_start, guest_offset, blob))
        run_values = []

    for cluster in sorted_unique[1:]:
        if cluster == previous + 1:
            run_values.append(volume.read_fat_entry(cluster))
            previous = cluster
            continue
        flush()
        run_start = cluster
        previous = cluster
        run_values = [volume.read_fat_entry(cluster)]
    flush()
    return runs


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
