# dialogs/update_dialog.py
# -*- coding: utf-8 -*-
"""
Update dialog for SaveState.

This dialog is a *view* on the UpdateManager singleton. Closing it does NOT
cancel a running download: when reopened it syncs immediately to the current
manager state. No background logic lives here.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

import config
from update_manager import (
    INSTALL_SOURCE,
    STATE_CHECKING,
    STATE_DOWNLOADED,
    STATE_DOWNLOADING,
    STATE_ERROR,
    STATE_IDLE,
    STATE_UNSUPPORTED,
    STATE_UPDATE_AVAILABLE,
    STATE_UP_TO_DATE,
)


def _human_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    f = float(n)
    for u in units:
        if f < 1024.0:
            return f"{f:.1f} {u}" if u != "B" else f"{int(f)} B"
        f /= 1024.0
    return f"{f:.1f} TB"


def _shorten_path(path: str) -> str:
    """Turn a long absolute path into something like '%TEMP%\\savestate_update\\file.zip'."""
    import os
    if not path:
        return ""
    norm = os.path.normpath(path)
    # Windows: check %TEMP% and %LOCALAPPDATA%
    replacements = []
    for var in ("TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME"):
        val = os.environ.get(var)
        if val:
            replacements.append((os.path.normpath(val), f"%{var}%" if os.name == "nt" else f"${var}"))
    # Prefer the longest match so USERPROFILE doesn't shadow LOCALAPPDATA
    replacements.sort(key=lambda r: -len(r[0]))
    for prefix, token in replacements:
        try:
            if norm.lower().startswith(prefix.lower()):
                tail = norm[len(prefix):]
                return token + tail
        except Exception:
            pass
    return norm


class UpdateDialog(QDialog):
    """Non-modal view onto UpdateManager. Safe to open/close repeatedly."""

    def __init__(self, update_manager, settings_manager, parent=None):
        super().__init__(parent)
        self._um = update_manager
        self._sm = settings_manager
        self.setWindowTitle("SaveState Update")
        self.setMinimumWidth(520)
        # Frameless to match the rest of the app look. Keep a close button via our own layout.
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Dialog)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        # Header
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 14pt; font-weight: 700;")
        root.addWidget(self.title_label)

        self.version_label = QLabel()
        self.version_label.setStyleSheet("color: #bdbdbd;")
        root.addWidget(self.version_label)

        # Changelog area
        self.changelog = QTextBrowser()
        self.changelog.setOpenExternalLinks(True)
        self.changelog.setMinimumHeight(180)
        self.changelog.setStyleSheet(
            "QTextBrowser { background-color: #151515; border: 1px solid #333; border-radius: 4px; padding: 8px; }"
        )
        root.addWidget(self.changelog, stretch=1)

        # Progress bar (shown only while downloading / after download)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #1f1f1f;
                border: 1px solid #2e7d32;
                border-radius: 4px;
                text-align: center;
                color: #f2f2f2;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #2e7d32;
                border-radius: 3px;
            }
            """
        )
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #bdbdbd;")
        root.addWidget(self.status_label)

        # Skip-this-version checkbox (only visible in the "available" state)
        self.skip_checkbox = QCheckBox("Skip this version")
        self.skip_checkbox.setVisible(False)
        root.addWidget(self.skip_checkbox)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.open_release_button = QPushButton("View on GitHub")
        self.open_release_button.clicked.connect(self._open_release_page)
        btn_row.addWidget(self.open_release_button)
        btn_row.addStretch(1)
        self.primary_button = QPushButton()
        self.primary_button.setDefault(True)
        self.primary_button.clicked.connect(self._on_primary_clicked)
        btn_row.addWidget(self.primary_button)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        btn_row.addWidget(self.close_button)
        root.addLayout(btn_row)

        # Wire manager signals. These remain connected only while the dialog
        # is alive; we disconnect on close so the manager is never held back.
        self._um.state_changed.connect(self._on_state_changed)
        self._um.progress.connect(self._on_progress)
        self._um.error.connect(self._on_error)
        self._um.update_available.connect(self._on_update_available)
        self._um.download_ready.connect(self._on_download_ready)

        # Initial sync to current manager state
        self._refresh_from_manager()

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _refresh_from_manager(self):
        """Pull the current UpdateManager state and rebuild the UI from it."""
        state = self._um.state
        release = self._um.release
        tag_latest = release.get("tag_name", "") if release else ""
        tag_current = getattr(config, "APP_RELEASE_TAG", "")

        self.version_label.setText(
            f"Current: {tag_current or config.APP_VERSION}"
            + (f"   →   Latest: {tag_latest}" if tag_latest else "")
        )
        self._apply_state(state)

    def _apply_state(self, state: str):
        release = self._um.release
        body = (release or {}).get("body", "") if release else ""
        title_name = (release or {}).get("name") or (release or {}).get("tag_name") or ""

        # Default visibilities
        self.progress_bar.setVisible(False)
        self.skip_checkbox.setVisible(False)
        self.open_release_button.setVisible(bool(release and release.get("html_url")))

        if state == STATE_UNSUPPORTED:
            self.title_label.setText("Updates unavailable")
            self.changelog.setPlainText(
                "This installation cannot be updated automatically.\n\n"
                f"Reason: {self._um.last_error or 'unsupported install type'}\n\n"
                "You can still download the latest release manually from GitHub."
            )
            self.primary_button.setText("Check on GitHub")
            self.primary_button.setEnabled(True)
            self.status_label.setText("")
            return

        if state == STATE_CHECKING:
            self.title_label.setText("Checking for updates...")
            self.changelog.setPlainText("Contacting GitHub, please wait...")
            self.primary_button.setText("Checking...")
            self.primary_button.setEnabled(False)
            self.status_label.setText("")
            return

        if state == STATE_UP_TO_DATE:
            self.title_label.setText("You're up to date")
            self.changelog.setPlainText("SaveState is running the latest released version.")
            self.primary_button.setText("Check again")
            self.primary_button.setEnabled(True)
            self.status_label.setText("")
            return

        if state == STATE_UPDATE_AVAILABLE:
            self.title_label.setText(f"Update available: {title_name}")
            self._render_changelog(body)
            self.primary_button.setText("Download update")
            self.primary_button.setEnabled(True)
            self.skip_checkbox.setVisible(True)
            # Reflect any previously stored skip state for this tag
            tag = (release or {}).get("tag_name", "")
            try:
                settings, _ = self._sm.load_settings()
                self.skip_checkbox.setChecked(settings.get("skip_update_tag", "") == tag)
            except Exception:
                self.skip_checkbox.setChecked(False)
            self.status_label.setText("")
            return

        if state == STATE_DOWNLOADING:
            self.title_label.setText(f"Downloading: {title_name}")
            self._render_changelog(body)
            self.progress_bar.setVisible(True)
            done, total = self._um.progress_tuple
            self._update_progress_widgets(done, total)
            self.primary_button.setText("Cancel")
            self.primary_button.setEnabled(True)
            return

        if state == STATE_DOWNLOADED:
            self._render_changelog(body)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            if self._um.can_auto_install():
                self.progress_bar.setFormat("Downloaded - ready to install")
                self.primary_button.setText("Install and restart")
                self.primary_button.setEnabled(True)
                self.status_label.setStyleSheet("color: #bdbdbd;")
                if self._um.install_type == INSTALL_SOURCE:
                    self.title_label.setText("Ready to install (source)")
                    self.status_label.setText(
                        "The source tree will be overwritten with the new release, "
                        "then SaveState will relaunch automatically."
                    )
                else:
                    self.title_label.setText("Ready to install")
                    self.status_label.setText(
                        "SaveState will close and relaunch itself automatically."
                    )
            else:
                # Flatpak / Snap / read-only install: auto-install refused.
                self.title_label.setText("Downloaded (manual install required)")
                self.progress_bar.setFormat("Downloaded")
                self.primary_button.setText("Open download folder")
                self.primary_button.setEnabled(True)
                self.status_label.setStyleSheet("color: #ffb74d;")
                reason = self._um.swap_unsupported_reason() or "this install type"
                short = _shorten_path(self._um.downloaded_path or "")
                self.status_label.setText(
                    f"Auto-install unavailable ({reason}). Saved to: {short}"
                )
            return

        if state == STATE_ERROR:
            self.title_label.setText("Update error")
            self.changelog.setPlainText(self._um.last_error or "Unknown error")
            self.primary_button.setText("Retry")
            self.primary_button.setEnabled(True)
            self.status_label.setText("")
            return

        # STATE_IDLE or anything else
        self.title_label.setText("Check for updates")
        self.changelog.setPlainText(
            "Click 'Check for updates' to contact GitHub and look for a new release."
        )
        self.primary_button.setText("Check for updates")
        self.primary_button.setEnabled(True)
        self.status_label.setText("")

    def _render_changelog(self, body: str):
        if not body:
            self.changelog.setPlainText("(No release notes provided.)")
            return
        # GitHub returns Markdown; Qt's QTextBrowser supports a subset of it
        # via setMarkdown. That's good enough for release notes.
        try:
            self.changelog.setMarkdown(body)
        except Exception:
            self.changelog.setPlainText(body)

    def _update_progress_widgets(self, done: int, total: int):
        if total > 0:
            pct = max(0, min(100, int(done * 100 / total)))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setFormat(
                f"{pct}%  ({_human_size(done)} / {_human_size(total)})"
            )
        else:
            # Unknown size: indeterminate
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat(f"{_human_size(done)} downloaded")

    # ------------------------------------------------------------------
    # Manager signal handlers
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_state_changed(self, state: str):
        self._apply_state(state)

    @Slot(int, int)
    def _on_progress(self, done: int, total: int):
        if self._um.state == STATE_DOWNLOADING:
            self._update_progress_widgets(done, total)

    @Slot(str)
    def _on_error(self, msg: str):
        self.status_label.setStyleSheet("color: #e57373;")
        self.status_label.setText(msg)

    @Slot(dict)
    def _on_update_available(self, release: dict):
        self._refresh_from_manager()

    @Slot(str)
    def _on_download_ready(self, path: str):
        # State handler already updates the UI; nothing extra needed here.
        pass

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def _on_primary_clicked(self):
        state = self._um.state
        if state == STATE_UNSUPPORTED:
            self._open_release_page()
            return
        if state in (STATE_IDLE, STATE_UP_TO_DATE, STATE_ERROR):
            self.status_label.setStyleSheet("color: #bdbdbd;")
            self.status_label.setText("")
            self._um.check_async()
            return
        if state == STATE_UPDATE_AVAILABLE:
            # Persist / clear "skip" choice before starting download
            self._persist_skip_choice()
            if self.skip_checkbox.isChecked():
                # The user skipped: just close the dialog.
                self.close()
                return
            self.status_label.setStyleSheet("color: #bdbdbd;")
            self.status_label.setText("")
            self._um.start_download()
            return
        if state == STATE_DOWNLOADING:
            self._um.cancel_download()
            return
        if state == STATE_DOWNLOADED:
            if not self._um.can_auto_install():
                self._open_download_folder()
                return
            ok = self._um.apply_and_restart()
            if ok:
                # Ask the main window to exit cleanly so the helper can swap the file.
                parent = self.parent()
                if parent is not None and hasattr(parent, "close"):
                    # Small delay so our script has time to spawn.
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(300, parent.close)
            return

    def _persist_skip_choice(self):
        release = self._um.release or {}
        tag = release.get("tag_name", "")
        try:
            settings, _ = self._sm.load_settings()
            desired = tag if self.skip_checkbox.isChecked() else ""
            if settings.get("skip_update_tag", "") != desired:
                settings["skip_update_tag"] = desired
                self._sm.save_settings(settings)
        except Exception:
            logging.exception("Failed to persist skip_update_tag")

    def _open_release_page(self):
        release = self._um.release
        url = (release or {}).get("html_url")
        if not url:
            url = f"https://github.com/{getattr(config, 'GITHUB_REPO', '')}/releases/latest"
        try:
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            logging.exception("Failed to open release URL")

    def _open_download_folder(self):
        """Reveal the downloaded update file in the OS file browser."""
        import os
        path = self._um.downloaded_path
        if not path or not os.path.exists(path):
            return
        folder = os.path.dirname(path)
        try:
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception:
            logging.exception("Failed to open download folder")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        # Detach from manager signals so the dialog can be GC'd even if the
        # download is still running in the background.
        try:
            self._um.state_changed.disconnect(self._on_state_changed)
            self._um.progress.disconnect(self._on_progress)
            self._um.error.disconnect(self._on_error)
            self._um.update_available.disconnect(self._on_update_available)
            self._um.download_ready.disconnect(self._on_download_ready)
        except Exception:
            pass
        super().closeEvent(event)
