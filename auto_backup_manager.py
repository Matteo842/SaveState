"""
auto_backup_manager.py

In-process automatic local backup engine for SaveState.

Runs entirely inside the main application process (no subprocess, no extra
executable) so it stays compatible with single-file Nuitka builds. A single
lightweight QTimer ticks on the GUI thread; the actual backup work is offloaded
to a WorkerThread so the UI never freezes.

The feature relies on the application staying alive in the system tray, exactly
like the cloud periodic sync already does. When at least one profile has
auto-backup enabled, MainWindow keeps running in the tray on close.

Per-profile configuration is stored in the profile dictionary under the
``auto_backup`` key:

    "auto_backup": {
        "enabled": true,
        "mode": "interval_changed" | "interval_fixed" | "process_close",
        "interval_minutes": 60,
        "process_names": ["Game.exe"]
    }

Modes
-----
- interval_changed : every ``interval_minutes``, back up only if the save folder
                     changed since the last backup.
- interval_fixed   : back up every ``interval_minutes`` unconditionally.
- process_close    : back up whenever a watched process transitions from
                     running to not-running (i.e. the game was closed).
"""

import logging
import os
import time
from datetime import datetime

from PySide6.QtCore import QTimer

import core_logic
import backup_runner
import backup_safety
import process_watch_utils
from gui_utils import WorkerThread


# --- Configuration constants ---------------------------------------------
CHECK_INTERVAL_MS = 15000          # How often the timer ticks (15 s).
MIN_BACKUP_COOLDOWN_SEC = 60       # Never auto-back up the same profile more often than this.

# Sentinel prefix used by the worker to report that a backup was intentionally
# skipped because the save was in use (not an error, and not a real backup).
SKIPPED_IN_USE_PREFIX = "SKIPPED_IN_USE:"

MODE_INTERVAL_CHANGED = "interval_changed"
MODE_INTERVAL_FIXED = "interval_fixed"
MODE_PROCESS_CLOSE = "process_close"
VALID_MODES = (MODE_INTERVAL_CHANGED, MODE_INTERVAL_FIXED, MODE_PROCESS_CLOSE)

DEFAULT_INTERVAL_MINUTES = 60


def _default_auto_backup_config() -> dict:
    """Return a fresh default auto-backup config dict (disabled)."""
    return {
        "enabled": False,
        "mode": MODE_PROCESS_CLOSE,
        "interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "process_names": [],
    }


def _do_silent_backup(profile_name, paths=None):
    """Worker entry point. Returns (success, message) for WorkerThread.

    Runs on a WorkerThread (never the GUI thread), so the blocking quiescence
    check below is safe. If the save is being actively written, the backup is
    skipped instead of capturing a corrupt, half-written save.
    """
    try:
        # Safety gate: never archive a save while an app is writing it.
        try:
            safe = backup_safety.wait_for_quiescence(paths, profile_name=profile_name)
        except Exception as e_safe:
            # A failure in the safety check itself must not silently allow an
            # unsafe backup: be conservative and skip.
            logging.error(
                f"Auto-backup safety check errored for '{profile_name}': {e_safe}",
                exc_info=True,
            )
            return False, f"{SKIPPED_IN_USE_PREFIX}{profile_name}"
        if not safe:
            return False, f"{SKIPPED_IN_USE_PREFIX}{profile_name}"

        ok = backup_runner.run_silent_backup(profile_name)
        if ok:
            return True, f"Auto-backup completed: {profile_name}"
        return False, f"Auto-backup failed: {profile_name}"
    except Exception as e:
        logging.error(f"Auto-backup worker error for '{profile_name}': {e}", exc_info=True)
        return False, f"Auto-backup error for {profile_name}: {e}"


class AutoBackupManager:
    """Manages the automatic local backup timer and its per-profile state."""

    def __init__(self, main_window):
        self.main_window = main_window
        self._timer: QTimer | None = None
        self._started = False
        self._busy = False
        self._worker: WorkerThread | None = None
        self._active_profile: str | None = None

        # name -> resolved config dict ({mode, interval_minutes, process_names, paths, data})
        self._enabled: dict[str, dict] = {}
        # name -> runtime state ({last_trigger, last_check, proc_was_running})
        self._state: dict[str, dict] = {}

        # run_silent_backup creates Qt popups; those must never be built off the
        # GUI thread. Suppress them inside the worker; the manager shows its own
        # notification from the GUI thread instead. This only affects the
        # running GUI process (the --backup CLI runs in a separate process).
        try:
            backup_runner.set_gui_notifications_enabled(False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        """Create the timer and load the current configuration."""
        if self._started:
            return
        self._timer = QTimer(self.main_window)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)
        self._started = True
        logging.info("AutoBackupManager started.")
        self.reload()

    def stop(self):
        if not self._started:
            return
        if self._timer:
            try:
                self._timer.stop()
            except Exception:
                pass
        self._started = False
        logging.info("AutoBackupManager stopped.")

    def reload(self):
        """Re-read auto-backup configuration from the in-memory profiles.

        Safe to call repeatedly (e.g. after a profile is edited/created/deleted).
        """
        if not self._started:
            return

        profiles = getattr(self.main_window, "profiles", None) or {}
        new_enabled: dict[str, dict] = {}

        for name, data in profiles.items():
            if not isinstance(data, dict):
                continue
            cfg = data.get("auto_backup")
            if not isinstance(cfg, dict) or not cfg.get("enabled"):
                continue
            mode = cfg.get("mode")
            if mode not in VALID_MODES:
                mode = MODE_PROCESS_CLOSE
            try:
                interval_minutes = max(1, int(cfg.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)))
            except (TypeError, ValueError):
                interval_minutes = DEFAULT_INTERVAL_MINUTES
            process_names = [
                process_watch_utils.normalize_process_name(p)
                for p in (cfg.get("process_names") or [])
                if isinstance(p, str) and p.strip()
            ]
            process_names = [p for p in process_names if p]

            new_enabled[name] = {
                "mode": mode,
                "interval_minutes": interval_minutes,
                "process_names": process_names,
                "paths": self._paths_for(data),
                "data": data,
            }

        self._enabled = new_enabled

        # Rebuild runtime state, preserving timers for profiles that stayed enabled.
        now = time.monotonic()
        running_names = None
        new_state: dict[str, dict] = {}
        for name, cfg in self._enabled.items():
            st = self._state.get(name, {})
            st.setdefault("last_trigger", now)
            st.setdefault("last_check", now)
            if cfg["mode"] == MODE_PROCESS_CLOSE:
                if running_names is None:
                    running_names = process_watch_utils.list_running_process_names()
                # Initialize so we only fire on a future running -> not-running edge.
                matched = set(cfg["process_names"]) & running_names
                st["proc_was_running"] = bool(matched)
                logging.info(
                    "[AutoBackup] Watching '%s' (process_close): processes=%s, "
                    "currently_running=%s (matched=%s).",
                    name, cfg["process_names"], bool(matched), sorted(matched),
                )
                if not cfg["process_names"]:
                    logging.warning(
                        "[AutoBackup] Profile '%s' uses process_close but has NO "
                        "process names configured; it will never trigger.", name,
                    )
            else:
                # Interval-based modes: the timer only *evaluates* these every
                # ``interval_minutes``, not every tick. Make that explicit so it
                # is obvious why nothing happens right after enabling the profile.
                mode_label = (
                    "on save change" if cfg["mode"] == MODE_INTERVAL_CHANGED
                    else "fixed schedule"
                )
                next_check_min = max(
                    0.0,
                    (cfg["interval_minutes"] * 60 - (now - st["last_check"])) / 60.0,
                )
                logging.info(
                    "[AutoBackup] Watching '%s' (%s): interval=%d min, "
                    "next check in ~%.1f min.",
                    name, mode_label, cfg["interval_minutes"], next_check_min,
                )
            new_state[name] = st
        self._state = new_state

        # Start/stop the timer depending on whether anything is enabled.
        if self._enabled:
            if self._timer and not self._timer.isActive():
                self._timer.start()
            logging.info(f"AutoBackupManager: monitoring {len(self._enabled)} profile(s).")
        else:
            if self._timer and self._timer.isActive():
                self._timer.stop()
            logging.debug("AutoBackupManager: no profiles enabled, timer idle.")

    def is_any_enabled(self) -> bool:
        """True if at least one profile currently has auto-backup enabled.

        Used by MainWindow to decide whether to keep running in the tray.
        """
        return bool(self._enabled)

    # ------------------------------------------------------------------
    # Tick logic
    # ------------------------------------------------------------------
    def _on_tick(self):
        if self._busy or not self._enabled:
            return
        try:
            settings = getattr(self.main_window, "current_settings", {}) or {}
            backup_base_dir = settings.get("backup_base_dir")
            now = time.monotonic()

            # Compute running processes once per tick, only if needed.
            running_names = None

            for name, cfg in self._enabled.items():
                st = self._state.get(name)
                if st is None:
                    continue

                mode = cfg["mode"]
                interval_sec = cfg["interval_minutes"] * 60

                should_backup = False

                if mode == MODE_PROCESS_CLOSE:
                    if not cfg["process_names"]:
                        continue
                    if running_names is None:
                        running_names = process_watch_utils.list_running_process_names()
                    is_running = bool(set(cfg["process_names"]) & running_names)
                    was_running = bool(st.get("proc_was_running"))
                    # Log only on a running-state change to keep the log readable.
                    if is_running != was_running:
                        logging.info(
                            "[AutoBackup] '%s' process state changed: %s -> %s "
                            "(watching %s).",
                            name,
                            "RUNNING" if was_running else "not running",
                            "RUNNING" if is_running else "not running",
                            cfg["process_names"],
                        )
                    if was_running and not is_running:
                        logging.info(
                            "[AutoBackup] '%s' detected game close -> requesting backup.",
                            name,
                        )
                        should_backup = True
                    st["proc_was_running"] = is_running

                elif mode == MODE_INTERVAL_FIXED:
                    if now - st["last_trigger"] >= interval_sec:
                        # Even on a fixed schedule, never create a byte-identical
                        # duplicate: it would only evict an older (possibly more
                        # valuable) backup via rotation. Back up only if the save
                        # actually changed since the last backup.
                        if self._save_changed_since_last_backup(name, cfg, backup_base_dir):
                            logging.info(
                                "[AutoBackup] '%s' fixed interval elapsed (%d min) "
                                "and save changed -> requesting backup.",
                                name, cfg["interval_minutes"],
                            )
                            should_backup = True
                        else:
                            # Nothing changed: re-arm the clock so we wait a full
                            # interval before checking again (instead of every tick).
                            st["last_trigger"] = now
                            logging.info(
                                "[AutoBackup] '%s' fixed interval elapsed but save "
                                "unchanged since last backup -> skipping duplicate.",
                                name,
                            )

                elif mode == MODE_INTERVAL_CHANGED:
                    if now - st["last_check"] >= interval_sec:
                        st["last_check"] = now
                        changed = self._save_changed_since_last_backup(name, cfg, backup_base_dir)
                        logging.info(
                            "[AutoBackup] '%s' change check (every %d min): "
                            "save folder changed since last backup = %s.",
                            name, cfg["interval_minutes"], changed,
                        )
                        if changed:
                            should_backup = True
                    else:
                        remaining_min = (interval_sec - (now - st["last_check"])) / 60.0
                        logging.debug(
                            "[AutoBackup] '%s' next change check in %.1f min.",
                            name, remaining_min,
                        )

                if not should_backup:
                    continue

                # Cooldown guard to avoid rapid repeated backups. It does not
                # apply to process_close: a game-close is a discrete edge that
                # cannot repeat until the game runs again, and the cooldown could
                # otherwise silently swallow a legitimate backup right after the
                # app starts or the profile is re-saved (both reset last_trigger).
                if mode != MODE_PROCESS_CLOSE and now - st["last_trigger"] < MIN_BACKUP_COOLDOWN_SEC:
                    remaining = MIN_BACKUP_COOLDOWN_SEC - (now - st["last_trigger"])
                    logging.info(
                        "[AutoBackup] Backup for '%s' suppressed by cooldown "
                        "(%.0fs remaining).", name, remaining,
                    )
                    continue

                self._trigger_backup(name)
                # Only one backup per tick; the rest are evaluated next tick.
                break
        except Exception as e:
            logging.error(f"AutoBackupManager tick error: {e}", exc_info=True)

    def _save_changed_since_last_backup(self, name, cfg, backup_base_dir) -> bool:
        """True if the save folder is newer than the most recent backup."""
        paths = cfg.get("paths") or []
        if not paths:
            logging.warning(
                "[AutoBackup] '%s' change check: no save paths configured.", name,
            )
            return False
        latest_mtime = self._latest_mtime(paths)
        if latest_mtime <= 0:
            logging.warning(
                "[AutoBackup] '%s' change check: could not read save mtime "
                "(paths missing?). paths=%s", name, paths,
            )
            return False
        try:
            _count, last_dt = core_logic.get_profile_backup_summary(
                name, backup_base_dir, profile_data=cfg.get("data")
            )
        except Exception as e:
            logging.warning(f"AutoBackupManager: backup summary failed for '{name}': {e}")
            last_dt = None

        if last_dt is None:
            # No backup yet -> consider it changed so the first backup is taken.
            logging.info(
                "[AutoBackup] '%s' change check: no previous backup found -> "
                "treating as changed.", name,
            )
            return True
        try:
            save_dt = datetime.fromtimestamp(latest_mtime)
            logging.info(
                "[AutoBackup] '%s' change check: save mtime=%s, last backup=%s.",
                name, save_dt.strftime("%Y-%m-%d %H:%M:%S"),
                last_dt.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return save_dt > last_dt
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Backup execution
    # ------------------------------------------------------------------
    def _trigger_backup(self, profile_name):
        if self._busy:
            return
        self._busy = True
        self._active_profile = profile_name
        logging.info(f"AutoBackupManager: triggering automatic backup for '{profile_name}'.")
        try:
            # Pass the resolved save paths so the worker can run the in-use
            # safety check before archiving anything.
            cfg = self._enabled.get(profile_name) or {}
            paths = list(cfg.get("paths") or [])
            self._worker = WorkerThread(_do_silent_backup, profile_name, paths)
            self._worker.finished.connect(self._on_backup_finished)
            self._worker.start()
        except Exception as e:
            logging.error(f"AutoBackupManager: failed to start backup worker: {e}", exc_info=True)
            self._busy = False
            self._active_profile = None

    def _on_backup_finished(self, success, message):
        name = self._active_profile
        skipped = isinstance(message, str) and message.startswith(SKIPPED_IN_USE_PREFIX)

        # Update trigger time and reset the change-detection clock only when a
        # real backup ran. A skip (save in use) must NOT advance these, so the
        # engine keeps trying on the next tick/interval instead of waiting a
        # full cycle after having produced nothing.
        if not skipped and name and name in self._state:
            self._state[name]["last_trigger"] = time.monotonic()
            self._state[name]["last_check"] = time.monotonic()

        self._busy = False
        self._active_profile = None
        if self._worker is not None:
            try:
                self._worker.finished.disconnect(self._on_backup_finished)
            except Exception:
                pass
            self._worker = None

        # A skipped backup produced nothing: don't refresh "Last backup" and
        # don't raise an error popup (it is not a failure). The safety module
        # has already logged why it was skipped; keep it quiet so it does not
        # interrupt gameplay.
        if skipped:
            logging.info(
                "[AutoBackup] '%s' backup skipped (save in use); will retry.",
                name,
            )
            return

        # Refresh the profile table so "Last backup" updates.
        try:
            ptm = getattr(self.main_window, "profile_table_manager", None)
            if ptm is not None and hasattr(ptm, "update_profile_table"):
                ptm.update_profile_table()
        except Exception:
            pass

        # Show a notification from the GUI thread (safe here).
        try:
            backup_runner.show_notification(bool(success), message, force=True)
        except Exception:
            log_level = logging.INFO if success else logging.ERROR
            logging.log(log_level, f"Auto-backup result: {message}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _paths_for(profile_data: dict) -> list[str]:
        if isinstance(profile_data.get("paths"), list) and profile_data["paths"]:
            return [p for p in profile_data["paths"] if isinstance(p, str) and p]
        p = profile_data.get("path")
        if isinstance(p, str) and p:
            return [p]
        return []

    @staticmethod
    def _latest_mtime(paths) -> float:
        """Most recent modification time across the given files/folders."""
        latest = 0.0
        for p in paths:
            if not p or not os.path.exists(p):
                continue
            try:
                if os.path.isfile(p):
                    latest = max(latest, os.path.getmtime(p))
                    continue
                for root, _dirs, files in os.walk(p):
                    try:
                        latest = max(latest, os.path.getmtime(root))
                    except OSError:
                        pass
                    for f in files:
                        try:
                            latest = max(latest, os.path.getmtime(os.path.join(root, f)))
                        except OSError:
                            pass
            except OSError:
                continue
        return latest
