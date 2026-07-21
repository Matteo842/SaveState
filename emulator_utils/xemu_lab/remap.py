"""FATX remap: reallocate XBSV backup clusters onto free target clusters."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .backup import GameBackup
from .fatx import (
    FATX_DIRENT_END,
    FATX_DIRENT_SIZE,
    FATXBoundsError,
    FATXVolume,
)


class RemapError(Exception):
    """FATX remap rejected or impossible."""


@dataclass(frozen=True)
class RemapPlan:
    """Pending guest writes after cluster reallocation."""

    pending: List[Tuple[int, bytes]]
    cluster_map: Dict[int, int]
    title_dirent_offset: int
    game_first_cluster: int
    mode: str = "remap"


@dataclass
class SameGuestDecision:
    use_same_guest: bool
    reason: str
    colliding_clusters: List[int] = field(default_factory=list)


def decide_restore_path(
    backup: GameBackup,
    volume: FATXVolume,
) -> SameGuestDecision:
    """Choose same-guest vs remap based on FATX collisions on the target."""

    if backup.fatx_cluster_size != volume.header.cluster_size:
        raise RemapError(
            "Backup fatx_cluster_size "
            f"({backup.fatx_cluster_size}) != target "
            f"({volume.header.cluster_size})"
        )
    if backup.fat_entry_size != volume.header.fat_entry_size:
        raise RemapError(
            "Backup fat_entry_size "
            f"({backup.fat_entry_size}) != target "
            f"({volume.header.fat_entry_size})"
        )

    backup_clusters = {cluster for cluster, _go, _payload in backup.data_chunks}
    if not backup_clusters:
        raise RemapError("Backup has no data clusters")

    title_clusters = volume.collect_title_clusters(backup.title_id)
    title_present = bool(title_clusters)

    colliding: List[int] = []
    for cluster in sorted(backup_clusters):
        if volume.is_cluster_free(cluster):
            continue
        if title_present and cluster in title_clusters:
            continue
        colliding.append(cluster)

    if not colliding:
        return SameGuestDecision(
            use_same_guest=True,
            reason=(
                "same-guest: backup clusters free or already owned by Title ID"
                if title_present
                else "same-guest: all backup clusters free"
            ),
        )

    return SameGuestDecision(
        use_same_guest=False,
        reason=(
            "remap: backup FATX clusters occupied by other data"
            if not title_present
            else "remap: backup clusters collide outside Title ID"
        ),
        colliding_clusters=colliding,
    )


def build_remap_plan(
    backup: GameBackup,
    volume: FATXVolume,
) -> RemapPlan:
    """Allocate free clusters and produce guest writes for remapped restore."""

    backup_clusters = sorted(
        {cluster for cluster, _go, _payload in backup.data_chunks}
    )
    if not backup_clusters:
        raise RemapError("Backup has no data clusters")

    payloads = {
        cluster: payload for cluster, _go, payload in backup.data_chunks
    }
    old_offsets = {
        cluster: offset for cluster, offset, _payload in backup.data_chunks
    }

    try:
        new_clusters = volume.find_free_clusters(len(backup_clusters))
    except FATXBoundsError as exc:
        raise RemapError(str(exc)) from exc

    cluster_map = {
        old: new for old, new in zip(backup_clusters, new_clusters)
    }

    fat_values = _parse_fat_values(backup)
    title_raw, title_old_first = _extract_title_dirent(backup)
    if title_old_first not in cluster_map:
        raise RemapError(
            f"Title ID first_cluster ({title_old_first}) "
            "missing from backup data_chunks"
        )
    title_new_first = cluster_map[title_old_first]
    title_dirent = _patch_dirent_first_cluster(title_raw, title_new_first)

    root = volume.header.root_dir_first_cluster
    udata = volume.find_child(root, "UDATA")
    if udata is None or not udata.is_directory:
        raise RemapError("UDATA missing on target: remap impossible")

    existing = volume.find_child(udata.first_cluster, backup.title_id)
    if existing is None:
        existing = volume.find_child(udata.first_cluster, backup.title_id.upper())
    if existing is not None:
        title_slot = existing.guest_offset
        # Same Title ID: replace the dirent; old clusters stay orphaned
        # (v1: no free-chain — safe, wastes space).
    else:
        try:
            title_slot, _dir_cluster = volume.find_directory_slot(
                udata.first_cluster
            )
        except FATXBoundsError as exc:
            raise RemapError(str(exc)) from exc

    pending: List[Tuple[int, bytes]] = []

    # 1) Remapped data clusters, with internal dirents patched.
    chunk_size = volume.header.cluster_size
    title_udata_offset = _title_dirent_offset(backup)
    for old_cluster in backup_clusters:
        payload = bytearray(payloads[old_cluster])
        old_base = old_offsets[old_cluster]
        for guest_offset, raw in backup.directory_entries:
            if not (old_base <= guest_offset < old_base + chunk_size):
                continue
            if guest_offset == title_udata_offset:
                continue
            name_len = raw[0]
            if not 1 <= name_len <= 42:
                continue
            old_first = struct.unpack_from("<I", raw, 44)[0]
            new_first = cluster_map.get(old_first, old_first)
            patched = _patch_dirent_first_cluster(raw, new_first)
            rel = guest_offset - old_base
            payload[rel : rel + FATX_DIRENT_SIZE] = patched
        new_cluster = cluster_map[old_cluster]
        pending.append((volume.cluster_offset(new_cluster), bytes(payload)))

    # 2) FAT for the new chains.
    eoc = volume.header.last_cluster_marker
    for old_cluster, new_cluster in cluster_map.items():
        old_next = fat_values.get(old_cluster)
        if old_next is None:
            raise RemapError(
                f"FAT value missing in backup for cluster {old_cluster}"
            )
        if old_next >= volume.header.end_of_chain_start or old_next == 0:
            new_next = eoc
        else:
            if old_next not in cluster_map:
                raise RemapError(
                    f"FAT next {old_next} outside remapped set "
                    f"(from cluster {old_cluster})"
                )
            new_next = cluster_map[old_next]
        pending.append(
            (
                volume.fat_entry_offset(new_cluster),
                volume.encode_fat_entry(new_next),
            )
        )

    # 3) Title ID dirent in UDATA (+ END after if writing onto an END slot).
    pending.append((title_slot, title_dirent))
    _maybe_append_end_marker(volume, udata.first_cluster, title_slot, pending)

    return RemapPlan(
        pending=pending,
        cluster_map=cluster_map,
        title_dirent_offset=title_slot,
        game_first_cluster=title_new_first,
        mode="remap",
    )


def _title_dirent_offset(backup: GameBackup) -> int:
    raw, _first = _extract_title_dirent(backup)
    for guest_offset, entry_raw in backup.directory_entries:
        if entry_raw == raw:
            return guest_offset
    raise RemapError("Title ID dirent offset not found")


def _extract_title_dirent(backup: GameBackup) -> Tuple[bytes, int]:
    data_ranges = [
        (offset, offset + len(payload))
        for _cluster, offset, payload in backup.data_chunks
    ]

    def in_data(guest_offset: int) -> bool:
        return any(start <= guest_offset < end for start, end in data_ranges)

    matches: List[Tuple[int, bytes]] = []
    for guest_offset, raw in backup.directory_entries:
        name_len = raw[0]
        if not 1 <= name_len <= 42:
            continue
        name = raw[2 : 2 + name_len].decode("latin-1", errors="replace")
        if name.casefold() != backup.title_id.casefold():
            continue
        if in_data(guest_offset):
            continue
        matches.append((guest_offset, raw))

    if not matches:
        # Fallback: first dirent with the Title ID name.
        for guest_offset, raw in backup.directory_entries:
            name_len = raw[0]
            if not 1 <= name_len <= 42:
                continue
            name = raw[2 : 2 + name_len].decode("latin-1", errors="replace")
            if name.casefold() == backup.title_id.casefold():
                first = struct.unpack_from("<I", raw, 44)[0]
                return raw, first
        raise RemapError(
            f"Directory entry for Title ID {backup.title_id} missing from backup"
        )

    raw = matches[0][1]
    first = struct.unpack_from("<I", raw, 44)[0]
    return raw, first


def _patch_dirent_first_cluster(raw: bytes, first_cluster: int) -> bytes:
    if len(raw) != FATX_DIRENT_SIZE:
        raise RemapError("Directory entry is not 64 bytes")
    out = bytearray(raw)
    struct.pack_into("<I", out, 44, first_cluster)
    return bytes(out)


def _parse_fat_values(backup: GameBackup) -> Dict[int, int]:
    values: Dict[int, int] = {}
    entry_size = backup.fat_entry_size
    for first_cluster, _guest_offset, blob in backup.fat_runs:
        if len(blob) % entry_size:
            raise RemapError("fat_run length is not aligned")
        count = len(blob) // entry_size
        for index in range(count):
            cluster = first_cluster + index
            start = index * entry_size
            value = int.from_bytes(blob[start : start + entry_size], "little")
            values[cluster] = value
    return values


def _maybe_append_end_marker(
    volume: FATXVolume,
    udata_first_cluster: int,
    title_slot: int,
    pending: List[Tuple[int, bytes]],
) -> None:
    """If the slot was END, write END into the next slot if free."""

    try:
        raw = volume.device.read_at(title_slot, 1)
    except Exception:
        return
    if raw[0] != FATX_DIRENT_END:
        return

    next_offset = title_slot + FATX_DIRENT_SIZE
    # Must stay in the same directory cluster.
    title_cluster = volume.cluster_for_offset(title_slot)
    next_cluster = volume.cluster_for_offset(next_offset)
    if title_cluster is None or next_cluster != title_cluster:
        return
    end_raw = bytes([FATX_DIRENT_END]) + bytes(FATX_DIRENT_SIZE - 1)
    pending.append((next_offset, end_raw))
