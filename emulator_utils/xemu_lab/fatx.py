"""Parser FATX guest-aware per il disco retail della prima Xbox."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from .qcow2 import BlockDevice, UnsupportedQCOW2Feature


SECTOR_SIZE = 0x200
FATX_HEADER_SIZE = 0x1000
FATX_PAGE_SIZE = 0x1000
FATX_DIRENT_SIZE = 0x40
FATX_MAX_NAME = 42
FATX16_CLUSTER_LIMIT = 0xFFF0

FATX_DIRENT_NEVER_USED = 0x00
FATX_DIRENT_DELETED = 0xE5
FATX_DIRENT_END = 0xFF
FATX_DIRECTORY_ATTRIBUTE = 0x10

TITLE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}$")


class FATXError(Exception):
    """Errore base del parser FATX."""


class FATXFormatError(FATXError):
    """Struttura FATX incoerente o non valida."""


class FATXBoundsError(FATXError):
    """Cluster o offset fuori dalla partizione FATX."""


@dataclass(frozen=True)
class XboxRegion:
    name: str
    offset: int
    size: int
    description: str
    is_fatx: bool = True

    @property
    def end(self) -> int:
        return self.offset + self.size

    def contains(self, guest_offset: int) -> bool:
        return self.offset <= guest_offset < self.end


# Layout fisso retail. La lunghezza E è quella usata dalle implementazioni
# fatx-tools; per il parsing della FAT produce la file area osservata su xemu.
XBOX_REGIONS: Tuple[XboxRegion, ...] = (
    XboxRegion("CONFIG", 0x00000000, 0x00080000, "Area configurazione", False),
    XboxRegion("X", 0x00080000, 0x2EE00000, "Cache gioco X"),
    XboxRegion("Y", 0x2EE80000, 0x2EE00000, "Cache gioco Y"),
    XboxRegion("Z", 0x5DC80000, 0x2EE00000, "Cache gioco Z"),
    XboxRegion("C", 0x8CA80000, 0x1F400000, "Sistema"),
    XboxRegion("E", 0xABE80000, 0x1312D6000, "Dati utente e giochi"),
)

XBOX_PARTITIONS: Dict[str, XboxRegion] = {
    region.name: region for region in XBOX_REGIONS if region.is_fatx
}


def get_region(name: str) -> XboxRegion:
    normalized = name.upper()
    for region in XBOX_REGIONS:
        if region.name == normalized:
            return region
    raise KeyError(f"Regione Xbox sconosciuta: {name}")


def region_for_offset(guest_offset: int) -> Optional[XboxRegion]:
    if guest_offset < 0:
        raise ValueError("L'offset guest deve essere >= 0")
    for region in XBOX_REGIONS:
        if region.contains(guest_offset):
            return region
    return None


@dataclass(frozen=True)
class FATXHeader:
    partition: XboxRegion
    serial_number: int
    sectors_per_cluster: int
    cluster_size: int
    root_dir_first_cluster: int
    max_clusters: int
    data_cluster_count: int
    fat_entry_size: int
    fat_size: int
    fat_offset: int
    file_area_offset: int

    @property
    def is_fat16(self) -> bool:
        return self.fat_entry_size == 2

    @property
    def last_cluster_marker(self) -> int:
        return 0xFFFF if self.is_fat16 else 0xFFFFFFFF

    @property
    def reserved_cluster_start(self) -> int:
        return 0xFFF0 if self.is_fat16 else 0xFFFFFFF0

    @property
    def end_of_chain_start(self) -> int:
        """Primo valore FAT che termina una catena (incluse varianti EOC)."""

        return 0xFFF8 if self.is_fat16 else 0xFFFFFFF8


@dataclass(frozen=True)
class FATXLocation:
    partition: str
    area: str
    guest_offset: int
    relative_offset: int
    cluster: Optional[int] = None
    offset_in_cluster: Optional[int] = None


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    attributes: int
    first_cluster: int
    file_size: int
    guest_offset: int
    directory_cluster: int
    raw: bytes

    @property
    def is_directory(self) -> bool:
        return bool(self.attributes & FATX_DIRECTORY_ATTRIBUTE)


@dataclass(frozen=True)
class TreeEntry:
    path: str
    entry: DirectoryEntry


@dataclass(frozen=True)
class GameDirectory:
    area: str
    title_id: str
    entry: DirectoryEntry


class FATXVolume:
    """Vista read-only di una singola partizione FATX."""

    def __init__(self, device: BlockDevice, partition: XboxRegion):
        if not partition.is_fatx:
            raise ValueError(f"{partition.name} non è una partizione FATX")
        self.device = device
        self.partition = partition
        self.header = self._read_header()

    @classmethod
    def open_partition(
        cls,
        device: BlockDevice,
        name: str,
    ) -> "FATXVolume":
        region = get_region(name)
        return cls(device, region)

    def _read_header(self) -> FATXHeader:
        if self.partition.end > self.device.size:
            raise FATXBoundsError(
                f"Partizione {self.partition.name} oltre il disco guest"
            )

        raw = self.device.read_at(self.partition.offset, FATX_HEADER_SIZE)
        if raw[:4] != b"FATX":
            raise FATXFormatError(
                f"Magic FATX assente in {self.partition.name} "
                f"@ 0x{self.partition.offset:x}"
            )

        serial_number, sectors_per_cluster, root_cluster = struct.unpack_from(
            "<III", raw, 4
        )
        if sectors_per_cluster <= 0 or (
            sectors_per_cluster & (sectors_per_cluster - 1)
        ):
            raise FATXFormatError(
                f"SectorsPerCluster non valido: {sectors_per_cluster}"
            )
        if sectors_per_cluster > 0x80:
            raise FATXFormatError(
                f"SectorsPerCluster troppo grande: {sectors_per_cluster}"
            )

        cluster_size = sectors_per_cluster * SECTOR_SIZE
        data_clusters = self.partition.size // cluster_size
        max_clusters = data_clusters + 1
        fat_entry_size = (
            2 if max_clusters < FATX16_CLUSTER_LIMIT else 4
        )
        fat_bytes = max_clusters * fat_entry_size
        fat_size = _align_up(fat_bytes, FATX_PAGE_SIZE)
        fat_offset = self.partition.offset + FATX_HEADER_SIZE
        file_area_offset = fat_offset + fat_size
        data_cluster_count = (
            self.partition.end - file_area_offset
        ) // cluster_size

        if root_cluster < 1 or root_cluster > data_cluster_count:
            raise FATXFormatError(
                f"RootDirFirstCluster fuori range: {root_cluster}"
            )
        if data_cluster_count <= 0:
            raise FATXFormatError("La FAT occupa l'intera partizione")

        return FATXHeader(
            partition=self.partition,
            serial_number=serial_number,
            sectors_per_cluster=sectors_per_cluster,
            cluster_size=cluster_size,
            root_dir_first_cluster=root_cluster,
            max_clusters=max_clusters,
            data_cluster_count=data_cluster_count,
            fat_entry_size=fat_entry_size,
            fat_size=fat_size,
            fat_offset=fat_offset,
            file_area_offset=file_area_offset,
        )

    def read_fat_entry(self, cluster: int) -> int:
        if not isinstance(cluster, int):
            raise TypeError("Il cluster FAT deve essere un intero")
        if cluster < 0 or cluster >= self.header.max_clusters:
            raise FATXBoundsError(f"Cluster FAT fuori range: {cluster}")

        offset = self.header.fat_offset + cluster * self.header.fat_entry_size
        raw = self.device.read_at(offset, self.header.fat_entry_size)
        return int.from_bytes(raw, "little")

    def cluster_offset(self, cluster: int) -> int:
        if not isinstance(cluster, int):
            raise TypeError("Il cluster deve essere un intero")
        if cluster < 1 or cluster > self.header.data_cluster_count:
            raise FATXBoundsError(f"Cluster dati fuori range: {cluster}")

        offset = (
            self.header.file_area_offset
            + (cluster - 1) * self.header.cluster_size
        )
        if offset + self.header.cluster_size > self.partition.end:
            raise FATXBoundsError(
                f"Cluster {cluster} oltre la partizione {self.partition.name}"
            )
        return offset

    def cluster_for_offset(self, guest_offset: int) -> Optional[int]:
        if not self.partition.contains(guest_offset):
            return None
        if guest_offset < self.header.file_area_offset:
            return None

        cluster = (
            (guest_offset - self.header.file_area_offset)
            // self.header.cluster_size
            + 1
        )
        if cluster > self.header.data_cluster_count:
            return None
        return cluster

    def classify_offset(self, guest_offset: int) -> FATXLocation:
        if not self.partition.contains(guest_offset):
            raise FATXBoundsError(
                f"Offset 0x{guest_offset:x} fuori da {self.partition.name}"
            )

        relative = guest_offset - self.partition.offset
        if guest_offset < self.header.fat_offset:
            return FATXLocation(
                self.partition.name,
                "superblock",
                guest_offset,
                relative,
            )
        if guest_offset < self.header.file_area_offset:
            return FATXLocation(
                self.partition.name,
                "fat",
                guest_offset,
                relative,
            )

        cluster = self.cluster_for_offset(guest_offset)
        if cluster is None:
            return FATXLocation(
                self.partition.name,
                "tail",
                guest_offset,
                relative,
            )
        cluster_offset = self.cluster_offset(cluster)
        return FATXLocation(
            self.partition.name,
            "data",
            guest_offset,
            relative,
            cluster=cluster,
            offset_in_cluster=guest_offset - cluster_offset,
        )

    def read_cluster(self, cluster: int) -> bytes:
        return self.device.read_at(
            self.cluster_offset(cluster),
            self.header.cluster_size,
        )

    def get_chain(
        self,
        first_cluster: int,
        max_clusters: Optional[int] = None,
    ) -> List[int]:
        if (
            first_cluster < 1
            or first_cluster > self.header.data_cluster_count
        ):
            raise FATXBoundsError(
                f"Primo cluster fuori range: {first_cluster}"
            )

        limit = (
            self.header.data_cluster_count
            if max_clusters is None
            else max_clusters
        )
        if limit <= 0:
            raise ValueError("max_clusters deve essere > 0")
        limit = min(limit, self.header.data_cluster_count)

        chain: List[int] = []
        seen: Set[int] = set()
        current = first_cluster
        while True:
            if current in seen:
                raise FATXFormatError(
                    f"Ciclo FAT rilevato al cluster {current}"
                )
            if current < 1 or current > self.header.data_cluster_count:
                raise FATXBoundsError(
                    f"Catena FAT punta fuori range: {current}"
                )
            if len(chain) >= limit:
                raise FATXFormatError(
                    f"Catena FAT oltre il limite di {limit} cluster"
                )

            seen.add(current)
            chain.append(current)
            next_cluster = self.read_fat_entry(current)
            if next_cluster == 0:
                raise FATXFormatError(
                    f"Catena FAT interrotta dopo il cluster {current}"
                )
            # FAT16/FAT32 usano un intervallo di marker EOC (es. 0xFFF8..0xFFFF).
            if next_cluster >= self.header.end_of_chain_start:
                break
            if next_cluster >= self.header.reserved_cluster_start:
                raise FATXFormatError(
                    f"Marker FAT 0x{next_cluster:x} inatteso "
                    f"dopo il cluster {current}"
                )
            current = next_cluster

        return chain

    def iter_directory(self, first_cluster: int) -> Iterator[DirectoryEntry]:
        stop = False
        for directory_cluster in self.get_chain(first_cluster):
            cluster_data = self.read_cluster(directory_cluster)
            cluster_guest_offset = self.cluster_offset(directory_cluster)
            for entry_offset in range(0, len(cluster_data), FATX_DIRENT_SIZE):
                raw = cluster_data[
                    entry_offset : entry_offset + FATX_DIRENT_SIZE
                ]
                filename_length = raw[0]
                if filename_length in (
                    FATX_DIRENT_NEVER_USED,
                    FATX_DIRENT_END,
                ):
                    stop = True
                    break
                if filename_length == FATX_DIRENT_DELETED:
                    continue

                entry = self._parse_directory_entry(
                    raw,
                    cluster_guest_offset + entry_offset,
                    directory_cluster,
                )
                if entry is not None:
                    yield entry
            if stop:
                break

    def _parse_directory_entry(
        self,
        raw: bytes,
        guest_offset: int,
        directory_cluster: int,
    ) -> Optional[DirectoryEntry]:
        if len(raw) != FATX_DIRENT_SIZE:
            raise FATXFormatError("Directory entry troncata")

        filename_length = raw[0]
        if not 1 <= filename_length <= FATX_MAX_NAME:
            return None

        attributes = raw[1]
        if attributes & ~0x37:
            raise FATXFormatError(
                f"Attributi directory entry non validi "
                f"@ 0x{guest_offset:x}: 0x{attributes:02x}"
            )

        name_bytes = raw[2 : 2 + filename_length]
        if not _is_valid_fatx_name(name_bytes):
            raise FATXFormatError(
                f"Nome directory entry non valido @ 0x{guest_offset:x}"
            )
        name = name_bytes.decode("latin-1")

        first_cluster, file_size = struct.unpack_from("<II", raw, 44)
        if first_cluster > self.header.data_cluster_count:
            raise FATXFormatError(
                f"FirstCluster fuori range @ 0x{guest_offset:x}: "
                f"{first_cluster}"
            )
        if bool(attributes & FATX_DIRECTORY_ATTRIBUTE) and first_cluster == 0:
            return None

        return DirectoryEntry(
            name=name,
            attributes=attributes,
            first_cluster=first_cluster,
            file_size=file_size,
            guest_offset=guest_offset,
            directory_cluster=directory_cluster,
            raw=raw,
        )

    def find_child(
        self,
        directory_cluster: int,
        name: str,
    ) -> Optional[DirectoryEntry]:
        folded = name.casefold()
        for entry in self.iter_directory(directory_cluster):
            if entry.name.casefold() == folded:
                return entry
        return None

    def resolve_path(self, path: str) -> DirectoryEntry:
        parts = [part for part in re.split(r"[\\/]+", path) if part]
        if parts and parts[0].upper().rstrip(":") == self.partition.name:
            parts = parts[1:]
        if not parts:
            raise ValueError("Il percorso deve indicare almeno una entry")

        current_cluster = self.header.root_dir_first_cluster
        current: Optional[DirectoryEntry] = None
        for index, part in enumerate(parts):
            current = self.find_child(current_cluster, part)
            if current is None:
                raise FileNotFoundError(
                    f"Percorso FATX non trovato: {path}"
                )
            if index < len(parts) - 1:
                if not current.is_directory:
                    raise NotADirectoryError(
                        f"Componente FATX non directory: {current.name}"
                    )
                current_cluster = current.first_cluster
        assert current is not None
        return current

    def walk(
        self,
        first_cluster: Optional[int] = None,
        base_path: str = "",
        max_depth: int = 32,
    ) -> Iterator[TreeEntry]:
        if max_depth < 0:
            raise ValueError("max_depth deve essere >= 0")
        root_cluster = (
            self.header.root_dir_first_cluster
            if first_cluster is None
            else first_cluster
        )
        stack: List[Tuple[int, str, int]] = [(root_cluster, base_path, 0)]
        visited: Set[int] = set()

        while stack:
            directory_cluster, parent_path, depth = stack.pop()
            if directory_cluster in visited:
                continue
            visited.add(directory_cluster)

            entries = list(self.iter_directory(directory_cluster))
            directories: List[Tuple[int, str, int]] = []
            for entry in entries:
                path = (
                    f"{parent_path}/{entry.name}"
                    if parent_path
                    else entry.name
                )
                yield TreeEntry(path, entry)
                if (
                    entry.is_directory
                    and entry.first_cluster > 0
                    and depth < max_depth
                ):
                    directories.append(
                        (entry.first_cluster, path, depth + 1)
                    )
            stack.extend(reversed(directories))

    def find_named_entries(
        self,
        filename: str,
        max_depth: int = 32,
    ) -> List[TreeEntry]:
        folded = filename.casefold()
        return [
            item
            for item in self.walk(max_depth=max_depth)
            if item.entry.name.casefold() == folded
        ]

    def list_games(
        self,
        areas: Sequence[str] = ("UDATA", "TDATA"),
    ) -> List[GameDirectory]:
        games: List[GameDirectory] = []
        root = self.header.root_dir_first_cluster
        for area_name in areas:
            area_entry = self.find_child(root, area_name)
            if area_entry is None or not area_entry.is_directory:
                continue
            for entry in self.iter_directory(area_entry.first_cluster):
                if entry.is_directory and TITLE_ID_PATTERN.fullmatch(entry.name):
                    games.append(
                        GameDirectory(
                            area=area_name.upper(),
                            title_id=entry.name.lower(),
                            entry=entry,
                        )
                    )
        return games

    def read_file(self, entry: DirectoryEntry) -> bytes:
        if entry.is_directory:
            raise IsADirectoryError(entry.name)
        if entry.file_size == 0:
            return b""
        if entry.first_cluster == 0:
            raise FATXFormatError(
                f"File {entry.name} non vuoto senza first cluster"
            )

        remaining = entry.file_size
        data = bytearray()
        for cluster in self.get_chain(entry.first_cluster):
            chunk = self.read_cluster(cluster)
            take = min(remaining, len(chunk))
            data.extend(chunk[:take])
            remaining -= take
            if remaining == 0:
                break
        if remaining:
            raise FATXFormatError(
                f"File {entry.name} più grande della catena FAT"
            )
        return bytes(data)

    def is_cluster_free(self, cluster: int) -> bool:
        if cluster < 1 or cluster > self.header.data_cluster_count:
            return False
        return self.read_fat_entry(cluster) == 0

    def iter_free_clusters(
        self,
        *,
        exclude: Optional[Set[int]] = None,
    ) -> Iterator[int]:
        """Yield cluster dati con FAT=0 (liberi)."""

        blocked = exclude or set()
        for cluster in range(1, self.header.data_cluster_count + 1):
            if cluster in blocked:
                continue
            if self.read_fat_entry(cluster) == 0:
                yield cluster

    def find_free_clusters(
        self,
        count: int,
        *,
        exclude: Optional[Set[int]] = None,
    ) -> List[int]:
        """Trova ``count`` cluster liberi senza modificarli."""

        if count <= 0:
            raise ValueError("count deve essere > 0")
        found: List[int] = []
        for cluster in self.iter_free_clusters(exclude=exclude):
            found.append(cluster)
            if len(found) >= count:
                return found
        raise FATXBoundsError(
            f"Cluster FATX liberi insufficienti: servono {count}, "
            f"ne ho {len(found)}"
        )

    def fat_entry_offset(self, cluster: int) -> int:
        if cluster < 0 or cluster >= self.header.max_clusters:
            raise FATXBoundsError(f"Cluster FAT fuori range: {cluster}")
        return self.header.fat_offset + cluster * self.header.fat_entry_size

    def encode_fat_entry(self, value: int) -> bytes:
        return int(value).to_bytes(self.header.fat_entry_size, "little")

    def find_directory_slot(
        self,
        directory_first_cluster: int,
    ) -> Tuple[int, int]:
        """Trova uno slot dirent scrivibile (libero, deleted, o prima di END).

        Restituisce ``(guest_offset, directory_cluster)``.
        Non estende la directory: se è piena solleva ``FATXBoundsError``.
        """

        for directory_cluster in self.get_chain(directory_first_cluster):
            cluster_data = self.read_cluster(directory_cluster)
            cluster_guest_offset = self.cluster_offset(directory_cluster)
            for entry_offset in range(0, len(cluster_data), FATX_DIRENT_SIZE):
                marker = cluster_data[entry_offset]
                guest_offset = cluster_guest_offset + entry_offset
                if marker in (
                    FATX_DIRENT_NEVER_USED,
                    FATX_DIRENT_END,
                    FATX_DIRENT_DELETED,
                ):
                    return guest_offset, directory_cluster
        raise FATXBoundsError(
            f"Nessuno slot libero nella directory "
            f"(first_cluster={directory_first_cluster})"
        )

    def collect_title_clusters(self, title_id: str) -> Set[int]:
        """Cluster dati usati da un Title ID in UDATA (e solo quelli)."""

        normalized = title_id.strip().lower()
        root = self.header.root_dir_first_cluster
        area = self.find_child(root, "UDATA")
        if area is None or not area.is_directory:
            return set()
        game = self.find_child(area.first_cluster, normalized)
        if game is None:
            game = self.find_child(area.first_cluster, title_id)
        if game is None or not game.is_directory:
            return set()

        clusters: Set[int] = set(self.get_chain(game.first_cluster))
        for item in self.walk(
            first_cluster=game.first_cluster,
            base_path=normalized,
        ):
            if item.entry.first_cluster > 0:
                clusters.update(self.get_chain(item.entry.first_cluster))
        return clusters


def discover_fatx_volumes(
    device: BlockDevice,
    names: Sequence[str] = ("X", "Y", "Z", "C", "E"),
) -> Dict[str, FATXVolume]:
    """Apre solo le partizioni che contengono davvero una magic FATX."""

    volumes: Dict[str, FATXVolume] = {}
    for name in names:
        partition = get_region(name)
        if partition.end > device.size:
            continue
        try:
            magic = device.read_at(partition.offset, 4)
        except UnsupportedQCOW2Feature:
            continue
        if magic != b"FATX":
            continue
        volumes[name] = FATXVolume(device, partition)
    return volumes


def _is_valid_fatx_name(name: bytes) -> bool:
    if not name or name in (b".", b".."):
        return False
    invalid_ascii = set(b'"*+,/:;<=>?\\|')
    return all(byte >= 0x20 and byte not in invalid_ascii for byte in name)


def _align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("L'allineamento deve essere una potenza di due")
    return (value + alignment - 1) & ~(alignment - 1)
