"""
backup_safety.py

Pre-backup safety checks used by the automatic backup engine to avoid archiving
save files while a game (or any other application) is actively writing them.

Why this matters
----------------
When a save file is being written but is still *readable* (the common case on
Windows/Linux, where games and Steam Cloud keep files opened with shared read
access), ``zipfile`` happily copies whatever bytes are currently on disk. The
resulting archive has a perfectly valid CRC, so neither the backup error handler
nor a post-archive ``testzip`` can detect the problem: the save inside is simply
half-written and therefore corrupt. Restoring it later would give the user a
broken save.

The only robust, portable way to avoid this without game-specific knowledge is
to confirm the save is *quiescent* (its files are not changing) immediately
before archiving, and to refuse to back up otherwise.

Design constraints (safety first)
---------------------------------
- We must NEVER interfere with the game's own writes. Therefore we only call
  ``os.stat`` (read metadata); we never open the save files, and in particular
  never request an exclusive/locking handle. A passive stat cannot cause the
  game to fail a write.
- "In use" is inferred from instability: if any file's size or modification
  time changes across a short settle window, an application is writing and the
  backup is deferred; if the files stay unchanged, the save is considered safe.
"""

import logging
import os
import time

# --- Tunables (seconds) ---------------------------------------------------
# Required period during which nothing under the save paths may change for the
# save to be considered "settled".
DEFAULT_SETTLE_SECONDS = 3.0
# Pause between failed attempts before snapshotting again.
DEFAULT_POLL_SECONDS = 2.0
# Upper bound on how long we wait for the save to settle. If it never settles
# within this window, the caller MUST skip the backup (something keeps writing).
DEFAULT_MAX_WAIT_SECONDS = 45.0


def _iter_files(paths):
    """Yield every regular file under the given files/directories."""
    for p in paths:
        if not p:
            continue
        try:
            if os.path.isfile(p):
                yield p
            elif os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        yield os.path.join(root, f)
        except OSError:
            continue


def snapshot(paths) -> dict:
    """Return ``{file_path: (size, mtime_ns)}`` for all files under ``paths``.

    A file that fails ``stat`` (e.g. it vanished mid-write) is recorded with a
    ``None`` value so that it reads as "unstable" when compared. Files appearing
    or disappearing between snapshots naturally change the set of keys, which is
    also detected as instability.
    """
    snap = {}
    for fp in _iter_files(paths):
        try:
            st = os.stat(fp)
            snap[fp] = (st.st_size, st.st_mtime_ns)
        except OSError:
            snap[fp] = None
    return snap


def wait_for_quiescence(paths,
                        settle_seconds: float = DEFAULT_SETTLE_SECONDS,
                        poll_seconds: float = DEFAULT_POLL_SECONDS,
                        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
                        profile_name: str = "") -> bool:
    """Block until the save files are stable, or until ``max_wait_seconds``.

    Returns
    -------
    bool
        ``True``  -> the save folder is quiescent; it is safe to back up now.
        ``False`` -> the save kept changing (an app is actively writing); the
                     caller MUST NOT create a backup, to avoid archiving a
                     partially-written, corrupt save.

    This function is intentionally conservative: any doubt (files still
    changing, files disappearing) results in ``False``.
    """
    paths = [p for p in (paths or []) if p]
    if not paths:
        # Nothing to protect; let the normal backup validation handle it.
        return True

    settle_seconds = max(0.5, float(settle_seconds))
    max_wait_seconds = max(settle_seconds, float(max_wait_seconds))
    deadline = time.monotonic() + max_wait_seconds

    attempt = 0
    while True:
        attempt += 1
        first = snapshot(paths)
        time.sleep(settle_seconds)
        second = snapshot(paths)

        stable = (first == second) and all(v is not None for v in second.values())
        if stable:
            if attempt > 1:
                logging.info(
                    "[AutoBackup] '%s' save folder settled after %d attempt(s); "
                    "proceeding with backup.", profile_name, attempt,
                )
            return True

        if time.monotonic() >= deadline:
            logging.warning(
                "[AutoBackup] '%s' save files kept changing for ~%.0fs; SKIPPING "
                "backup to avoid archiving a partially-written (corrupt) save.",
                profile_name, max_wait_seconds,
            )
            return False

        logging.info(
            "[AutoBackup] '%s' save files still changing (attempt %d); an app is "
            "writing, deferring backup.", profile_name, attempt,
        )
        time.sleep(max(0.0, float(poll_seconds)))
