"""Nomi display per Title ID Xbox (stessa mappa di single_game_merger)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Union

from .fatx import FATXVolume
from .qcow2 import QCOW2BlockDevice


PathLike = Union[str, Path]

# Copia della mappa usata da single_game_merger.GAME_NAMES (non modificare il merger).
GAME_NAMES = {
    "4c410015": "Mercenaries",
    "5345000f": "ToeJam & Earl III",
    "4d530064": "Halo 2",
    "4541005a": "NFS Underground 2",
    "45410083": "Black",
    "4d53006e": "Forza Motorsport",
}


@dataclass(frozen=True)
class ListedGame:
    title_id: str
    name: str
    area: str
    first_cluster: int


def game_display_name(title_id: str) -> str:
    normalized = title_id.strip().lower()
    return GAME_NAMES.get(normalized, f"Unknown ({normalized})")


def list_games_on_image(
    image_path: PathLike,
    partition: str = "E",
    areas: Sequence[str] = ("UDATA",),
) -> List[ListedGame]:
    """Scansiona Title ID su un QCOW2 in coordinate guest (UDATA di default)."""

    path = Path(image_path)
    games: List[ListedGame] = []
    seen: set[str] = set()
    with QCOW2BlockDevice(path) as device:
        volume = FATXVolume.open_partition(device, partition)
        for game in volume.list_games(areas=areas):
            key = f"{game.area}:{game.title_id}"
            if key in seen:
                continue
            seen.add(key)
            games.append(
                ListedGame(
                    title_id=game.title_id,
                    name=game_display_name(game.title_id),
                    area=game.area,
                    first_cluster=game.entry.first_cluster,
                )
            )
    return games
