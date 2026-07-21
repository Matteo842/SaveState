"""Guest-aware QCOW2 block device (read + overwrite + opt-in allocate).

The rest of the project must reason exclusively in guest disk offsets.
This module is the only place that maps those offsets to positions in the
QCOW2 container. Allocate-on-write (L2/refcount) is opt-in and QEMU-free.
"""

from __future__ import annotations

import os
import struct
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager
from typing import (
    BinaryIO,
    Iterator,
    List,
    Optional,
    Protocol,
    Set,
    Tuple,
    Union,
)


PathLike = Union[str, os.PathLike]

QCOW2_MAGIC = 0x514649FB
QCOW2_MIN_CLUSTER_BITS = 9
QCOW2_MAX_CLUSTER_BITS = 21
QCOW2_MAX_L1_BYTES = 32 * 1024 * 1024
QCOW2_MAX_CACHED_L2_TABLES = 32

QCOW_OFLAG_COPIED = 1 << 63
QCOW_OFLAG_COMPRESSED = 1 << 62
QCOW_OFLAG_ZERO = 1
QCOW_OFFSET_MASK = 0x00FFFFFFFFFFFE00

QCOW2_INCOMPAT_DIRTY = 1 << 0
QCOW2_INCOMPAT_CORRUPT = 1 << 1
QCOW2_INCOMPAT_EXTERNAL_DATA = 1 << 2
QCOW2_INCOMPAT_COMPRESSION_TYPE = 1 << 3
QCOW2_INCOMPAT_EXTENDED_L2 = 1 << 4
QCOW2_KNOWN_INCOMPAT = (
    QCOW2_INCOMPAT_DIRTY
    | QCOW2_INCOMPAT_CORRUPT
    | QCOW2_INCOMPAT_EXTERNAL_DATA
    | QCOW2_INCOMPAT_COMPRESSION_TYPE
    | QCOW2_INCOMPAT_EXTENDED_L2
)


class QCOW2Error(Exception):
    """Base QCOW2 block device error."""


class QCOW2FormatError(QCOW2Error):
    """Container does not match the expected QCOW2 format."""


class UnsupportedQCOW2Feature(QCOW2Error):
    """Container uses a feature not safely supported."""


class QCOW2WriteError(QCOW2Error):
    """Write rejected or failed on the block device."""


class BlockDevice(Protocol):
    """Minimal interface used by guest-aware parsers."""

    @property
    def size(self) -> int:
        """Guest disk size in bytes."""

    def read_at(self, offset: int, size: int) -> bytes:
        """Read bytes at a guest disk offset."""


@dataclass(frozen=True)
class QCOW2Header:
    version: int
    backing_file_offset: int
    backing_file_size: int
    cluster_bits: int
    cluster_size: int
    virtual_size: int
    crypt_method: int
    l1_size: int
    l1_table_offset: int
    refcount_table_offset: int
    refcount_table_clusters: int
    snapshot_count: int
    snapshots_offset: int
    incompatible_features: int
    compatible_features: int
    autoclear_features: int
    refcount_order: int
    header_length: int
    compression_type: int

    @property
    def is_dirty(self) -> bool:
        return bool(self.incompatible_features & QCOW2_INCOMPAT_DIRTY)


@dataclass(frozen=True)
class ClusterMapping:
    """Mapping of a standard guest cluster."""

    guest_cluster: int
    guest_offset: int
    host_offset: Optional[int]
    allocated: bool
    reads_as_zero: bool


@dataclass(frozen=True)
class HostCheckpoint:
    """QCOW2 metadata snapshot + host size for allocate rollback.

    Does not clone guest data: only existing refcount/L1/L2/refcount-block
    headers and the file size. New clusters are appended at the end
    and disappear on truncate.
    """

    host_size: int
    incompatible_features: int
    l1_table_offset: int
    l1_raw: bytes
    l2_blobs: Tuple[Tuple[int, bytes], ...]
    refcount_table_offset: int
    refcount_table_clusters: int
    refcount_table_raw: bytes
    refcount_block_blobs: Tuple[Tuple[int, bytes], ...]


class QCOW2BlockDevice:
    """QCOW2 block device with no write API."""

    def __init__(self, path: PathLike):
        self.path = Path(path)
        self._file: Optional[BinaryIO] = None
        self._host_size = 0
        self._header: Optional[QCOW2Header] = None
        self._l1_table: Tuple[int, ...] = ()
        self._l2_cache: "OrderedDict[int, Tuple[int, ...]]" = OrderedDict()

    def __enter__(self) -> "QCOW2BlockDevice":
        return self.open()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def open(self) -> "QCOW2BlockDevice":
        if self._file is not None:
            return self

        try:
            self._file = self.path.open("rb")
            self._host_size = os.fstat(self._file.fileno()).st_size
            self._header = self._read_header()
            self._l1_table = self._read_l1_table()
            self._validate_l1_coverage()
        except Exception:
            self.close()
            raise
        return self

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
        self._file = None
        self._host_size = 0
        self._header = None
        self._l1_table = ()
        self._l2_cache.clear()

    @property
    def header(self) -> QCOW2Header:
        self._require_open()
        assert self._header is not None
        return self._header

    @property
    def size(self) -> int:
        return self.header.virtual_size

    @property
    def cluster_size(self) -> int:
        return self.header.cluster_size

    @property
    def cluster_count(self) -> int:
        return (self.size + self.cluster_size - 1) // self.cluster_size

    @property
    def host_size(self) -> int:
        self._require_open()
        return self._host_size

    def read_at(self, offset: int, size: int) -> bytes:
        """Read a guest range, correctly walking L1/L2."""

        self._validate_guest_range(offset, size)
        if size == 0:
            return b""

        result = bytearray(size)
        result_offset = 0
        while result_offset < size:
            guest_offset = offset + result_offset
            guest_cluster = guest_offset // self.cluster_size
            in_cluster = guest_offset % self.cluster_size
            chunk_size = min(size - result_offset, self.cluster_size - in_cluster)
            mapping = self.map_cluster(guest_cluster)

            if mapping.allocated and not mapping.reads_as_zero:
                assert mapping.host_offset is not None
                chunk = self._read_exact_host(
                    mapping.host_offset + in_cluster,
                    chunk_size,
                )
                result[result_offset : result_offset + chunk_size] = chunk

            result_offset += chunk_size

        return bytes(result)

    def read_cluster(self, guest_cluster: int) -> bytes:
        if not isinstance(guest_cluster, int) or guest_cluster < 0:
            raise ValueError("Guest cluster number must be >= 0")
        if guest_cluster >= self.cluster_count:
            raise ValueError("Guest cluster beyond virtual size")

        guest_offset = guest_cluster * self.cluster_size
        return self.read_at(
            guest_offset,
            min(self.cluster_size, self.size - guest_offset),
        )

    def map_cluster(self, guest_cluster: int) -> ClusterMapping:
        """Return the guest cluster mapping without reading data."""

        if not isinstance(guest_cluster, int) or guest_cluster < 0:
            raise ValueError("Guest cluster number must be >= 0")
        guest_offset = guest_cluster * self.cluster_size
        l2_entry = self.raw_l2_entry(guest_cluster)

        if l2_entry == 0:
            return ClusterMapping(
                guest_cluster,
                guest_offset,
                None,
                allocated=False,
                reads_as_zero=True,
            )
        if l2_entry & QCOW_OFLAG_COMPRESSED:
            raise UnsupportedQCOW2Feature(
                f"Guest cluster {guest_cluster} compressed: read not supported"
            )
        if self.header.version == 2 and l2_entry & QCOW_OFLAG_ZERO:
            raise QCOW2FormatError(
                f"Invalid ZERO bit in QCOW2 v2 at cluster {guest_cluster}"
            )

        l2_reserved = l2_entry & ~(
            QCOW_OFLAG_COPIED | QCOW_OFLAG_ZERO | QCOW_OFFSET_MASK
        )
        if l2_reserved:
            raise QCOW2FormatError(
                f"L2 entry for cluster {guest_cluster} has reserved bits: "
                f"0x{l2_reserved:x}"
            )

        reads_as_zero = bool(l2_entry & QCOW_OFLAG_ZERO)
        host_offset = l2_entry & QCOW_OFFSET_MASK
        if host_offset == 0:
            return ClusterMapping(
                guest_cluster,
                guest_offset,
                None,
                allocated=False,
                reads_as_zero=True,
            )

        self._validate_host_cluster_offset(host_offset, "data cluster")
        return ClusterMapping(
            guest_cluster,
            guest_offset,
            host_offset,
            allocated=True,
            reads_as_zero=reads_as_zero,
        )

    def raw_l2_entry(self, guest_cluster: int) -> int:
        """Return the L2 descriptor for read-only diagnostics."""

        self._require_open()
        if not isinstance(guest_cluster, int) or guest_cluster < 0:
            raise ValueError("Guest cluster number must be >= 0")
        if guest_cluster >= self.cluster_count:
            raise ValueError("Guest cluster beyond virtual size")

        entries_per_l2 = self.cluster_size // 8
        l1_index, l2_index = divmod(guest_cluster, entries_per_l2)
        if l1_index >= len(self._l1_table):
            raise QCOW2FormatError("L1 table does not cover the guest disk")

        l1_entry = self._l1_table[l1_index]
        if l1_entry == 0:
            return 0

        l1_reserved = l1_entry & ~(QCOW_OFLAG_COPIED | QCOW_OFFSET_MASK)
        if l1_reserved:
            raise QCOW2FormatError(
                f"L1 entry {l1_index} has reserved bits: 0x{l1_reserved:x}"
            )

        l2_table_offset = l1_entry & QCOW_OFFSET_MASK
        self._validate_host_cluster_offset(l2_table_offset, "L2 table")
        return self._get_l2_table(l1_index, l2_table_offset)[l2_index]

    def is_compressed_cluster(self, guest_cluster: int) -> bool:
        return bool(self.raw_l2_entry(guest_cluster) & QCOW_OFLAG_COMPRESSED)

    def read_compressed_payload(self, guest_cluster: int) -> bytes:
        """Read the compressed payload without interpreting or decompressing it."""

        entry = self.raw_l2_entry(guest_cluster)
        if not entry & QCOW_OFLAG_COMPRESSED:
            raise ValueError(f"Guest cluster {guest_cluster} is not compressed")

        size_bits = self.cluster_size.bit_length() - 1 - 8
        csize_shift = 62 - size_bits
        host_offset_mask = (1 << csize_shift) - 1
        additional_sector_mask = (1 << size_bits) - 1
        host_offset = entry & host_offset_mask
        additional_sectors = (
            entry >> csize_shift
        ) & additional_sector_mask
        compressed_size = (
            (additional_sectors + 1) * 512 - (host_offset & 511)
        )

        if compressed_size <= 0 or compressed_size > self.cluster_size * 2:
            raise QCOW2FormatError(
                f"Invalid compressed size: {compressed_size}"
            )
        return self._read_exact_host(host_offset, compressed_size)

    def map_offset(self, guest_offset: int) -> Optional[int]:
        """Map a guest byte to the corresponding physical host offset."""

        self._validate_guest_range(guest_offset, 1)
        mapping = self.map_cluster(guest_offset // self.cluster_size)
        if not mapping.allocated or mapping.reads_as_zero:
            return None
        assert mapping.host_offset is not None
        return mapping.host_offset + (guest_offset % self.cluster_size)

    def iter_mappings(self) -> Iterator[ClusterMapping]:
        for guest_cluster in range(self.cluster_count):
            yield self.map_cluster(guest_cluster)

    def _read_header(self) -> QCOW2Header:
        prefix = self._read_exact_host(0, 72)
        magic, version = struct.unpack_from(">II", prefix, 0)
        if magic != QCOW2_MAGIC:
            raise QCOW2FormatError("Invalid QCOW2 magic")
        if version not in (2, 3):
            raise UnsupportedQCOW2Feature(
                f"Unsupported QCOW2 version {version}"
            )

        backing_file_offset = struct.unpack_from(">Q", prefix, 8)[0]
        backing_file_size = struct.unpack_from(">I", prefix, 16)[0]
        cluster_bits = struct.unpack_from(">I", prefix, 20)[0]
        virtual_size = struct.unpack_from(">Q", prefix, 24)[0]
        crypt_method = struct.unpack_from(">I", prefix, 32)[0]
        l1_size = struct.unpack_from(">I", prefix, 36)[0]
        l1_table_offset = struct.unpack_from(">Q", prefix, 40)[0]
        refcount_table_offset = struct.unpack_from(">Q", prefix, 48)[0]
        refcount_table_clusters = struct.unpack_from(">I", prefix, 56)[0]
        snapshot_count = struct.unpack_from(">I", prefix, 60)[0]
        snapshots_offset = struct.unpack_from(">Q", prefix, 64)[0]

        if not QCOW2_MIN_CLUSTER_BITS <= cluster_bits <= QCOW2_MAX_CLUSTER_BITS:
            raise QCOW2FormatError(
                f"cluster_bits out of range: {cluster_bits}"
            )
        cluster_size = 1 << cluster_bits
        if virtual_size <= 0:
            raise QCOW2FormatError("Invalid virtual size")
        if crypt_method != 0:
            raise UnsupportedQCOW2Feature("Encrypted QCOW2 not supported")
        if backing_file_offset or backing_file_size:
            raise UnsupportedQCOW2Feature("QCOW2 backing file not supported")
        if l1_size <= 0:
            raise QCOW2FormatError("Empty L1 table")
        if l1_size * 8 > QCOW2_MAX_L1_BYTES:
            raise QCOW2FormatError("L1 table exceeds safety limit")
        if l1_table_offset == 0:
            raise QCOW2FormatError("Null L1 table offset")
        if l1_table_offset % cluster_size:
            raise QCOW2FormatError("L1 table not cluster-aligned")

        incompatible_features = 0
        compatible_features = 0
        autoclear_features = 0
        refcount_order = 4
        header_length = 72
        compression_type = 0

        if version == 3:
            version3 = self._read_exact_host(72, 32)
            incompatible_features = struct.unpack_from(">Q", version3, 0)[0]
            compatible_features = struct.unpack_from(">Q", version3, 8)[0]
            autoclear_features = struct.unpack_from(">Q", version3, 16)[0]
            refcount_order = struct.unpack_from(">I", version3, 24)[0]
            header_length = struct.unpack_from(">I", version3, 28)[0]

            if header_length < 104 or header_length > cluster_size:
                raise QCOW2FormatError(
                    f"Invalid v3 header length: {header_length}"
                )
            if header_length % 8:
                raise QCOW2FormatError(
                    f"Unaligned v3 header length: {header_length}"
                )
            if header_length > self._host_size:
                raise QCOW2FormatError("Header beyond end of host file")
            if refcount_order > 6:
                raise QCOW2FormatError(
                    f"Invalid refcount_order: {refcount_order}"
                )
            if header_length >= 112:
                additional_header = self._read_exact_host(104, 8)
                compression_type = additional_header[0]
                if any(additional_header[1:]):
                    raise QCOW2FormatError(
                        "Non-zero QCOW2 v3 header padding"
                    )

            unknown = incompatible_features & ~QCOW2_KNOWN_INCOMPAT
            if unknown:
                raise UnsupportedQCOW2Feature(
                    f"Unknown incompatible features: 0x{unknown:x}"
                )
            if incompatible_features & QCOW2_INCOMPAT_CORRUPT:
                raise QCOW2FormatError("QCOW2 marked corrupt")
            if incompatible_features & QCOW2_INCOMPAT_EXTERNAL_DATA:
                raise UnsupportedQCOW2Feature(
                    "QCOW2 with external data file not supported"
                )
            if incompatible_features & QCOW2_INCOMPAT_EXTENDED_L2:
                raise UnsupportedQCOW2Feature(
                    "QCOW2 with extended L2 entries not supported"
                )
            if incompatible_features & QCOW2_INCOMPAT_COMPRESSION_TYPE:
                if compression_type == 0:
                    raise QCOW2FormatError(
                        "compression type feature without non-default type"
                    )
                raise UnsupportedQCOW2Feature(
                    f"Unsupported QCOW2 compression type {compression_type}"
                )
            if compression_type != 0:
                raise QCOW2FormatError(
                    "compression_type present without incompatible feature"
                )

        return QCOW2Header(
            version=version,
            backing_file_offset=backing_file_offset,
            backing_file_size=backing_file_size,
            cluster_bits=cluster_bits,
            cluster_size=cluster_size,
            virtual_size=virtual_size,
            crypt_method=crypt_method,
            l1_size=l1_size,
            l1_table_offset=l1_table_offset,
            refcount_table_offset=refcount_table_offset,
            refcount_table_clusters=refcount_table_clusters,
            snapshot_count=snapshot_count,
            snapshots_offset=snapshots_offset,
            incompatible_features=incompatible_features,
            compatible_features=compatible_features,
            autoclear_features=autoclear_features,
            refcount_order=refcount_order,
            header_length=header_length,
            compression_type=compression_type,
        )

    def _read_l1_table(self) -> Tuple[int, ...]:
        header = self.header
        byte_count = header.l1_size * 8
        if header.l1_table_offset + byte_count > self._host_size:
            raise QCOW2FormatError("Truncated L1 table")
        raw = self._read_exact_host(header.l1_table_offset, byte_count)
        return struct.unpack(f">{header.l1_size}Q", raw)

    def _validate_l1_coverage(self) -> None:
        entries_per_l2 = self.cluster_size // 8
        required_l1 = (
            self.cluster_count + entries_per_l2 - 1
        ) // entries_per_l2
        if len(self._l1_table) < required_l1:
            raise QCOW2FormatError(
                f"L1 table too short: {len(self._l1_table)} < {required_l1}"
            )

    def _get_l2_table(
        self,
        l1_index: int,
        l2_table_offset: int,
    ) -> Tuple[int, ...]:
        cached = self._l2_cache.get(l1_index)
        if cached is not None:
            self._l2_cache.move_to_end(l1_index)
            return cached

        raw = self._read_exact_host(l2_table_offset, self.cluster_size)
        entries_per_l2 = self.cluster_size // 8
        table = struct.unpack(f">{entries_per_l2}Q", raw)
        self._l2_cache[l1_index] = table
        self._l2_cache.move_to_end(l1_index)
        while len(self._l2_cache) > QCOW2_MAX_CACHED_L2_TABLES:
            self._l2_cache.popitem(last=False)
        return table

    def _validate_host_cluster_offset(self, offset: int, label: str) -> None:
        if offset == 0:
            raise QCOW2FormatError(f"Null offset for {label}")
        if offset % self.cluster_size:
            raise QCOW2FormatError(f"Unaligned offset for {label}: 0x{offset:x}")
        if offset + self.cluster_size > self._host_size:
            raise QCOW2FormatError(f"{label.capitalize()} beyond host file")

    def _validate_guest_range(self, offset: int, size: int) -> None:
        self._require_open()
        if not isinstance(offset, int) or not isinstance(size, int):
            raise TypeError("Offset and size must be integers")
        if offset < 0 or size < 0:
            raise ValueError("Offset and size must be >= 0")
        if offset > self.size or size > self.size - offset:
            raise ValueError("Read beyond guest disk size")

    def _read_exact_host(self, offset: int, size: int) -> bytes:
        self._require_open()
        if offset < 0 or size < 0 or offset > self._host_size:
            raise QCOW2FormatError("Invalid host range")
        if size > self._host_size - offset:
            raise QCOW2FormatError("Read beyond end of host file")

        assert self._file is not None
        self._file.seek(offset)
        data = self._file.read(size)
        if len(data) != size:
            raise QCOW2FormatError(
                f"Truncated host read: requested {size}, got {len(data)}"
            )
        return data

    def _require_open(self) -> None:
        if self._file is None:
            raise QCOW2Error("Block device not open; use the context manager")


def _decompress_qcow2_cluster(payload: bytes) -> bytes:
    """Decompress a QCOW2 cluster (raw deflate or zlib wrapper)."""

    last_error: Optional[BaseException] = None
    for wbits in (-12, -15, 15):
        try:
            return zlib.decompress(payload, wbits=wbits)
        except zlib.error as exc:
            last_error = exc
    try:
        return zlib.decompress(payload)
    except zlib.error as exc:
        last_error = exc
    raise QCOW2FormatError(
        f"Cluster decompression failed: {last_error}"
    ) from last_error


class QCOW2WritableBlockDevice(QCOW2BlockDevice):
    """QCOW2 block device with guest-aware overwrite and opt-in allocate-on-write.

    By default writes only to already-allocated host clusters that are neither
    zero nor compressed. With ``allocate=True`` (or ``ensure_allocated``) creates
    host clusters, updates L2/L1/refcount, and can decompress default zlib clusters.
    """

    def __init__(self, path: PathLike):
        super().__init__(path)
        self._writable = False
        self._refcount_table: List[int] = []
        self._clusters_allocated = 0
        self._host_bytes_grown = 0
        self._metadata_dirty = False

    def __enter__(self) -> "QCOW2WritableBlockDevice":
        return self.open()

    def open(self) -> "QCOW2WritableBlockDevice":
        if self._file is not None:
            if not self._writable:
                raise QCOW2WriteError(
                    "Device already open read-only; close and reopen"
                )
            return self

        try:
            self._file = self.path.open("r+b")
            self._writable = True
            self._host_size = os.fstat(self._file.fileno()).st_size
            self._header = self._read_header()
            self._l1_table = self._read_l1_table()
            self._validate_l1_coverage()
            if self.header.is_dirty:
                raise QCOW2WriteError(
                    "QCOW2 has dirty bit: write rejected"
                )
            self._refcount_table = list(self._read_refcount_table())
            self._clusters_allocated = 0
            self._host_bytes_grown = 0
            self._metadata_dirty = False
        except Exception:
            self.close()
            raise
        return self

    def close(self) -> None:
        self._writable = False
        self._refcount_table = []
        self._metadata_dirty = False
        super().close()

    @property
    def clusters_allocated(self) -> int:
        return self._clusters_allocated

    @property
    def host_bytes_grown(self) -> int:
        return self._host_bytes_grown

    def write_at(
        self,
        offset: int,
        data: bytes,
        *,
        allocate: bool = False,
    ) -> None:
        """Overwrite guest bytes; with allocate=True create missing clusters."""

        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("Data to write must be bytes-like")
        payload = bytes(data)
        self._validate_guest_range(offset, len(payload))
        self._require_writable()
        if not payload:
            return

        guest_clusters: List[int] = []
        cursor = 0
        while cursor < len(payload):
            guest_offset = offset + cursor
            guest_cluster = guest_offset // self.cluster_size
            in_cluster = guest_offset % self.cluster_size
            chunk_size = min(
                len(payload) - cursor,
                self.cluster_size - in_cluster,
            )
            guest_clusters.append(guest_cluster)
            cursor += chunk_size

        if allocate:
            nested = self._metadata_dirty
            if not nested:
                self._begin_metadata_mutation()
            try:
                for guest_cluster in guest_clusters:
                    self.ensure_allocated(guest_cluster)
                self._write_payload_chunks(offset, payload)
                if not nested:
                    self.flush()
            finally:
                if not nested:
                    self._end_metadata_mutation()
            return

        for guest_cluster in guest_clusters:
            self._require_writable_mapping(guest_cluster)
        self._write_payload_chunks(offset, payload)

    def needs_allocation(self, guest_cluster: int) -> bool:
        """True if the cluster is not overwrite-safe (unalloc/zero/compressed)."""

        self._require_open()
        if self.is_compressed_cluster(guest_cluster):
            return True
        mapping = self.map_cluster(guest_cluster)
        return (not mapping.allocated) or mapping.reads_as_zero

    def read_cluster_content(self, guest_cluster: int) -> bytes:
        """Read a guest cluster, decompressing if needed."""

        self._require_open()
        if self.is_compressed_cluster(guest_cluster):
            compressed = self.read_compressed_payload(guest_cluster)
            data = _decompress_qcow2_cluster(compressed)
            if len(data) != self.cluster_size:
                raise QCOW2FormatError(
                    f"Compressed cluster {guest_cluster}: "
                    f"expected {self.cluster_size} bytes, got {len(data)}"
                )
            return data
        mapping = self.map_cluster(guest_cluster)
        if not mapping.allocated or mapping.reads_as_zero:
            return bytes(self.cluster_size)
        return self.read_cluster(guest_cluster)

    def write_guest_cluster(
        self,
        guest_cluster: int,
        data: bytes,
        *,
        allocate: bool = False,
    ) -> None:
        """Write an entire guest QCOW2 cluster (opt-in allocate)."""

        if len(data) != self.cluster_size:
            raise ValueError(
                f"write_guest_cluster requires {self.cluster_size} bytes, "
                f"got {len(data)}"
            )
        self.write_at(
            guest_cluster * self.cluster_size,
            data,
            allocate=allocate,
        )

    def ensure_allocated(self, guest_cluster: int) -> ClusterMapping:
        """Ensure a normal guest cluster is allocated and writable."""

        self._require_writable()
        if not isinstance(guest_cluster, int) or guest_cluster < 0:
            raise ValueError("Guest cluster number must be >= 0")
        if guest_cluster >= self.cluster_count:
            raise ValueError("Guest cluster beyond virtual size")
        if self.header.snapshot_count:
            raise UnsupportedQCOW2Feature(
                "Allocate-on-write not supported with QCOW2 snapshots"
            )
        if self.header.compression_type != 0:
            raise UnsupportedQCOW2Feature(
                "Non-default QCOW2 compression not supported in allocate"
            )

        if self.is_compressed_cluster(guest_cluster):
            return self._reallocate_compressed_cluster(guest_cluster)

        mapping = self.map_cluster(guest_cluster)
        if mapping.allocated and not mapping.reads_as_zero:
            if mapping.host_offset is None:
                raise QCOW2WriteError(
                    f"Guest cluster {guest_cluster} has no host offset"
                )
            return mapping

        return self._allocate_normal_cluster(
            guest_cluster,
            initial_data=bytes(self.cluster_size),
        )

    def flush(self) -> None:
        self._require_writable()
        assert self._file is not None
        self._file.flush()
        os.fsync(self._file.fileno())

    @contextmanager
    def allocating(self) -> Iterator["QCOW2WritableBlockDevice"]:
        """Metadata mutation session (dirty bit + final flush).

        If the session fails mid-way, the dirty bit stays set: the image
        is no longer considered writable until an explicit rollback
        (``restore_host_checkpoint``) or external restore.
        """

        nested = self._metadata_dirty
        if not nested:
            self._begin_metadata_mutation()
        succeeded = False
        try:
            yield self
            if not nested:
                self.flush()
                self._end_metadata_mutation()
            succeeded = True
        finally:
            if not nested and not succeeded:
                try:
                    self.flush()
                except Exception:
                    pass

    def capture_host_checkpoint(self) -> HostCheckpoint:
        """Capture host metadata for allocate undo (files typically small)."""

        self._require_writable()
        header = self.header
        l1_raw = self._read_exact_host(
            header.l1_table_offset,
            header.l1_size * 8,
        )
        l2_blobs: List[Tuple[int, bytes]] = []
        for entry in self._l1_table:
            if entry == 0:
                continue
            l2_offset = entry & QCOW_OFFSET_MASK
            if l2_offset == 0:
                continue
            l2_blobs.append(
                (l2_offset, self._read_exact_host(l2_offset, self.cluster_size))
            )

        refcount_bytes = header.refcount_table_clusters * self.cluster_size
        refcount_raw = self._read_exact_host(
            header.refcount_table_offset,
            refcount_bytes,
        )
        block_blobs: List[Tuple[int, bytes]] = []
        seen_blocks: Set[int] = set()
        entry_count = refcount_bytes // 8
        for index in range(entry_count):
            block_offset = struct.unpack_from(">Q", refcount_raw, index * 8)[0]
            block_offset &= QCOW_OFFSET_MASK
            if block_offset == 0 or block_offset in seen_blocks:
                continue
            if block_offset + self.cluster_size > self._host_size:
                continue
            seen_blocks.add(block_offset)
            block_blobs.append(
                (
                    block_offset,
                    self._read_exact_host(block_offset, self.cluster_size),
                )
            )

        return HostCheckpoint(
            host_size=self._host_size,
            incompatible_features=header.incompatible_features,
            l1_table_offset=header.l1_table_offset,
            l1_raw=l1_raw,
            l2_blobs=tuple(l2_blobs),
            refcount_table_offset=header.refcount_table_offset,
            refcount_table_clusters=header.refcount_table_clusters,
            refcount_table_raw=refcount_raw,
            refcount_block_blobs=tuple(block_blobs),
        )

    def restore_host_checkpoint(self, checkpoint: HostCheckpoint) -> None:
        """Restore metadata + truncate host (failed allocate undo)."""

        self._require_writable()
        assert self._file is not None
        self._file.flush()
        self._file.truncate(checkpoint.host_size)
        self._host_size = checkpoint.host_size

        # Refcount header (offset 48 = u64, 56 = u32).
        self._write_exact_host(
            48,
            struct.pack(">Q", checkpoint.refcount_table_offset),
        )
        self._write_exact_host(
            56,
            struct.pack(">I", checkpoint.refcount_table_clusters),
        )
        self._write_exact_host(
            checkpoint.refcount_table_offset,
            checkpoint.refcount_table_raw,
        )
        for offset, blob in checkpoint.refcount_block_blobs:
            self._write_exact_host(offset, blob)

        self._write_exact_host(checkpoint.l1_table_offset, checkpoint.l1_raw)
        for offset, blob in checkpoint.l2_blobs:
            self._write_exact_host(offset, blob)

        # Reload in-memory state and clear dirty.
        self._header = self._read_header()
        self._l1_table = self._read_l1_table()
        self._l2_cache.clear()
        self._refcount_table = list(self._read_refcount_table())
        self._metadata_dirty = False
        self._set_dirty_bit(
            bool(checkpoint.incompatible_features & QCOW2_INCOMPAT_DIRTY)
        )
        # If the checkpoint was clean, ensure dirty=0.
        if not (checkpoint.incompatible_features & QCOW2_INCOMPAT_DIRTY):
            self._set_dirty_bit(False)
        self.flush()
        self._clusters_allocated = 0
        self._host_bytes_grown = 0

    def _write_payload_chunks(self, offset: int, payload: bytes) -> None:
        cursor = 0
        while cursor < len(payload):
            guest_offset = offset + cursor
            guest_cluster = guest_offset // self.cluster_size
            in_cluster = guest_offset % self.cluster_size
            chunk_size = min(
                len(payload) - cursor,
                self.cluster_size - in_cluster,
            )
            mapping = self._require_writable_mapping(guest_cluster)
            assert mapping.host_offset is not None
            self._write_exact_host(
                mapping.host_offset + in_cluster,
                payload[cursor : cursor + chunk_size],
            )
            cursor += chunk_size

    def _require_writable(self) -> None:
        self._require_open()
        if not self._writable:
            raise QCOW2WriteError("Block device not open for writing")

    def _require_writable_mapping(self, guest_cluster: int) -> ClusterMapping:
        if self.is_compressed_cluster(guest_cluster):
            raise UnsupportedQCOW2Feature(
                f"Guest cluster {guest_cluster} compressed: "
                "write not supported (use allocate=True)"
            )
        mapping = self.map_cluster(guest_cluster)
        if not mapping.allocated or mapping.reads_as_zero:
            raise QCOW2WriteError(
                f"Guest cluster {guest_cluster} unallocated or zero: "
                "allocate-on-write not enabled (use allocate=True)"
            )
        if mapping.host_offset is None:
            raise QCOW2WriteError(
                f"Guest cluster {guest_cluster} has no host offset"
            )
        return mapping

    def _reallocate_compressed_cluster(
        self,
        guest_cluster: int,
    ) -> ClusterMapping:
        compressed = self.read_compressed_payload(guest_cluster)
        decompressed = _decompress_qcow2_cluster(compressed)
        if len(decompressed) != self.cluster_size:
            raise QCOW2FormatError(
                f"Compressed cluster {guest_cluster}: "
                f"expected {self.cluster_size} bytes, "
                f"got {len(decompressed)}"
            )
        # Previous compressed payload is left orphaned (intentional v1 leak).
        return self._allocate_normal_cluster(
            guest_cluster,
            initial_data=decompressed,
        )

    def _allocate_normal_cluster(
        self,
        guest_cluster: int,
        initial_data: bytes,
    ) -> ClusterMapping:
        if len(initial_data) != self.cluster_size:
            raise ValueError("initial_data must be exactly one cluster")

        self._ensure_l2_table(guest_cluster)
        host_offset = self._alloc_host_clusters(1)
        self._write_exact_host(host_offset, initial_data)
        self._set_l2_entry(
            guest_cluster,
            QCOW_OFLAG_COPIED | host_offset,
        )
        self._clusters_allocated += 1
        guest_offset = guest_cluster * self.cluster_size
        return ClusterMapping(
            guest_cluster,
            guest_offset,
            host_offset,
            allocated=True,
            reads_as_zero=False,
        )

    def _ensure_l2_table(self, guest_cluster: int) -> None:
        entries_per_l2 = self.cluster_size // 8
        l1_index = guest_cluster // entries_per_l2
        if l1_index >= len(self._l1_table):
            raise QCOW2FormatError("L1 index beyond table")

        l1_entry = self._l1_table[l1_index]
        if l1_entry != 0:
            return

        l2_offset = self._alloc_host_clusters(1)
        self._write_exact_host(l2_offset, bytes(self.cluster_size))
        new_entry = QCOW_OFLAG_COPIED | l2_offset
        self._set_l1_entry(l1_index, new_entry)

    def _set_l1_entry(self, l1_index: int, entry: int) -> None:
        table = list(self._l1_table)
        table[l1_index] = entry
        self._l1_table = tuple(table)
        offset = self.header.l1_table_offset + l1_index * 8
        self._write_exact_host(offset, struct.pack(">Q", entry))
        self._l2_cache.pop(l1_index, None)

    def _set_l2_entry(self, guest_cluster: int, entry: int) -> None:
        entries_per_l2 = self.cluster_size // 8
        l1_index, l2_index = divmod(guest_cluster, entries_per_l2)
        l1_entry = self._l1_table[l1_index]
        if l1_entry == 0:
            raise QCOW2WriteError(
                f"L2 table missing for guest cluster {guest_cluster}"
            )
        l2_table_offset = l1_entry & QCOW_OFFSET_MASK
        self._write_exact_host(
            l2_table_offset + l2_index * 8,
            struct.pack(">Q", entry),
        )
        self._l2_cache.pop(l1_index, None)

    def _read_refcount_table(self) -> Tuple[int, ...]:
        header = self.header
        if header.refcount_table_offset == 0 or header.refcount_table_clusters <= 0:
            raise QCOW2FormatError("Refcount table missing")
        byte_count = header.refcount_table_clusters * self.cluster_size
        if header.refcount_table_offset + byte_count > self._host_size:
            raise QCOW2FormatError("Truncated refcount table")
        raw = self._read_exact_host(header.refcount_table_offset, byte_count)
        count = byte_count // 8
        return struct.unpack(f">{count}Q", raw)

    @property
    def _refcount_bits(self) -> int:
        return 1 << self.header.refcount_order

    @property
    def _refcount_block_entries(self) -> int:
        return (self.cluster_size * 8) // self._refcount_bits

    def _alloc_host_clusters(self, count: int) -> int:
        if count <= 0:
            raise ValueError("count must be >= 1")
        self._align_host_size()
        offset = self._host_size
        self._append_raw_clusters(count)
        for index in range(count):
            self._set_refcount(offset + index * self.cluster_size, 1)
        return offset

    def _align_host_size(self) -> None:
        remainder = self._host_size % self.cluster_size
        if remainder:
            self._append_raw_bytes(self.cluster_size - remainder)

    def _append_raw_clusters(self, count: int) -> int:
        offset = self._host_size
        self._append_raw_bytes(count * self.cluster_size)
        return offset

    def _append_raw_bytes(self, size: int) -> None:
        if size <= 0:
            return
        assert self._file is not None
        self._file.seek(0, os.SEEK_END)
        self._file.write(bytes(size))
        self._host_size += size
        self._host_bytes_grown += size

    def _set_refcount(self, host_offset: int, value: int) -> None:
        if host_offset % self.cluster_size:
            raise QCOW2FormatError(
                f"Unaligned refcount offset: 0x{host_offset:x}"
            )
        if value < 0 or value >= (1 << self._refcount_bits):
            raise QCOW2WriteError(f"Invalid refcount value: {value}")

        cluster_index = host_offset // self.cluster_size
        entries = self._refcount_block_entries
        table_index = cluster_index // entries
        block_index = cluster_index % entries

        while table_index >= len(self._refcount_table):
            self._grow_refcount_table()

        block_offset = self._refcount_table[table_index] & QCOW_OFFSET_MASK
        if block_offset == 0:
            block_offset = self._allocate_refcount_block(table_index)

        self._write_refcount_entry(block_offset, block_index, value)

    def _allocate_refcount_block(self, table_index: int) -> int:
        block_offset = self._append_raw_clusters(1)
        self._write_exact_host(block_offset, bytes(self.cluster_size))
        self._refcount_table[table_index] = block_offset
        self._persist_refcount_table_entry(table_index, block_offset)

        # The block must count itself (refcount=1).
        block_cluster = block_offset // self.cluster_size
        entries = self._refcount_block_entries
        block_table_index = block_cluster // entries
        block_in_block = block_cluster % entries
        if block_table_index == table_index:
            self._write_refcount_entry(block_offset, block_in_block, 1)
        else:
            self._set_refcount(block_offset, 1)
        return block_offset

    def _grow_refcount_table(self) -> None:
        """Grow the refcount table (old table left orphaned)."""

        header = self.header
        entries_per_cluster = self.cluster_size // 8
        old_clusters = header.refcount_table_clusters
        new_clusters = old_clusters + 1
        new_offset = self._append_raw_clusters(new_clusters)
        old_raw = self._read_exact_host(
            header.refcount_table_offset,
            old_clusters * self.cluster_size,
        )
        self._write_exact_host(new_offset, old_raw)
        padding = (new_clusters - old_clusters) * self.cluster_size
        if padding:
            self._write_exact_host(
                new_offset + len(old_raw),
                bytes(padding),
            )

        # Update header: table offset + cluster count.
        assert self._file is not None
        self._write_exact_host(48, struct.pack(">Q", new_offset))
        self._write_exact_host(56, struct.pack(">I", new_clusters))
        self._header = self._read_header()

        new_entries = new_clusters * entries_per_cluster
        extended = list(self._refcount_table)
        while len(extended) < new_entries:
            extended.append(0)
        self._refcount_table = extended

        for index in range(new_clusters):
            self._set_refcount(new_offset + index * self.cluster_size, 1)

    def _persist_refcount_table_entry(
        self,
        table_index: int,
        entry: int,
    ) -> None:
        offset = self.header.refcount_table_offset + table_index * 8
        self._write_exact_host(offset, struct.pack(">Q", entry))

    def _write_refcount_entry(
        self,
        block_offset: int,
        block_index: int,
        value: int,
    ) -> None:
        bits = self._refcount_bits
        if bits == 16:
            data = struct.pack(">H", value)
            byte_offset = block_offset + block_index * 2
        elif bits == 32:
            data = struct.pack(">I", value)
            byte_offset = block_offset + block_index * 4
        elif bits == 64:
            data = struct.pack(">Q", value)
            byte_offset = block_offset + block_index * 8
        elif bits == 8:
            data = bytes((value,))
            byte_offset = block_offset + block_index
        else:
            raise UnsupportedQCOW2Feature(
                f"refcount_order={self.header.refcount_order} "
                "not supported for writing"
            )
        self._write_exact_host(byte_offset, data)

    def _begin_metadata_mutation(self) -> None:
        if self._metadata_dirty:
            return
        self._set_dirty_bit(True)
        self._metadata_dirty = True

    def _end_metadata_mutation(self) -> None:
        if not self._metadata_dirty:
            return
        self.flush()
        self._set_dirty_bit(False)
        self._metadata_dirty = False
        self.flush()

    def _set_dirty_bit(self, dirty: bool) -> None:
        if self.header.version < 3:
            return
        features = self.header.incompatible_features
        if dirty:
            features |= QCOW2_INCOMPAT_DIRTY
        else:
            features &= ~QCOW2_INCOMPAT_DIRTY
        self._write_exact_host(72, struct.pack(">Q", features))
        # Update in-memory header without re-reading the whole file.
        assert self._header is not None
        self._header = QCOW2Header(
            version=self._header.version,
            backing_file_offset=self._header.backing_file_offset,
            backing_file_size=self._header.backing_file_size,
            cluster_bits=self._header.cluster_bits,
            cluster_size=self._header.cluster_size,
            virtual_size=self._header.virtual_size,
            crypt_method=self._header.crypt_method,
            l1_size=self._header.l1_size,
            l1_table_offset=self._header.l1_table_offset,
            refcount_table_offset=self._header.refcount_table_offset,
            refcount_table_clusters=self._header.refcount_table_clusters,
            snapshot_count=self._header.snapshot_count,
            snapshots_offset=self._header.snapshots_offset,
            incompatible_features=features,
            compatible_features=self._header.compatible_features,
            autoclear_features=self._header.autoclear_features,
            refcount_order=self._header.refcount_order,
            header_length=self._header.header_length,
            compression_type=self._header.compression_type,
        )

    def _write_exact_host(self, offset: int, data: bytes) -> None:
        self._require_writable()
        size = len(data)
        if offset < 0 or size < 0:
            raise QCOW2FormatError("Invalid host range for write")
        if offset > self._host_size:
            raise QCOW2FormatError("Write beyond end of host file")
        if size > self._host_size - offset:
            raise QCOW2FormatError(
                "Write beyond end of host file "
                "(extend first with allocate)"
            )

        assert self._file is not None
        self._file.seek(offset)
        written = self._file.write(data)
        if written != size:
            raise QCOW2WriteError(
                f"Incomplete host write: requested {size}, wrote {written}"
            )
