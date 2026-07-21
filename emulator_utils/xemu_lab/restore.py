"""Surgical guest-aware restore from XBSV v6/v7 backups (+ FATX 6.1 remap).

Includes preflight, guest undo journal, and QCOW2 metadata checkpoints to
protect the live HDD (no golden image in production).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from .backup import GameBackup, load_backup
from .fatx import FATXError, FATXVolume, get_region
from .qcow2 import (
    HostCheckpoint,
    QCOW2WriteError,
    QCOW2WritableBlockDevice,
    UnsupportedQCOW2Feature,
)
from .remap import RemapError, build_remap_plan, decide_restore_path
from .safety import SafetyError, assert_xemu_closed, assert_path_writable


PathLike = Union[str, Path]


class RestoreError(Exception):
    """Restore rejected or failed."""


@dataclass(frozen=True)
class RestoreReport:
    target_path: Path
    title_id: str
    directory_entries: int
    fat_bytes: int
    data_clusters: int
    verified: bool
    clusters_allocated: int = 0
    host_bytes_grown: int = 0
    allocate_used: bool = False
    envelopes_written: int = 0
    mode: str = "same-guest"
    clusters_remapped: int = 0
    rolled_back: bool = False
    peer_titles_verified: int = 0


@dataclass
class _RestorePlan:
    pending: List[Tuple[int, bytes]]
    mode: str
    clusters_remapped: int
    use_envelopes: bool
    allow_allocate: bool
    peer_title_ids: Set[str] = field(default_factory=set)


def safe_restore_backup_to_path(
    backup: GameBackup,
    target_path: PathLike,
    verify: bool = True,
    allow_allocate: bool = True,
    force_mode: Optional[str] = None,
    require_xemu_closed: bool = True,
) -> RestoreReport:
    """Product API: preflight + restore with undo on the live HDD."""

    target = Path(target_path)
    if require_xemu_closed:
        assert_xemu_closed()
    assert_path_writable(target)
    return restore_backup_to_path(
        backup,
        target,
        verify=verify,
        allow_allocate=allow_allocate,
        force_mode=force_mode,
    )


def safe_restore_backup_file(
    bin_path: PathLike,
    target_path: PathLike,
    json_path: Optional[PathLike] = None,
    verify: bool = True,
    allow_allocate: bool = True,
    force_mode: Optional[str] = None,
    require_xemu_closed: bool = True,
) -> RestoreReport:
    backup = load_backup(bin_path, json_path=json_path)
    return safe_restore_backup_to_path(
        backup,
        target_path,
        verify=verify,
        allow_allocate=allow_allocate,
        force_mode=force_mode,
        require_xemu_closed=require_xemu_closed,
    )


def restore_backup_to_path(
    backup: GameBackup,
    target_path: PathLike,
    verify: bool = True,
    allow_allocate: bool = False,
    force_mode: Optional[str] = None,
) -> RestoreReport:
    """Apply the backup onto the target image (with internal undo)."""

    target = Path(target_path)
    if not target.is_file():
        raise RestoreError(f"Target missing: {target}")

    try:
        with QCOW2WritableBlockDevice(target) as device:
            report = restore_backup_to_device(
                backup,
                device,
                verify=verify,
                allow_allocate=allow_allocate,
                force_mode=force_mode,
            )
    except SafetyError as exc:
        raise RestoreError(str(exc)) from exc
    except (QCOW2WriteError, UnsupportedQCOW2Feature, RemapError, FATXError) as exc:
        raise RestoreError(str(exc)) from exc
    return report


def restore_backup_file(
    bin_path: PathLike,
    target_path: PathLike,
    json_path: Optional[PathLike] = None,
    verify: bool = True,
    allow_allocate: bool = False,
    force_mode: Optional[str] = None,
) -> RestoreReport:
    backup = load_backup(bin_path, json_path=json_path)
    return restore_backup_to_path(
        backup,
        target_path,
        verify=verify,
        allow_allocate=allow_allocate,
        force_mode=force_mode,
    )


def restore_backup_to_device(
    backup: GameBackup,
    device: QCOW2WritableBlockDevice,
    verify: bool = True,
    allow_allocate: bool = False,
    force_mode: Optional[str] = None,
) -> RestoreReport:
    if backup.fatx_cluster_size <= 0:
        raise RestoreError("Invalid fatx_cluster_size in backup")

    plan = _build_restore_plan(
        backup,
        device,
        allow_allocate=allow_allocate,
        force_mode=force_mode,
    )
    _preflight_disk_space(device, backup, plan)

    guest_undo = _capture_guest_undo(device, backup, plan)
    host_checkpoint: Optional[HostCheckpoint] = None
    if plan.allow_allocate:
        host_checkpoint = device.capture_host_checkpoint()

    allocated_before = device.clusters_allocated
    grown_before = device.host_bytes_grown
    envelopes_written = 0
    rolled_back = False

    try:
        envelopes_written = _apply_plan(device, backup, plan)
        if verify:
            for guest_offset, payload in plan.pending:
                actual = device.read_at(guest_offset, len(payload))
                if actual != payload:
                    raise RestoreError(
                        f"Read-back verification failed @ guest 0x{guest_offset:x}"
                    )
            _verify_title_visible(device, backup)
            _verify_peer_titles(device, backup, plan.peer_title_ids)
    except Exception as exc:
        rolled_back = _rollback_restore(
            device,
            guest_undo,
            host_checkpoint,
        )
        if rolled_back:
            raise RestoreError(
                f"Restore failed ({exc}). "
                "HDD restored to previous state "
                "(guest undo"
                + (" + QCOW2 checkpoint" if host_checkpoint else "")
                + ")."
            ) from exc
        raise RestoreError(
            f"Restore failed ({exc}). "
            "WARNING: incomplete undo — do not start xemu on this HDD; "
            "restore from a previous SaveState backup if available."
        ) from exc

    fat_bytes = sum(len(blob) for _first, _off, blob in backup.fat_runs)
    return RestoreReport(
        target_path=device.path,
        title_id=backup.title_id,
        directory_entries=len(backup.directory_entries),
        fat_bytes=fat_bytes,
        data_clusters=len(backup.data_chunks),
        verified=bool(verify),
        clusters_allocated=device.clusters_allocated - allocated_before,
        host_bytes_grown=device.host_bytes_grown - grown_before,
        allocate_used=plan.allow_allocate,
        envelopes_written=envelopes_written,
        mode=plan.mode,
        clusters_remapped=plan.clusters_remapped,
        rolled_back=rolled_back,
        peer_titles_verified=len(plan.peer_title_ids),
    )


def _build_restore_plan(
    backup: GameBackup,
    device: QCOW2WritableBlockDevice,
    *,
    allow_allocate: bool,
    force_mode: Optional[str],
) -> _RestorePlan:
    mode = "same-guest"
    clusters_remapped = 0
    pending: List[Tuple[int, bytes]]
    use_envelopes = True
    allocate = allow_allocate
    peer_ids: Set[str] = set()

    if force_mode == "remap" or (
        force_mode is None and _can_consider_fatx_remap(device, backup)
    ):
        volume = FATXVolume.open_partition(device, backup.partition)
        peer_ids = {
            game.title_id.lower()
            for game in volume.list_games(areas=("UDATA",))
            if game.title_id.lower() != backup.title_id.lower()
        }

        if force_mode == "remap":
            decision_remap = True
        elif force_mode == "same-guest":
            _assert_same_guest_geometry(backup, volume)
            decision_remap = False
        else:
            decision = decide_restore_path(backup, volume)
            decision_remap = not decision.use_same_guest
            if not decision_remap and not geometry_matches(backup, volume):
                # Backup absolute offsets are invalid on the target → remap.
                decision_remap = True

        if decision_remap:
            plan = build_remap_plan(backup, volume)
            pending = list(plan.pending)
            mode = "remap"
            clusters_remapped = len(plan.cluster_map)
            use_envelopes = False
            allocate = True
        else:
            _assert_same_guest_geometry(backup, volume)
            pending = _surgical_pending(backup)
            mode = "same-guest"
    else:
        pending = _surgical_pending(backup)

    return _RestorePlan(
        pending=pending,
        mode=mode,
        clusters_remapped=clusters_remapped,
        use_envelopes=use_envelopes,
        allow_allocate=allocate,
        peer_title_ids=peer_ids,
    )


def geometry_matches(backup: GameBackup, volume: FATXVolume) -> bool:
    """True if backup guest offsets match the target geometry."""

    if backup.fatx_cluster_size != volume.header.cluster_size:
        return False
    if backup.fat_entry_size != volume.header.fat_entry_size:
        return False
    try:
        for cluster, offset, _payload in backup.data_chunks:
            if volume.cluster_offset(cluster) != offset:
                return False
        for first, offset, _blob in backup.fat_runs:
            if volume.fat_entry_offset(first) != offset:
                return False
        for offset, _raw in backup.directory_entries:
            if not volume.partition.contains(offset):
                return False
    except FATXError:
        return False
    return True


def _assert_same_guest_geometry(backup: GameBackup, volume: FATXVolume) -> None:
    if backup.fatx_cluster_size != volume.header.cluster_size:
        raise RestoreError(
            "Backup fatx_cluster_size "
            f"({backup.fatx_cluster_size}) != target "
            f"({volume.header.cluster_size})"
        )
    if backup.fat_entry_size != volume.header.fat_entry_size:
        raise RestoreError(
            "Backup fat_entry_size "
            f"({backup.fat_entry_size}) != target "
            f"({volume.header.fat_entry_size})"
        )
    if not geometry_matches(backup, volume):
        raise RestoreError(
            "Target FATX geometry differs from backup "
            "(cluster/FAT offsets misaligned). Same-guest restore rejected "
            "to avoid corruption; retry with automatic remap."
        )


def _apply_plan(
    device: QCOW2WritableBlockDevice,
    backup: GameBackup,
    plan: _RestorePlan,
) -> int:
    envelopes_written = 0
    if plan.allow_allocate:
        if plan.use_envelopes:
            _preflight_allocate(backup, device, plan.pending)
        with device.allocating():
            if plan.use_envelopes and backup.has_qcow2_envelopes:
                if (
                    backup.qcow2_cluster_size
                    and backup.qcow2_cluster_size != device.cluster_size
                ):
                    raise RestoreError(
                        "Backup qcow2_cluster_size "
                        f"({backup.qcow2_cluster_size}) != target "
                        f"({device.cluster_size})"
                    )
                for guest_cluster, payload in backup.qcow2_envelopes:
                    if not device.needs_allocation(guest_cluster):
                        continue
                    device.write_guest_cluster(
                        guest_cluster,
                        payload,
                        allocate=True,
                    )
                    envelopes_written += 1
                for guest_offset, payload in plan.pending:
                    device.write_at(guest_offset, payload, allocate=True)
            else:
                _write_pending_allocating_coalesced(device, plan.pending)
    else:
        for guest_offset, payload in plan.pending:
            _ensure_range(
                device,
                guest_offset,
                len(payload),
                allocate=False,
            )
        for guest_offset, payload in plan.pending:
            device.write_at(guest_offset, payload)
        device.flush()
    return envelopes_written


def _capture_guest_undo(
    device: QCOW2WritableBlockDevice,
    backup: GameBackup,
    plan: _RestorePlan,
) -> List[Tuple[int, bytes]]:
    """Read guest bytes about to be overwritten (readable clusters only)."""

    ranges = list(plan.pending)
    if plan.use_envelopes and plan.allow_allocate and backup.has_qcow2_envelopes:
        for guest_cluster, payload in backup.qcow2_envelopes:
            if device.needs_allocation(guest_cluster):
                continue
            ranges.append((guest_cluster * device.cluster_size, payload))

    merged = _merge_ranges(ranges)
    undo: List[Tuple[int, bytes]] = []
    for offset, size in merged:
        try:
            undo.append((offset, device.read_at(offset, size)))
        except (QCOW2WriteError, UnsupportedQCOW2Feature, ValueError):
            # Unallocated/compressed cluster: host checkpoint handles rollback.
            continue
    return undo


def _merge_ranges(
    ranges: Sequence[Tuple[int, bytes]],
) -> List[Tuple[int, int]]:
    """Merge contiguous/overlapping (offset, size) ranges."""

    points: List[Tuple[int, int]] = []
    for offset, payload in ranges:
        if not payload:
            continue
        points.append((offset, offset + len(payload)))
    if not points:
        return []
    points.sort()
    merged: List[Tuple[int, int]] = []
    start, end = points[0]
    for next_start, next_end in points[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            merged.append((start, end - start))
            start, end = next_start, next_end
    merged.append((start, end - start))
    return merged


def _rollback_restore(
    device: QCOW2WritableBlockDevice,
    guest_undo: List[Tuple[int, bytes]],
    host_checkpoint: Optional[HostCheckpoint],
) -> bool:
    """Best-effort undo. True if checkpoint/undo was applied."""

    restored = False
    try:
        if host_checkpoint is not None:
            device.restore_host_checkpoint(host_checkpoint)
            restored = True
        for offset, payload in guest_undo:
            # After checkpoint, overwrite-safe clusters are writable again.
            try:
                device.write_at(offset, payload, allocate=False)
            except (QCOW2WriteError, UnsupportedQCOW2Feature):
                if host_checkpoint is None:
                    continue
                device.write_at(offset, payload, allocate=True)
            restored = True
        device.flush()
    except Exception:
        return restored
    return restored


def _preflight_disk_space(
    device: QCOW2WritableBlockDevice,
    backup: GameBackup,
    plan: _RestorePlan,
) -> None:
    """Reject if the host volume lacks space for the estimated growth."""

    if not plan.allow_allocate:
        return
    estimate = _estimate_host_growth(device, backup, plan)
    if estimate <= 0:
        return
    try:
        free = shutil.disk_usage(device.path).free
    except OSError as exc:
        raise RestoreError(f"Unable to read disk space: {exc}") from exc
    # Margin for L2/refcount extras.
    needed = estimate + (16 * device.cluster_size)
    if free < needed:
        raise RestoreError(
            f"Insufficient disk space for restore "
            f"(need about {needed} free bytes, {free} remaining)."
        )


def _estimate_host_growth(
    device: QCOW2WritableBlockDevice,
    backup: GameBackup,
    plan: _RestorePlan,
) -> int:
    clusters: Set[int] = set()
    if plan.use_envelopes and backup.has_qcow2_envelopes:
        for guest_cluster, _payload in backup.qcow2_envelopes:
            if device.needs_allocation(guest_cluster):
                clusters.add(guest_cluster)
    for offset, payload in plan.pending:
        if not payload:
            continue
        start = offset // device.cluster_size
        end = (offset + len(payload) - 1) // device.cluster_size
        for guest_cluster in range(start, end + 1):
            if device.needs_allocation(guest_cluster):
                clusters.add(guest_cluster)
    return len(clusters) * device.cluster_size


def _surgical_pending(backup: GameBackup) -> List[Tuple[int, bytes]]:
    pending: List[Tuple[int, bytes]] = []
    for guest_offset, raw in backup.directory_entries:
        pending.append((guest_offset, raw))
    for _first, guest_offset, blob in backup.fat_runs:
        pending.append((guest_offset, blob))
    for _cluster, guest_offset, payload in backup.data_chunks:
        pending.append((guest_offset, payload))
    return pending


def _can_consider_fatx_remap(
    device: QCOW2WritableBlockDevice,
    backup: GameBackup,
) -> bool:
    """True if the target has an Xbox layout large enough for the partition."""

    try:
        region = get_region(backup.partition)
    except KeyError:
        return False
    return region.end <= device.size


def _preflight_allocate(
    backup: GameBackup,
    device: QCOW2WritableBlockDevice,
    pending: List[Tuple[int, bytes]],
) -> None:
    """Reject unsafe allocate without envelopes on unalloc/zero clusters."""

    if backup.has_qcow2_envelopes:
        return

    touched = _touched_qcow2_clusters(pending, device.cluster_size)
    coverage = _coverage_by_cluster(pending, device.cluster_size)
    dangerous: List[int] = []
    for guest_cluster in sorted(touched):
        if not device.needs_allocation(guest_cluster):
            continue
        if device.is_compressed_cluster(guest_cluster):
            continue
        covered = coverage.get(guest_cluster, 0)
        if covered < device.cluster_size:
            dangerous.append(guest_cluster)

    if dangerous:
        raise RestoreError(
            "Allocate on unallocated/zero QCOW2 clusters with partial "
            "coverage (they share FAT/root with the save). XBSV v6 backups "
            "without envelopes are unsafe on a virgin/sparse HDD. "
            f"At-risk clusters: {dangerous[:8]}"
            + ("..." if len(dangerous) > 8 else "")
            + ". Recreate the backup (XBSV v7 with QCOW2 envelopes)."
        )


def _write_pending_allocating_coalesced(
    device: QCOW2WritableBlockDevice,
    pending: List[Tuple[int, bytes]],
) -> None:
    """RMW per QCOW2 cluster: decompressed/zero base + pending fragments."""

    by_cluster: Dict[int, bytearray] = {}
    for offset, payload in pending:
        cursor = 0
        while cursor < len(payload):
            guest_offset = offset + cursor
            guest_cluster = guest_offset // device.cluster_size
            in_cluster = guest_offset % device.cluster_size
            chunk = min(
                len(payload) - cursor,
                device.cluster_size - in_cluster,
            )
            if guest_cluster not in by_cluster:
                by_cluster[guest_cluster] = bytearray(
                    device.read_cluster_content(guest_cluster)
                )
            by_cluster[guest_cluster][
                in_cluster : in_cluster + chunk
            ] = payload[cursor : cursor + chunk]
            cursor += chunk

    for guest_cluster, data in sorted(by_cluster.items()):
        device.write_guest_cluster(
            guest_cluster,
            bytes(data),
            allocate=True,
        )


def _verify_title_visible(
    device: QCOW2WritableBlockDevice,
    backup: GameBackup,
) -> None:
    try:
        region = get_region(backup.partition)
    except KeyError:
        return
    if region.end > device.size:
        return

    try:
        volume = FATXVolume.open_partition(device, backup.partition)
    except Exception as exc:
        raise RestoreError(
            f"FATX verification failed opening partition {backup.partition}: {exc}"
        ) from exc

    title = backup.title_id.lower()
    found = [
        game
        for game in volume.list_games()
        if game.title_id.lower() == title
    ]
    if not found:
        raise RestoreError(
            f"Title ID {backup.title_id} not visible in FATX after restore "
            "(likely shared QCOW2/FAT metadata corruption or failed remap)."
        )


def _verify_peer_titles(
    device: QCOW2WritableBlockDevice,
    backup: GameBackup,
    peer_ids: Set[str],
) -> None:
    """Other Title IDs present before restore must remain listable."""

    if not peer_ids:
        return
    try:
        region = get_region(backup.partition)
    except KeyError:
        return
    if region.end > device.size:
        return

    volume = FATXVolume.open_partition(device, backup.partition)
    after = {
        game.title_id.lower()
        for game in volume.list_games(areas=("UDATA",))
    }
    missing = sorted(peer_ids - after)
    if missing:
        raise RestoreError(
            "After restore, Title IDs that were present before are missing "
            f"(possible corruption): {', '.join(missing)}"
        )


def _touched_qcow2_clusters(
    pending: List[Tuple[int, bytes]],
    cluster_size: int,
) -> Set[int]:
    touched: Set[int] = set()
    for offset, payload in pending:
        if not payload:
            continue
        start = offset // cluster_size
        end = (offset + len(payload) - 1) // cluster_size
        touched.update(range(start, end + 1))
    return touched


def _coverage_by_cluster(
    pending: List[Tuple[int, bytes]],
    cluster_size: int,
) -> Dict[int, int]:
    masks: Dict[int, bytearray] = {}
    for offset, payload in pending:
        cursor = 0
        while cursor < len(payload):
            guest_offset = offset + cursor
            guest_cluster = guest_offset // cluster_size
            in_cluster = guest_offset % cluster_size
            chunk = min(len(payload) - cursor, cluster_size - in_cluster)
            mask = masks.setdefault(guest_cluster, bytearray(cluster_size))
            for index in range(in_cluster, in_cluster + chunk):
                mask[index] = 1
            cursor += chunk
    return {gc: sum(mask) for gc, mask in masks.items()}


def _ensure_range(
    device: QCOW2WritableBlockDevice,
    offset: int,
    size: int,
    *,
    allocate: bool,
) -> None:
    if size == 0:
        return
    cursor = 0
    while cursor < size:
        guest_offset = offset + cursor
        guest_cluster = guest_offset // device.cluster_size
        in_cluster = guest_offset % device.cluster_size
        chunk = min(size - cursor, device.cluster_size - in_cluster)
        if allocate:
            device.ensure_allocated(guest_cluster)
        else:
            device._require_writable_mapping(guest_cluster)
        cursor += chunk
