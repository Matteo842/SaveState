# update_manager.py
# -*- coding: utf-8 -*-
"""
Cross-platform in-app updater for SaveState.

Design constraints honoured:
- No network activity unless the user opts in ("check_updates_on_startup").
- No admin/root privileges required: the swap is performed via a helper
  script spawned at exit, which only touches files the running user owns.
- Updates are driven exclusively by GitHub Releases (stable tagged builds).
  Commits / branches / pre-releases are ignored, so the author can push
  experimental work to `main` without triggering updates.
- Supported install layouts (see detect_install_type):
    * "frozen"  - Nuitka / PyInstaller binary (onefile .exe or onefolder .zip).
                  Linux .AppImage / .tar.gz also handled here.
    * "source"  - running from source (`python main.py`). The updater pulls
                  the GitHub-generated source zipball and overlays it on
                  the project root, then restarts the interpreter.
    * "managed" - Flatpak / Snap / read-only install. Download works, but
                  auto-install is refused and the user gets a GitHub link.

Threading model:
- UpdateManager is a QObject living on the GUI thread. It owns two
  QThread workers (check / download). The download worker survives the
  UpdateDialog being closed, so progress keeps going while the UI is
  hidden. The dialog is just a view on UpdateManager's state.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from typing import Optional

import requests
from PySide6.QtCore import QObject, QThread, Signal, Slot

import config


# --- Public state strings (also used as UI hints) ---
STATE_IDLE = "idle"
STATE_CHECKING = "checking"
STATE_UP_TO_DATE = "up_to_date"
STATE_UPDATE_AVAILABLE = "update_available"
STATE_DOWNLOADING = "downloading"
STATE_DOWNLOADED = "downloaded"
STATE_ERROR = "error"
STATE_UNSUPPORTED = "unsupported"


# --- Install type enum (plain strings to keep signals simple) ---
INSTALL_SOURCE = "source"
INSTALL_FROZEN = "frozen"
INSTALL_MANAGED = "managed"


# Captured at import time so that later argv mutation (e.g. by Qt, tests,
# or our own code) can't break the "restart the same command" logic in
# source mode.
_ORIGINAL_ARGV = list(sys.argv)
_ORIGINAL_PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Install layout detection
# ---------------------------------------------------------------------------

def _is_frozen() -> bool:
    """True when running from a packaged binary (Nuitka / PyInstaller)."""
    if getattr(sys, "frozen", False):
        return True
    try:
        import builtins  # noqa: WPS433
        if hasattr(builtins, "__compiled__"):
            return True
    except Exception:
        pass
    return "__compiled__" in globals()


def _get_executable_path() -> str:
    """Path of the on-disk executable for frozen builds.

    Several special cases must be handled:

    - Linux AppImage: ``APPIMAGE`` env var points to the outer .AppImage
      the user launched. ``sys.executable`` would point inside the mounted
      AppImage filesystem, which is read-only.
    - Nuitka one-file: at runtime Nuitka extracts the program into a
      ``%TEMP%\\onefile_xxxxx\\`` directory and ``sys.executable`` /
      ``sys.argv[0]`` point INTO that temp dir (which gets wiped when the
      process exits). Replacing files there is useless because the user's
      actual .exe lives elsewhere. Nuitka exposes the real path through
      the ``NUITKA_ONEFILE_BINARY`` env var.
    - PyInstaller: ``sys.executable`` already points to the real exe (the
      extraction dir is in ``sys._MEIPASS`` and is separate), so the
      fallback works as-is.
    """
    appimage = os.environ.get("APPIMAGE")
    if appimage and os.path.isfile(appimage):
        return appimage
    nuitka_binary = os.environ.get("NUITKA_ONEFILE_BINARY")
    if nuitka_binary and os.path.isfile(nuitka_binary):
        return nuitka_binary
    return os.path.abspath(sys.executable)


def _get_source_project_root() -> str:
    """Best-effort path of the source tree when running `python main.py`."""
    # The module update_manager.py lives in the project root, so its __file__
    # is a very reliable anchor (more so than sys.argv[0], which may be
    # relative or launched from another cwd).
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        if _ORIGINAL_ARGV and _ORIGINAL_ARGV[0]:
            return os.path.dirname(os.path.abspath(_ORIGINAL_ARGV[0]))
        return os.getcwd()


def _is_flatpak() -> bool:
    return bool(os.environ.get("FLATPAK_ID")) or os.path.exists("/.flatpak-info")


def _is_snap() -> bool:
    return bool(os.environ.get("SNAP"))


def _is_on_desktop(path: str) -> bool:
    """Return True if `path` lives inside a folder named "Desktop".

    Matches common Desktop locations on Windows (`%USERPROFILE%\\Desktop`,
    `%OneDrive%\\Desktop`) and Linux (`~/Desktop`, `~/Scrivania`, etc).
    We don't rely on localized folder names — we just pattern-match any
    path component equal to "Desktop" (case-insensitive). That catches the
    practical cases without pulling in OS-specific API.
    """
    try:
        parts = [p.lower() for p in os.path.normpath(path).split(os.sep)]
    except Exception:
        return False
    return "desktop" in parts


def detect_install_type() -> tuple[str, str]:
    """Return (type, reason). `reason` is empty when auto-install is ok."""
    if _is_flatpak():
        return (INSTALL_MANAGED, "Flatpak install (use Flathub to update)")
    if _is_snap():
        return (INSTALL_MANAGED, "Snap install (use snap refresh)")
    if not _is_frozen():
        root = _get_source_project_root()
        if not os.access(root, os.W_OK):
            return (INSTALL_MANAGED, "Source folder is not writable")
        return (INSTALL_SOURCE, "")
    exe = _get_executable_path()
    if not exe or not os.path.isfile(exe):
        return (INSTALL_MANAGED, "Executable path could not be determined")
    target_dir = os.path.dirname(exe) or "."
    if not os.access(target_dir, os.W_OK):
        return (INSTALL_MANAGED, "Install folder is not writable (system install?)")
    if os.path.isfile(exe) and not os.access(exe, os.W_OK):
        return (INSTALL_MANAGED, "Executable file is not writable")
    return (INSTALL_FROZEN, "")


# Backwards-compatible alias. True when we can replace files in place.
def is_swap_supported() -> tuple[bool, str]:
    it, reason = detect_install_type()
    return (it != INSTALL_MANAGED, reason)


def is_updater_supported() -> tuple[bool, str]:
    return is_swap_supported()


# ---------------------------------------------------------------------------
# Asset picker
# ---------------------------------------------------------------------------

def _pick_release_asset(release: dict, install_type: str) -> Optional[dict]:
    """Pick the right asset from a GitHub release.

    - INSTALL_SOURCE  -> synthetic asset pointing at zipball_url.
    - INSTALL_FROZEN  -> Windows: .exe > .zip ; Linux: .AppImage > .tar.gz.
    - INSTALL_MANAGED -> same as frozen (so the user can still download a
                         binary and install it manually).
    """
    if install_type == INSTALL_SOURCE:
        zipball = release.get("zipball_url")
        if not zipball:
            return None
        tag = release.get("tag_name", "latest")
        safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", str(tag))
        return {
            "name": f"source-{safe_tag}.zip",
            "browser_download_url": zipball,
            "size": 0,  # GitHub does not set Content-Length on zipballs reliably
            "_is_source_zipball": True,
        }

    assets = release.get("assets") or []
    sysname = platform.system()

    if sysname == "Windows":
        priority = [r"\.exe$", r"win.*\.zip$", r"\.zip$"]
    elif sysname == "Linux":
        priority = [r"\.AppImage$", r"linux.*\.tar\.gz$", r"\.tar\.gz$", r"linux.*\.zip$"]
    else:
        return None

    candidates = [
        a for a in assets
        if isinstance(a, dict)
        and a.get("name")
        and not a["name"].lower().endswith((".sha256", ".sig", ".asc", ".txt"))
    ]

    for pat in priority:
        rx = re.compile(pat, re.IGNORECASE)
        for a in candidates:
            if rx.search(a["name"]):
                return a
    return None


# ---------------------------------------------------------------------------
# Tag comparison
# ---------------------------------------------------------------------------

def _parse_tag(tag: str) -> list:
    """Parse a tag like 'v2.6c' into a comparable list of (number, letter)
    tuples. Handles all of the variants this project has used historically:

        v2.6    -> [(2, ''), (6, '')]
        v2.6.0  -> [(2, ''), (6, ''), (0, '')]
        v2.6c   -> [(2, ''), (6, 'c')]
        v2.6.b  -> [(2, ''), (6, ''), (0, 'b')]
        v2.7    -> [(2, ''), (7, '')]

    Empty / unparseable input returns an empty list, which the caller
    treats as "I don't know how to compare this".
    """
    if not tag:
        return []
    s = tag.strip().lstrip("vV").strip()
    if not s:
        return []
    parts = []
    for component in s.split("."):
        m = re.match(r"(\d*)([A-Za-z]*)", component)
        if not m:
            return []
        num_str, letters = m.groups()
        if num_str == "" and letters == "":
            return []
        num = int(num_str) if num_str else 0
        parts.append((num, letters.lower()))
    return parts


def _all_default(parts: list, start: int) -> bool:
    """Return True if every component from index `start` is (0, '')."""
    return all(n == 0 and l == "" for n, l in parts[start:])


def _compare_tags(a: str, b: str) -> Optional[int]:
    """Return -1, 0, +1 like cmp(a, b), or None if either tag can't be parsed.

    SaveState versioning convention (per project author):
        - X.Y                    base release
        - X.Y[letter]            small hotfix on top of X.Y (b, c, d, ...)
        - X.Y.Z                  MAJOR fix that comes AFTER all X.Y[letter]
        - X.Y.Z[letter]          small hotfix on top of X.Y.Z

    Resulting ordering example for the 2.6 family:
        2.6 < 2.6b < 2.6c < 2.6.1 < 2.6.1b < 2.6.2 < 2.7

    Implementation:
      - Numeric components compared as integers, position by position.
      - When two components have equal numbers but DIFFERENT letter
        suffixes, we look at whether the side without the letter has
        deeper components after it. If yes, that side wins (".1 beats c").
        If no, the side with the letter wins ("c beats nothing").
      - Trailing (0, '') components are treated as absent so 2.6 == 2.6.0.
    """
    pa = _parse_tag(a)
    pb = _parse_tag(b)
    if not pa or not pb:
        return None
    return _compare_at(pa, pb, 0)


def _compare_at(pa: list, pb: list, i: int) -> int:
    if i >= len(pa) and i >= len(pb):
        return 0
    if i >= len(pa):
        return 0 if _all_default(pb, i) else -1
    if i >= len(pb):
        return 0 if _all_default(pa, i) else 1

    na, la = pa[i]
    nb, lb = pb[i]
    if na != nb:
        return -1 if na < nb else 1
    if la == lb:
        return _compare_at(pa, pb, i + 1)

    # Numbers equal at this position, letters differ.
    if la == "":
        # pa has no letter here. Does it have a meaningful deeper component?
        if i + 1 < len(pa) and not _all_default(pa, i + 1):
            return 1   # deeper component beats a letter hotfix
        return -1      # base release < hotfix release at same level
    if lb == "":
        if i + 1 < len(pb) and not _all_default(pb, i + 1):
            return -1
        return 1
    # Both have letters but they differ — compare alphabetically.
    return -1 if la < lb else 1


def _asset_kind(asset: dict) -> str:
    """Classify an asset: 'source', 'exe', 'zip', 'appimage', 'tar.gz' or 'unknown'."""
    if asset.get("_is_source_zipball"):
        return "source"
    name = (asset.get("name") or "").lower()
    if name.endswith(".exe"):
        return "exe"
    if name.endswith(".appimage"):
        return "appimage"
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return "tar.gz"
    if name.endswith(".zip"):
        return "zip"
    return "unknown"


# ---------------------------------------------------------------------------
# Extraction helpers (run in the GUI-thread BEFORE we spawn the restart
# script; keeps the helper scripts simple and lets us respect the
# Desktop-no-readme rule without involving PowerShell).
# ---------------------------------------------------------------------------

_README_PATTERNS = ("readme", "license", "licence", "copying", "notice", "changelog")


def _is_readme_like(name: str) -> bool:
    base = os.path.basename(name).lower()
    if not base:
        return False
    # Strip extension for the compare
    stem = os.path.splitext(base)[0]
    return stem in _README_PATTERNS or base in _README_PATTERNS


def _extract_zip_to_staging(zip_path: str, staging_dir: str,
                            strip_top_level: bool = False,
                            drop_readmes: bool = False) -> None:
    """Extract a zip file into `staging_dir`, optionally flattening the top
    folder (GitHub zipballs always add one) and filtering README/LICENSE."""
    if os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)
    os.makedirs(staging_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        top_prefix = ""
        if strip_top_level and names:
            first = names[0]
            slash = first.find("/")
            if slash > 0 and all(n.startswith(first[:slash + 1]) or n == first[:slash] for n in names):
                top_prefix = first[:slash + 1]

        for info in zf.infolist():
            raw_name = info.filename
            if not raw_name:
                continue
            rel = raw_name[len(top_prefix):] if top_prefix and raw_name.startswith(top_prefix) else raw_name
            if not rel or rel.endswith("/"):
                # A directory; create later as part of file writes.
                continue
            # Security: never honour absolute paths or parent traversal.
            if rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
                logging.warning(f"Skipping unsafe zip entry: {raw_name!r}")
                continue
            if drop_readmes and _is_readme_like(rel):
                logging.debug(f"Desktop rule: skipping {rel!r}")
                continue
            dest_path = os.path.join(staging_dir, rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with zf.open(info, "r") as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst)


# ---------------------------------------------------------------------------
# Workers (QThread)
# ---------------------------------------------------------------------------

class _CheckWorker(QThread):
    """Calls GitHub Releases API once and emits the result."""
    finished_ok = Signal(dict)
    finished_err = Signal(str)

    def __init__(self, repo: str, parent=None):
        super().__init__(parent)
        self._repo = repo

    def run(self):
        url = f"https://api.github.com/repos/{self._repo}/releases/latest"
        try:
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": f"SaveState-Updater/{config.APP_VERSION}",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 404:
                self.finished_err.emit("No releases published yet")
                return
            resp.raise_for_status()
            self.finished_ok.emit(resp.json())
        except requests.Timeout:
            self.finished_err.emit("Request timed out")
        except requests.ConnectionError:
            self.finished_err.emit("No internet connection")
        except Exception as e:
            self.finished_err.emit(f"Check failed: {e}")


class _DownloadWorker(QThread):
    """Streams a release asset to disk, emitting progress.

    Persists in memory as a member of UpdateManager so closing the dialog
    does NOT cancel the download.
    """
    progress = Signal(int, int)
    finished_ok = Signal(str)
    finished_err = Signal(str)

    def __init__(self, url: str, dest_path: str, expected_size: int = 0, parent=None):
        super().__init__(parent)
        self._url = url
        self._dest = dest_path
        self._expected = expected_size
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        tmp_dest = self._dest + ".part"
        try:
            os.makedirs(os.path.dirname(self._dest), exist_ok=True)
            # Use a permissive Accept so the same code path works for both
            # release asset URLs (which serve octet-stream) and the
            # api.github.com zipball/tarball endpoints (which 415 if you
            # ask for octet-stream explicitly and instead want */* or no
            # Accept header at all).
            headers = {
                "Accept": "*/*",
                "User-Agent": f"SaveState-Updater/{config.APP_VERSION}",
            }
            with requests.get(self._url, headers=headers, stream=True, timeout=30, allow_redirects=True) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", self._expected or 0))
                done = 0
                self.progress.emit(0, total)
                with open(tmp_dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if self._cancel:
                            raise RuntimeError("cancelled")
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        self.progress.emit(done, total)
            os.replace(tmp_dest, self._dest)
            self.finished_ok.emit(self._dest)
        except Exception as e:
            try:
                if os.path.exists(tmp_dest):
                    os.remove(tmp_dest)
            except Exception:
                pass
            if str(e) == "cancelled":
                self.finished_err.emit("Download cancelled")
            else:
                self.finished_err.emit(f"Download failed: {e}")


# ---------------------------------------------------------------------------
# UpdateManager (singleton-ish, owned by MainWindow)
# ---------------------------------------------------------------------------

class UpdateManager(QObject):
    """Coordinates update check, download and apply. GUI-thread object."""

    state_changed = Signal(str)
    update_available = Signal(dict)
    progress = Signal(int, int)
    error = Signal(str)
    download_ready = Signal(str)

    def __init__(self, repo: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._repo = repo or getattr(config, "GITHUB_REPO", "")
        self._state: str = STATE_IDLE
        self._release: Optional[dict] = None
        self._asset: Optional[dict] = None
        self._downloaded_path: Optional[str] = None
        self._last_error: str = ""
        self._bytes_done: int = 0
        self._bytes_total: int = 0
        self._check_worker: Optional[_CheckWorker] = None
        self._dl_worker: Optional[_DownloadWorker] = None

        self._install_type, self._install_reason = detect_install_type()
        if self._install_type == INSTALL_MANAGED:
            logging.info(
                f"UpdateManager: auto-install disabled ({self._install_reason}). "
                "Update check and download remain available."
            )
        else:
            try:
                if self._install_type == INSTALL_FROZEN:
                    target = _get_executable_path()
                else:
                    target = _get_source_project_root()
                logging.info(
                    f"UpdateManager: install_type={self._install_type}, "
                    f"target={target}"
                )
            except Exception:
                logging.info(f"UpdateManager: install_type={self._install_type}")

    # --- Public getters ---
    @property
    def state(self) -> str:
        return self._state

    @property
    def release(self) -> Optional[dict]:
        return self._release

    @property
    def asset(self) -> Optional[dict]:
        return self._asset

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def progress_tuple(self) -> tuple[int, int]:
        return (self._bytes_done, self._bytes_total)

    @property
    def downloaded_path(self) -> Optional[str]:
        return self._downloaded_path

    @property
    def install_type(self) -> str:
        return self._install_type

    def is_supported(self) -> bool:
        return True

    def can_auto_install(self) -> bool:
        return self._install_type in (INSTALL_FROZEN, INSTALL_SOURCE)

    def swap_unsupported_reason(self) -> str:
        return self._install_reason

    # --- State helpers ---
    def _set_state(self, new_state: str):
        if new_state == self._state:
            return
        self._state = new_state
        logging.debug(f"UpdateManager state -> {new_state}")
        self.state_changed.emit(new_state)

    # --- Check ---
    def check_async(self):
        if self._state in (STATE_CHECKING, STATE_DOWNLOADING):
            return
        if not self._repo:
            self._last_error = "GitHub repo not configured"
            self._set_state(STATE_ERROR)
            self.error.emit(self._last_error)
            return
        self._set_state(STATE_CHECKING)
        self._check_worker = _CheckWorker(self._repo, parent=self)
        self._check_worker.finished_ok.connect(self._on_check_ok)
        self._check_worker.finished_err.connect(self._on_check_err)
        self._check_worker.start()

    @Slot(dict)
    def _on_check_ok(self, release: dict):
        try:
            tag = str(release.get("tag_name", "")).strip()
            current_tag = str(getattr(config, "APP_RELEASE_TAG", "")).strip()
            if not tag:
                self._last_error = "Release missing tag_name"
                self._set_state(STATE_ERROR)
                self.error.emit(self._last_error)
                return
            # Decide whether the GitHub release is actually newer.
            # Exact match -> up to date, fast path.
            # Otherwise try a structured numeric comparison; only consider
            # the release "newer" when we can prove it. If parsing fails
            # for either tag, fall back to "different = update available"
            # so the user is at least notified.
            if tag == current_tag:
                self._set_state(STATE_UP_TO_DATE)
                return
            cmp = _compare_tags(current_tag, tag)
            if cmp is not None:
                if cmp >= 0:
                    logging.info(
                        f"UpdateManager: current tag {current_tag!r} >= "
                        f"latest {tag!r}, treating as up to date."
                    )
                    self._set_state(STATE_UP_TO_DATE)
                    return
            else:
                logging.warning(
                    f"UpdateManager: could not parse tags for comparison "
                    f"(current={current_tag!r}, latest={tag!r}); falling "
                    "back to 'different means update'."
                )
            asset = _pick_release_asset(release, self._install_type)
            if not asset:
                self._last_error = f"No compatible asset in release {tag}"
                self._set_state(STATE_ERROR)
                self.error.emit(self._last_error)
                return
            self._release = release
            self._asset = asset
            self._set_state(STATE_UPDATE_AVAILABLE)
            self.update_available.emit(release)
        finally:
            self._check_worker = None

    @Slot(str)
    def _on_check_err(self, msg: str):
        self._last_error = msg
        self._set_state(STATE_ERROR)
        self.error.emit(msg)
        self._check_worker = None

    # --- Download ---
    def start_download(self):
        if self._state in (STATE_DOWNLOADING, STATE_DOWNLOADED):
            return
        if self._state != STATE_UPDATE_AVAILABLE or not self._asset:
            logging.warning("UpdateManager.start_download called with no asset")
            return
        url = self._asset.get("browser_download_url")
        name = self._asset.get("name", "update.bin")
        size = int(self._asset.get("size", 0) or 0)
        if not url:
            self._last_error = "Asset has no download URL"
            self._set_state(STATE_ERROR)
            self.error.emit(self._last_error)
            return
        tmp_dir = os.path.join(tempfile.gettempdir(), "savestate_update")
        dest = os.path.join(tmp_dir, name)
        self._bytes_done = 0
        self._bytes_total = size
        self._set_state(STATE_DOWNLOADING)
        self._dl_worker = _DownloadWorker(url, dest, size, parent=self)
        self._dl_worker.progress.connect(self._on_dl_progress)
        self._dl_worker.finished_ok.connect(self._on_dl_ok)
        self._dl_worker.finished_err.connect(self._on_dl_err)
        self._dl_worker.start()

    def cancel_download(self):
        if self._dl_worker is not None:
            self._dl_worker.cancel()

    @Slot(int, int)
    def _on_dl_progress(self, done: int, total: int):
        self._bytes_done = done
        self._bytes_total = total
        self.progress.emit(done, total)

    @Slot(str)
    def _on_dl_ok(self, path: str):
        self._downloaded_path = path
        self._set_state(STATE_DOWNLOADED)
        self.download_ready.emit(path)
        self._dl_worker = None

    @Slot(str)
    def _on_dl_err(self, msg: str):
        self._last_error = msg
        self._set_state(STATE_UPDATE_AVAILABLE)
        self.error.emit(msg)
        self._dl_worker = None

    # --- Apply ---
    def apply_and_restart(self) -> bool:
        if self._state != STATE_DOWNLOADED or not self._downloaded_path:
            logging.warning("apply_and_restart called in wrong state")
            return False
        if not self.can_auto_install():
            self._last_error = (
                f"Cannot auto-install on this install: {self._install_reason}. "
                "Please install the downloaded file manually."
            )
            self._set_state(STATE_ERROR)
            self.error.emit(self._last_error)
            return False

        try:
            asset = self._asset or {}
            kind = _asset_kind(asset)
            downloaded = self._downloaded_path

            if self._install_type == INSTALL_SOURCE:
                return self._apply_source(downloaded)

            # Frozen install
            exe_path = _get_executable_path()
            logging.info(
                f"Update apply: install_type=frozen, kind={kind}, "
                f"target_exe={exe_path}, downloaded={downloaded}"
            )
            if platform.system() == "Windows":
                return self._apply_frozen_windows(exe_path, downloaded, kind)
            return self._apply_frozen_linux(exe_path, downloaded, kind)
        except Exception as e:
            logging.exception("apply_and_restart failed")
            self._last_error = f"Apply failed: {e}"
            self._set_state(STATE_ERROR)
            self.error.emit(self._last_error)
            return False

    # ------------------------------------------------------------------
    # Source apply (runs `python main.py` updater)
    # ------------------------------------------------------------------

    def _apply_source(self, zip_path: str) -> bool:
        project_root = _get_source_project_root()
        tmp_root = os.path.join(tempfile.gettempdir(), "savestate_update")
        staging = os.path.join(tmp_root, "staging_source")

        logging.info(f"Source update: extracting {zip_path} -> {staging}")
        _extract_zip_to_staging(zip_path, staging, strip_top_level=True, drop_readmes=False)
        return self._spawn_copy_and_restart(
            staging=staging,
            target_dir=project_root,
            restart_cmd=self._build_source_restart_cmd(),
            cleanup_paths=[zip_path, staging],
        )

    def _build_source_restart_cmd(self) -> list[str]:
        """Return argv list used to relaunch `python main.py` after update."""
        argv = [_ORIGINAL_PYTHON] + list(_ORIGINAL_ARGV)
        # argv[0] may be relative ("main.py"); make it absolute against the
        # project root so the helper script can cd anywhere safely.
        if len(argv) >= 2:
            a0 = argv[1]
            if a0 and not os.path.isabs(a0):
                argv[1] = os.path.join(_get_source_project_root(), a0)
        return argv

    # ------------------------------------------------------------------
    # Frozen apply: Windows
    # ------------------------------------------------------------------

    def _apply_frozen_windows(self, exe_path: str, downloaded: str, kind: str) -> bool:
        if kind == "exe":
            return self._spawn_exe_swap_windows(exe_path, downloaded)
        if kind == "zip":
            install_dir = os.path.dirname(exe_path)
            staging = os.path.join(os.path.dirname(downloaded), "staging_frozen")
            drop_readmes = _is_on_desktop(install_dir)
            logging.info(
                f"Frozen zip update: extract={downloaded} -> {staging} "
                f"(drop_readmes={drop_readmes}, install_dir={install_dir})"
            )
            _extract_zip_to_staging(downloaded, staging,
                                     strip_top_level=False, drop_readmes=drop_readmes)
            return self._spawn_copy_and_restart(
                staging=staging,
                target_dir=install_dir,
                restart_cmd=[exe_path],
                cleanup_paths=[downloaded, staging],
            )
        self._last_error = f"Unsupported asset type for Windows: {kind}"
        self._set_state(STATE_ERROR)
        self.error.emit(self._last_error)
        return False

    def _spawn_exe_swap_windows(self, exe_path: str, new_file: str) -> bool:
        tmp_dir = os.path.dirname(new_file)
        bat_path = os.path.join(tmp_dir, "savestate_update.bat")
        log_path = os.path.join(tmp_dir, "savestate_update.log")
        pid = os.getpid()
        script = f"""@echo off
setlocal EnableDelayedExpansion
set "TARGET={exe_path}"
set "SRC={new_file}"
set "LOG={log_path}"
echo [%date% %time%] Update starting > "%LOG%"
echo TARGET=%TARGET% >> "%LOG%"
echo SRC=%SRC% >> "%LOG%"
echo Waiting for PID {pid} to exit... >> "%LOG%"
set /a waits=0
:wait_loop
tasklist /NH /FI "PID eq {pid}" 2>nul | find /I "{pid}" >nul
if not errorlevel 1 (
    set /a waits+=1
    if !waits! geq 60 (
        echo PID {pid} did not exit within 60 seconds, giving up. >> "%LOG%"
        goto fail
    )
    timeout /t 1 /nobreak >nul
    goto wait_loop
)
rem PyInstaller bootloader can keep the .exe locked for a moment after the
rem Python process exits. Sleep a couple of seconds before swapping.
timeout /t 2 /nobreak >nul
set /a tries=0
:move_loop
move /y "%SRC%" "%TARGET%" >> "%LOG%" 2>&1
if errorlevel 1 (
    set /a tries+=1
    if !tries! lss 30 (
        timeout /t 1 /nobreak >nul
        goto move_loop
    )
    echo MOVE failed after %tries% retries. >> "%LOG%"
    goto fail
)
echo [%date% %time%] Move OK, restarting %TARGET% >> "%LOG%"
start "" "%TARGET%"
del "%~f0"
exit /b 0
:fail
echo [%date% %time%] Update FAILED. >> "%LOG%"
echo SaveState update failed.
echo See log file: %LOG%
echo.
pause
exit /b 1
"""
        with open(bat_path, "w", encoding="ascii", errors="replace") as f:
            f.write(script)
        logging.info(f"Update bat written to {bat_path} (log will be at {log_path})")
        _spawn_detached_windows(["cmd.exe", "/c", bat_path])
        self._set_state(STATE_IDLE)
        return True

    def _spawn_copy_and_restart(self, staging: str, target_dir: str,
                                 restart_cmd: list[str],
                                 cleanup_paths: list[str]) -> bool:
        """Write a platform helper script that copies `staging` onto
        `target_dir` with overlay semantics, then runs `restart_cmd`.
        The script waits for the current PID to exit first."""
        import subprocess
        tmp_dir = os.path.dirname(staging)
        pid = os.getpid()

        if platform.system() == "Windows":
            bat_path = os.path.join(tmp_dir, "savestate_update.bat")
            log_path = os.path.join(tmp_dir, "savestate_update.log")
            restart_line = _windows_start_cmd(restart_cmd)
            cleanup_lines = "\n".join(
                f'rmdir /s /q "{p}" 2>nul\r\ndel /q "{p}" 2>nul' for p in cleanup_paths
            )
            # robocopy exit codes: 0..7 are success-ish, >=8 are real errors.
            # /R:30 /W:1 = up to 30 retries with 1s wait (~30s window) which
            # is generous enough to ride out the PyInstaller bootloader keeping
            # the .exe locked for a moment after our PID exits.
            script = f"""@echo off
setlocal EnableDelayedExpansion
set "STAGING={staging}"
set "TARGET={target_dir}"
set "LOG={log_path}"
echo [%date% %time%] Update starting > "%LOG%"
echo STAGING=%STAGING% >> "%LOG%"
echo TARGET=%TARGET% >> "%LOG%"
echo Waiting for PID {pid} to exit... >> "%LOG%"
set /a waits=0
:wait_loop
tasklist /NH /FI "PID eq {pid}" 2>nul | find /I "{pid}" >nul
if not errorlevel 1 (
    set /a waits+=1
    if !waits! geq 60 (
        echo PID {pid} did not exit within 60 seconds, giving up. >> "%LOG%"
        goto fail
    )
    timeout /t 1 /nobreak >nul
    goto wait_loop
)
rem PyInstaller bootloader can keep the .exe locked for a moment after the
rem Python process exits. Sleep a couple of seconds before robocopy.
timeout /t 2 /nobreak >nul
echo [%date% %time%] Running robocopy... >> "%LOG%"
robocopy "%STAGING%" "%TARGET%" /E /R:30 /W:1 >> "%LOG%" 2>&1
set RC=!ERRORLEVEL!
echo robocopy exit code: !RC! >> "%LOG%"
rem robocopy returns 0..7 for success, >=8 for real errors. The parens in
rem the echo MUST be escaped with ^^ otherwise cmd.exe miscounts the IF
rem block's parens and makes goto fail run unconditionally.
if !RC! GEQ 8 (
    echo robocopy failed ^(exit code !RC!^) >> "%LOG%"
    goto fail
)
echo [%date% %time%] Cleanup... >> "%LOG%"
{cleanup_lines}
echo [%date% %time%] Restarting... >> "%LOG%"
{restart_line}
del "%~f0"
exit /b 0
:fail
echo [%date% %time%] Update FAILED. >> "%LOG%"
echo SaveState update failed.
echo See log file: %LOG%
echo.
pause
exit /b 1
"""
            with open(bat_path, "w", encoding="ascii", errors="replace") as f:
                f.write(script)
            logging.info(f"Update bat written to {bat_path} (log will be at {log_path})")
            _spawn_detached_windows(["cmd.exe", "/c", bat_path])
            self._set_state(STATE_IDLE)
            return True

        # Linux / macOS
        sh_path = os.path.join(tmp_dir, "savestate_update.sh")
        restart_line = _posix_restart_cmd(restart_cmd)
        cleanup_lines = "\n".join(f'rm -rf -- "{p}"' for p in cleanup_paths)
        script = f"""#!/bin/sh
set -e
STAGING="{staging}"
TARGET="{target_dir}"
PID={pid}
while kill -0 "$PID" 2>/dev/null; do
    sleep 1
done
# Overlay copy: preserve files in TARGET that don't exist in STAGING.
cp -a "$STAGING"/. "$TARGET"/
{cleanup_lines}
{restart_line}
rm -- "$0"
"""
        with open(sh_path, "w", encoding="utf-8") as f:
            f.write(script)
        st = os.stat(sh_path)
        os.chmod(sh_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP)
        subprocess.Popen(
            ["/bin/sh", sh_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        self._set_state(STATE_IDLE)
        return True

    # ------------------------------------------------------------------
    # Frozen apply: Linux (AppImage / tar.gz)
    # ------------------------------------------------------------------

    def _apply_frozen_linux(self, exe_path: str, downloaded: str, kind: str) -> bool:
        import subprocess
        tmp_dir = os.path.dirname(downloaded)
        sh_path = os.path.join(tmp_dir, "savestate_update.sh")
        pid = os.getpid()

        if kind in ("appimage", "exe"):
            script = f"""#!/bin/sh
set -e
TARGET="{exe_path}"
SRC="{downloaded}"
PID={pid}
while kill -0 "$PID" 2>/dev/null; do
    sleep 1
done
tries=0
while ! mv -f "$SRC" "$TARGET"; do
    tries=$((tries+1))
    if [ "$tries" -ge 15 ]; then
        exit 1
    fi
    sleep 1
done
chmod +x "$TARGET" || true
( nohup "$TARGET" >/dev/null 2>&1 & ) >/dev/null 2>&1
rm -- "$0"
"""
        elif kind in ("zip", "tar.gz"):
            install_dir = os.path.dirname(exe_path)
            staging = os.path.join(tmp_dir, "staging_frozen")
            drop_readmes = _is_on_desktop(install_dir)
            if kind == "zip":
                _extract_zip_to_staging(downloaded, staging,
                                         strip_top_level=False, drop_readmes=drop_readmes)
            else:
                # tar.gz: extract and optionally remove readmes after
                if os.path.isdir(staging):
                    shutil.rmtree(staging, ignore_errors=True)
                os.makedirs(staging, exist_ok=True)
                import tarfile
                with tarfile.open(downloaded, "r:gz") as tf:
                    tf.extractall(staging)
                if drop_readmes:
                    for root, _dirs, files in os.walk(staging):
                        for fn in files:
                            if _is_readme_like(fn):
                                try:
                                    os.remove(os.path.join(root, fn))
                                except Exception:
                                    pass
            return self._spawn_copy_and_restart(
                staging=staging,
                target_dir=install_dir,
                restart_cmd=[exe_path],
                cleanup_paths=[downloaded, staging],
            )
        else:
            self._last_error = f"Unsupported asset type for Linux: {kind}"
            self._set_state(STATE_ERROR)
            self.error.emit(self._last_error)
            return False

        with open(sh_path, "w", encoding="utf-8") as f:
            f.write(script)
        st = os.stat(sh_path)
        os.chmod(sh_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP)
        subprocess.Popen(
            ["/bin/sh", sh_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        self._set_state(STATE_IDLE)
        return True


# ---------------------------------------------------------------------------
# Small helpers for script generation
# ---------------------------------------------------------------------------

def _shell_quote_windows(s: str) -> str:
    """Conservative quoter for the Windows cmd.exe `start ""` pattern."""
    s = s.replace('"', '""')
    return f'"{s}"'


def _windows_start_cmd(cmd: list[str]) -> str:
    """Build a `start ""` line that launches `cmd` detached."""
    quoted = " ".join(_shell_quote_windows(c) for c in cmd)
    return f'start "" {quoted}'


def _shell_quote_posix(s: str) -> str:
    if not s:
        return "''"
    if all(c.isalnum() or c in "@%+=:,./-_" for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def _posix_restart_cmd(cmd: list[str]) -> str:
    quoted = " ".join(_shell_quote_posix(c) for c in cmd)
    return f"( nohup {quoted} >/dev/null 2>&1 & ) >/dev/null 2>&1"


def _spawn_detached_windows(cmd: list[str]) -> None:
    """Launch the helper script in its own console.

    We intentionally do NOT use CREATE_NO_WINDOW: showing a small console
    window during the swap is the standard updater UX (Discord, Obsidian,
    Telegram, etc. all do this) and is a critical fail-safe — when the
    swap fails, the script ends with `pause` and the user can read the
    error message instead of the update silently doing nothing.
    """
    import subprocess
    CREATE_NEW_CONSOLE = 0x00000010
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        cmd,
        creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
