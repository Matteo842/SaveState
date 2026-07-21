"""Safety checks for copies and writes on the active HDD."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Set, Union

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - fallback without dependency
    psutil = None


PathLike = Union[str, Path]


class SafetyError(Exception):
    """Operation blocked by a safety check."""


@dataclass(frozen=True)
class CopyReport:
    source: Path
    destination: Path
    bytes_copied: int
    sha256: str


def normalize_path(path: PathLike) -> str:
    return str(Path(path).resolve()).replace("/", "\\").casefold()


def is_same_path(left: PathLike, right: PathLike) -> bool:
    return normalize_path(left) == normalize_path(right)


def assert_not_golden(
    path: PathLike,
    backup_folder: PathLike,
    extra_protected: Optional[Iterable[PathLike]] = None,
) -> None:
    """Block destructive writes/copies on golden archive images."""

    target = Path(path).resolve()
    folder = Path(backup_folder).resolve()
    protected: Set[str] = set()
    if folder.is_dir():
        for child in folder.iterdir():
            if child.is_file() and child.suffix.casefold() == ".qcow2":
                protected.add(normalize_path(child))
    if extra_protected:
        for item in extra_protected:
            protected.add(normalize_path(item))

    if normalize_path(target) in protected:
        raise SafetyError(
            f"Protected path (golden/archive): {target}"
        )
    try:
        if folder in target.parents or target == folder:
            raise SafetyError(
                f"Operation inside golden folder forbidden: {target}"
            )
    except OSError:
        pass


def find_xemu_processes() -> list[str]:
    """Return running xemu emulator processes."""

    matches: list[str] = []
    if psutil is not None:
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                name = (proc.info.get("name") or "")
                exe = (proc.info.get("exe") or "")
            except (psutil.Error, TypeError):
                continue
            stem = Path(name).stem.casefold()
            exe_name = Path(exe).name.casefold()
            if stem == "xemu" or exe_name == "xemu.exe":
                matches.append(name or exe_name)
        return matches

    if os.name == "nt":
        try:
            import subprocess

            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.splitlines():
                if "xemu.exe" in line.casefold():
                    matches.append("xemu.exe")
        except OSError:
            pass
    return matches


def assert_path_writable(path: PathLike) -> None:
    """Verify the target file exists and is not read-only."""

    target = Path(path)
    if not target.is_file():
        raise SafetyError(f"HDD missing: {target}")
    if not os.access(target, os.W_OK):
        raise SafetyError(f"HDD not writable (read-only?): {target}")
    if os.name == "nt":
        import stat as stat_mod

        if not (target.stat().st_mode & stat_mod.S_IWRITE):
            raise SafetyError(f"HDD not writable (read-only?): {target}")


def assert_xemu_closed() -> None:
    running = find_xemu_processes()
    if running:
        raise SafetyError(
            "xemu appears to be running ("
            + ", ".join(sorted(set(running)))
            + "). Close it before copying or writing the HDD."
        )


def sha256_file(path: PathLike) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def atomic_copy_qcow2(
    source: PathLike,
    destination: PathLike,
    backup_folder: PathLike,
) -> CopyReport:
    """Copy source → destination with temp file, replace, and hash verify.

    The golden (`source`) stays open read-only at the OS copy level.
    The destination must not lie inside the golden archive.
    """

    src = Path(source).resolve()
    dst = Path(destination).resolve()
    if not src.is_file():
        raise SafetyError(f"Source missing: {src}")
    if is_same_path(src, dst):
        raise SafetyError("Source and destination are the same")

    assert_not_golden(dst, backup_folder, extra_protected=[src])
    assert_xemu_closed()

    src_hash = sha256_file(src)
    dst.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=dst.name + ".",
        suffix=".partial",
        dir=str(dst.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copyfile(src, temp_path, follow_symlinks=True)
        temp_hash = sha256_file(temp_path)
        if temp_hash != src_hash:
            raise SafetyError(
                "Temporary copy hash does not match source"
            )
        os.replace(temp_path, dst)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise

    dst_hash = sha256_file(dst)
    if dst_hash != src_hash:
        raise SafetyError(
            "Destination hash does not match after replace"
        )

    return CopyReport(
        source=src,
        destination=dst,
        bytes_copied=src.stat().st_size,
        sha256=dst_hash,
    )


def rollback_active_from_golden(
    golden: PathLike,
    active: PathLike,
    backup_folder: PathLike,
) -> CopyReport:
    """Restore the active HDD by re-copying the golden (same atomic procedure)."""

    return atomic_copy_qcow2(golden, active, backup_folder)
