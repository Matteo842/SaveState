"""Confronti guest-aware fra immagini QCOW2, senza scritture."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple, Union

from .fatx import (
    FATXVolume,
    XBOX_REGIONS,
    discover_fatx_volumes,
    region_for_offset,
)
from .qcow2 import QCOW2BlockDevice, UnsupportedQCOW2Feature


PathLike = Union[str, Path]
ProgressCallback = Callable[[int, int, int], None]


class GuestComparisonError(Exception):
    """Le due immagini non possono essere confrontate guest-aware."""


@dataclass(frozen=True, order=True)
class DifferenceBucket:
    region: str
    area: str
    cluster: Optional[int] = None

    @property
    def label(self) -> str:
        if self.cluster is None:
            return f"{self.region}:{self.area}"
        return f"{self.region}:{self.area}:cluster={self.cluster}"


@dataclass(frozen=True)
class DifferenceSample:
    guest_offset: int
    left_byte: int
    right_byte: int
    bucket: DifferenceBucket


@dataclass
class GuestDiffSummary:
    left_path: Path
    right_path: Path
    virtual_size: int
    qcow2_cluster_size: int
    total_different_bytes: int = 0
    scanned_guest_clusters: int = 0
    compared_guest_clusters: int = 0
    differing_guest_clusters: int = 0
    buckets: Dict[DifferenceBucket, int] = field(default_factory=dict)
    samples: List[DifferenceSample] = field(default_factory=list)

    def add(self, bucket: DifferenceBucket, count: int) -> None:
        if count <= 0:
            return
        self.total_different_bytes += count
        self.buckets[bucket] = self.buckets.get(bucket, 0) + count

    def region_totals(self) -> Dict[str, int]:
        totals: Dict[str, int] = {}
        for bucket, count in self.buckets.items():
            totals[bucket.region] = totals.get(bucket.region, 0) + count
        return totals

    def cluster_totals(self, partition: str) -> Dict[int, int]:
        normalized = partition.upper()
        totals: Dict[int, int] = {}
        for bucket, count in self.buckets.items():
            if (
                bucket.region == normalized
                and bucket.area == "data"
                and bucket.cluster is not None
            ):
                totals[bucket.cluster] = (
                    totals.get(bucket.cluster, 0) + count
                )
        return totals

    def other_than(self, *regions: str) -> int:
        excluded = {region.upper() for region in regions}
        return sum(
            count
            for bucket, count in self.buckets.items()
            if bucket.region.upper() not in excluded
        )


def compare_paths(
    left_path: PathLike,
    right_path: PathLike,
    progress: Optional[ProgressCallback] = None,
    sample_limit: int = 20,
) -> GuestDiffSummary:
    """Apre due QCOW2 in `rb` e ne confronta il contenuto guest."""

    with QCOW2BlockDevice(left_path) as left, QCOW2BlockDevice(
        right_path
    ) as right:
        return compare_devices(
            left,
            right,
            progress=progress,
            sample_limit=sample_limit,
        )


def compare_devices(
    left: QCOW2BlockDevice,
    right: QCOW2BlockDevice,
    progress: Optional[ProgressCallback] = None,
    sample_limit: int = 20,
) -> GuestDiffSummary:
    if sample_limit < 0:
        raise ValueError("sample_limit deve essere >= 0")
    if left.size != right.size:
        raise GuestComparisonError(
            f"Dimensioni guest diverse: {left.size} != {right.size}"
        )
    if left.cluster_size != right.cluster_size:
        raise GuestComparisonError(
            "Cluster QCOW2 diversi: confronto ottimizzato non disponibile"
        )
    dirty_paths = [
        str(device.path)
        for device in (left, right)
        if device.header.is_dirty
    ]
    if dirty_paths:
        raise GuestComparisonError(
            "Confronto rifiutato: QCOW2 con dirty bit: "
            + ", ".join(dirty_paths)
        )

    left_volumes = discover_fatx_volumes(left)
    right_volumes = discover_fatx_volumes(right)
    classification_volumes = _matching_volumes(left_volumes, right_volumes)

    summary = GuestDiffSummary(
        left_path=left.path,
        right_path=right.path,
        virtual_size=left.size,
        qcow2_cluster_size=left.cluster_size,
    )
    total_clusters = left.cluster_count

    for guest_cluster in range(total_clusters):
        left_compressed = left.is_compressed_cluster(guest_cluster)
        right_compressed = right.is_compressed_cluster(guest_cluster)
        if left_compressed or right_compressed:
            summary.scanned_guest_clusters += 1
            summary.compared_guest_clusters += 1
            if (
                left_compressed
                and right_compressed
                and left.header.compression_type
                == right.header.compression_type
                and left.read_compressed_payload(guest_cluster)
                == right.read_compressed_payload(guest_cluster)
            ):
                _notify_progress(
                    progress,
                    guest_cluster,
                    total_clusters,
                    summary.total_different_bytes,
                )
                continue
            raise UnsupportedQCOW2Feature(
                "Confronto di cluster compressi differenti non supportato "
                f"(cluster guest {guest_cluster})"
            )

        left_mapping = left.map_cluster(guest_cluster)
        right_mapping = right.map_cluster(guest_cluster)
        summary.scanned_guest_clusters += 1

        left_zero = (
            not left_mapping.allocated or left_mapping.reads_as_zero
        )
        right_zero = (
            not right_mapping.allocated or right_mapping.reads_as_zero
        )
        if left_zero and right_zero:
            _notify_progress(
                progress,
                guest_cluster,
                total_clusters,
                summary.total_different_bytes,
            )
            continue

        summary.compared_guest_clusters += 1
        left_data = left.read_cluster(guest_cluster)
        right_data = right.read_cluster(guest_cluster)
        if left_data == right_data:
            _notify_progress(
                progress,
                guest_cluster,
                total_clusters,
                summary.total_different_bytes,
            )
            continue

        summary.differing_guest_clusters += 1
        cluster_guest_offset = guest_cluster * left.cluster_size
        for relative_start, relative_end, bucket in _iter_bucket_segments(
            cluster_guest_offset,
            len(left_data),
            classification_volumes,
        ):
            left_segment = left_data[relative_start:relative_end]
            right_segment = right_data[relative_start:relative_end]
            if left_segment == right_segment:
                continue

            count = _count_byte_differences(left_segment, right_segment)
            summary.add(bucket, count)
            if len(summary.samples) < sample_limit:
                _collect_samples(
                    summary,
                    cluster_guest_offset + relative_start,
                    left_segment,
                    right_segment,
                    bucket,
                    sample_limit,
                )

        _notify_progress(
            progress,
            guest_cluster,
            total_clusters,
            summary.total_different_bytes,
        )

    return summary


def _matching_volumes(
    left: Dict[str, FATXVolume],
    right: Dict[str, FATXVolume],
) -> Dict[str, FATXVolume]:
    matching: Dict[str, FATXVolume] = {}
    for name, left_volume in left.items():
        right_volume = right.get(name)
        if right_volume is None:
            continue
        left_header = left_volume.header
        right_header = right_volume.header
        comparable = (
            left_header.cluster_size == right_header.cluster_size
            and left_header.fat_entry_size == right_header.fat_entry_size
            and left_header.fat_size == right_header.fat_size
            and left_header.file_area_offset
            == right_header.file_area_offset
        )
        if comparable:
            matching[name] = left_volume
    return matching


def _iter_bucket_segments(
    guest_start: int,
    size: int,
    volumes: Dict[str, FATXVolume],
) -> Iterator[Tuple[int, int, DifferenceBucket]]:
    guest_end = guest_start + size
    cursor = guest_start

    while cursor < guest_end:
        region = region_for_offset(cursor)
        if region is None:
            next_boundary = min(
                (
                    candidate.offset
                    for candidate in XBOX_REGIONS
                    if candidate.offset > cursor
                ),
                default=guest_end,
            )
            segment_end = min(guest_end, next_boundary)
            bucket = DifferenceBucket("OTHER", "raw")
        elif not region.is_fatx:
            segment_end = min(guest_end, region.end)
            bucket = DifferenceBucket(region.name, "raw")
        else:
            volume = volumes.get(region.name)
            if volume is None:
                segment_end = min(guest_end, region.end)
                bucket = DifferenceBucket(region.name, "raw")
            else:
                location = volume.classify_offset(cursor)
                bucket = DifferenceBucket(
                    region.name,
                    location.area,
                    location.cluster,
                )
                if location.area == "superblock":
                    segment_end = min(
                        guest_end,
                        volume.header.fat_offset,
                    )
                elif location.area == "fat":
                    segment_end = min(
                        guest_end,
                        volume.header.file_area_offset,
                    )
                elif location.area == "data":
                    assert location.cluster is not None
                    segment_end = min(
                        guest_end,
                        volume.cluster_offset(location.cluster)
                        + volume.header.cluster_size,
                    )
                else:
                    segment_end = min(guest_end, region.end)

        if segment_end <= cursor:
            raise GuestComparisonError(
                f"Classificazione bloccata a 0x{cursor:x}"
            )
        yield (
            cursor - guest_start,
            segment_end - guest_start,
            bucket,
        )
        cursor = segment_end


def _count_byte_differences(left: bytes, right: bytes) -> int:
    if len(left) != len(right):
        raise GuestComparisonError("Segmenti di dimensione diversa")
    return sum(left_byte != right_byte for left_byte, right_byte in zip(left, right))


def _collect_samples(
    summary: GuestDiffSummary,
    guest_start: int,
    left: bytes,
    right: bytes,
    bucket: DifferenceBucket,
    sample_limit: int,
) -> None:
    remaining = sample_limit - len(summary.samples)
    if remaining <= 0:
        return

    for index, (left_byte, right_byte) in enumerate(zip(left, right)):
        if left_byte == right_byte:
            continue
        summary.samples.append(
            DifferenceSample(
                guest_offset=guest_start + index,
                left_byte=left_byte,
                right_byte=right_byte,
                bucket=bucket,
            )
        )
        remaining -= 1
        if remaining == 0:
            break


def _notify_progress(
    progress: Optional[ProgressCallback],
    guest_cluster: int,
    total_clusters: int,
    different_bytes: int,
) -> None:
    if progress is None:
        return
    completed = guest_cluster + 1
    if completed == total_clusters or completed % 2048 == 0:
        progress(completed, total_clusters, different_bytes)
