# cloud_utils/cloud_panel.py
# -*- coding: utf-8 -*-
"""
Cloud Save Panel UI - Inline panel for managing cloud backups via Google Drive.
Similar to the settings panel, this is embedded in the main window.
"""

import os
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QCheckBox, QLineEdit, QProgressBar, QMessageBox, QStackedWidget,
    QComboBox
)
from PySide6.QtCore import Qt, Signal, Slot, QEvent, QThread, QObject, QTimer, QSize
from PySide6.QtGui import QIcon, QColor, QPixmap
from cloud_utils.cloud_settings_panel import CloudSettingsPanel
from cloud_utils.google_drive_manager import get_drive_manager, StorageCheckWorker
import cloud_settings_manager
from utils import resource_path
from gui_components import favorites_manager
from core_logic import sanitize_foldername, is_group_profile, get_group_member_profiles


class AuthWorker(QObject):
    """Worker thread for Google Drive authentication to avoid blocking UI."""
    finished = Signal(bool, str)  # success, error_message
    auth_url_ready = Signal(str)  # authorization URL for manual browser opening (Linux fix)
    
    def __init__(self, drive_manager, worker_id):
        super().__init__()
        self.drive_manager = drive_manager
        self.worker_id = worker_id  # Unique ID to identify this worker
        self.is_cancelled = False
    
    def cancel(self):
        """Mark this worker as cancelled."""
        self.is_cancelled = True
        logging.info(f"AuthWorker {self.worker_id} marked as cancelled")
    
    def run(self):
        """Execute authentication in background."""
        try:
            # Define callback to emit auth URL signal
            def url_callback(url):
                if not self.is_cancelled:
                    self.auth_url_ready.emit(url)
            
            success = self.drive_manager.authenticate(auth_url_callback=url_callback)
            
            # Don't emit signal if this worker was cancelled
            if self.is_cancelled:
                logging.info(f"AuthWorker {self.worker_id} completed but was cancelled, ignoring results")
                return
            
            if success:
                self.finished.emit(True, "")
            else:
                self.finished.emit(False, "Authentication failed. Please check your credentials.")
        except Exception as e:
            # Don't emit signal if this worker was cancelled
            if self.is_cancelled:
                logging.info(f"AuthWorker {self.worker_id} failed but was cancelled, ignoring error")
                return
            
            error_msg = str(e)
            logging.error(f"Authentication error: {error_msg}")
            self.finished.emit(False, f"Error during authentication: {error_msg}")


class UploadWorker(QObject):
    """Worker thread for uploading backups to avoid blocking UI."""
    progress = Signal(int, int, str)  # current, total, message
    progress_detailed = Signal(int, int, str)  # bytes_current, bytes_total, message
    finished = Signal(int, int)  # success_count, total_count
    summary_ready = Signal(dict)  # aggregated stats for UI messaging
    cancelled = Signal()  # Emitted when operation is cancelled
    
    def __init__(self, provider, backup_list, backup_base_dir, max_backups=None):
        super().__init__()
        self.provider = provider  # Can be any StorageProvider (Google Drive, FTP, SMB, WebDAV)
        self.backup_list = backup_list
        self.backup_base_dir = backup_base_dir
        self.max_backups = max_backups
        self._cancelled = False
        self._current_file_msg = ""

    def _on_file_progress(self, idx, total, message):
        self._current_file_msg = message
        self.progress.emit(idx, total, message)

    def _on_chunk_progress(self, current_bytes, total_bytes):
        if self._current_file_msg:
            self.progress_detailed.emit(current_bytes, total_bytes, self._current_file_msg)
    
    def cancel(self):
        """Request cancellation of the upload operation."""
        self._cancelled = True
        # Also request cancellation from provider if it supports it
        if self.provider and hasattr(self.provider, 'request_cancellation'):
            self.provider.request_cancellation()
        logging.info("Upload cancellation requested")
    
    def run(self):
        """Execute upload in background."""
        # Set callbacks if the provider supports them (Google Drive specific)
        if hasattr(self.provider, 'set_progress_callback'):
            self.provider.set_progress_callback(self._on_file_progress)
        if hasattr(self.provider, 'set_chunk_callback'):
            self.provider.set_chunk_callback(self._on_chunk_progress)
        
        try:
            success_count = 0
            total = len(self.backup_list)
            results = []
            
            for idx, backup_name in enumerate(self.backup_list, 1):
                # Check for cancellation
                if self._cancelled:
                    logging.info(f"Upload cancelled by user at {idx}/{total}")
                    self.cancelled.emit()
                    return
                
                # Set initial message via progress signal (callbacks handle detailed updates)
                self._current_file_msg = f"Uploading {backup_name} ({idx}/{total})"
                self.progress.emit(idx, total, self._current_file_msg)
                
                backup_path = os.path.join(self.backup_base_dir, backup_name)
                
                try:
                    res = self.provider.upload_backup(backup_path, backup_name, max_backups=self.max_backups)
                    ok = False
                    uploaded_cnt = 0
                    skipped_cnt = 0
                    was_cancelled = False
                    
                    if isinstance(res, dict):
                        ok = bool(res.get('ok', True))
                        uploaded_cnt = int(res.get('uploaded_count', 0))
                        skipped_cnt = int(res.get('skipped_newer_or_same', 0))
                        was_cancelled = bool(res.get('cancelled', False))
                    else:
                        ok = bool(res)
                    
                    # If cancelled, exit immediately
                    if was_cancelled or self._cancelled:
                        logging.info(f"Upload cancelled during {backup_name}")
                        self.cancelled.emit()
                        return

                    if ok:
                        success_count += 1
                        logging.info(f"Successfully uploaded: {backup_name}")
                    else:
                        logging.error(f"Failed to upload: {backup_name}")

                    results.append({
                        'name': backup_name,
                        'ok': ok,
                        'uploaded_count': uploaded_cnt,
                        'skipped_newer_or_same': skipped_cnt
                    })
                except Exception as e:
                    # Check if cancelled during exception
                    if self._cancelled:
                        logging.info(f"Upload cancelled during {backup_name} (exception caught)")
                        self.cancelled.emit()
                        return
                    logging.error(f"Error uploading {backup_name}: {e}")
            
            # Aggregate and emit summary for UI
            try:
                profiles_changed = sum(1 for r in results if r.get('uploaded_count', 0) > 0)
                files_uploaded = sum(int(r.get('uploaded_count', 0)) for r in results)
                files_skipped = sum(int(r.get('skipped_newer_or_same', 0)) for r in results)
                summary = {
                    'profiles_total': total,
                    'profiles_ok': success_count,
                    'profiles_changed': profiles_changed,
                    'profiles_unchanged': max(0, total - profiles_changed),
                    'files_uploaded': files_uploaded,
                    'files_skipped': files_skipped,
                    'details': results,
                }
                self.summary_ready.emit(summary)
            except Exception:
                pass

            self.finished.emit(success_count, total)
            
        finally:
            # Clear callbacks if the provider supports them
            if hasattr(self.provider, 'set_progress_callback'):
                self.provider.set_progress_callback(None)
            if hasattr(self.provider, 'set_chunk_callback'):
                self.provider.set_chunk_callback(None)


class DownloadWorker(QObject):
    """Worker thread for downloading backups to avoid blocking UI."""
    progress = Signal(int, int, str)  # current, total, message
    progress_detailed = Signal(int, int, str)  # bytes_current, bytes_total, message
    finished = Signal(int, int, dict)  # success_count, total_count, summary_stats (includes 'profiles_to_create')
    cancelled = Signal()  # Emitted when operation is cancelled
    
    def __init__(self, provider, backup_list, backup_base_dir, existing_profiles):
        super().__init__()
        self.provider = provider  # Can be any StorageProvider
        self.backup_list = backup_list
        self.backup_base_dir = backup_base_dir
        self.existing_profiles = existing_profiles  # Dict of existing profiles
        self._cancelled = False
        self._current_file_msg = ""

    def _on_file_progress(self, idx, total, message):
        self._current_file_msg = message
        self.progress.emit(idx, total, message)

    def _on_chunk_progress(self, current_bytes, total_bytes):
        if self._current_file_msg:
            self.progress_detailed.emit(current_bytes, total_bytes, self._current_file_msg)
    
    def cancel(self):
        """Request cancellation of the download operation."""
        self._cancelled = True
        # Also request cancellation from provider if it supports it
        if self.provider and hasattr(self.provider, 'request_cancellation'):
            self.provider.request_cancellation()
        logging.info("Download cancellation requested")
    
    def run(self):
        """Execute download in background."""
        # Set callbacks if the provider supports them
        if hasattr(self.provider, 'set_progress_callback'):
            self.provider.set_progress_callback(self._on_file_progress)
        if hasattr(self.provider, 'set_chunk_callback'):
            self.provider.set_chunk_callback(self._on_chunk_progress)
        
        try:
            success_count = 0
            total = len(self.backup_list)
            
            # Track detailed statistics
            stats = {
                'downloaded': 0,
                'skipped': 0,
                'failed': 0,
                'files_total': 0,
                'profiles_to_create': []  # List of (profile_name, backup_path) tuples
            }
            
            for idx, backup_name in enumerate(self.backup_list, 1):
                # Check for cancellation before processing
                if self._cancelled:
                    logging.info(f"Download cancelled by user at {idx}/{total}")
                    self.cancelled.emit()
                    return
                
                self._current_file_msg = f"Downloading {backup_name} ({idx}/{total})"
                self.progress.emit(idx, total, self._current_file_msg)
                
                backup_path = os.path.join(self.backup_base_dir, backup_name)
                
                try:
                    # download_backup now returns a dict with stats
                    download_result = self.provider.download_backup(backup_name, backup_path)
                    
                    # Check for cancellation immediately after download attempt
                    if self._cancelled:
                        logging.info(f"Download cancelled during {backup_name}")
                        self.cancelled.emit()
                        return
                    
                    # Handle result (could be bool or dict depending on version)
                    ok = False
                    if isinstance(download_result, dict):
                        ok = download_result.get('ok', False)
                        stats['downloaded'] += download_result.get('downloaded', 0)
                        stats['skipped'] += download_result.get('skipped', 0)
                        stats['failed'] += download_result.get('failed', 0)
                        stats['files_total'] += download_result.get('total', 0)
                    else:
                        ok = bool(download_result)
                        # Fallback stats if old version
                        if ok:
                            stats['downloaded'] += 1
                    
                    if ok:
                        success_count += 1
                        logging.info(f"Successfully downloaded: {backup_name}")
                        
                        # Check if profile exists, if not, add to list of profiles to create
                        if backup_name not in self.existing_profiles:
                            logging.info(f"Profile '{backup_name}' does not exist, will create it after download completes")
                            stats['profiles_to_create'].append((backup_name, backup_path))
                    else:
                        logging.error(f"Failed to download: {backup_name}")
                except Exception as e:
                    # Check if the error is due to cancellation
                    if self._cancelled:
                        logging.info(f"Download cancelled during {backup_name} (exception caught)")
                        self.cancelled.emit()
                        return
                    logging.error(f"Error downloading {backup_name}: {e}")
            
            self.finished.emit(success_count, total, stats)
            
        finally:
            # Clear callbacks if the provider supports them
            if hasattr(self.provider, 'set_progress_callback'):
                self.provider.set_progress_callback(None)
            if hasattr(self.provider, 'set_chunk_callback'):
                self.provider.set_chunk_callback(None)


class DeleteWorker(QObject):
    """Worker thread for deleting backups from cloud to avoid blocking UI."""
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(int, int)  # success_count, total_count
    cancelled = Signal()  # Emitted when operation is cancelled
    
    def __init__(self, provider, backup_list):
        super().__init__()
        self.provider = provider  # Can be any StorageProvider
        self.backup_list = backup_list
        self._cancelled = False
    
    def cancel(self):
        """Request cancellation of the delete operation."""
        self._cancelled = True
        # Note: Delete doesn't involve chunk operations, but we set the flag for consistency
        logging.info("Delete cancellation requested")
    
    def run(self):
        """Execute deletion in background."""
        success_count = 0
        total = len(self.backup_list)
        
        for idx, backup_name in enumerate(self.backup_list, 1):
            # Check for cancellation
            if self._cancelled:
                logging.info(f"Delete cancelled by user at {idx}/{total}")
                self.cancelled.emit()
                return
            
            self.progress.emit(idx, total, f"Deleting {backup_name}...")
            
            try:
                if self.provider.delete_cloud_backup(backup_name):
                    success_count += 1
                    logging.info(f"Successfully deleted from cloud: {backup_name}")
                else:
                    logging.error(f"Failed to delete from cloud: {backup_name}")
            except Exception as e:
                logging.error(f"Error deleting {backup_name}: {e}")
        
        self.finished.emit(success_count, total)


class RefreshCloudStatusWorker(QObject):
    """Worker thread for refreshing cloud backup status to avoid blocking UI."""
    finished = Signal(dict)  # cloud_backups dict
    error = Signal(str)  # error message
    
    def __init__(self, provider):
        super().__init__()
        self.provider = provider  # Can be any StorageProvider
    
    def run(self):
        """Execute cloud status refresh in background."""
        try:
            logging.info("Refreshing cloud backup status in background...")
            cloud_backups_list = self.provider.list_cloud_backups()
            
            # Convert to dict for easy lookup
            cloud_backups = {
                backup['name']: backup for backup in cloud_backups_list
            }
            
            logging.info(f"Cloud status updated: {len(cloud_backups)} backups in cloud")
            self.finished.emit(cloud_backups)
            
        except Exception as e:
            error_msg = f"Error refreshing cloud status: {str(e)}"
            logging.error(error_msg, exc_info=True)
            self.error.emit(error_msg)


class BackupScannerWorker(QObject):
    """Worker thread for scanning local backups to avoid blocking UI."""
    finished = Signal(dict)  # local_backups dict
    error = Signal(str)

    def __init__(self, backup_base_dir):
        super().__init__()
        self.backup_base_dir = backup_base_dir

    def run(self):
        """Scan local directory for backups."""
        local_backups = {}
        try:
            if os.path.isdir(self.backup_base_dir):
                entries = os.listdir(self.backup_base_dir)
                for entry in entries:
                    entry_path = os.path.join(self.backup_base_dir, entry)
                    
                    # Only process directories
                    if not os.path.isdir(entry_path):
                        continue
                    
                    # Skip special folders
                    if entry.startswith('.') or entry == '__pycache__':
                        continue
                        
                    # Count backup files in this folder
                    try:
                        backup_files = [f for f in os.listdir(entry_path) if f.endswith('.zip')]
                        file_count = len(backup_files)
                    except Exception:
                        file_count = 0
                        
                    local_backups[entry] = {
                        'name': entry,
                        'path': entry_path,
                        'local_file_count': file_count,
                        'cloud_file_count': 0,
                        'has_local': True,
                        'has_cloud': False
                    }
            self.finished.emit(local_backups)
        except Exception as e:
            logging.error(f"Error scanning backup directory: {e}")
            self.error.emit(str(e))



class CloudSavePanel(QWidget):
    """
    Inline panel for Cloud Save management.
    Shows list of backups from the backup folder and allows sync with Google Drive.
    """
    
    # Signals
    sync_requested = Signal(list)  # Emitted when user wants to sync selected backups
    download_requested = Signal(str)  # Emitted when user wants to download a backup
    
    def __init__(self, backup_base_dir, profiles, parent=None):
        """
        Initialize the Cloud Save panel.
        
        Args:
            backup_base_dir: Base directory where backups are stored
            profiles: Dictionary of current profiles
            parent: Parent widget (MainWindow)
        """
        super().__init__(parent)
        
        self.backup_base_dir = backup_base_dir
        self.profiles = profiles
        self.main_window = parent
        
        # Track which backups are available locally
        self.local_backups = []
        
        # Google Drive manager
        self.drive_manager = get_drive_manager()
        
        # Register all storage providers
        from cloud_utils.provider_factory import register_all_providers
        register_all_providers()
        
        # Cloud backups cache
        self.cloud_backups = {}
        
        # Local backups cache (raw scan results)
        self.cached_local_backups = {}
        
        # Cloud settings (will be loaded from settings panel)
        self.cloud_settings = {}
        
        # Periodic sync timer
        self.sync_timer = None
        self._sync_in_progress = False
        self._disconnect_after_current_sync = False
        
        # Track current operation for cancellation
        self._current_worker = None
        self._current_operation = None  # 'upload', 'download', 'delete'
        
        # Auth worker tracking to handle timeouts properly
        self._auth_worker_counter = 0
        self._current_auth_worker = None
        self._active_auth_threads = []  # Keep references to prevent premature destruction
        self._active_auth_workers = []  # Keep worker references to prevent garbage collection
        
        # Refresh button cooldown timer
        self._refresh_cooldown_active = False
        self._refresh_cooldown_seconds = 3  # 3 seconds cooldown
        
        # Sorting state for table headers (like Windows Explorer)
        # None = default sorting (favorites first, then alphabetical)
        # Otherwise: (column_index, ascending: bool)
        self._sort_column = None  # Column index being sorted (1=State, 2=Profile, 3=Local, 4=Cloud)
        self._sort_ascending = True  # True = ascending (A-Z, ▲), False = descending (Z-A, ▼)
        
        # --- Icon cache: load once at startup to avoid per-row disk I/O ---
        self._icon_cache = {}  # key -> QPixmap (scaled)
        self._checkmark_style = ""  # cached checkmark style for checkboxes
        self._preload_icons()
        
        # Debounce timer for _repopulate_table to avoid rapid successive rebuilds
        self._repopulate_timer = QTimer(self)
        self._repopulate_timer.setSingleShot(True)
        self._repopulate_timer.setInterval(50)  # 50ms debounce
        self._repopulate_timer.timeout.connect(self._do_repopulate_table)
        
        # Use stacked widget to switch between main panel and settings
        self.stacked_widget = QStackedWidget(self)
        
        # Create main panel widget
        self.main_panel = QWidget()
        
        # Create settings panel
        self.settings_panel = CloudSettingsPanel(parent=self)
        self.settings_panel.settings_saved.connect(self._on_cloud_settings_saved)
        
        # Add both to stacked widget
        self.stacked_widget.addWidget(self.main_panel)  # Index 0
        self.stacked_widget.addWidget(self.settings_panel)  # Index 1
        
        # Set layout for CloudSavePanel
        container_layout = QVBoxLayout(self)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.stacked_widget)
        
        # Enable focus for keyboard events
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self._init_ui()
        
        # Load cloud settings from disk
        self._load_cloud_settings_from_disk()
        
    def _preload_icons(self):
        """Pre-load and cache all icons used in the backup table to avoid per-row disk I/O."""
        try:
            # Cache state icons (32x32 scaled)
            for icon_name in ("cloud_local.png", "local.png", "cloud.png"):
                icon_path = resource_path(f"icons/{icon_name}")
                if os.path.exists(icon_path):
                    pixmap = QPixmap(icon_path)
                    self._icon_cache[icon_name] = pixmap.scaled(
                        32, 32,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

            # Cache checkmark style for checkboxes
            checkmark_path = resource_path("icons/checkmark.png")
            if os.path.exists(checkmark_path):
                self._checkmark_style = f"image: url({checkmark_path});"
        except Exception as e:
            logging.warning(f"Error preloading icons: {e}")

    def _load_cloud_settings_from_disk(self):
        """Load cloud settings from disk on initialization."""
        try:
            settings = cloud_settings_manager.load_cloud_settings()
            self.cloud_settings = settings
            self.settings_panel.load_settings(settings)
            
            # Apply settings to drive manager
            self._apply_settings_to_drive_manager()

            # Setup periodic sync even if not connected (will auto-connect when needed)
            self._setup_periodic_sync()
            
            # Select the saved active provider in the dropdown (after UI is created)
            QTimer.singleShot(100, self._restore_active_provider)
            
        except Exception as e:
            logging.error(f"Error loading cloud settings from disk: {e}")
    
    def _restore_active_provider(self):
        """Restore the active provider from saved settings."""
        try:
            active_provider = self.cloud_settings.get('active_provider', 'google_drive')
            
            # Find the index of the provider in the combo box
            for i in range(self.provider_combo.count()):
                if self.provider_combo.itemData(i) == active_provider:
                    # Block signals to avoid triggering _on_provider_changed
                    self.provider_combo.blockSignals(True)
                    self.provider_combo.setCurrentIndex(i)
                    self.provider_combo.blockSignals(False)
                    
                    # Update UI for the selected provider
                    self._update_connect_button_for_provider(active_provider)
                    self._update_connection_status_for_provider(active_provider)
                    self._update_configure_button_state(active_provider)
                    break
                    
        except Exception as e:
            logging.error(f"Error restoring active provider: {e}")
    
    def _get_active_provider(self):
        """
        Get the currently active storage provider based on the dropdown selection.
        
        Returns:
            StorageProvider instance or None if no provider is connected
        """
        try:
            provider_type_str = self.provider_combo.currentData()
            
            if provider_type_str == 'google_drive':
                return self.drive_manager
            
            from cloud_utils.provider_factory import ProviderFactory
            return ProviderFactory.get_provider_by_string(provider_type_str)
        except Exception as e:
            logging.error(f"Error getting active provider: {e}")
            return None
    
    def _is_any_provider_connected(self):
        """
        Check if any storage provider is currently connected.
        
        Returns:
            True if any provider is connected, False otherwise
        """
        try:
            provider_type_str = self.provider_combo.currentData()
            
            if provider_type_str == 'google_drive':
                return self.drive_manager.is_connected
            
            provider = self._get_active_provider()
            return provider is not None and provider.is_connected
        except Exception as e:
            logging.debug(f"Error checking provider connection: {e}")
            return False
    
    def _init_ui(self):
        """Initialize the UI components for the main panel."""
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)
        
        # --- Header Section ---
        header_layout = QHBoxLayout()
        
        title_label = QLabel("<h2>Cloud Save Manager</h2>")
        title_label.setObjectName("CloudPanelTitle")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch(1)
        
        # Google Drive connection status
        self.connection_status_label = QLabel("● Not Connected")
        self.connection_status_label.setObjectName("ConnectionStatus")
        self.connection_status_label.setStyleSheet("color: #FF5555;")
        header_layout.addWidget(self.connection_status_label)
        
        main_layout.addLayout(header_layout)
        
        # --- Description ---
        description = QLabel(
            "Sync your save backups to cloud storage or network folders. "
            "Select backups to upload or download."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #AAAAAA; font-size: 10pt;")
        main_layout.addWidget(description)
        
        # --- Toolbar Row (all controls in one compact horizontal line) ---
        toolbar_row = QHBoxLayout()
        toolbar_row.setContentsMargins(0, 4, 0, 4)  # Reduced vertical margins
        toolbar_row.setSpacing(8)
        
        # Provider dropdown
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Google Drive", "google_drive")
        self.provider_combo.addItem("Network Folder", "smb")
        self.provider_combo.addItem("FTP Server", "ftp")
        self.provider_combo.addItem("WebDAV", "webdav")
        self.provider_combo.addItem("Git Repository", "git")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_combo.setMinimumWidth(140)
        toolbar_row.addWidget(self.provider_combo)
        
        # Configure button (square, icon only - like ExitButton)
        self.configure_provider_button = QPushButton()
        self.configure_provider_button.setObjectName("ConfigureButton")  # For CSS styling
        self.configure_provider_button.setToolTip("Configure the selected storage provider")
        self.configure_provider_button.clicked.connect(self._on_configure_provider_clicked)
        # Load configure icon
        try:
            configure_icon_path = resource_path("icons/configure.png")
            if os.path.exists(configure_icon_path):
                configure_icon = QIcon(configure_icon_path)
                # Verify icon is valid (not null/empty)
                if not configure_icon.isNull():
                    self.configure_provider_button.setIcon(configure_icon)
                    self.configure_provider_button.setIconSize(QSize(16, 16))
                    # Explicitly clear any text to prevent dual display
                    self.configure_provider_button.setText("")
                else:
                    # Icon file exists but couldn't be loaded properly
                    self.configure_provider_button.setText("⚙")
                    logging.warning(f"Configure icon loaded but is null: {configure_icon_path}")
            else:
                # Fallback to text if icon not found
                self.configure_provider_button.setText("⚙")
                logging.warning(f"Configure icon not found: {configure_icon_path}")
        except Exception as e:
            logging.warning(f"Could not set configure button icon: {e}")
            self.configure_provider_button.setText("⚙")
        # Initially disabled since Google Drive (default) uses OAuth
        self.configure_provider_button.setEnabled(False)
        toolbar_row.addWidget(self.configure_provider_button)
        
        # Connect button
        self.connect_button = QPushButton("Connect to Google Drive")
        self.connect_button.setObjectName("PrimaryButton")
        self.connect_button.clicked.connect(self._on_connect_or_logout_clicked)
        
        # Calculate fixed width for various connect texts (increased padding for better fit)
        from PySide6.QtGui import QFontMetrics
        font_metrics = self.connect_button.fontMetrics()
        connect_texts = ["Connect to Google Drive", "Connect to Network Folder", "Logout"]
        max_width = max(font_metrics.horizontalAdvance(t) for t in connect_texts) + 60  # Increased padding
        self._connect_button_fixed_width = max_width
        self.connect_button.setFixedWidth(self._connect_button_fixed_width)
        toolbar_row.addWidget(self.connect_button)
        
        # Disconnect button (also fixed width to prevent layout shifts)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.clicked.connect(self._on_disconnect_clicked)
        # Calculate fixed width for various disconnect/connect texts
        disconnect_texts = [
            "Disconnect", 
            "Connect to FTP Server", 
            "Connect to Network Folder",
            "Connect to WebDAV",
            "Connect to Git"
        ]
        max_disconnect_width = max(font_metrics.horizontalAdvance(t) for t in disconnect_texts) + 50
        self.disconnect_button.setFixedWidth(max_disconnect_width)
        toolbar_row.addWidget(self.disconnect_button)
        
        # Spacer to push filter checkbox to the right
        toolbar_row.addStretch(1)
        
        # Filter checkbox (right side)
        self.show_all_backups_checkbox = QCheckBox("Show all backups")
        self.show_all_backups_checkbox.setToolTip(
            "When enabled, shows all backup folders even if they don't match any profile"
        )
        self.show_all_backups_checkbox.toggled.connect(self._on_filter_changed)
        toolbar_row.addWidget(self.show_all_backups_checkbox)
        
        main_layout.addLayout(toolbar_row)
        
        # --- Backup List Table ---
        list_group = QGroupBox("Available Backups")
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(6, 6, 6, 6)
        list_layout.setSpacing(6)
        
        self.backup_table = QTableWidget()
        self.backup_table.setColumnCount(5)
        self.backup_table.setHorizontalHeaderLabels([
            "Select", "State", "Profile", "Local Status", "Cloud Status"
        ])
        
        # Configure table
        self.backup_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.backup_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)  # Disable row selection, use checkboxes only
        self.backup_table.setAlternatingRowColors(False)  # Disabled to fix white row bug
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.verticalHeader().setDefaultSectionSize(40)  # Increase row height for better icon visibility
        self.backup_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Remove focus rectangle
        
        # Set column widths
        header = self.backup_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # Select checkbox
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # State
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Profile
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Local Status
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Cloud Status
        self.backup_table.setColumnWidth(0, 50)  # Slightly wider for checkbox
        self.backup_table.setColumnWidth(1, 60)  # Wider for icons with padding
        
        # Enable clickable headers for sorting (like Windows Explorer)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._on_header_clicked)
        # Style the header to show it's clickable
        header.setStyleSheet("""
            QHeaderView::section {
                padding: 6px;
            }
            QHeaderView::section:hover {
                background-color: #3a3a3a;
            }
        """)
        
        list_layout.addWidget(self.backup_table)
        list_group.setLayout(list_layout)
        main_layout.addWidget(list_group, stretch=1)
        
        # --- Progress Bar (initially hidden) ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFormat("%v/%m files (%p%)")
        main_layout.addWidget(self.progress_bar)
        
        # --- Action Buttons Row (all buttons in one row at bottom) ---
        actions_layout = QHBoxLayout()
        
        # Stacked widget to switch between Refresh button and Search bar
        self.refresh_search_stack = QStackedWidget()
        from PySide6.QtWidgets import QSizePolicy
        self.refresh_search_stack.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        
        # Refresh button widget
        self.refresh_button = QPushButton("Refresh List")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        # NO minimum width - let it use its natural size
        
        # Search bar widget
        self.filter_search = QLineEdit()
        self.filter_search.setPlaceholderText("Type to filter backups...")
        self.filter_search.textChanged.connect(self._on_search_changed)
        # NO minimum width - let it use its natural size
        
        # Add both to stacked widget
        self.refresh_search_stack.addWidget(self.refresh_button)  # Index 0
        self.refresh_search_stack.addWidget(self.filter_search)   # Index 1
        self.refresh_search_stack.setCurrentIndex(0)  # Show refresh button by default
        
        actions_layout.addWidget(self.refresh_search_stack)
        actions_layout.addStretch(1)
        
        self.upload_button = QPushButton("Upload Selected")
        self.upload_button.setEnabled(False)
        self.upload_button.clicked.connect(self._on_upload_clicked)
        actions_layout.addWidget(self.upload_button)
        
        self.download_button = QPushButton("Download Selected")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._on_download_clicked)
        actions_layout.addWidget(self.download_button)
        
        self.delete_button = QPushButton("Delete Selected from Cloud")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._on_delete_or_cancel_clicked)
        
        # Calculate width needed for BOTH possible texts and use the larger one
        # This prevents resizing when switching between "Delete..." and "Cancel..."
        delete_text = "Delete Selected from Cloud"
        cancel_text = "Cancel Operation"
        
        # Get font metrics to calculate text width
        from PySide6.QtGui import QFontMetrics
        font_metrics = self.delete_button.fontMetrics()
        delete_width = font_metrics.horizontalAdvance(delete_text)
        cancel_width = font_metrics.horizontalAdvance(cancel_text)
        
        # Use the wider text + icon space + padding
        max_text_width = max(delete_width, cancel_width)
        # Add space for icon (32px) + padding (40px for margins and spacing)
        self._delete_button_fixed_width = max_text_width + 32 + 40
        self.delete_button.setFixedWidth(self._delete_button_fixed_width)
        
        # Set trash icon (same as delete profile button) and save it for later
        try:
            from PySide6.QtWidgets import QApplication, QStyle
            style = QApplication.instance().style()
            self._delete_icon = style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            self._cancel_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
            self.delete_button.setIcon(self._delete_icon)
        except Exception as e:
            logging.warning(f"Could not set delete button icon: {e}")
            self._delete_icon = None
            self._cancel_icon = None
        actions_layout.addWidget(self.delete_button)
        
        # Exit button (icon only, square)
        self.exit_button = QPushButton()
        self.exit_button.setObjectName("ExitButton")  # Set object name for CSS styling
        self.exit_button.setToolTip("Exit Cloud Panel")
        self.exit_button.clicked.connect(self._on_exit_clicked)
        # Try to load exit.png, fallback to standard icon
        try:
            exit_icon_path = resource_path("icons/exit.png")
            if os.path.exists(exit_icon_path):
                exit_icon = QIcon(exit_icon_path)
                self.exit_button.setIcon(exit_icon)
            else:
                # Fallback to standard close icon
                from PySide6.QtWidgets import QApplication, QStyle
                style = QApplication.instance().style()
                exit_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)
                self.exit_button.setIcon(exit_icon)
            self.exit_button.setIconSize(QSize(32, 32))
        except Exception as e:
            logging.warning(f"Could not set exit button icon: {e}")
            self.exit_button.setText("X")  # Fallback text
        
        actions_layout.addWidget(self.exit_button)
        
        main_layout.addLayout(actions_layout)
        
        # Initial population
        self.refresh_local_backups()
    
    def refresh_local_backups(self):
        """Start background scan of local backups."""
        # Show scanning state if table is empty or requested
        if self.backup_table.rowCount() == 0:
            # You could add a temporary "Scanning..." row or disable UI here
            pass
            
        if hasattr(self, 'scan_thread') and self.scan_thread is not None:
            try:
                if self.scan_thread.isRunning():
                    return
            except RuntimeError:
                # C++ object already deleted, so it's definitely not running
                self.scan_thread = None

        self.scan_thread = QThread()
        self.scan_worker = BackupScannerWorker(self.backup_base_dir)
        self.scan_worker.moveToThread(self.scan_thread)
        
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        
        self.scan_thread.start()

    def _on_scan_finished(self, local_backups):
        """Handle completion of local backup scan."""
        # Don't update UI if panel is not visible
        if not self.isVisible():
            logging.debug("Scan finished but panel not visible, caching results only")
            self.cached_local_backups = local_backups
            return
        
        self.cached_local_backups = local_backups
        self._repopulate_table()

    def _on_header_clicked(self, logical_index):
        """Handle click on table header for sorting (like Windows Explorer)."""
        # Ignore clicks on Select column (index 0)
        if logical_index == 0:
            return
        
        # Toggle sort order if clicking on the same column
        if self._sort_column == logical_index:
            self._sort_ascending = not self._sort_ascending
        else:
            # New column selected - start with ascending order
            self._sort_column = logical_index
            self._sort_ascending = True
        
        # Update header labels to show sort indicator
        self._update_header_labels()
        
        # Re-populate the table with new sorting
        self._repopulate_table()
    
    def _update_header_labels(self):
        """Update table header labels to show sort indicators (▲/▼)."""
        base_labels = ["Select", "State", "Profile", "Local Status", "Cloud Status"]
        
        for i, label in enumerate(base_labels):
            if i == self._sort_column:
                # Add sort indicator arrow
                arrow = " ▲" if self._sort_ascending else " ▼"
                self.backup_table.setHorizontalHeaderItem(i, QTableWidgetItem(label + arrow))
            else:
                self.backup_table.setHorizontalHeaderItem(i, QTableWidgetItem(label))
    
    def _reset_sorting(self):
        """Reset sorting to default (favorites first, then alphabetical)."""
        self._sort_column = None
        self._sort_ascending = True
        # Reset header labels to remove arrows
        base_labels = ["Select", "State", "Profile", "Local Status", "Cloud Status"]
        for i, label in enumerate(base_labels):
            self.backup_table.setHorizontalHeaderItem(i, QTableWidgetItem(label))

    def _repopulate_table(self):
        """Schedule a debounced table repopulation (avoids rapid successive rebuilds)."""
        self._repopulate_timer.start()  # restarts the 50ms timer on each call

    def _do_repopulate_table(self):
        """Refresh the table UI using cached local data and cloud data (no disk I/O)."""
        # Disable UI updates during bulk population to prevent per-row redraws
        self.backup_table.setUpdatesEnabled(False)
        try:
            self._do_repopulate_table_inner()
        finally:
            self.backup_table.setUpdatesEnabled(True)

    def _do_repopulate_table_inner(self):
        self.backup_table.setRowCount(0)
        self.local_backups.clear()
        
        show_all = self.show_all_backups_checkbox.isChecked()
        search_text = self.filter_search.text().lower()
        
        # copy cached local backups to work with
        all_backups = self.cached_local_backups.copy()
        
        # --- Merge cloud backups ---
        if self._is_any_provider_connected() and self.cloud_backups:
            for cloud_name, cloud_info in self.cloud_backups.items():
                if cloud_name in all_backups:
                    # Update existing entry with cloud info
                    all_backups[cloud_name]['has_cloud'] = True
                    all_backups[cloud_name]['cloud_file_count'] = cloud_info.get('file_count', 0)
                else:
                    # Add cloud-only backup
                    all_backups[cloud_name] = {
                        'name': cloud_name,
                        'path': None,
                        'local_file_count': 0,
                        'cloud_file_count': cloud_info.get('file_count', 0),
                        'has_local': False,
                        'has_cloud': True
                    }
        
        # --- Filter and populate table ---
        
        # Load favorites for sorting
        try:
            favorites = favorites_manager.load_favorites()
        except Exception:
            favorites = {}

        # Build reverse mapping: backup folder name -> original profile name
        # Uses backup_folder_name from profile data (stable across renames),
        # falling back to sanitize_foldername for profiles without it
        sanitized_to_profile = {}
        for profile_name, profile_data in self.profiles.items():
            if isinstance(profile_data, dict):
                folder_name = profile_data.get('backup_folder_name', sanitize_foldername(profile_name))
            else:
                folder_name = sanitize_foldername(profile_name)
            sanitized_to_profile[folder_name] = profile_name

        # Prepare backup data with metadata for sorting
        backup_items = []
        for backup_name in all_backups.keys():
            backup = all_backups[backup_name]
            # Resolve original profile name for favorites lookup
            # Favorites are stored with original profile names, not sanitized folder names
            original_profile_name = sanitized_to_profile.get(backup_name, backup_name)
            backup_items.append({
                'name': backup_name,
                'data': backup,
                'is_favorite': favorites.get(original_profile_name, False),
                'has_local': backup.get('has_local', False),
                'has_cloud': backup.get('has_cloud', False),
                'local_file_count': backup.get('local_file_count', 0),
                'cloud_file_count': backup.get('cloud_file_count', 0),
                'is_group': False,
            })
        
        # --- Add group profiles to backup_items ---
        # Groups are virtual entries that allow batch-selecting all members
        for group_name, group_data in self.profiles.items():
            if not is_group_profile(group_data):
                continue
            
            # Get member profiles and calculate aggregated stats
            member_names = get_group_member_profiles(group_name, self.profiles)
            if not member_names:
                continue
            
            # Calculate combined local/cloud file counts from members
            total_local_files = 0
            total_cloud_files = 0
            has_any_local = False
            has_any_cloud = False
            
            for member_name in member_names:
                member_data = self.profiles.get(member_name, {})
                if isinstance(member_data, dict):
                    sanitized_member = member_data.get('backup_folder_name', sanitize_foldername(member_name))
                else:
                    sanitized_member = sanitize_foldername(member_name)
                # Check local backups
                if sanitized_member in all_backups:
                    member_backup = all_backups[sanitized_member]
                    total_local_files += member_backup.get('local_file_count', 0)
                    total_cloud_files += member_backup.get('cloud_file_count', 0)
                    if member_backup.get('has_local'):
                        has_any_local = True
                    if member_backup.get('has_cloud'):
                        has_any_cloud = True
            
            # Create group entry for sorting
            backup_items.append({
                'name': group_name,
                'data': {
                    'name': group_name,
                    'path': None,
                    'local_file_count': total_local_files,
                    'cloud_file_count': total_cloud_files,
                    'has_local': has_any_local,
                    'has_cloud': has_any_cloud,
                    'is_group': True,
                    'member_names': member_names,
                },
                'is_favorite': favorites.get(group_name, False),
                'has_local': has_any_local,
                'has_cloud': has_any_cloud,
                'local_file_count': total_local_files,
                'cloud_file_count': total_cloud_files,
                'is_group': True,
            })
        
        # Apply sorting based on current sort column
        if self._sort_column is None:
            # Default sorting: favorites first, then alphabetical
            backup_items.sort(key=lambda x: (not x['is_favorite'], x['name'].lower()))
        elif self._sort_column == 1:
            # Sort by State: order by (has_local, has_cloud) combination
            # Both > Local only > Cloud only
            def state_sort_key(x):
                if x['has_local'] and x['has_cloud']:
                    return 0  # Both
                elif x['has_local']:
                    return 1  # Local only
                elif x['has_cloud']:
                    return 2  # Cloud only
                else:
                    return 3  # Unknown
            backup_items.sort(key=lambda x: (state_sort_key(x), x['name'].lower()), 
                            reverse=not self._sort_ascending)
        elif self._sort_column == 2:
            # Sort by Profile name (alphabetical)
            backup_items.sort(key=lambda x: x['name'].lower(), 
                            reverse=not self._sort_ascending)
        elif self._sort_column == 3:
            # Sort by Local Status (file count)
            backup_items.sort(key=lambda x: (x['local_file_count'], x['name'].lower()), 
                            reverse=not self._sort_ascending)
        elif self._sort_column == 4:
            # Sort by Cloud Status (file count)
            backup_items.sort(key=lambda x: (x['cloud_file_count'], x['name'].lower()), 
                            reverse=not self._sort_ascending)
        
        for item in backup_items:
            backup_name = item['name']
            backup = item['data']
            is_group = item.get('is_group', False)
            
            # Handle groups specially
            if is_group:
                # Search filter for groups
                if search_text and search_text not in backup_name.lower():
                    continue
                
                # Add group to list
                backup['profile'] = backup_name
                backup['is_known_profile'] = True
                backup['is_favorite'] = favorites.get(backup_name, False)
                
                self.local_backups.append(backup)
                self._add_backup_row(backup)
                continue
            
            # Check if this backup folder matches a profile
            # Use the sanitized_to_profile mapping to handle sanitized folder names
            # (e.g., backup folder "Hollow Knight Silksong" matches profile "Hollow Knight: Silksong")
            if backup_name in self.profiles:
                # Direct match (folder name == profile name)
                profile_name = backup_name
                is_known_profile = True
            elif backup_name in sanitized_to_profile:
                # Match via sanitized name lookup
                profile_name = sanitized_to_profile[backup_name]
                is_known_profile = True
            else:
                # No match found
                profile_name = backup_name
                is_known_profile = False
            
            # Filter: if not showing all, skip non-profile backups UNLESS they have cloud sync
            has_cloud = backup.get('has_cloud', False)
            if not show_all and not is_known_profile and not has_cloud:
                continue
            
            # Search filter
            if search_text and search_text not in backup_name.lower():
                continue
            
            # Add profile name to backup info
            backup['profile'] = profile_name
            backup['is_known_profile'] = is_known_profile
            # Use original profile name for favorites lookup (favorites are stored with original names)
            backup['is_favorite'] = favorites.get(profile_name, False)
            
            self.local_backups.append(backup)
            self._add_backup_row(backup)
        
        # Update action button states after repopulating the table
        self._update_action_buttons_state()
    
    def _add_backup_row(self, backup_info):
        """Add a row to the backup table."""
        row = self.backup_table.rowCount()
        self.backup_table.insertRow(row)
        
        has_local = backup_info.get('has_local', False)
        has_cloud = backup_info.get('has_cloud', False)
        
        # Column 0: Checkbox (styled)
        checkbox_widget = QWidget()
        checkbox_widget.setStyleSheet("background-color: transparent;")
        checkbox_layout = QHBoxLayout(checkbox_widget)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        checkbox = QCheckBox()
        # Use pre-cached checkmark style (loaded once at startup)
        checkmark_style = self._checkmark_style
        
        checkbox.setStyleSheet(f"""
            QCheckBox {{
                spacing: 0px;
            }}
            QCheckBox::indicator {{
                width: 24px;
                height: 24px;
                border-radius: 4px;
                border: 2px solid #555555;
                background-color: #2b2b2b;
            }}
            QCheckBox::indicator:hover {{
                border: 2px solid #888888;
                background-color: #353535;
            }}
            QCheckBox::indicator:checked {{
                border: 2px solid #4CAF50;
                background-color: #4CAF50;
                {checkmark_style}
            }}
            QCheckBox::indicator:checked:hover {{
                border: 2px solid #66BB6A;
                background-color: #66BB6A;
            }}
        """)
        
        checkbox_layout.addWidget(checkbox)
        self.backup_table.setCellWidget(row, 0, checkbox_widget)
        
        # Connect checkbox state change to update button states
        checkbox.stateChanged.connect(self._update_action_buttons_state)
        
        # Column 1: State (Local/Cloud/Both) - with icon
        state_widget = QWidget()
        state_widget.setStyleSheet("background-color: transparent;")  # Remove dark background
        state_layout = QHBoxLayout(state_widget)
        state_layout.setContentsMargins(0, 0, 0, 0)
        state_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Determine which icon to use
        if has_local and has_cloud:
            icon_name = "cloud_local.png"
            tooltip = "Available locally and in cloud"
        elif has_local:
            icon_name = "local.png"
            tooltip = "Available locally only"
        elif has_cloud:
            icon_name = "cloud.png"
            tooltip = "Available in cloud only"
        else:
            icon_name = None
            tooltip = "Unknown state"
        
        # Create icon label - use pre-cached icons
        if icon_name:
            cached_pixmap = self._icon_cache.get(icon_name)
            if cached_pixmap:
                icon_label = QLabel()
                icon_label.setStyleSheet("background-color: transparent;")
                icon_label.setPixmap(cached_pixmap)
                icon_label.setToolTip(tooltip)
                state_layout.addWidget(icon_label)
            else:
                # Fallback to text if icon not found in cache
                text_label = QLabel("Both" if has_local and has_cloud else ("Local" if has_local else "Cloud"))
                text_label.setToolTip(tooltip)
                state_layout.addWidget(text_label)
        else:
            text_label = QLabel("?")
            text_label.setToolTip(tooltip)
            state_layout.addWidget(text_label)
        
        self.backup_table.setCellWidget(row, 1, state_widget)
        
        # Column 2: Profile (use backup name as profile name)
        profile_name = backup_info['profile']
        folder_name = backup_info.get('name', profile_name)  # Actual folder name on disk (sanitized)
        is_known = backup_info.get('is_known_profile', False)
        is_favorite = backup_info.get('is_favorite', False)
        is_group = backup_info.get('is_group', False)
        
        display_name = profile_name
        if is_group:
            display_name = "📁 " + profile_name  # Folder icon for groups
        elif is_favorite:
            display_name = "★ " + profile_name
        
        profile_item = QTableWidgetItem(display_name)
        # Store the actual folder name as UserRole data for use in operations
        profile_item.setData(Qt.ItemDataRole.UserRole, folder_name)
        # Store group flag and member names for checkbox sync
        profile_item.setData(Qt.ItemDataRole.UserRole + 1, is_group)
        if is_group:
            profile_item.setData(Qt.ItemDataRole.UserRole + 2, backup_info.get('member_names', []))
        profile_item.setFlags(profile_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if is_group:
            profile_item.setForeground(QColor("#FFA500"))  # Orange for groups
        elif is_known:
            profile_item.setForeground(QColor("#4CAF50"))  # Green for known profiles
        else:
            profile_item.setForeground(QColor("#AAAAAA"))  # Gray for unknown
        self.backup_table.setItem(row, 2, profile_item)
        
        # Connect group checkbox to toggle members
        if is_group:
            member_names = backup_info.get('member_names', [])
            checkbox.stateChanged.connect(
                lambda state, members=member_names: self._on_group_checkbox_changed(state, members)
            )
        
        # Column 3: Local Status
        local_count = backup_info.get('local_file_count', 0)
        if has_local:
            local_status = f"{local_count} files"
            local_color = QColor("#4CAF50")
        else:
            local_status = "Not local"
            local_color = QColor("#AAAAAA")
        
        local_item = QTableWidgetItem(local_status)
        local_item.setFlags(local_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        local_item.setForeground(local_color)
        self.backup_table.setItem(row, 3, local_item)
        
        # Column 4: Cloud Status
        cloud_count = backup_info.get('cloud_file_count', 0)
        if has_cloud:
            cloud_status = f"{cloud_count} files"
            cloud_color = QColor("#4CAF50")
        else:
            cloud_status = "Not synced"
            cloud_color = QColor("#AAAAAA")
        
        cloud_item = QTableWidgetItem(cloud_status)
        cloud_item.setFlags(cloud_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        cloud_item.setForeground(cloud_color)
        self.backup_table.setItem(row, 4, cloud_item)
    
    def _update_action_buttons_state(self):
        """Update the state of action buttons based on current selection."""
        if not self._is_any_provider_connected():
            # If not connected, disable all buttons
            self.upload_button.setEnabled(False)
            self.download_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return
        
        # Get selected backups
        selected_backups = []
        for row in range(self.backup_table.rowCount()):
            checkbox_widget = self.backup_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    # Get backup info from the row
                    profile_item = self.backup_table.item(row, 2)
                    if profile_item:
                        folder_name = profile_item.data(Qt.ItemDataRole.UserRole)
                        # Find backup info in local_backups
                        backup_info = None
                        for backup in self.local_backups:
                            if backup.get('name') == folder_name:
                                backup_info = backup
                                break
                        if backup_info:
                            selected_backups.append(backup_info)
        
        # Update button states based on selection
        if not selected_backups:
            # No selection - disable all buttons
            self.upload_button.setEnabled(False)
            self.download_button.setEnabled(False)
            self.delete_button.setEnabled(False)
        else:
            # Check if any selected backup has local files (for upload)
            has_local = any(backup.get('has_local', False) for backup in selected_backups)
            self.upload_button.setEnabled(has_local)
            
            # Check if any selected backup has cloud files (for download/delete)
            has_cloud = any(backup.get('has_cloud', False) for backup in selected_backups)
            self.download_button.setEnabled(has_cloud)
            self.delete_button.setEnabled(has_cloud)
    
    def _set_delete_button_to_cancel_mode(self):
        """Transform delete button into cancel button during operations."""
        self.delete_button.setText("Cancel Operation")
        if self._cancel_icon:
            self.delete_button.setIcon(self._cancel_icon)
        self.delete_button.setEnabled(True)
        # Change object name to get different styling if needed
        self.delete_button.setObjectName("CancelButton")
        # Clear any disabled styling (cancel button is always enabled)
        self.delete_button.setStyleSheet("")
        # Reapply fixed width to maintain button size
        self.delete_button.setFixedWidth(self._delete_button_fixed_width)
    
    def _set_delete_button_to_delete_mode(self):
        """Restore delete button to normal state after operations."""
        self.delete_button.setText("Delete Selected from Cloud")
        if self._delete_icon:
            self.delete_button.setIcon(self._delete_icon)
        # Restore object name
        self.delete_button.setObjectName("DangerButton")
        # Reapply fixed width to maintain button size
        self.delete_button.setFixedWidth(self._delete_button_fixed_width)
        
        # Update all button states based on current selection
        self._update_action_buttons_state()
    
    def _on_delete_or_cancel_clicked(self):
        """Handle delete button click - acts as delete or cancel depending on mode."""
        # Check if we're in cancel mode (operation in progress)
        if self._current_worker is not None:
            self._on_cancel_operation_clicked()
        else:
            self._on_delete_clicked()
    
    def _handle_storage_check_cancellation(self):
        """Handle cancellation of the storage check operation."""
        logging.info("Cancelling storage check...")
        self._storage_check_cancelled = True
        
        # Stop thread if running
        if hasattr(self, '_storage_check_thread') and self._storage_check_thread:
            try:
                if self._storage_check_thread.isRunning():
                    self._storage_check_thread.quit()
                    # We don't wait() here to keep UI responsive
            except RuntimeError:
                pass
        
        # Restore UI state
        self.progress_bar.setVisible(False)
        self._enable_buttons_after_operation()
        self._set_delete_button_to_delete_mode()
        
        # Clear pending selection
        self._pending_upload_selection = None
        self._current_operation = None

    def _on_cancel_operation_clicked(self):
        """Cancel the current operation (upload/download/delete)."""
        # Handle storage check cancellation specially
        if getattr(self, '_current_operation', None) == 'storage_check':
            self._handle_storage_check_cancellation()
            return
            
        if self._current_worker is None:
            return
        
        logging.info(f"Cancelling {self._current_operation} operation...")
        
        # Call cancel method on worker
        try:
            if hasattr(self._current_worker, 'cancel'):
                self._current_worker.cancel()
                # Update progress bar to show cancellation
                self.progress_bar.setFormat("Cancelling operation...")
        except Exception as e:
            logging.error(f"Error requesting cancellation: {e}")
    
    def _on_filter_changed(self, checked):
        """Handle filter checkbox change."""
        self._repopulate_table()
    
    def _on_search_changed(self, text):
        """Handle search text change and switch back to refresh button if empty."""
        self._repopulate_table()
        
        # Switch back to refresh button if text is empty
        if not text:
            self.refresh_search_stack.setCurrentIndex(0)  # Show refresh button
    
    def showEvent(self, event):
        """Handle show event to ensure the panel can receive keyboard input."""
        super().showEvent(event)
        # Set focus to the main panel so it can receive keyboard events
        self.setFocus()
    
    def event(self, event_obj):
        """Handles events for the cloud panel, specifically KeyPress to activate search bar."""
        if event_obj.type() == QEvent.Type.KeyPress:
            # Check if refresh button is currently shown (search bar hidden)
            if self.refresh_search_stack.currentIndex() == 0:
                key_text = event_obj.text()
                # Check if the key produces a printable character and is not just whitespace
                # Also exclude special keys
                if key_text and key_text.isprintable() and key_text.strip() != '' and \
                   event_obj.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab, 
                                          Qt.Key.Key_Backtab, Qt.Key.Key_Escape):
                    # Switch to search bar, set focus to it, and input the typed character
                    self.refresh_search_stack.setCurrentIndex(1)  # Show search bar
                    self.filter_search.setFocus()
                    self.filter_search.setText(key_text)  # This also triggers _on_search_changed
                    return True  # Event handled, stop further processing
            # Handle Escape key when search bar is visible and has focus
            elif self.refresh_search_stack.currentIndex() == 1 and self.filter_search.hasFocus() and \
                 event_obj.key() == Qt.Key.Key_Escape:
                self.filter_search.clear()  # This will trigger _on_search_changed, which switches back
                self.backup_table.setFocus()  # Return focus to table
                return True  # Event handled
        
        # For all other events or if the key press wasn't handled above,
        # call the base class's event handler
        return super().event(event_obj)
    
    def _on_refresh_clicked(self):
        """Refresh the backup list."""
        # Prevent spam clicking with cooldown
        if self._refresh_cooldown_active:
            logging.debug("Refresh button on cooldown, ignoring click")
            return
        
        logging.info("Refreshing backup list...")
        
        # Disable button and start cooldown
        self._refresh_cooldown_active = True
        self.refresh_button.setEnabled(False)
        original_text = self.refresh_button.text()
        
        # Perform refresh
        self.refresh_local_backups()
        
        # Also refresh cloud status if connected
        if self._is_any_provider_connected():
            self._refresh_cloud_status()
        
        # Create countdown timer
        remaining_seconds = self._refresh_cooldown_seconds
        
        def update_countdown():
            nonlocal remaining_seconds
            remaining_seconds -= 1
            if remaining_seconds > 0:
                self.refresh_button.setText(f"Wait {remaining_seconds}s...")
            else:
                # Cooldown finished
                self.refresh_button.setText(original_text)
                self.refresh_button.setEnabled(True)
                self._refresh_cooldown_active = False
        
        # Update button text immediately
        self.refresh_button.setText(f"Wait {remaining_seconds}s...")
        
        # Setup timer to update countdown every second
        QTimer.singleShot(1000, update_countdown)
        QTimer.singleShot(2000, update_countdown)
        QTimer.singleShot(3000, update_countdown)
    
    def _on_provider_changed(self, index):
        """Handle provider selection change in the dropdown."""
        provider_type = self.provider_combo.itemData(index)
        
        logging.info(f"Provider changed to: {provider_type}")
        
        # Update connect button text based on provider
        self._update_connect_button_for_provider(provider_type)
        
        # Update connection status
        self._update_connection_status_for_provider(provider_type)
        
        # Update configure button state (enabled/disabled based on provider)
        self._update_configure_button_state(provider_type)
        
        # Save the selected provider to settings
        self.cloud_settings['active_provider'] = provider_type
        cloud_settings_manager.save_cloud_settings(self.cloud_settings)
        
        # Disconnect from current provider if connected
        if self.drive_manager and self.drive_manager.is_connected:
            # Keep Google Drive connected for now, but in the future
            # we might want to ask user before disconnecting
            pass
        
        # Refresh the table to reflect the new provider status
        self._repopulate_table()
    
    def _update_connect_button_for_provider(self, provider_type):
        """Update the connect button text and visibility based on selected provider."""
        if provider_type == "google_drive":
            # Google Drive uses the connect button for Login/Logout
            self.connect_button.setVisible(True)
            if self.drive_manager and self.drive_manager.is_connected:
                self.connect_button.setText("Logout")
            else:
                self.connect_button.setText("Connect to Google Drive")
        else:
            # For FTP/SMB/WebDAV/Git, hide the connect button (they only use disconnect button)
            self.connect_button.setVisible(False)
    
    def _update_connection_status_for_provider(self, provider_type):
        """Update the connection status label and disconnect button for the selected provider."""
        if provider_type == "google_drive":
            if self.drive_manager and self.drive_manager.is_connected:
                self.connection_status_label.setText("● Connected")
                self.connection_status_label.setStyleSheet("color: #55FF55;")
                self.disconnect_button.setEnabled(True)
                self.disconnect_button.setText("Disconnect")
            else:
                self.connection_status_label.setText("● Not Connected")
                self.connection_status_label.setStyleSheet("color: #FF5555;")
                self.disconnect_button.setEnabled(False)
                self.disconnect_button.setText("Disconnect")
        elif provider_type == "smb":
            try:
                from cloud_utils.smb_provider import SMBProvider
                from cloud_utils.provider_factory import ProviderFactory, ProviderType
                
                smb_provider = ProviderFactory.get_provider(ProviderType.SMB)
                if smb_provider and smb_provider.is_connected:
                    self.connection_status_label.setText("● Connected")
                    self.connection_status_label.setStyleSheet("color: #55FF55;")
                    self.disconnect_button.setEnabled(True)
                    self.disconnect_button.setText("Disconnect")
                else:
                    self.connection_status_label.setText("● Not Connected")
                    self.connection_status_label.setStyleSheet("color: #FF5555;")
                    self.disconnect_button.setEnabled(True)
                    self.disconnect_button.setText("Connect to Network Folder")
            except ImportError:
                self.connection_status_label.setText("● Not Available")
                self.connection_status_label.setStyleSheet("color: #AAAAAA;")
                self.disconnect_button.setEnabled(False)
        elif provider_type == "ftp":
            try:
                from cloud_utils.ftp_provider import FTPProvider
                from cloud_utils.provider_factory import ProviderFactory, ProviderType
                
                ftp_provider = ProviderFactory.get_provider(ProviderType.FTP)
                if ftp_provider and ftp_provider.is_connected:
                    self.connection_status_label.setText("● Connected")
                    self.connection_status_label.setStyleSheet("color: #55FF55;")
                    self.disconnect_button.setEnabled(True)
                    self.disconnect_button.setText("Disconnect")
                else:
                    self.connection_status_label.setText("● Not Connected")
                    self.connection_status_label.setStyleSheet("color: #FF5555;")
                    self.disconnect_button.setEnabled(True)
                    self.disconnect_button.setText("Connect to FTP Server")
            except ImportError:
                self.connection_status_label.setText("● Not Available")
                self.connection_status_label.setStyleSheet("color: #AAAAAA;")
                self.disconnect_button.setEnabled(False)
                self.disconnect_button.setText("Disconnect")
        elif provider_type == "webdav":
            try:
                from cloud_utils.webdav_provider import WebDAVProvider
                from cloud_utils.provider_factory import ProviderFactory, ProviderType
                
                webdav_provider = ProviderFactory.get_provider(ProviderType.WEBDAV)
                if webdav_provider and webdav_provider.is_connected:
                    self.connection_status_label.setText("● Connected")
                    self.connection_status_label.setStyleSheet("color: #55FF55;")
                    self.disconnect_button.setEnabled(True)
                    self.disconnect_button.setText("Disconnect")
                else:
                    self.connection_status_label.setText("● Not Connected")
                    self.connection_status_label.setStyleSheet("color: #FF5555;")
                    self.disconnect_button.setEnabled(True)
                    self.disconnect_button.setText("Connect to WebDAV")
            except ImportError:
                self.connection_status_label.setText("● Not Available")
                self.connection_status_label.setStyleSheet("color: #AAAAAA;")
                self.disconnect_button.setEnabled(False)
                self.disconnect_button.setText("Disconnect")
        elif provider_type == "git":
            try:
                from cloud_utils.git_provider import GitProvider
                from cloud_utils.provider_factory import ProviderFactory, ProviderType
                
                git_provider = ProviderFactory.get_provider(ProviderType.GIT)
                if git_provider and git_provider.is_connected:
                    self.connection_status_label.setText("● Connected")
                    self.connection_status_label.setStyleSheet("color: #55FF55;")
                    self.disconnect_button.setEnabled(True)
                    self.disconnect_button.setText("Disconnect")
                else:
                    self.connection_status_label.setText("● Not Connected")
                    self.connection_status_label.setStyleSheet("color: #FF5555;")
                    self.disconnect_button.setEnabled(True)
                    self.disconnect_button.setText("Connect to Git")
            except ImportError:
                self.connection_status_label.setText("● Not Available")
                self.connection_status_label.setStyleSheet("color: #AAAAAA;")
                self.disconnect_button.setEnabled(False)
                self.disconnect_button.setText("Disconnect")
        else:
            self.connection_status_label.setText("● Not Connected")
            self.connection_status_label.setStyleSheet("color: #FF5555;")
            self.disconnect_button.setEnabled(False)
            self.disconnect_button.setText("Disconnect")
    
    def _update_configure_button_state(self, provider_type):
        """Enable/disable the Configure button based on the selected provider.
        
        Google Drive uses OAuth flow, so no configuration dialog is needed.
        Other providers (SMB, FTP, WebDAV) require manual configuration.
        """
        if provider_type == "google_drive":
            # Google Drive uses OAuth, disable configure button
            self.configure_provider_button.setEnabled(False)
            self.configure_provider_button.setToolTip("Google Drive uses OAuth authentication")
        else:
            # Other providers need configuration
            self.configure_provider_button.setEnabled(True)
            self.configure_provider_button.setToolTip("Configure the selected storage provider")
    
    def _on_configure_provider_clicked(self):
        """Open configuration dialog for the selected provider."""
        provider_type = self.provider_combo.currentData()
        
        logging.info(f"Opening configuration for provider: {provider_type}")
        
        if provider_type == "google_drive":
            # Google Drive doesn't have a separate config dialog
            # Just show a message
            QMessageBox.information(
                self,
                "Google Drive Configuration",
                "Google Drive is configured through the OAuth flow.\n\n"
                "Click 'Connect to Google Drive' to authenticate."
            )
        elif provider_type == "smb":
            self._show_smb_config_dialog()
        elif provider_type == "ftp":
            self._show_ftp_config_dialog()
        elif provider_type == "webdav":
            self._show_webdav_config_dialog()
        elif provider_type == "git":
            self._show_git_config_dialog()
    
    def _show_smb_config_dialog(self):
        """Show the SMB configuration dialog."""
        try:
            from cloud_utils.smb_config_dialog import SMBConfigDialog
            
            # Pass current settings
            current_config = {
                'smb_path': self.cloud_settings.get('smb_path', ''),
                'smb_use_credentials': self.cloud_settings.get('smb_use_credentials', False),
                'smb_username': self.cloud_settings.get('smb_username', ''),
                'smb_auto_connect': self.cloud_settings.get('smb_auto_connect', False)
            }
            
            dialog = SMBConfigDialog(self, current_config)
            dialog.config_saved.connect(self._on_smb_config_saved)
            dialog.exec()
            
        except Exception as e:
            logging.error(f"Error showing SMB config dialog: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Could not open configuration dialog:\n{str(e)}"
            )
    
    def _on_smb_config_saved(self, config):
        """Handle SMB configuration saved."""
        logging.info(f"SMB configuration saved: {config}")
        
        # Update cloud settings
        self.cloud_settings.update(config)
        cloud_settings_manager.save_cloud_settings(self.cloud_settings)
        
        # If auto-connect is enabled and we have a path, try to connect
        if config.get('smb_auto_connect') and config.get('smb_path'):
            self._connect_to_smb()
    
    def _connect_to_smb(self):
        """Connect to the configured SMB network folder."""
        try:
            from cloud_utils.smb_provider import SMBProvider
            from cloud_utils.provider_factory import ProviderFactory, ProviderType
            
            smb_path = self.cloud_settings.get('smb_path', '')
            if not smb_path:
                # SMB is not configured, open config dialog automatically
                logging.info("SMB not configured, opening config dialog")
                self._show_smb_config_dialog()
                return
            
            # Get or create SMB provider
            smb_provider = ProviderFactory.get_provider(ProviderType.SMB)
            if not smb_provider:
                QMessageBox.critical(
                    self,
                    "Error",
                    "SMB provider is not available."
                )
                return
            
            # Connect
            success = smb_provider.connect(
                path=smb_path,
                use_credentials=self.cloud_settings.get('smb_use_credentials', False),
                username=self.cloud_settings.get('smb_username', '')
            )
            
            if success:
                self.connection_status_label.setText("● Connected")
                self.connection_status_label.setStyleSheet("color: #55FF55;")
                self.disconnect_button.setText("Disconnect")
                self.disconnect_button.setEnabled(True)
                
                # Refresh the backup list to show cloud backups
                self.refresh_local_backups()
                self._refresh_cloud_status()
                
                logging.info(f"Connected to SMB: {smb_path}")
            else:
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"Could not connect to:\n{smb_path}\n\n"
                    "Please check that the path is accessible."
                )
                
        except Exception as e:
            logging.error(f"Error connecting to SMB: {e}")
            QMessageBox.critical(
                self,
                "Connection Error",
                f"Error connecting to network folder:\n{str(e)}"
            )
    
    def _show_ftp_config_dialog(self):
        """Show the FTP configuration dialog."""
        try:
            from cloud_utils.ftp_config_dialog import FTPConfigDialog
            
            # Pass current settings
            current_config = {
                'ftp_host': self.cloud_settings.get('ftp_host', ''),
                'ftp_port': self.cloud_settings.get('ftp_port', 21),
                'ftp_base_path': self.cloud_settings.get('ftp_base_path', '/'),
                'ftp_username': self.cloud_settings.get('ftp_username', 'anonymous'),
                'ftp_use_tls': self.cloud_settings.get('ftp_use_tls', False),
                'ftp_passive_mode': self.cloud_settings.get('ftp_passive_mode', True),
                'ftp_auto_connect': self.cloud_settings.get('ftp_auto_connect', False)
            }
            
            dialog = FTPConfigDialog(self, current_config)
            dialog.config_saved.connect(self._on_ftp_config_saved)
            dialog.exec()
            
        except Exception as e:
            logging.error(f"Error showing FTP config dialog: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Could not open configuration dialog:\n{str(e)}"
            )
    
    def _on_ftp_config_saved(self, config):
        """Handle FTP configuration saved."""
        logging.info(f"FTP configuration saved: {config}")
        
        # Update cloud settings
        self.cloud_settings.update(config)
        cloud_settings_manager.save_cloud_settings(self.cloud_settings)
        
        # If auto-connect is enabled and we have a host, try to connect
        if config.get('ftp_auto_connect') and config.get('ftp_host'):
            self._connect_to_ftp()
    
    def _connect_to_ftp(self):
        """Connect to the configured FTP server."""
        try:
            from cloud_utils.ftp_provider import FTPProvider
            from cloud_utils.provider_factory import ProviderFactory, ProviderType
            
            ftp_host = self.cloud_settings.get('ftp_host', '')
            if not ftp_host:
                # FTP is not configured, open config dialog automatically
                logging.info("FTP not configured, opening config dialog")
                self._show_ftp_config_dialog()
                return
            
            # Get or create FTP provider
            ftp_provider = ProviderFactory.get_provider(ProviderType.FTP)
            if not ftp_provider:
                QMessageBox.critical(
                    self,
                    "Error",
                    "FTP provider is not available."
                )
                return
            
            # Connect
            success = ftp_provider.connect(
                host=ftp_host,
                port=self.cloud_settings.get('ftp_port', 21),
                username=self.cloud_settings.get('ftp_username', 'anonymous'),
                password=self.cloud_settings.get('ftp_password', ''),
                use_tls=self.cloud_settings.get('ftp_use_tls', False),
                passive_mode=self.cloud_settings.get('ftp_passive_mode', True),
                base_path=self.cloud_settings.get('ftp_base_path', '/')
            )
            
            if success:
                self.connection_status_label.setText("● Connected")
                self.connection_status_label.setStyleSheet("color: #55FF55;")
                self.disconnect_button.setText("Disconnect")
                self.disconnect_button.setEnabled(True)
                
                # Refresh the backup list to show cloud backups
                self.refresh_local_backups()
                self._refresh_cloud_status()
                
                logging.info(f"Connected to FTP: {ftp_host}")
            else:
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"Could not connect to:\n{ftp_host}\n\n"
                    "Please check your settings and try again."
                )
                
        except Exception as e:
            logging.error(f"Error connecting to FTP: {e}")
            QMessageBox.critical(
                self,
                "Connection Error",
                f"Error connecting to FTP server:\n{str(e)}"
            )
    
    def _show_webdav_config_dialog(self):
        """Show the WebDAV configuration dialog."""
        try:
            from cloud_utils.webdav_config_dialog import WebDAVConfigDialog
            
            # Pass current settings
            current_config = {
                'webdav_url': self.cloud_settings.get('webdav_url', ''),
                'webdav_username': self.cloud_settings.get('webdav_username', ''),
                'webdav_verify_ssl': self.cloud_settings.get('webdav_verify_ssl', True),
                'webdav_use_digest': self.cloud_settings.get('webdav_use_digest', False),
                'webdav_auto_connect': self.cloud_settings.get('webdav_auto_connect', False)
            }
            
            dialog = WebDAVConfigDialog(self, current_config)
            dialog.config_saved.connect(self._on_webdav_config_saved)
            dialog.exec()
            
        except Exception as e:
            logging.error(f"Error showing WebDAV config dialog: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Could not open configuration dialog:\n{str(e)}"
            )
    
    def _on_webdav_config_saved(self, config):
        """Handle WebDAV configuration saved."""
        logging.info(f"WebDAV configuration saved: {config}")
        
        # Update cloud settings
        self.cloud_settings.update(config)
        cloud_settings_manager.save_cloud_settings(self.cloud_settings)
        
        # If auto-connect is enabled and we have a URL, try to connect
        if config.get('webdav_auto_connect') and config.get('webdav_url'):
            self._connect_to_webdav()
    
    def _connect_to_webdav(self):
        """Connect to the configured WebDAV server."""
        try:
            from cloud_utils.webdav_provider import WebDAVProvider
            from cloud_utils.provider_factory import ProviderFactory, ProviderType
            
            webdav_url = self.cloud_settings.get('webdav_url', '')
            if not webdav_url:
                # WebDAV is not configured, open config dialog automatically
                logging.info("WebDAV not configured, opening config dialog")
                self._show_webdav_config_dialog()
                return
            
            # Get or create WebDAV provider
            webdav_provider = ProviderFactory.get_provider(ProviderType.WEBDAV)
            if not webdav_provider:
                QMessageBox.critical(
                    self,
                    "Error",
                    "WebDAV provider is not available."
                )
                return
            
            # Connect
            success = webdav_provider.connect(
                url=webdav_url,
                username=self.cloud_settings.get('webdav_username', ''),
                password=self.cloud_settings.get('webdav_password', ''),
                use_digest_auth=self.cloud_settings.get('webdav_use_digest', False),
                verify_ssl=self.cloud_settings.get('webdav_verify_ssl', True)
            )
            
            if success:
                self.connection_status_label.setText("● Connected")
                self.connection_status_label.setStyleSheet("color: #55FF55;")
                self.disconnect_button.setText("Disconnect")
                self.disconnect_button.setEnabled(True)
                
                # Refresh the backup list to show cloud backups
                self.refresh_local_backups()
                self._refresh_cloud_status()
                
                logging.info(f"Connected to WebDAV: {webdav_url}")
            else:
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"Could not connect to:\n{webdav_url}\n\n"
                    "Please check your settings and try again."
                )
                
        except Exception as e:
            logging.error(f"Error connecting to WebDAV: {e}")
            QMessageBox.critical(
                self,
                "Connection Error",
                f"Error connecting to WebDAV server:\n{str(e)}"
            )
    
    def _show_git_config_dialog(self):
        """Show the Git configuration dialog."""
        try:
            from cloud_utils.git_config_dialog import GitConfigDialog
            
            current_config = {
                'git_repo_path': self.cloud_settings.get('git_repo_path', ''),
                'git_branch': self.cloud_settings.get('git_branch', 'main'),
                'git_remote_url': self.cloud_settings.get('git_remote_url', ''),
                'git_auto_push': self.cloud_settings.get('git_auto_push', True),
                'git_auto_pull': self.cloud_settings.get('git_auto_pull', True),
                'git_auto_connect': self.cloud_settings.get('git_auto_connect', False)
            }
            
            dialog = GitConfigDialog(self, current_config)
            dialog.config_saved.connect(self._on_git_config_saved)
            dialog.exec()
            
        except Exception as e:
            logging.error(f"Error showing Git config dialog: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Could not open configuration dialog:\n{str(e)}"
            )
    
    def _on_git_config_saved(self, config):
        """Handle Git configuration saved."""
        logging.info(f"Git configuration saved: {config}")
        self.cloud_settings.update(config)
        cloud_settings_manager.save_cloud_settings(self.cloud_settings)
        if config.get('git_auto_connect') and config.get('git_repo_path'):
            self._connect_to_git()
    
    def _connect_to_git(self):
        """Connect to the configured Git repository."""
        try:
            from cloud_utils.git_provider import GitProvider
            from cloud_utils.provider_factory import ProviderFactory, ProviderType
            
            repo_path = self.cloud_settings.get('git_repo_path', '')
            if not repo_path:
                logging.info("Git not configured, opening config dialog")
                self._show_git_config_dialog()
                return
            
            git_provider = ProviderFactory.get_provider(ProviderType.GIT)
            if not git_provider:
                QMessageBox.critical(
                    self,
                    "Error",
                    "Git provider is not available. Ensure Git is installed."
                )
                return
            
            success = git_provider.connect(
                repo_path=repo_path,
                remote_url=self.cloud_settings.get('git_remote_url', '') or None,
                branch=self.cloud_settings.get('git_branch', 'main'),
                auto_push=self.cloud_settings.get('git_auto_push', True),
                auto_pull=self.cloud_settings.get('git_auto_pull', True)
            )
            
            if success:
                self.connection_status_label.setText("● Connected")
                self.connection_status_label.setStyleSheet("color: #55FF55;")
                self.disconnect_button.setText("Disconnect")
                self.disconnect_button.setEnabled(True)
                self.refresh_local_backups()
                self._refresh_cloud_status()
                logging.info(f"Connected to Git: {repo_path}")
            else:
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"Could not connect to repository:\n{repo_path}\n\n"
                    "Ensure Git is installed and the path is valid."
                )
                
        except Exception as e:
            logging.error(f"Error connecting to Git: {e}")
            QMessageBox.critical(
                self,
                "Connection Error",
                f"Error connecting to Git repository:\n{str(e)}"
            )
    
    def _on_connect_or_logout_clicked(self):
        """Handle Connect button click - acts as Connect or Logout depending on state."""
        provider_type = self.provider_combo.currentData()
        
        if provider_type == "google_drive":
            # Original Google Drive logic
            if self.drive_manager.is_connected:
                self._on_logout_clicked()
            else:
                self._on_connect_clicked()
        elif provider_type == "smb":
            # SMB connection logic
            from cloud_utils.provider_factory import ProviderFactory, ProviderType
            smb_provider = ProviderFactory.get_provider(ProviderType.SMB)
            
            if smb_provider and smb_provider.is_connected:
                # Disconnect
                smb_provider.disconnect()
                self.connection_status_label.setText("● Not Connected")
                self.connection_status_label.setStyleSheet("color: #FF5555;")
                self.connect_button.setText("Connect to Network Folder")
                self.disconnect_button.setEnabled(False)
                
                # Disable action buttons
                self.upload_button.setEnabled(False)
                self.download_button.setEnabled(False)
                self.delete_button.setEnabled(False)
                self.delete_button.setStyleSheet("""
                    QPushButton {
                        background-color: #555555;
                        color: #888888;
                        border: 1px solid #444444;
                    }
                    QPushButton:hover {
                        background-color: #555555;
                        color: #888888;
                    }
                """)
                
                self._repopulate_table()
            else:
                # Connect
                self._connect_to_smb()
        elif provider_type == "ftp":
            # FTP connection logic
            from cloud_utils.provider_factory import ProviderFactory, ProviderType
            ftp_provider = ProviderFactory.get_provider(ProviderType.FTP)
            
            if ftp_provider and ftp_provider.is_connected:
                # Disconnect
                ftp_provider.disconnect()
                self.connection_status_label.setText("● Not Connected")
                self.connection_status_label.setStyleSheet("color: #FF5555;")
                self.connect_button.setText("Connect to FTP Server")
                self.disconnect_button.setEnabled(False)
                
                # Disable action buttons
                self.upload_button.setEnabled(False)
                self.download_button.setEnabled(False)
                self.delete_button.setEnabled(False)
                self.delete_button.setStyleSheet("""
                    QPushButton {
                        background-color: #555555;
                        color: #888888;
                        border: 1px solid #444444;
                    }
                    QPushButton:hover {
                        background-color: #555555;
                        color: #888888;
                    }
                """)
                
                self._repopulate_table()
            else:
                # Connect
                self._connect_to_ftp()
        elif provider_type == "webdav":
            # WebDAV connection logic
            from cloud_utils.provider_factory import ProviderFactory, ProviderType
            webdav_provider = ProviderFactory.get_provider(ProviderType.WEBDAV)
            
            if webdav_provider and webdav_provider.is_connected:
                # Disconnect
                webdav_provider.disconnect()
                self.connection_status_label.setText("● Not Connected")
                self.connection_status_label.setStyleSheet("color: #FF5555;")
                self.connect_button.setText("Connect to WebDAV")
                self.disconnect_button.setEnabled(False)
                
                # Disable action buttons
                self.upload_button.setEnabled(False)
                self.download_button.setEnabled(False)
                self.delete_button.setEnabled(False)
                self.delete_button.setStyleSheet("""
                    QPushButton {
                        background-color: #555555;
                        color: #888888;
                        border: 1px solid #444444;
                    }
                    QPushButton:hover {
                        background-color: #555555;
                        color: #888888;
                    }
                """)
                
                self._repopulate_table()
            else:
                # Connect
                self._connect_to_webdav()
        elif provider_type == "git":
            # Git connection logic
            from cloud_utils.provider_factory import ProviderFactory, ProviderType
            git_provider = ProviderFactory.get_provider(ProviderType.GIT)
            
            if git_provider and git_provider.is_connected:
                # Disconnect
                git_provider.disconnect()
                self.connection_status_label.setText("● Not Connected")
                self.connection_status_label.setStyleSheet("color: #FF5555;")
                self.disconnect_button.setText("Connect to Git")
                self.disconnect_button.setEnabled(True)
                
                # Disable action buttons
                self.upload_button.setEnabled(False)
                self.download_button.setEnabled(False)
                self.delete_button.setEnabled(False)
                self.delete_button.setStyleSheet("""
                    QPushButton {
                        background-color: #555555;
                        color: #888888;
                        border: 1px solid #444444;
                    }
                    QPushButton:hover {
                        background-color: #555555;
                        color: #888888;
                    }
                """)
                
                self._repopulate_table()
            else:
                # Connect
                self._connect_to_git()
        else:
            QMessageBox.information(
                self,
                "Not Implemented",
                f"Connection for {provider_type} is not yet implemented."
            )
    
    def _on_connect_clicked(self):
        """Handle Google Drive connection."""
        logging.info("Connecting to Google Drive...")
        
        # Cancel any previous auth worker (don't kill thread, just ignore its results)
        if self._current_auth_worker is not None:
            try:
                self._current_auth_worker.cancel()
                logging.info("Cancelled previous auth worker")
            except Exception as e:
                logging.debug(f"Could not cancel previous worker: {e}")
        
        # Clean up finished/deleted threads from the list
        self._cleanup_finished_auth_threads()
        
        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.progress_bar.setFormat("Authenticating...")
        self.connect_button.setEnabled(False)
        
        # Create worker with unique ID
        self._auth_worker_counter += 1
        worker_id = self._auth_worker_counter
        
        # Create worker and thread
        auth_thread = QThread()
        auth_worker = AuthWorker(self.drive_manager, worker_id)
        auth_worker.moveToThread(auth_thread)
        
        # Store reference to current worker
        self._current_auth_worker = auth_worker
        
        # Add thread and worker to active lists to prevent premature destruction
        self._active_auth_threads.append(auth_thread)
        self._active_auth_workers.append(auth_worker)
        
        # Connect signals
        auth_thread.started.connect(auth_worker.run)
        # Linux fix: show URL for manual browser opening (use QueuedConnection for thread safety)
        auth_worker.auth_url_ready.connect(self._show_auth_url_dialog, Qt.ConnectionType.QueuedConnection)
        auth_worker.finished.connect(self._on_auth_finished)
        auth_worker.finished.connect(auth_thread.quit)
        auth_worker.finished.connect(auth_worker.deleteLater)
        auth_worker.finished.connect(lambda: self._remove_worker_from_list(auth_worker))
        auth_thread.finished.connect(auth_thread.deleteLater)
        
        # Start authentication
        auth_thread.start()

        # Setup a timeout in case the OAuth window is closed/denied and never returns
        try:
            if hasattr(self, 'auth_timeout_timer') and self.auth_timeout_timer:
                try:
                    self.auth_timeout_timer.stop()
                except Exception:
                    pass
            from PySide6.QtCore import QTimer
            self.auth_timeout_timer = QTimer(self)
            self.auth_timeout_timer.setSingleShot(True)
            # 60 seconds timeout; if exceeded, abort and restore UI
            self.auth_timeout_timer.timeout.connect(self._on_auth_timeout)
            self.auth_timeout_timer.start(60000)
        except Exception:
            pass
    
    def _on_auth_finished(self, success, error_message):
        """Handle authentication completion."""
        self.progress_bar.setVisible(False)
        self.connect_button.setEnabled(True)

        # Stop timeout timer if running
        try:
            if hasattr(self, 'auth_timeout_timer') and self.auth_timeout_timer:
                self.auth_timeout_timer.stop()
                self.auth_timeout_timer = None
        except Exception:
            pass
        
        # Note: auth_thread will be set to None automatically via the lambda signal connection
        
        if success:
            self._set_connected(True)
            self._refresh_cloud_status()
            
            # Setup periodic sync if enabled
            self._setup_periodic_sync()
            
            # Update storage status bars if settings panel is visible
            try:
                if self.stacked_widget.currentIndex() == 1 and hasattr(self, 'settings_panel') and self.settings_panel:
                    self.settings_panel.refresh_storage_status()
            except Exception:
                pass
        else:
            self._set_connected(False)
            QMessageBox.warning(
                self,
                "Connection Failed",
                f"Could not connect to Google Drive.\n\n"
                f"{error_message}\n\n"
                "Please make sure:\n"
                "• You have a valid client_secret.json file\n"
                "• You authorized the application in your browser\n"
                "• You have an active internet connection"
            )
        
        # Close the auth URL dialog if it's open
        self._close_auth_url_dialog()

    def _show_auth_url_dialog(self, url: str):
        """
        Show dialog with authorization URL for manual browser opening.
        This is useful on Linux where webbrowser.open() may fail silently.
        """
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QApplication
        from PySide6.QtCore import Qt

        logging.info(f"_show_auth_url_dialog called with URL length: {len(url) if url else 0}")
        
        # Close any existing dialog first
        self._close_auth_url_dialog()
        
        # Store URL for copy functionality
        self._auth_url = url if url else ""

        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Google Drive Authorization")
        dialog.setMinimumWidth(550)
        dialog.setModal(False)  # Non-modal so user can interact with browser

        layout = QVBoxLayout(dialog)

        # Instruction label
        instruction_label = QLabel(
            "A browser window should open for authorization.\n\n"
            "If the browser didn't open automatically, copy the URL below\n"
            "and paste it into your browser to authorize SaveState:"
        )
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        # URL text field (read-only, selectable) - use QLineEdit for single line
        url_field = QLineEdit()
        url_field.setText(self._auth_url)
        url_field.setReadOnly(True)
        url_field.setStyleSheet("QLineEdit { background-color: #2a2a2a; color: #ffffff; padding: 8px; }")
        url_field.setCursorPosition(0)  # Show start of URL
        layout.addWidget(url_field)
        
        # Store reference to update if needed
        self._auth_url_field = url_field

        # Button row
        button_layout = QHBoxLayout()

        # Copy button
        copy_button = QPushButton("Copy URL")
        def copy_url():
            clipboard = QApplication.clipboard()
            clipboard.setText(self._auth_url)
            copy_button.setText("Copied!")
            logging.info("Auth URL copied to clipboard")
            # Reset button text after 2 seconds
            QTimer.singleShot(2000, lambda: copy_button.setText("Copy URL") if copy_button else None)
        copy_button.clicked.connect(copy_url)
        button_layout.addWidget(copy_button)

        button_layout.addStretch()
        
        # Cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self._cancel_auth_from_dialog)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)
        
        # Info label
        info_label = QLabel("This dialog will close automatically when authorization completes.")
        info_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(info_label)

        # Store reference to dialog so we can close it later
        self._auth_url_dialog = dialog
        
        # Connect dialog rejected (X button) to cancel auth
        dialog.rejected.connect(self._cancel_auth_from_dialog)

        dialog.show()
        logging.info(f"Displayed auth URL dialog for manual browser opening (URL: {self._auth_url[:50]}...)")

    def _close_auth_url_dialog(self):
        """Close the auth URL dialog if it's open."""
        try:
            if hasattr(self, '_auth_url_dialog') and self._auth_url_dialog:
                # Disconnect rejected signal to prevent recursive cancel
                try:
                    self._auth_url_dialog.rejected.disconnect()
                except Exception:
                    pass
                self._auth_url_dialog.close()
                self._auth_url_dialog.deleteLater()
                self._auth_url_dialog = None
                logging.debug("Closed auth URL dialog")
        except Exception as e:
            logging.debug(f"Error closing auth URL dialog: {e}")
            self._auth_url_dialog = None
    
    def _cancel_auth_from_dialog(self):
        """Cancel authentication when user closes the auth URL dialog or clicks Cancel."""
        logging.info("User cancelled authentication from dialog")
        
        # Close the dialog first
        self._close_auth_url_dialog()
        
        # Cancel the current auth worker
        if self._current_auth_worker is not None:
            try:
                self._current_auth_worker.cancel()
                logging.info("Cancelled auth worker from dialog")
            except Exception as e:
                logging.debug(f"Could not cancel auth worker: {e}")
            self._current_auth_worker = None
        
        # Stop timeout timer if running
        try:
            if hasattr(self, 'auth_timeout_timer') and self.auth_timeout_timer:
                self.auth_timeout_timer.stop()
                self.auth_timeout_timer = None
        except Exception:
            pass
        
        # Restore UI state
        try:
            self.progress_bar.setVisible(False)
            self.connect_button.setEnabled(True)
            self._set_connected(False)
        except Exception as e:
            logging.debug(f"Error restoring UI after auth cancel: {e}")

    def _on_auth_timeout(self):
        """Abort authentication if it takes too long (e.g., user closed or denied)."""
        logging.warning("Authentication timeout reached. Aborting and restoring UI.")

        # Close auth URL dialog if open
        self._close_auth_url_dialog()

        # Cancel the current worker (don't kill thread - let it finish naturally)
        # The OAuth flow will eventually timeout or complete, but we'll ignore the results
        if self._current_auth_worker is not None:
            try:
                self._current_auth_worker.cancel()
                logging.info("Cancelled auth worker due to timeout")
            except Exception as e:
                logging.debug(f"Could not cancel worker: {e}")
            self._current_auth_worker = None

        # NOTE: We do NOT terminate the thread! OAuth flow is blocking and cannot be interrupted.
        # The thread will finish naturally when OAuth completes or times out.
        # This prevents the "QThread: Destroyed while thread is still running" crash.

        # Restore UI state
        try:
            self.progress_bar.setVisible(False)
            self.connect_button.setEnabled(True)
            self._set_connected(False)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Authentication Cancelled",
                "Authentication timed out or was cancelled.\n\n"
                "You can try connecting again. If you complete the authorization in your browser, "
                "it will be saved for next time."
            )
        except Exception as e:
            logging.error(f"Error restoring UI after timeout: {e}")
    
    def _on_disconnect_clicked(self):
        """Handle disconnect/connect button click based on current provider and state."""
        provider_type = self.provider_combo.currentData()
        
        if provider_type == "google_drive":
            # Google Drive disconnection
            logging.info("Disconnecting from Google Drive...")
            self.drive_manager.disconnect()
            self._set_connected(False)
            self.cloud_backups.clear()
            self._repopulate_table()  # Refresh to clear cloud status
            # If settings panel is open, update usage bars to "Not connected"
            try:
                if self.stacked_widget.currentIndex() == 1 and hasattr(self, 'settings_panel') and self.settings_panel:
                    self.settings_panel.refresh_storage_status()
            except Exception:
                pass
        else:
            # For FTP/SMB/WebDAV, the disconnect button acts as connect/disconnect toggle
            active_provider = self._get_active_provider()
            
            # Check if provider thinks it's connected
            provider_thinks_connected = active_provider and active_provider.is_connected
            
            # Check if UI thinks we're connected (button shows "Disconnect")
            ui_shows_connected = self.disconnect_button.text() == "Disconnect"
            
            # If UI shows connected but provider is not, sync the UI
            if ui_shows_connected and not provider_thinks_connected:
                logging.warning(f"UI out of sync with provider state, updating UI to disconnected")
                self.cloud_backups.clear()
                
                # Force update the button text and status
                if provider_type == "smb":
                    self.disconnect_button.setText("Connect to Network Folder")
                elif provider_type == "ftp":
                    self.disconnect_button.setText("Connect to FTP Server")
                elif provider_type == "webdav":
                    self.disconnect_button.setText("Connect to WebDAV")
                elif provider_type == "git":
                    self.disconnect_button.setText("Connect to Git")
                
                self.disconnect_button.setEnabled(True)
                self.connection_status_label.setText("● Not Connected")
                self.connection_status_label.setStyleSheet("color: #FF5555;")
                self._repopulate_table()
                
                # Show message that connection was lost
                QMessageBox.warning(
                    self,
                    "Connection Lost",
                    f"The connection to {provider_type} was lost or is no longer accessible.\n\n"
                    f"You can try connecting again."
                )
                return
            
            if provider_thinks_connected:
                # Disconnect
                logging.info(f"Disconnecting from {provider_type}...")
                try:
                    active_provider.disconnect()
                    logging.info(f"Successfully disconnected from {provider_type}")
                except Exception as e:
                    logging.error(f"Error during disconnect: {e}")
                    # Force disconnect even if it failed
                    if active_provider:
                        active_provider._connected = False
                
                # Always update UI after disconnect attempt (even if it failed)
                self.cloud_backups.clear()
                
                # Force update the button text and status
                if provider_type == "smb":
                    self.disconnect_button.setText("Connect to Network Folder")
                    self.disconnect_button.setEnabled(True)
                    self.connection_status_label.setText("● Not Connected")
                    self.connection_status_label.setStyleSheet("color: #FF5555;")
                elif provider_type == "ftp":
                    self.disconnect_button.setText("Connect to FTP Server")
                    self.disconnect_button.setEnabled(True)
                    self.connection_status_label.setText("● Not Connected")
                    self.connection_status_label.setStyleSheet("color: #FF5555;")
                elif provider_type == "webdav":
                    self.disconnect_button.setText("Connect to WebDAV")
                    self.disconnect_button.setEnabled(True)
                    self.connection_status_label.setText("● Not Connected")
                    self.connection_status_label.setStyleSheet("color: #FF5555;")
                elif provider_type == "git":
                    self.disconnect_button.setText("Connect to Git")
                    self.disconnect_button.setEnabled(True)
                    self.connection_status_label.setText("● Not Connected")
                    self.connection_status_label.setStyleSheet("color: #FF5555;")
                
                self._repopulate_table()
            else:
                # Connect
                if provider_type == "ftp":
                    self._connect_to_ftp()
                elif provider_type == "smb":
                    self._connect_to_smb()
                elif provider_type == "webdav":
                    self._connect_to_webdav()
                elif provider_type == "git":
                    self._connect_to_git()
    
    def _on_logout_clicked(self):
        """Handle logout - delete token file and disconnect."""
        # Show confirmation dialog (important since button is near disconnect)
        reply = QMessageBox.question(
            self,
            "Confirm Logout",
            "Are you sure you want to logout from Google Drive?\n\n"
            "This will delete your saved credentials and you will need to\n"
            "re-authenticate next time you connect.\n\n"
            "This action cannot be undone!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        logging.info("Logging out from Google Drive...")
        
        try:
            # Disconnect first
            self.drive_manager.disconnect()
            self._set_connected(False)
            self.cloud_backups.clear()
            self._repopulate_table()
            
            # Delete token file
            token_file = self.drive_manager.token_file
            if token_file.exists():
                token_file.unlink()
                logging.info(f"Token file deleted: {token_file}")
                QMessageBox.information(
                    self,
                    "Logout Successful",
                    "You have been logged out successfully.\n\n"
                    "Your saved credentials have been deleted."
                )
            else:
                logging.warning("Token file not found during logout")
                QMessageBox.information(
                    self,
                    "Logout Complete",
                    "Logged out (no saved credentials found)."
                )
            
            # Update settings panel if open
            try:
                if self.stacked_widget.currentIndex() == 1 and hasattr(self, 'settings_panel') and self.settings_panel:
                    self.settings_panel.refresh_storage_status()
            except Exception:
                pass
                
        except Exception as e:
            logging.error(f"Error during logout: {e}")
            QMessageBox.critical(
                self,
                "Logout Error",
                f"An error occurred during logout:\n{str(e)}"
            )
    
    def _set_connected(self, connected):
        """Update UI based on connection status."""
        if connected:
            # Transform connect button to logout button
            self.connect_button.setText("Logout")
            self.connect_button.setToolTip("Delete saved credentials and logout from Google Drive")
            self.connect_button.setEnabled(True)
            
            self.connection_status_label.setText("● Connected")
            self.connection_status_label.setStyleSheet("color: #4CAF50;")
            self.disconnect_button.setEnabled(True)
            
            # Update button states based on selection
            self._update_action_buttons_state()
        else:
            # Restore connect button
            self.connect_button.setText("Connect to Google Drive")
            self.connect_button.setToolTip("")
            self.connect_button.setEnabled(True)
            
            self.connection_status_label.setText("● Not Connected")
            self.connection_status_label.setStyleSheet("color: #FF5555;")
            self.disconnect_button.setEnabled(False)
            
            # Disable all action buttons when disconnected
            self.upload_button.setEnabled(False)
            self.download_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            # Apply disabled styling to make it visually clear it's disabled
            self.delete_button.setStyleSheet("""
                QPushButton {
                    background-color: #555555;
                    color: #888888;
                    border: 1px solid #444444;
                }
                QPushButton:hover {
                    background-color: #555555;
                    color: #888888;
                }
            """)
        
        # Reapply fixed width to maintain button size
        self.connect_button.setFixedWidth(self._connect_button_fixed_width)
    
    def _disable_buttons_during_operation(self):
        """Disable buttons during cloud operations."""
        self.upload_button.setEnabled(False)
        self.download_button.setEnabled(False)
        # Only disable refresh if it's showing the button (not the search bar)
        if self.refresh_search_stack.currentIndex() == 0:
            self.refresh_button.setEnabled(False)
    
    def _enable_buttons_after_operation(self):
        """Re-enable buttons after cloud operations complete."""
        # Update button states based on current selection
        self._update_action_buttons_state()
        
        # Always re-enable refresh button (if visible)
        if self.refresh_search_stack.currentIndex() == 0:
            self.refresh_button.setEnabled(True)
    
    def _on_upload_clicked(self):
        """Handle upload selected backups to cloud."""
        # Check if there's already an operation in progress
        if self._current_worker is not None or getattr(self, '_current_operation', None) == 'storage_check':
            QMessageBox.warning(
                self, 
                "Operation in Progress", 
                "Please wait for the current operation to complete before starting a new one."
            )
            return
        
        selected = self._get_selected_backups()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select backups to upload.")
            return
        
        # Get active provider
        active_provider = self._get_active_provider()
        if not active_provider:
            QMessageBox.warning(self, "No Provider", "No storage provider is selected.")
            return
            
        if not active_provider.is_connected:
            QMessageBox.warning(self, "Not Connected", "Please connect to the storage provider first.")
            return

        # Disable buttons immediately and show cancel button
        self._disable_buttons_during_operation()
        self._set_delete_button_to_cancel_mode()
        
        # Show indeterminate progress bar initially
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Preparing upload...")
        
        # Force immediate UI update
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        
        # Check storage limit asynchronously if enabled (avoid blocking the UI thread)
        # Only if provider supports it or worker handles it gracefully (which it now does)
        if self.cloud_settings.get('max_cloud_storage_enabled', False):
            max_storage_gb = self.cloud_settings.get('max_cloud_storage_gb', 5)
            
            self.progress_bar.setFormat("Checking storage...")
            
            # Launch background worker
            try:
                self._pending_upload_selection = selected
                self._current_operation = 'storage_check' # Mark operation type
                self._storage_check_cancelled = False # Reset cancel flag
                
                self._storage_check_thread = QThread()
                self._storage_check_worker = StorageCheckWorker(active_provider, max_storage_gb)
                self._storage_check_worker.moveToThread(self._storage_check_thread)
                self._storage_check_thread.started.connect(self._storage_check_worker.run)
                self._storage_check_worker.finished.connect(self._on_storage_check_finished)
                self._storage_check_worker.error.connect(self._on_storage_check_error)
                self._storage_check_worker.finished.connect(self._storage_check_thread.quit)
                self._storage_check_worker.finished.connect(self._storage_check_worker.deleteLater)
                self._storage_check_thread.finished.connect(self._storage_check_thread.deleteLater)
                self._storage_check_thread.start()
                return  # Continue after check completes
            except Exception as e:
                logging.error(f"Could not start storage check worker: {e}")
                # Fall through to start upload (but first reset UI state slightly to allow start_upload to handle it)
                self._current_operation = None
        
        # No storage limit enabled or check failed to start; start upload immediately
        self._start_upload_selected(selected)
    
    def _on_storage_check_finished(self, within_limit: bool, current_gb: float, max_gb: int):
        """Handle completion of background storage limit check."""
        # Check for cancellation
        if getattr(self, '_storage_check_cancelled', False):
            logging.info("Storage check cancelled, ignoring result.")
            self._current_operation = None
            return

        # Hide indeterminate progress used for storage check
        # Don't hide it if we are proceeding to upload, let upload handle it
        # But if we stop (limit reached), we should hide it.
        
        try:
            if not within_limit:
                self.progress_bar.setVisible(False)
                self._enable_buttons_after_operation()
                self._set_delete_button_to_delete_mode()
                self._current_operation = None
                
                QMessageBox.warning(
                    self,
                    "Storage Limit Reached",
                    f"Cloud storage limit reached!\n\n"
                    f"Current: {current_gb} GB\n"
                    f"Limit: {max_gb} GB\n\n"
                    f"Please delete old backups or increase the limit in settings."
                )
                self._pending_upload_selection = None
                return

            # Warn if close to limit
            try:
                if max_gb and current_gb > (max_gb * 0.8):
                    # We need to hide progress temporarily to show dialog? 
                    # Or just show dialog on top.
                    reply = QMessageBox.question(
                        self,
                        "Storage Warning",
                        f"Cloud storage is at {int((current_gb/max_gb)*100)}% of limit.\n\n"
                        f"Current: {current_gb} GB\n"
                        f"Limit: {max_gb} GB\n\n"
                        f"Continue with upload?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.No:
                        self.progress_bar.setVisible(False)
                        self._enable_buttons_after_operation()
                        self._set_delete_button_to_delete_mode()
                        self._current_operation = None
                        self._pending_upload_selection = None
                        return
            except Exception:
                pass

            # Proceed with upload
            selected = list(self._pending_upload_selection or [])
            self._pending_upload_selection = None
            # Reset operation flag so _start_upload_selected can take over
            self._current_operation = None 
            if selected:
                self._start_upload_selected(selected)
        except Exception as e:
            logging.error(f"Error handling storage check result: {e}")
            self._current_operation = None
            self.progress_bar.setVisible(False)
            self._enable_buttons_after_operation()
            self._set_delete_button_to_delete_mode()

    def _on_storage_check_error(self, message: str):
        """Handle errors from storage check worker; proceed optimistically (same as check fallback)."""
        # Check for cancellation
        if getattr(self, '_storage_check_cancelled', False):
            self._current_operation = None
            return
            
        logging.warning(f"Storage check failed: {message}. Proceeding with upload.")
        # Don't hide progress, just proceed
        try:
            selected = list(self._pending_upload_selection or [])
        except Exception:
            selected = []
        self._pending_upload_selection = None
        self._current_operation = None
        if selected:
            self._start_upload_selected(selected)

    def _start_upload_selected(self, selected: list[str]):
        """Start the upload process for the given selected backup names."""
        logging.info(f"Uploading {len(selected)} backups to cloud...")
        
        # Get the active provider
        active_provider = self._get_active_provider()
        if not active_provider:
            QMessageBox.warning(
                self,
                "No Provider",
                "No storage provider is selected. Please select a provider first."
            )
            self._enable_buttons_after_operation()
            self._set_delete_button_to_delete_mode()
            return
        
        if not active_provider.is_connected:
            QMessageBox.warning(
                self,
                "Not Connected",
                "Please connect to the storage provider first."
            )
            self._enable_buttons_after_operation()
            self._set_delete_button_to_delete_mode()
            return
        
        # Reset cancellation flag if the provider supports it
        if hasattr(active_provider, 'reset_cancellation'):
            active_provider.reset_cancellation()
        
        # Show progress - UI updates IMMEDIATELY
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting upload...")
        self._disable_buttons_during_operation()
        
        # Transform delete button to cancel mode IMMEDIATELY
        self._set_delete_button_to_cancel_mode()
        
        # Use QTimer to allow UI to update before starting the thread
        # This ensures buttons are disabled and cancel button is shown instantly
        QTimer.singleShot(50, lambda: self._finalize_upload_start(selected, active_provider))
        
    def _finalize_upload_start(self, selected: list[str], provider=None):
        """Finalize upload start after UI update."""
        # Get max backups setting
        max_backups = None
        if self.cloud_settings.get('max_cloud_backups_enabled', False):
            max_backups = self.cloud_settings.get('max_cloud_backups_count', 5)
        
        # Use provided provider or get active one
        if provider is None:
            provider = self._get_active_provider()
            if not provider or not provider.is_connected:
                logging.error("No active provider available for upload")
                self.progress_bar.setVisible(False)
                self._enable_buttons_after_operation()
                self._set_delete_button_to_delete_mode()
                return
        
        # Create worker and thread
        self.upload_thread = QThread()
        self.upload_worker = UploadWorker(provider, selected, self.backup_base_dir, max_backups)
        self.upload_worker.moveToThread(self.upload_thread)
        self._last_upload_summary = None
        
        # Track current operation for cancellation
        self._current_worker = self.upload_worker
        self._current_operation = 'upload'
        
        # Connect signals
        self.upload_thread.started.connect(self.upload_worker.run)
        self.upload_worker.progress.connect(self._on_upload_progress)
        self.upload_worker.progress_detailed.connect(self._on_detailed_progress)
        self.upload_worker.summary_ready.connect(self._on_upload_summary)
        self.upload_worker.cancelled.connect(self._on_upload_cancelled)
        self.upload_worker.finished.connect(self._on_upload_finished)
        self.upload_worker.finished.connect(self.upload_thread.quit)
        self.upload_worker.finished.connect(self.upload_worker.deleteLater)
        self.upload_thread.finished.connect(self.upload_thread.deleteLater)
        
        # Start upload
        self.upload_thread.start()
    
    def _on_upload_progress(self, current, total, message):
        """Handle upload progress updates (message only)."""
        # Update text only, let detailed_progress handle the bar value
        self.progress_bar.setFormat(f"{message}")

    def _on_detailed_progress(self, current_bytes, total_bytes, message):
        """Handle detailed progress updates (bytes)."""
        if total_bytes > 0:
            self.progress_bar.setRange(0, total_bytes)
            self.progress_bar.setValue(current_bytes)
            
            # Format size
            current_mb = current_bytes / (1024 * 1024)
            total_mb = total_bytes / (1024 * 1024)
            
            self.progress_bar.setFormat(f"{message} - {current_mb:.1f}/{total_mb:.1f} MB")
        else:
            # Unknown total size
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat(f"{message}")
    
    def _on_upload_cancelled(self):
        """Handle upload cancellation."""
        self.progress_bar.setVisible(False)
        self._enable_buttons_after_operation()
        
        # Wait for thread to actually terminate before clearing worker
        if hasattr(self, 'upload_thread') and self.upload_thread is not None:
            try:
                if self.upload_thread.isRunning():
                    self.upload_thread.quit()
                    self.upload_thread.wait(1000)  # Wait up to 1 second
            except RuntimeError:
                pass # Thread already deleted
        
        # Clear current operation tracking
        self._current_worker = None
        self._current_operation = None
        
        # Restore delete button
        self._set_delete_button_to_delete_mode()
        
        # Refresh cloud status in case some files were uploaded before cancellation
        self._refresh_cloud_status()
    
    def _on_upload_finished(self, success_count, total_count):
        """Handle upload completion."""
        self.progress_bar.setVisible(False)
        self._enable_buttons_after_operation()
        
        # Clear current operation tracking
        self._current_worker = None
        self._current_operation = None
        
        # Restore delete button
        self._set_delete_button_to_delete_mode()
        
        # Decide message based on summary (skips vs updates)
        title = "Upload Complete"
        msg = f"Successfully uploaded {success_count} of {total_count} backups."
        if isinstance(self._last_upload_summary, dict):
            changed = int(self._last_upload_summary.get('profiles_changed', 0))
            unchanged = int(self._last_upload_summary.get('profiles_unchanged', 0))
            files_up = int(self._last_upload_summary.get('files_uploaded', 0))
            files_skip = int(self._last_upload_summary.get('files_skipped', 0))
            if changed == 0 and unchanged > 0:
                title = "No Upload Needed"
                msg = f"No changes uploaded. {unchanged} profile(s) had newer or identical backups in the cloud."
            elif unchanged > 0:
                title = "Upload Complete (Partial)"
                msg = (
                    f"Uploaded changes for {changed} of {total_count} profile(s). "
                    f"{unchanged} up-to-date (cloud newer or identical)."
                )
            # Add file-level stats when available
            if files_up or files_skip:
                msg += f"\nFiles: {files_up} uploaded, {files_skip} skipped."
        
        # Show notifications
        self._show_notification(title, msg)
        
        # Only show popup if there was actual work done or if we explicitly want to notify
        # If everything was skipped due to no changes, maybe don't show a modal popup?
        # For now, we keep it consistent but maybe less intrusive for "No Upload Needed"
        QMessageBox.information(self, title, msg)
        
        # Refresh cloud status
        self._refresh_cloud_status()
        self._last_upload_summary = None

    def _on_upload_summary(self, summary: dict):
        """Capture summary from upload worker for final messaging."""
        self._last_upload_summary = summary
    
    def _on_download_clicked(self):
        """Handle download selected backups from cloud."""
        # Check if there's already an operation in progress
        if self._current_worker is not None:
            QMessageBox.warning(
                self, 
                "Operation in Progress", 
                "Please wait for the current operation to complete before starting a new one."
            )
            return
        
        selected = self._get_selected_backups()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select backups to download.")
            return
        
        logging.info(f"Downloading {len(selected)} backups from cloud...")
        
        # Get active provider
        active_provider = self._get_active_provider()
        if not active_provider:
            QMessageBox.warning(self, "No Provider", "No storage provider is selected.")
            return
            
        if not active_provider.is_connected:
            QMessageBox.warning(self, "Not Connected", "Please connect to the storage provider first.")
            return

        # Reset cancellation flag if supported
        if hasattr(active_provider, 'reset_cancellation'):
            active_provider.reset_cancellation()
        
        # Show progress - UI updates IMMEDIATELY
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting download...")
        self._disable_buttons_during_operation()
        
        # Transform delete button to cancel mode IMMEDIATELY
        self._set_delete_button_to_cancel_mode()
        
        # Use QTimer to allow UI to update before starting the thread
        # This ensures buttons are disabled and cancel button is shown instantly
        QTimer.singleShot(50, lambda: self._finalize_download_start(selected, active_provider))

    def _finalize_download_start(self, selected: list[str], provider=None):
        """Finalize download start after UI update."""
        # Use provided provider or get active one
        if provider is None:
            provider = self._get_active_provider()
            if not provider or not provider.is_connected:
                logging.error("No active provider available for download")
                self.progress_bar.setVisible(False)
                self._enable_buttons_after_operation()
                self._set_delete_button_to_delete_mode()
                return

        # Create worker and thread
        self.download_thread = QThread()
        self.download_worker = DownloadWorker(
            provider, 
            selected, 
            self.backup_base_dir,
            self.profiles  # Pass existing profiles
        )
        self.download_worker.moveToThread(self.download_thread)
        
        # Track current operation for cancellation
        self._current_worker = self.download_worker
        self._current_operation = 'download'
        
        # Connect signals
        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.progress_detailed.connect(self._on_detailed_progress)
        self.download_worker.cancelled.connect(self._on_download_cancelled)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.finished.connect(self.download_thread.quit)
        self.download_worker.finished.connect(self.download_worker.deleteLater)
        self.download_thread.finished.connect(self.download_thread.deleteLater)
        
        # Start download
        self.download_thread.start()
    
    def _on_download_progress(self, current, total, message):
        """Handle download progress updates (message only)."""
        # Update text only, let detailed_progress handle the bar value
        self.progress_bar.setFormat(f"{message}")
    
    def _on_download_cancelled(self):
        """Handle download cancellation."""
        self.progress_bar.setVisible(False)
        self._enable_buttons_after_operation()
        
        # Wait for thread to actually terminate before clearing worker
        if hasattr(self, 'download_thread') and self.download_thread is not None:
            try:
                if self.download_thread.isRunning():
                    self.download_thread.quit()
                    self.download_thread.wait(1000)  # Wait up to 1 second
            except RuntimeError:
                pass
        
        # Clear current operation tracking
        self._current_worker = None
        self._current_operation = None
        
        # Restore delete button
        self._set_delete_button_to_delete_mode()
        
        # Clean up any empty backup folders created during cancelled download
        try:
            if os.path.isdir(self.backup_base_dir):
                for entry in os.listdir(self.backup_base_dir):
                    entry_path = os.path.join(self.backup_base_dir, entry)
                    if os.path.isdir(entry_path):
                        # Check if folder is empty
                        try:
                            if not os.listdir(entry_path):
                                os.rmdir(entry_path)
                                logging.info(f"Deleted empty backup folder created during cancelled download: {entry_path}")
                        except Exception as e_clean:
                            logging.debug(f"Could not clean empty folder {entry_path}: {e_clean}")
        except Exception as e:
            logging.debug(f"Error during cleanup of empty folders: {e}")
        
        # Refresh list in case some files were downloaded before cancellation
        self.refresh_local_backups()
    
    def _on_profile_auto_created(self, profile_name, backup_path):
        """Handle automatic profile creation after download."""
        try:
            logging.info(f"Auto-creating profile '{profile_name}' with path '{backup_path}'")
            
            # Add profile to main window's profiles dict
            if self.main_window and hasattr(self.main_window, 'profiles'):
                self.main_window.profiles[profile_name] = {'path': backup_path}
                
                # Save profiles to disk
                import core_logic
                if core_logic.save_profiles(self.main_window.profiles):
                    logging.info(f"Profile '{profile_name}' created and saved successfully")
                    
                    # Update local profiles reference
                    self.profiles = self.main_window.profiles
                    
                    # DON'T update GUI here - it will be updated in _on_download_finished
                    # The profile table will be refreshed after all downloads complete
                else:
                    logging.error(f"Failed to save profile '{profile_name}'")
            else:
                logging.error("Cannot create profile: main_window or profiles not available")
                
        except Exception as e:
            logging.error(f"Error auto-creating profile '{profile_name}': {e}", exc_info=True)
    
    def _on_download_finished(self, success_count, total_count, stats=None):
        """Handle download completion."""
        self.progress_bar.setVisible(False)
        self._enable_buttons_after_operation()
        
        # Clear current operation tracking
        self._current_worker = None
        self._current_operation = None
        
        # Restore delete button
        self._set_delete_button_to_delete_mode()
        
        # Create profiles for downloaded backups that don't have profiles yet
        profiles_created = []
        if stats and isinstance(stats, dict):
            profiles_to_create = stats.get('profiles_to_create', [])
            if profiles_to_create:
                try:
                    import core_logic
                    for profile_name, backup_path in profiles_to_create:
                        logging.info(f"Creating profile '{profile_name}' with path '{backup_path}'")
                        if self.main_window and hasattr(self.main_window, 'profiles'):
                            self.main_window.profiles[profile_name] = {'path': backup_path}
                            profiles_created.append(profile_name)
                    
                    # Save all profiles at once
                    if profiles_created and core_logic.save_profiles(self.main_window.profiles):
                        logging.info(f"Created {len(profiles_created)} new profiles: {', '.join(profiles_created)}")
                        # Update local profiles reference
                        self.profiles = self.main_window.profiles
                except Exception as e:
                    logging.error(f"Error creating profiles: {e}", exc_info=True)
        
        # Update profile table in main window (in case new profiles were created)
        if profiles_created:
            try:
                if self.main_window and hasattr(self.main_window, 'profile_table_manager'):
                    self.main_window.profile_table_manager.update_profile_table()
                    logging.info("Profile table updated after download")
            except Exception as e:
                logging.error(f"Error updating profile table: {e}")
        
        # Determine message based on stats
        title = "Download Complete"
        msg = f"Successfully processed {success_count} of {total_count} backups."
        
        if stats and isinstance(stats, dict):
            downloaded = stats.get('downloaded', 0)
            skipped = stats.get('skipped', 0)
            failed = stats.get('failed', 0)
            
            if downloaded == 0 and skipped > 0:
                 title = "No Download Needed"
                 msg = "No files needed to be downloaded. Local files are identical to cloud versions (MD5 match) or newer."
            elif downloaded > 0:
                msg = f"Downloaded {downloaded} file(s)."
                if skipped > 0:
                    msg += f" Skipped {skipped} file(s) (already up-to-date)."
            
            if failed > 0:
                msg += f"\n\nWarning: {failed} file(s) failed to download or verify."
            
            # Add info about created profiles
            if profiles_created:
                msg += f"\n\nCreated {len(profiles_created)} new profile(s)."

        # Show notification
        self._show_notification(title, msg)
        
        QMessageBox.information(self, title, msg)
        
        # Refresh local list
        self.refresh_local_backups()
    
    def _on_delete_clicked(self):
        """Handle delete selected backups from cloud."""
        # Check if there's already an operation in progress
        if self._current_worker is not None:
            QMessageBox.warning(
                self, 
                "Operation in Progress", 
                "Please wait for the current operation to complete before starting a new one."
            )
            return
        
        selected = self._get_selected_backups()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select backups to delete from cloud.")
            return
        
        # Get active provider
        active_provider = self._get_active_provider()
        if not active_provider:
            QMessageBox.warning(self, "No Provider", "No storage provider is selected.")
            return
            
        if not active_provider.is_connected:
            QMessageBox.warning(self, "Not Connected", "Please connect to the storage provider first.")
            return

        # Determine provider name for dialog
        provider_name = "Cloud Storage"
        if hasattr(active_provider, 'name'):
            provider_name = active_provider.name
        
        # Ask for confirmation
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete {len(selected)} backup(s) from {provider_name}?\n\n"
            "This action cannot be undone!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        logging.info(f"Deleting {len(selected)} backups from cloud...")
        
        # Reset cancellation flag if supported
        if hasattr(active_provider, 'reset_cancellation'):
            active_provider.reset_cancellation()
        
        # Show progress - UI updates IMMEDIATELY
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(selected))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting deletion...")
        self._disable_buttons_during_operation()
        
        # Transform delete button to cancel mode IMMEDIATELY
        self._set_delete_button_to_cancel_mode()
        
        # Force immediate UI update before starting thread
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        
        # Create worker and thread
        self.delete_thread = QThread()
        self.delete_worker = DeleteWorker(active_provider, selected)
        self.delete_worker.moveToThread(self.delete_thread)
        
        # Track current operation for cancellation
        self._current_worker = self.delete_worker
        self._current_operation = 'delete'
        
        # Connect signals
        self.delete_thread.started.connect(self.delete_worker.run)
        self.delete_worker.progress.connect(self._on_delete_progress)
        self.delete_worker.cancelled.connect(self._on_delete_cancelled)
        self.delete_worker.finished.connect(self._on_delete_finished)
        self.delete_worker.finished.connect(self.delete_thread.quit)
        self.delete_worker.finished.connect(self.delete_worker.deleteLater)
        self.delete_thread.finished.connect(self.delete_thread.deleteLater)
        
        # Start deletion
        self.delete_thread.start()
    
    def _on_delete_progress(self, current, total, message):
        """Handle delete progress updates."""
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{message} ({current}/{total})")
    
    def _on_delete_cancelled(self):
        """Handle delete cancellation."""
        self.progress_bar.setVisible(False)
        self._enable_buttons_after_operation()
        
        # Wait for thread to actually terminate before clearing worker
        if hasattr(self, 'delete_thread') and self.delete_thread is not None:
            try:
                if self.delete_thread.isRunning():
                    self.delete_thread.quit()
                    self.delete_thread.wait(1000)  # Wait up to 1 second
            except RuntimeError:
                pass
        
        # Clear current operation tracking
        self._current_worker = None
        self._current_operation = None
        
        # Restore delete button
        self._set_delete_button_to_delete_mode()
        
        # Refresh cloud status in case some files were deleted before cancellation
        self._refresh_cloud_status()
    
    def _on_delete_finished(self, success_count, total_count):
        """Handle delete completion."""
        self.progress_bar.setVisible(False)
        self._enable_buttons_after_operation()
        
        # Clear current operation tracking
        self._current_worker = None
        self._current_operation = None
        
        # Restore delete button
        self._set_delete_button_to_delete_mode()
        
        # Show notification
        self._show_notification(
            "Deletion Complete",
            f"Successfully deleted {success_count} of {total_count} backups from Google Drive."
        )
        
        QMessageBox.information(
            self,
            "Deletion Complete",
            f"Successfully deleted {success_count} of {total_count} backups from cloud."
        )
        
        # Refresh cloud status
        self._refresh_cloud_status()
    
    def _on_group_checkbox_changed(self, state, member_names):
        """Handle group checkbox change - toggle all member profile checkboxes."""
        is_checked = state == Qt.CheckState.Checked.value
        
        # Find and toggle member checkboxes
        for row in range(self.backup_table.rowCount()):
            name_item = self.backup_table.item(row, 2)
            if not name_item:
                continue
            
            # Check if this row is a group (skip groups when toggling)
            is_row_group = name_item.data(Qt.ItemDataRole.UserRole + 1)
            if is_row_group:
                continue
            
            # Get the profile name (folder name)
            folder_name = name_item.data(Qt.ItemDataRole.UserRole)
            if not folder_name:
                continue
            
            # Check if this profile is a member of the group
            # Members are stored as original names, folder_name uses backup_folder_name
            for member_name in member_names:
                member_data = self.profiles.get(member_name, {})
                if isinstance(member_data, dict):
                    sanitized_member = member_data.get('backup_folder_name', sanitize_foldername(member_name))
                else:
                    sanitized_member = sanitize_foldername(member_name)
                if folder_name == sanitized_member:
                    checkbox_widget = self.backup_table.cellWidget(row, 0)
                    if checkbox_widget:
                        checkbox = checkbox_widget.findChild(QCheckBox)
                        if checkbox:
                            checkbox.setChecked(is_checked)
                    break
    
    def _get_selected_backups(self):
        """Get list of selected backup folder names (sanitized names for file operations).
        
        Note: Groups are expanded to their member profiles - groups themselves don't have
        backup folders, only their members do.
        """
        selected = []
        selected_set = set()  # To avoid duplicates when group members are also selected individually
        
        logging.debug(f"_get_selected_backups: scanning {self.backup_table.rowCount()} rows")
        
        for row in range(self.backup_table.rowCount()):
            checkbox_widget = self.backup_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    # Column 2 contains the profile name; UserRole data contains actual folder name
                    name_item = self.backup_table.item(row, 2)
                    if name_item:
                        # Check if this is a group - expand to member folder names
                        is_group = name_item.data(Qt.ItemDataRole.UserRole + 1)
                        logging.debug(f"Row {row}: is_group={is_group}, text={name_item.text()}")
                        
                        if is_group:
                            # Get member names and add their sanitized folder names
                            member_names = name_item.data(Qt.ItemDataRole.UserRole + 2)
                            logging.debug(f"Group members: {member_names}")
                            if member_names:
                                for member_name in member_names:
                                    member_data = self.profiles.get(member_name, {})
                                    if isinstance(member_data, dict):
                                        sanitized_member = member_data.get('backup_folder_name', sanitize_foldername(member_name))
                                    else:
                                        sanitized_member = sanitize_foldername(member_name)
                                    logging.debug(f"  Adding member: {member_name} -> {sanitized_member}")
                                    if sanitized_member not in selected_set:
                                        selected_set.add(sanitized_member)
                                        selected.append(sanitized_member)
                            continue
                        
                        # Get the actual folder name from UserRole data (sanitized name)
                        folder_name = name_item.data(Qt.ItemDataRole.UserRole)
                        if not folder_name:
                            # Fallback to displayed text if no data (shouldn't happen)
                            folder_name = name_item.text()
                            if folder_name.startswith("★ "):
                                folder_name = folder_name[2:]  # Remove star prefix
                        
                        if folder_name not in selected_set:
                            selected_set.add(folder_name)
                            selected.append(folder_name)
        
        logging.debug(f"_get_selected_backups: returning {len(selected)} items: {selected}")
        return selected
    
    def _on_exit_clicked(self):
        """Handle exit button - return to main view."""
        # Cancel any ongoing authentication
        if self._current_auth_worker is not None:
            try:
                self._current_auth_worker.cancel()
                logging.info("Cancelled auth worker on exit")
            except Exception as e:
                logging.debug(f"Could not cancel auth worker on exit: {e}")
            self._current_auth_worker = None
        
        # Close auth URL dialog if open
        self._close_auth_url_dialog()
        
        # Stop timeout timer if running
        try:
            if hasattr(self, 'auth_timeout_timer') and self.auth_timeout_timer:
                self.auth_timeout_timer.stop()
                self.auth_timeout_timer = None
        except Exception:
            pass
        
        # Restore UI state
        try:
            self.progress_bar.setVisible(False)
            self.connect_button.setEnabled(True)
        except Exception:
            pass
        
        if self.main_window:
            self.main_window.exit_cloud_panel()
    
    def update_backup_dir(self, new_dir):
        """Update the backup directory and refresh the list."""
        self.backup_base_dir = new_dir
        self.refresh_local_backups()
    
    def update_profiles(self, profiles):
        """Update the profiles dictionary and refresh the list."""
        self.profiles = profiles
        self._repopulate_table()
    
    def cleanup_on_close(self):
        """Clean up resources when the application is closing."""
        try:
            # Cancel all active auth workers (mark them as cancelled)
            for worker in self._active_auth_workers:
                try:
                    worker.cancel()
                except Exception as e:
                    logging.debug(f"Could not cancel worker: {e}")

            # DON'T wait for auth threads - they are blocking on OAuth server
            # and will terminate on their own (server has timeout) or when process exits.
            # Waiting would block app shutdown unnecessarily.
            
            # Clear the lists (threads will be garbage collected when they finish)
            self._active_auth_threads.clear()
            self._active_auth_workers.clear()
            logging.info("Cloud panel cleanup completed")
        except Exception as e:
            logging.error(f"Error during cloud panel cleanup: {e}")

    
    def perform_startup_actions(self):
        """Perform startup actions (auto-connect and/or auto-sync) if enabled in settings."""
        auto_connect = self.cloud_settings.get('auto_connect_on_startup', False)
        auto_sync_on_startup = self.cloud_settings.get('auto_sync_on_startup', False)
        active_provider = self.cloud_settings.get('active_provider', 'google_drive')

        if auto_connect:
            # Check which provider should auto-connect based on the active_provider setting
            if active_provider == 'google_drive':
                logging.info("Auto-connect on startup enabled, connecting to Google Drive...")
                # Disable Cloud button in main window while connecting
                self._set_main_cloud_button_connecting(True)
                self._perform_auto_connect_google_drive()
            elif active_provider == 'ftp':
                ftp_host = self.cloud_settings.get('ftp_host', '')
                if ftp_host:
                    logging.info(f"Auto-connect on startup enabled, connecting to FTP ({ftp_host})...")
                    self._connect_to_ftp()
                else:
                    logging.warning("Auto-connect enabled but FTP host not configured")
            elif active_provider == 'smb':
                smb_path = self.cloud_settings.get('smb_path', '')
                if smb_path:
                    logging.info(f"Auto-connect on startup enabled, connecting to SMB ({smb_path})...")
                    self._connect_to_smb()
                else:
                    logging.warning("Auto-connect enabled but SMB path not configured")
            elif active_provider == 'webdav':
                webdav_url = self.cloud_settings.get('webdav_url', '')
                if webdav_url:
                    logging.info(f"Auto-connect on startup enabled, connecting to WebDAV ({webdav_url})...")
                    self._connect_to_webdav()
                else:
                    logging.warning("Auto-connect enabled but WebDAV URL not configured")
            elif active_provider == 'git':
                git_repo_path = self.cloud_settings.get('git_repo_path', '')
                if git_repo_path:
                    logging.info(f"Auto-connect on startup enabled, connecting to Git ({git_repo_path})...")
                    self._connect_to_git()
                else:
                    logging.warning("Auto-connect enabled but Git repo path not configured")
            else:
                logging.debug(f"Auto-connect enabled but unknown provider: {active_provider}")
            return

        # If auto-connect is off but auto-sync-on-startup is enabled, do a one-off connect->sync->disconnect
        # Note: auto-sync currently only works with Google Drive
        if auto_sync_on_startup and active_provider == 'google_drive':
            logging.info("Auto-sync on startup enabled (one-off). Connecting for startup sync...")
            self._ensure_connected_then(self._perform_startup_sync, disconnect_after=True)
        else:
            logging.debug("Startup auto connect/sync disabled or not applicable for current provider")
    
    def _perform_auto_connect_google_drive(self):
        """Perform automatic connection to Google Drive in background."""
        if self.drive_manager.is_connected:
            logging.info("Already connected to Google Drive")
            self._perform_startup_sync()
            return
        
        logging.info("Starting automatic connection to Google Drive...")
        
        # Clean up finished/deleted threads from the list
        self._cleanup_finished_auth_threads()
        
        # Create worker with unique ID
        self._auth_worker_counter += 1
        worker_id = self._auth_worker_counter
        
        # Create worker and thread for background connection
        startup_auth_thread = QThread()
        startup_auth_worker = AuthWorker(self.drive_manager, worker_id)
        startup_auth_worker.moveToThread(startup_auth_thread)
        
        # Add thread and worker to active lists to prevent premature destruction
        self._active_auth_threads.append(startup_auth_thread)
        self._active_auth_workers.append(startup_auth_worker)
        
        # Connect signals
        startup_auth_thread.started.connect(startup_auth_worker.run)
        startup_auth_worker.finished.connect(self._on_startup_auth_finished)
        startup_auth_worker.finished.connect(startup_auth_thread.quit)
        startup_auth_worker.finished.connect(startup_auth_worker.deleteLater)
        startup_auth_worker.finished.connect(lambda: self._remove_worker_from_list(startup_auth_worker))
        startup_auth_thread.finished.connect(startup_auth_thread.deleteLater)
        
        # Start authentication
        startup_auth_thread.start()
    
    def _on_startup_auth_finished(self, success, error_message):
        """Handle startup authentication completion."""
        # Restore main window cloud button state regardless of success
        self._set_main_cloud_button_connecting(False)
        if success:
            logging.info("Startup auto-connect successful")
            self._set_connected(True)
            self._refresh_cloud_status()
            
            # Setup periodic sync if enabled
            self._setup_periodic_sync()
            
            # Perform startup sync if enabled
            self._perform_startup_sync()
        else:
            logging.warning(f"Startup auto-connect failed: {error_message}")
            self._set_connected(False)
    
    def _perform_startup_sync(self):
        """Perform sync on startup if enabled in settings."""
        if not self.cloud_settings.get('auto_sync_on_startup', False):
            return
        
        if not self.drive_manager.is_connected:
            logging.info("Startup sync skipped: not connected to Google Drive")
            return
        
        logging.info("Performing startup sync...")
        
        # Get profiles to sync
        if self.cloud_settings.get('sync_all_profiles', True):
            profiles_to_sync = list(self.profiles.keys())
        else:
            profiles_to_sync = list(self.profiles.keys())
        
        if profiles_to_sync:
            self._auto_sync_profiles(profiles_to_sync)
    
    def show_cloud_settings(self):
        """Show the cloud settings panel."""
        logging.debug("Showing cloud settings panel")
        self.stacked_widget.setCurrentIndex(1)  # Switch to settings panel
        try:
            if hasattr(self, 'settings_panel') and self.settings_panel:
                self.settings_panel.refresh_storage_status()
        except Exception:
            pass
    
    def exit_cloud_settings(self):
        """Exit cloud settings and return to main cloud panel."""
        logging.debug("Exiting cloud settings panel")
        self.stacked_widget.setCurrentIndex(0)  # Switch back to main panel
    
    def _refresh_cloud_status(self):
        """Refresh cloud backup status for all backups in background."""
        # Get active provider - don't show warnings here as this happens automatically
        active_provider = self._get_active_provider()
        if not active_provider or not active_provider.is_connected:
            return
        
        # Prevent multiple simultaneous refreshes which could cause QThread crash
        if hasattr(self, 'refresh_thread') and self.refresh_thread is not None:
            try:
                if self.refresh_thread.isRunning():
                    logging.debug("Cloud refresh already in progress, skipping request.")
                    return
            except RuntimeError:
                # C++ object already deleted, so it's definitely not running
                self.refresh_thread = None
        
        logging.info("Starting cloud status refresh...")
        
        # Create worker and thread for background refresh
        self.refresh_thread = QThread()
        self.refresh_worker = RefreshCloudStatusWorker(active_provider)
        self.refresh_worker.moveToThread(self.refresh_thread)
        
        # Connect signals
        self.refresh_thread.started.connect(self.refresh_worker.run)
        self.refresh_worker.finished.connect(self._on_refresh_cloud_status_finished)
        self.refresh_worker.error.connect(self._on_refresh_cloud_status_error)
        self.refresh_worker.finished.connect(self.refresh_thread.quit)
        self.refresh_worker.finished.connect(self.refresh_worker.deleteLater)
        self.refresh_worker.error.connect(self.refresh_thread.quit)
        self.refresh_worker.error.connect(self.refresh_worker.deleteLater)
        self.refresh_thread.finished.connect(self.refresh_thread.deleteLater)
        
        # Start refresh
        self.refresh_thread.start()
    
    def _on_refresh_cloud_status_finished(self, cloud_backups):
        """Handle cloud status refresh completion."""
        # If disconnected while refreshing, discard results
        if not self._is_any_provider_connected():
            logging.debug("Refresh finished but disconnected, discarding results.")
            return
        
        # Don't update UI if panel is not visible
        if not self.isVisible():
            logging.debug("Refresh finished but panel not visible, caching results only")
            self.cloud_backups = cloud_backups
            return

        self.cloud_backups = cloud_backups
        
        # Repopulate the entire table to include cloud-only backups
        self._repopulate_table()
    
    def _on_refresh_cloud_status_error(self, error_message):
        """Handle cloud status refresh error."""
        QMessageBox.warning(
            self,
            "Refresh Error",
            f"Could not refresh cloud status:\n{error_message}"
        )
    
    def _on_cloud_settings_saved(self, settings):
        """Handle cloud settings being saved."""
        self.cloud_settings = settings
        
        # Save settings to disk
        cloud_settings_manager.save_cloud_settings(settings)
        
        # Apply settings to drive manager
        self._apply_settings_to_drive_manager()
        
        # Apply periodic sync setting
        self._setup_periodic_sync()
    
    def _apply_settings_to_drive_manager(self):
        """Apply current settings to the Google Drive manager."""
        # Bandwidth limit
        if self.cloud_settings.get('bandwidth_limit_enabled', False):
            limit = self.cloud_settings.get('bandwidth_limit_mbps', 10)
            self.drive_manager.set_bandwidth_limit(limit)
        else:
            self.drive_manager.set_bandwidth_limit(None)
    
    def _show_notification(self, title, message):
        """Show a system notification if enabled in settings."""
        if not self.cloud_settings.get('show_sync_notifications', True):
            return
        
        try:
            # Try to use system notifications
            from notifypy import Notify  # pyright: ignore[reportMissingImports]
            
            notification = Notify()
            notification.title = title
            notification.message = message
            notification.application_name = "SaveState"
            notification.send()
            
        except Exception as e:
            logging.debug(f"Could not send notification: {e}")
            # Fallback: just log it
            logging.info(f"Notification: {title} - {message}")
    
    def _setup_periodic_sync(self):
        """Setup or update periodic sync timer based on settings. Runs even if not connected."""
        # Stop existing timer if any
        if self.sync_timer:
            try:
                if self.sync_timer.isActive():
                    self.sync_timer.stop()
            except RuntimeError:
                pass
            self.sync_timer = None
        
        # Check if periodic sync is enabled
        if not self.cloud_settings.get('auto_sync_enabled', False):
            logging.debug("Periodic sync disabled")
            return

        # Get interval in hours, convert to milliseconds
        interval_hours = self.cloud_settings.get('auto_sync_interval_hours', 12)
        try:
            # accept float hours if set manually in JSON
            interval_hours_val = float(interval_hours)
        except Exception:
            interval_hours_val = 12.0
        interval_ms = int(interval_hours_val * 60 * 60 * 1000)
        logging.info(f"Periodic sync enabled: every {interval_hours_val:g} hours")
        
        # Create and start timer
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self._perform_periodic_sync)
        self.sync_timer.start(interval_ms)
    
    def _perform_periodic_sync(self):
        """Perform automatic sync of all profiles. Connects temporarily if needed."""
        if self._sync_in_progress:
            logging.debug("Periodic sync skipped: a sync is already in progress")
            return

        def start_sync():
            logging.info("Starting periodic sync...")
            # Get profiles to sync
            if self.cloud_settings.get('sync_all_profiles', True):
                profiles_to_sync = list(self.profiles.keys())
            else:
                profiles_to_sync = list(self.profiles.keys())

            if not profiles_to_sync:
                logging.info("No profiles to sync")
                return

            self._auto_sync_profiles(profiles_to_sync)

        # If not connected, connect, run, and optionally disconnect
        if not self.drive_manager.is_connected:
            temp_disconnect = not self.cloud_settings.get('auto_connect_on_startup', False)
            self._ensure_connected_then(start_sync, disconnect_after=temp_disconnect)
            return
        
        # Already connected
        start_sync()
    
    def _auto_sync_profiles(self, profile_names):
        """Automatically sync specified profiles in background."""
        if self._sync_in_progress:
            logging.debug("Auto sync request ignored: another sync is running")
            return
            
        # Get active provider
        active_provider = self._get_active_provider()
        if not active_provider or not active_provider.is_connected:
            logging.debug("Auto sync skipped: no active provider connected")
            return
            
        self._sync_in_progress = True
        
        # Reset cancellation flag in provider before starting
        if hasattr(active_provider, 'reset_cancellation'):
            active_provider.reset_cancellation()
        
        # Get max backups setting
        max_backups = None
        if self.cloud_settings.get('max_cloud_backups_enabled', False):
            max_backups = self.cloud_settings.get('max_cloud_backups_count', 5)
        
        # Create worker for background sync
        self.auto_sync_thread = QThread()
        self.auto_sync_worker = UploadWorker(
            active_provider, 
            profile_names, 
            self.backup_base_dir, 
            max_backups
        )
        self.auto_sync_worker.moveToThread(self.auto_sync_thread)
        
        # NOTE: Auto-sync does NOT show cancel button, but we still support cancellation internally
        # if we add a way to cancel background operations in the future
        
        # Connect signals
        self.auto_sync_thread.started.connect(self.auto_sync_worker.run)
        self.auto_sync_worker.cancelled.connect(self._on_auto_sync_cancelled)
        self.auto_sync_worker.finished.connect(self._on_auto_sync_finished)
        self.auto_sync_worker.finished.connect(self.auto_sync_thread.quit)
        self.auto_sync_worker.finished.connect(self.auto_sync_worker.deleteLater)
        self.auto_sync_thread.finished.connect(self.auto_sync_thread.deleteLater)
        
        # Start sync
        self.auto_sync_thread.start()
    
    def _on_auto_sync_cancelled(self):
        """Handle automatic sync cancellation."""
        logging.info("Periodic sync was cancelled")
        
        # Show notification
        self._show_notification(
            "Periodic Sync Cancelled",
            "Automatic sync was cancelled."
        )
        
        # Refresh cloud status in case some files were synced before cancellation
        try:
            self._refresh_cloud_status()
        except Exception:
            pass

        # Disconnect if this was a temporary connection
        try:
            if self._disconnect_after_current_sync:
                active_provider = self._get_active_provider()
                if active_provider and active_provider.is_connected:
                    active_provider.disconnect()
                self._set_connected(False)
            self._disconnect_after_current_sync = False
        except Exception:
            self._disconnect_after_current_sync = False

        self._sync_in_progress = False
    
    def _on_auto_sync_finished(self, success_count, total_count):
        """Handle automatic sync completion."""
        logging.info(f"Periodic sync completed: {success_count}/{total_count} profiles synced")
        
        # Show notification
        provider_name = "Cloud"
        active_provider = self._get_active_provider()
        if active_provider and hasattr(active_provider, 'name'):
            provider_name = active_provider.name
            
        self._show_notification(
            "Periodic Sync Complete",
            f"Synced {success_count} of {total_count} profiles to {provider_name}."
        )
        
        # Refresh cloud status
        self._refresh_cloud_status()

        # Disconnect if this was a temporary connection
        try:
            if self._disconnect_after_current_sync:
                if active_provider and active_provider.is_connected:
                    active_provider.disconnect()
                self._set_connected(False)
            self._disconnect_after_current_sync = False
        except Exception:
            self._disconnect_after_current_sync = False

        self._sync_in_progress = False

    # ---- Helpers ----
    def _remove_worker_from_list(self, worker):
        """Remove a worker from the active workers list after it finishes."""
        try:
            if worker in self._active_auth_workers:
                self._active_auth_workers.remove(worker)
                logging.debug(f"Removed worker {getattr(worker, 'worker_id', '?')} from active list")
        except Exception as e:
            logging.debug(f"Error removing worker from list: {e}")
    
    def _cleanup_finished_auth_threads(self):
        """Remove finished or deleted threads from the active list."""
        cleaned_threads = []
        for t in self._active_auth_threads:
            try:
                if t.isRunning():
                    cleaned_threads.append(t)
            except RuntimeError:
                # Thread object was already deleted by Qt
                pass
        self._active_auth_threads = cleaned_threads
    
    def _ensure_connected_then(self, on_connected_callable, disconnect_after: bool = False):
        """Ensure we're connected, then call the provided function. Optionally disconnect after sync ends."""
        if self.drive_manager.is_connected:
            on_connected_callable()
            return

        # Clean up finished/deleted threads from the list
        self._cleanup_finished_auth_threads()

        # Background connect then call
        self._disconnect_after_current_sync = bool(disconnect_after)

        def _after_auth(success, error_message):
            if success:
                self._set_connected(True)
                try:
                    self._refresh_cloud_status()
                except Exception:
                    pass
                on_connected_callable()
            else:
                logging.warning(f"Connection attempt failed: {error_message}")
                self._disconnect_after_current_sync = False

        # Create worker with unique ID
        self._auth_worker_counter += 1
        worker_id = self._auth_worker_counter
        
        ensure_auth_thread = QThread()
        ensure_auth_worker = AuthWorker(self.drive_manager, worker_id)
        ensure_auth_worker.moveToThread(ensure_auth_thread)
        
        # Add thread and worker to active lists to prevent premature destruction
        self._active_auth_threads.append(ensure_auth_thread)
        self._active_auth_workers.append(ensure_auth_worker)
        
        ensure_auth_thread.started.connect(ensure_auth_worker.run)
        ensure_auth_worker.finished.connect(_after_auth)
        ensure_auth_worker.finished.connect(ensure_auth_thread.quit)
        ensure_auth_worker.finished.connect(ensure_auth_worker.deleteLater)
        ensure_auth_worker.finished.connect(lambda: self._remove_worker_from_list(ensure_auth_worker))
        ensure_auth_thread.finished.connect(ensure_auth_thread.deleteLater)
        ensure_auth_thread.start()

    def _set_main_cloud_button_connecting(self, connecting: bool):
        """Update the main window Cloud button to reflect connecting state."""
        try:
            if self.main_window and hasattr(self.main_window, 'cloud_button') and self.main_window.cloud_button:
                self.main_window.cloud_button.setEnabled(not connecting)
                self.main_window.cloud_button.setText("Connecting..." if connecting else "Cloud Sync")
        except Exception:
            pass

