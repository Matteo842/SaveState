# SaveState_gui.py
# -*- coding: utf-8 -*-
#import sys
import os
import logging
import platform
import math
import configparser
import re  # Per espressioni regolari
import core_logic # Added import

# --- PySide6 Imports (misuriamo i moduli principali) ---
# Importa il modulo base prima, poi gli elementi specifici
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QFrame, QSizePolicy,
    QProgressBar, QGroupBox, QLineEdit,
    QStyle, QDockWidget, QPlainTextEdit, QTableWidget, QGraphicsOpacityEffect,
    QDialog, QFileDialog, QMenu, QSpinBox, QComboBox, QCheckBox, QFormLayout,
    QSizeGrip, QMessageBox, QGridLayout, QSystemTrayIcon, QInputDialog
)
from PySide6.QtGui import QKeyEvent # Added for keyPressEvent
from PySide6.QtCore import (
    Slot, Qt, QSize,
    QEvent, Signal,
    QTimer, QPropertyAnimation, QEasingCurve, QAbstractAnimation
)

# Try to import pynput for global mouse monitoring
try:
    from pynput import mouse
    PYNPUT_AVAILABLE = True
    logging.info("pynput.mouse imported successfully. Global mouse drag detection enabled.")
except ImportError:
    PYNPUT_AVAILABLE = False
    mouse = None  # Define mouse as None if import fails, to prevent NameError if referenced before conditional check
    logging.warning("pynput.mouse could not be imported. Global mouse drag detection will be disabled. "
                    "Install pynput for this feature (e.g., 'pip install pynput').")

from PySide6.QtGui import (
    QIcon, QColor, QDragEnterEvent, QDropEvent, QDragLeaveEvent, QDragMoveEvent,
    QPalette, QAction, QCursor, QPixmap, QPainter, QFont,
)

# Import condizionale per PyWin32 (solo su Windows)
if platform.system() == "Windows":
    try:
        import win32gui
        import win32con
        import win32api
        HAS_PYWIN32 = True
        logging.debug("PyWin32 importato con successo")
    except ImportError:
        HAS_PYWIN32 = False
        logging.warning("PyWin32 non disponibile. Il rilevamento del drag globale sarà limitato.")
else:
    HAS_PYWIN32 = False

from gui_utils import QtLogHandler
from utils import resource_path
from gui_components.profile_list_manager import ProfileListManager
from gui_components.theme_manager import ThemeManager
from gui_components.profile_creation_manager import ProfileCreationManager
from gui_components.drag_drop_handler import DragDropHandler
from cloud_utils.cloud_panel import CloudSavePanel
import cloud_settings_manager
import core_logic # Mantenuto per load_profiles
from gui_handlers import MainWindowHandlers
from controller_manager import ControllerManager
from gui_components.controller_panel import (
    ControllerPanel,
    CTRL_BUTTONS, CTRL_ACTIONS, CTRL_DEFAULT_MAPPINGS, CTRL_BADGE_COLOR,
)

# --- COSTANTI GLOBALI PER IDENTIFICARE L'ISTANZA ---
# Import from config.py for early access in main.py before heavy imports
from config import SHARED_MEM_KEY, LOCAL_SERVER_NAME
# --- FINE COSTANTI ---


# ---------------------------------------------------------------------------
# Controller dialog badger — adds controller badge icons to dialog buttons
# ---------------------------------------------------------------------------

from PySide6.QtCore import QObject as _QObject, QEvent as _QEvent
from PySide6.QtWidgets import QDialogButtonBox as _QDialogButtonBox

class _ControllerDialogBadger(_QObject):
    """Application-level event filter.
    Watches for any QDialog being shown and adds controller badge icons to its
    buttons, using the current button mapping from the main window.

    Recognised dialog patterns (by attribute inspection, no class imports):
      • QMessageBox              — Yes/OK → A,  No/Cancel → B
      • RestoreDialog            — ok_button → A, Cancel → B
      • ManageBackupsDialog      — delete_button → A, close_button → B,
                                   delete_all_button → X
      • Any dialog with button_box (QDialogButtonBox) — OK → A, Cancel → B
    """

    def __init__(self, main_window):
        super().__init__()
        self._mw = main_window

    def eventFilter(self, watched, event):
        if event.type() == _QEvent.Type.Show and isinstance(watched, QDialog):
            QTimer.singleShot(0, lambda d=watched: self._badge(d))
        return False

    # ------------------------------------------------------------------
    def _badge(self, dialog):
        if not dialog.isVisible():
            return

        mw   = self._mw
        make = mw._make_ctrl_badge_icon
        sz   = QSize(16, 16)

        # Resolve action → physical button name from current mapping
        saved   = mw.current_settings.get("controller_button_mappings", {})
        mapping = {**CTRL_DEFAULT_MAPPINGS, **saved}
        action_to_btn: dict[str, str] = {}
        for btn_name, action in mapping.items():
            if action and action not in action_to_btn:
                action_to_btn[action] = btn_name

        def _icon(action_key, fallback_btn, fallback_color):
            btn_name = action_to_btn.get(action_key, fallback_btn)
            color    = CTRL_BADGE_COLOR.get(btn_name, fallback_color)
            return make(btn_name, color, 16), sz

        def _set(widget, action_key, fallback_btn, fallback_color):
            if widget and widget.isVisible():
                ico, sz_ = _icon(action_key, fallback_btn, fallback_color)
                widget.setIcon(ico)
                widget.setIconSize(sz_)

        # ── QMessageBox ────────────────────────────────────────────────
        if isinstance(dialog, QMessageBox):
            for sb in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Ok,
                       QMessageBox.StandardButton.Open, QMessageBox.StandardButton.Save):
                btn = dialog.button(sb)
                if btn:
                    _set(btn, "backup", "A", "#1E8449")
                    break
            for sb in (QMessageBox.StandardButton.No, QMessageBox.StandardButton.Cancel,
                       QMessageBox.StandardButton.Close, QMessageBox.StandardButton.Discard,
                       QMessageBox.StandardButton.Abort):
                btn = dialog.button(sb)
                if btn:
                    _set(btn, "back", "B", "#922B21")
                    break
            return

        # ── ManageBackupsDialog  (delete_button, delete_all_button, close_button)
        if (hasattr(dialog, 'delete_button') and
                hasattr(dialog, 'delete_all_button') and
                hasattr(dialog, 'close_button')):
            _set(dialog.delete_button,     "backup",  "A", "#1E8449")
            _set(dialog.close_button,      "back",    "B", "#922B21")
            _set(dialog.delete_all_button, "restore", "X", "#1A5276")
            return

        # ── SteamDialog  (configure_button, refresh_button, close_button)
        if (hasattr(dialog, 'configure_button') and
                hasattr(dialog, 'refresh_button') and
                hasattr(dialog, 'close_button')):
            _set(dialog.configure_button, "backup", "A", "#1E8449")
            _set(dialog.close_button,     "back",   "B", "#922B21")
            _set(dialog.refresh_button,   "restore", "X", "#1A5276")
            return

        # ── QInputDialog  (Select Steam Profile, etc.: OK / Cancel)
        if isinstance(dialog, QInputDialog):
            for bb in dialog.findChildren(_QDialogButtonBox):
                ok_btn = bb.button(_QDialogButtonBox.StandardButton.Ok)
                cancel_btn = bb.button(_QDialogButtonBox.StandardButton.Cancel)
                _set(ok_btn, "backup", "A", "#1E8449")
                _set(cancel_btn, "back", "B", "#922B21")
                return
            return

        # ── RestoreDialog  (ok_button + button_box with Cancel) ────────
        if hasattr(dialog, 'ok_button') and hasattr(dialog, 'button_box'):
            _set(dialog.ok_button, "backup", "A", "#1E8449")
            bb = dialog.button_box
            if isinstance(bb, _QDialogButtonBox):
                cancel = bb.button(_QDialogButtonBox.StandardButton.Cancel)
                _set(cancel, "back", "B", "#922B21")
            return

        # ── Generic dialog with QDialogButtonBox  (New Profile, Edit…) ─
        if hasattr(dialog, 'button_box') and isinstance(dialog.button_box, _QDialogButtonBox):
            bb = dialog.button_box
            ok_btn     = bb.button(_QDialogButtonBox.StandardButton.Ok)
            cancel_btn = bb.button(_QDialogButtonBox.StandardButton.Cancel)
            _set(ok_btn,     "backup", "A", "#1E8449")
            _set(cancel_btn, "back",   "B", "#922B21")


# --- Finestra Principale ---
# Approccio semplificato: mostrare l'overlay quando la finestra è attiva

class MainWindow(QMainWindow):
    # Segnali per la gestione dell'overlay dal thread principale della GUI
    request_show_overlay = Signal()
    request_hide_overlay = Signal()  

    # --- Initialization ---
    # Initializes the main window, sets up UI elements, managers, and connects signals.
    def __init__(self, initial_settings, console_log_handler, qt_log_handler, settings_manager_instance):
        super().__init__()
        self.console_log_handler = console_log_handler # Salva riferimento al gestore console
        self.qt_log_handler = qt_log_handler
        self.settings_manager = settings_manager_instance # Assign settings_manager instance
        self.core_logic = core_logic # Assign core_logic module to an instance attribute
        
        # Use a custom, frameless title bar so we can reclaim vertical space
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self._drag_pos = None  # Used by the custom title bar drag logic
        self._window_pos = None  # Store window position for dragging
        self._is_linux = platform.system() == "Linux"  # Check if running on Linux
        
        # Inizializza il cancellation manager per i thread di ricerca
        from cancellation_utils import CancellationManager
        self.cancellation_manager = CancellationManager()
        
        # Inizializza le liste per il tracciamento dei thread
        self._detection_threads = []
        self.active_threads = {}
        self.processing_cancelled = False
        
        # Variabili per il rilevamento del drag globale
        self.is_drag_operation_active = False
        self.mouse_pressed = False            # True se il tasto sinistro è attualmente premuto
        self.mouse_press_time = 0         # Timestamp (ms) di quando il tasto è stato premuto
        self.min_press_duration = 250     # Durata minima (ms) della pressione per attivare il drag (1/4 di secondo)
        self.press_position = None          # Posizione (x, y) di quando il tasto è stato premuto
        self.min_drag_distance = 10         # Distanza minima (pixel) di movimento per attivare il drag
        self.mouse_listener = None # Initialize to None
        self.overlay_active = False # Flag to track if overlay is already active

        # Initial state of the listener will be set by update_global_drag_listener_state
        # called after settings are fully initialized and accessible.

        if PYNPUT_AVAILABLE and mouse is not None:
            try:
                # Configura il listener del mouse per il rilevamento globale del drag
                self.mouse_listener = mouse.Listener(
                    on_click=self.on_mouse_click,
                    on_move=self.on_mouse_move  # Aggiungiamo il gestore per il movimento
                )
                self.mouse_listener.daemon = True  # Il thread si chiuderà quando l'applicazione termina
                # self.mouse_listener.start()
                logging.info("Global mouse listener for drag detection initialized successfully.")
            except Exception as e:
                logging.error(f"Failed to start pynput mouse listener: {e}. Global drag detection will be disabled.", exc_info=True)
                self.mouse_listener = None # Ensure it's None if an error occurs during start
        else:
            logging.info("pynput is not available or mouse module is None. Global mouse drag detection is disabled.")

        # Translator removed - application is now English-only

        self.setGeometry(650, 250, 720, 600)
        self.setMinimumSize(720, 600)  # Set minimum size to current size
        self.setAcceptDrops(True)
        self.current_settings = initial_settings
        self.profiles = core_logic.load_profiles()
        self.installed_steam_games_dict = core_logic.find_installed_steam_games()
        # Log the result for debugging
        if self.installed_steam_games_dict:
            logging.info(f"Initialized installed_steam_games_dict with {len(self.installed_steam_games_dict)} games.")
            # Example: Log first 3 games found for quick verification
            # for i, (app_id, details) in enumerate(self.installed_steam_games_dict.items()):
            #     if i < 3:
            #         logging.debug(f"  Found Steam game: {details.get('name', 'N/A')} (AppID: {app_id})")
            #     else:
            #         break
        else:
            logging.warning("installed_steam_games_dict is empty or None after initialization from core_logic.find_installed_steam_games().")

        # Connect signals for overlay management
        self.request_show_overlay.connect(self._show_overlay)
        self.request_hide_overlay.connect(self._hide_overlay)

        # Initialize and set the global drag listener state based on settings
        self.update_global_drag_listener_state()

        # --- Overlay Widget for Drag and Drop ---
        self.overlay_widget = QWidget(self) # Parent to MainWindow directly
        self.overlay_widget.setObjectName("BusyOverlay")
        self.overlay_widget.setStyleSheet("QWidget#BusyOverlay { background-color: rgba(0, 0, 0, 200); }") # Semi-transparent background, darker
        self.overlay_widget.hide() # Start hidden
        self.overlay_widget.setMouseTracking(False) # Don't let the overlay intercept mouse events for itself

        self.loading_label = QLabel("Drop Here", self.overlay_widget)
        # font = self.loading_label.font()
        # font.setPointSize(24)
        # font.setBold(True)
        # self.loading_label.setFont(font) # Stylesheet handles this now
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; }")
        self.loading_label.hide()

        # Fade-in animation for the overlay (using QGraphicsOpacityEffect for QWidget)
        self.overlay_opacity_effect = QGraphicsOpacityEffect(self.overlay_widget)
        self.overlay_widget.setGraphicsEffect(self.overlay_opacity_effect)
        self.fade_in_animation = QPropertyAnimation(self.overlay_opacity_effect, b"opacity")
        self.fade_in_animation.setDuration(400) # ms - Increased duration for better visibility
        self.fade_in_animation.setStartValue(0.0)
        self.fade_in_animation.setEndValue(1.0) 
        self.fade_in_animation.setEasingCurve(QEasingCurve.InOutQuad)

        # Fade-out animation for the overlay
        self.fade_out_animation = QPropertyAnimation(self.overlay_opacity_effect, b"opacity")
        self.fade_out_animation.setDuration(400) # ms - Increased duration for better visibility
        self.fade_out_animation.setStartValue(1.0)
        self.fade_out_animation.setEndValue(0.0)
        self.fade_out_animation.setEasingCurve(QEasingCurve.InOutQuad)
        # Connect finished signals to hide widgets after animation
        self.fade_out_animation.finished.connect(self.overlay_widget.hide) # Hides the widget itself
        self.fade_out_animation.finished.connect(self._on_overlay_faded_out) # Manages overlay_active flag and hides label

        # Overlay lock flag (keeps overlay visible when True, e.g., during Multi-Profile dialog)
        self._overlay_locked = False
        
        self.developer_mode_enabled = False # Stato iniziale delle opzioni sviluppatore
        self.log_button_press_timer = None  # Timer per il long press
        self.log_icon_normal = None         # Icona normale del log
        self.log_icon_dev = None            # Icona modalità sviluppatore
                
        # Ottieni lo stile per le icone standard
        style = QApplication.instance().style()
        icon_size = QSize(16, 16) # Dimensione comune icone

        # --- Widget ---
        self.profile_table_widget = QTableWidget()
        
        self.settings_button = QPushButton()
        self.controller_button = QPushButton()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.new_profile_button = QPushButton()
        self.steam_button = QPushButton()
        self.delete_profile_button = QPushButton() # Crea pulsante Elimina Profilo
        self.backup_button = QPushButton()         # Crea pulsante Backup
        self.restore_button = QPushButton()        # Crea pulsante Ripristina
        self.manage_backups_button = QPushButton() # Crea pulsante Gestisci Backup
        self.open_backup_dir_button = QPushButton() # Crea pulsante Apri Cartella
        
        
        # New visible Cloud entry
        self.cloud_button = QPushButton("Cloud Sync")
        
        # Cloud icon
        cloud_icon_path = resource_path("icons/cloud-sync.png")
        if os.path.exists(cloud_icon_path):
            cloud_icon = QIcon(cloud_icon_path)
            self.cloud_button.setIcon(cloud_icon)
        else:
            logging.warning(f"File icona Cloud non trovato: {cloud_icon_path}")

        # Search bar for profiles (initially hidden)
        self.search_bar = QLineEdit(self)
        self.search_bar.setPlaceholderText("Type to search profiles...")
        self.search_bar.hide()
        self.search_bar.textChanged.connect(self._on_main_search_text_changed)
        
        # Nuovo pulsante per il Log
        self.toggle_log_button = QPushButton()
        self.toggle_log_button.setObjectName("LogToggleButton")
        self.toggle_log_button.setFlat(True)
        self.toggle_log_button.setFixedSize(QSize(24, 24))
        self.toggle_log_button.setObjectName("LogToggleButton")
        
        # Carica entrambe le icone per il pulsante log
        icon_normal_path = resource_path("icons/terminal.png")
        icon_dev_path = resource_path("icons/terminalDev.png") # Nuova icona

        if os.path.exists(icon_normal_path):
            self.log_icon_normal = QIcon(icon_normal_path)
        else:
            logging.warning(f"File icona log NORMALE non trovato: {icon_normal_path}")
            self.log_icon_normal = None # O gestisci il fallback

        if os.path.exists(icon_dev_path):
            self.log_icon_dev = QIcon(icon_dev_path)
        else:
            logging.warning(f"File icona log DEVELOPER non trovato: {icon_dev_path}")
            self.log_icon_dev = self.log_icon_normal # Usa icona normale come fallback se manca quella dev

        self.log_button_press_timer = QTimer(self)
        self.log_button_press_timer.setSingleShot(True) # Scatta una sola volta
        self.log_button_press_timer.setInterval(1500) # Durata pressione lunga in ms (1.5 secondi)
        logging.debug(f"Timer object created in __init__: {self.log_button_press_timer}")
        
        # Imposta l'icona iniziale (normale)
        if self.log_icon_normal:
            self.toggle_log_button.setIcon(self.log_icon_normal)
        else:
            self.toggle_log_button.setText("L") # Fallback testo se manca anche l'icona normale

        button_size = QSize(24, 24)
        self.toggle_log_button.setFixedSize(button_size)
        #self.toggle_log_button.setToolTip(self.tr("Mostra/Nascondi Log (Tieni premuto per Opzioni Sviluppatore)"))

        
        icon_path = resource_path("icons/settings.png") # Percorso relativo dell'icona
        if os.path.exists(icon_path): # Controlla se il file esiste
            self.settings_icon_normal = QIcon(icon_path)  # Save normal icon
            self.settings_button.setIcon(self.settings_icon_normal)
            self.settings_button.setIconSize(QSize(20, 20)) # Icona più grande
        else:
            logging.warning(f"File icona impostazioni non trovato: {icon_path}")
            self.settings_icon_normal = None
        
        # Cloud settings icon
        cloud_settings_icon_path = resource_path("icons/cloud option.png")
        if os.path.exists(cloud_settings_icon_path):
            self.settings_icon_cloud = QIcon(cloud_settings_icon_path)
        else:
            logging.warning(f"File icona cloud settings non trovato: {cloud_settings_icon_path}")
            self.settings_icon_cloud = self.settings_icon_normal  # Fallback to normal icon
            
        self.theme_button = QPushButton()
        # Style settings/theme/controller as square, icon-only buttons for the title bar
        self.settings_button.setFlat(True)
        self.settings_button.setFixedSize(QSize(28, 28))
        self.theme_button.setFlat(True)
        self.theme_button.setFixedSize(QSize(28, 28))
        controller_icon_path = resource_path("icons/controller.png")
        if os.path.exists(controller_icon_path):
            self.controller_button.setIcon(QIcon(controller_icon_path))
            self.controller_button.setIconSize(QSize(20, 20))
        else:
            self.controller_button.setText("🎮")
        self.controller_button.setFlat(True)
        self.controller_button.setFixedSize(QSize(28, 28))
        self.controller_button.setToolTip("Controller Settings")
        
        #self.status_label = QLabel(self.tr("Pronto."))
        self.status_label.setObjectName("StatusLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setMinimum(0)
        
        new_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder) # Icona Nuova Cartella?
        self.new_profile_button.setIcon(new_icon)
        
        steam_icon_path = resource_path("icons/steam.png") 
        if os.path.exists(steam_icon_path): # Controlla se il file esiste
             steam_icon = QIcon(steam_icon_path)
             self.steam_button.setIcon(steam_icon)
             self.steam_button.setIconSize(QSize(16, 16)) # Imposta la stessa dimensione delle altre icone
        else:
             logging.warning(f"File icona Steam non trovato: {steam_icon_path}")
             
        delete_prof_icon = style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon) # Icona Cestino
        self.delete_profile_button.setIcon(delete_prof_icon)
        
        self.backup_button = QPushButton("Backup")
        self.backup_button.setObjectName("BackupButton")
        backup_icon_path = resource_path("icons/backup.png")
        if os.path.exists(backup_icon_path):
             backup_icon = QIcon(backup_icon_path)
             self.backup_button.setIcon(backup_icon)
        else:
             logging.warning(f"File icona Backup non trovato: {backup_icon_path}")
             backup_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton) # Icona Salva (Floppy)
             self.backup_button.setIcon(backup_icon)
        
        # --- Backup Mode Toggle Integration ---
        self.backup_mode = "single" # Default mode
        
        # Toggle Button (Small +) - Will be parented to actions_group later for independent enable/disable
        self.backup_mode_toggle = QPushButton("+")
        self.backup_mode_toggle.setFixedSize(22, 18)
        self.backup_mode_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.backup_mode_toggle.setToolTip("Switch to 'Backup All' mode - Click to toggle")
        
        # Style for the toggle - clearer
        self.backup_mode_toggle.setStyleSheet("""
            QPushButton {
                border: none;
                background-color: transparent;
                color: rgba(255, 255, 255, 0.5);
                font-family: 'Segoe UI', Arial, sans-serif;
                font-weight: bold;
                font-size: 18px;
                padding: 0px;
                margin: 0px;
                /* Override global QPushButton min-width from theme */
                min-width: 0px;
                max-width: 22px;
                min-height: 0px;
                max-height: 18px;
            }
            QPushButton:hover {
                color: #3498DB;
                background-color: rgba(0,0,0,0.2);
                border-radius: 4px;
            }
            QPushButton:disabled {
                color: rgba(255, 255, 255, 0.2);
            }
        """)
        
        # Start hidden - visibility will be controlled by update_action_button_states
        # based on profile count (only show when 3+ profiles exist)
        self.backup_mode_toggle.setVisible(False)
        
        # Install event filter to handle manual positioning
        self.backup_button.installEventFilter(self)

        # Standard stylesheet (no extra padding needed now that we overlay)
        self.backup_button.setStyleSheet("""
            QPushButton#BackupButton {
                background-color: #222222;
                border: 1px solid #6b6b6b;
                color: #2980B9;
                border-radius: 5px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton#BackupButton:hover {
                background-color: #3a3a3a;
                border-color: #8b8b8b;
            }
            QPushButton#BackupButton:pressed {
                background-color: #454545;
                border-color: #8b8b8b;
            }
            QPushButton#BackupButton:disabled {
                border-color: #444444;
                color: #555555;
            }
        """)


        
        self.restore_button = QPushButton("Restore")
        self.restore_button.setObjectName("RestoreButton")
        restore_icon_path = resource_path("icons/restore.png")
        if os.path.exists(restore_icon_path):
            restore_icon = QIcon(restore_icon_path)
            self.restore_button.setIcon(restore_icon)
        else:
            logging.warning(f"File icona Restore non trovato: {restore_icon_path}")
            # Fallback to standard icon if custom icon is not found
            restore_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
            self.restore_button.setIcon(restore_icon)
        self.restore_button.setStyleSheet("""
            QPushButton#RestoreButton {
                background-color: #222222;
                border: 1px solid #6b6b6b;
                color: #27AE60;
                border-radius: 5px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton#RestoreButton:hover {
                background-color: #3a3a3a;
                border-color: #8b8b8b;
            }
            QPushButton#RestoreButton:pressed {
                background-color: #454545;
                border-color: #8b8b8b;
            }
            QPushButton#RestoreButton:disabled {
                border-color: #444444;
                color: #555555;
            }
        """)
        
        self.manage_backups_button = QPushButton("Manage Backups")
        self.manage_backups_button.setObjectName("ManageButton")
        manage_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView) # Icona Vista Dettagliata?
        self.manage_backups_button.setIcon(manage_icon)
        self.manage_backups_button.setStyleSheet("""
            QPushButton#ManageButton {
                background-color: #222222;
                border: 1px solid #6b6b6b;
                color: #e0e0e0;
                border-radius: 5px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton#ManageButton:hover {
                background-color: #3a3a3a;
                border-color: #8b8b8b;
            }
            QPushButton#ManageButton:pressed {
                background-color: #454545;
                border-color: #8b8b8b;
            }
            QPushButton#ManageButton:disabled {
                border-color: #444444;
                color: #555555;
            }
        """)
        
        self.open_backup_dir_button = QPushButton("Open Backup Folder")
        open_folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon) # Icona Apri Cartella
        self.open_backup_dir_button.setIcon(open_folder_icon)
        
        # Imposta dimensione icone (opzionale, regola i px se necessario)
        icon_size = QSize(16, 16) # Larghezza, Altezza in pixel
        icon_size_action = QSize(16, 16)  # Icone più grandi per pulsanti Backup/Restore
        self.new_profile_button.setIconSize(icon_size)
        self.delete_profile_button.setIconSize(icon_size)
        self.backup_button.setIconSize(icon_size_action)
        self.restore_button.setIconSize(icon_size_action)
        self.manage_backups_button.setIconSize(icon_size)
        self.open_backup_dir_button.setIconSize(icon_size)
        self.cloud_button.setIconSize(icon_size)
        # self.settings_button.setIconSize(icon_size)
        # self.steam_button.setIconSize(icon_size)

        #self.update_profile_table()

        # --- Layout ---
        main_layout = QVBoxLayout()
        # Make the title bar reach the window edges, while preserving content margins via a container
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)  # no gap below the title bar
        
        # Custom Title Bar (frameless)
        self.title_bar = QWidget()
        self.title_bar.setObjectName("CustomTitleBar")
        # Compact title bar height and internal padding
        self.title_bar.setMinimumHeight(36)
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(12, 4, 12, 4)
        title_layout.setSpacing(6)
        self.title_label = QLabel("SaveState - 1.4.6")
        self.title_label.setObjectName("TitleLabel")
        title_layout.addWidget(self.title_label)
        title_layout.addStretch(1)
        # Right-side icon buttons: Controller first, then Settings, then Theme
        self.controller_button.setObjectName("ControllerButton")
        self.settings_button.setObjectName("SettingsButton")
        self.theme_button.setObjectName("ThemeButton")
        title_layout.addWidget(self.controller_button)
        title_layout.addWidget(self.settings_button)
        title_layout.addWidget(self.theme_button)
        # Window control buttons (minimize, close) - no maximize/fullscreen
        self.minimize_button = QPushButton()
        self.minimize_button.setObjectName("MinimizeButton")
        self.minimize_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMinButton))
        self.minimize_button.setFixedSize(QSize(28, 28))
        self.minimize_button.setFlat(True)
        self.minimize_button.setIconSize(QSize(14, 14))
        self.minimize_button.clicked.connect(self.showMinimized)
        self.close_button = QPushButton()
        self.close_button.setObjectName("CloseButton")
        self.close_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self.close_button.setFixedSize(QSize(28, 28))
        self.close_button.setFlat(True)
        self.close_button.setIconSize(QSize(14, 14))
        self.close_button.clicked.connect(self.close)
        title_layout.addWidget(self.minimize_button)
        title_layout.addWidget(self.close_button)
        self.title_bar.setLayout(title_layout)
        # Allow dragging the window from the title bar
        self.title_bar.installEventFilter(self)
        
        # Title bar styling (darker than main UI, icon-only square buttons)
        self.title_bar.setStyleSheet(
            """
            QWidget#CustomTitleBar { background-color: #0d0d0d; border-bottom: 1px solid #333333; }
            QLabel#TitleLabel { color: #f2f2f2; font-size: 14pt; font-weight: 700; }
            QPushButton#SettingsButton, QPushButton#ThemeButton, QPushButton#ControllerButton, QPushButton#MinimizeButton, QPushButton#CloseButton {
                border: none; background: transparent; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 0px; border-radius: 4px;
            }
            QPushButton#SettingsButton:hover, QPushButton#ThemeButton:hover, QPushButton#ControllerButton:hover, QPushButton#MinimizeButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
            }
            QPushButton#ControllerButton[active="true"] {
                background-color: rgba(255, 255, 255, 0.2);
            }
            QPushButton#CloseButton:hover { background-color: #b00020; }
            """
        )
        
        main_layout.addWidget(self.title_bar)

        # Content container restores the usual margins around the app content
        content_container = QWidget()
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(12, 8, 12, 4)
        content_layout.setSpacing(4)
        content_container.setLayout(content_layout)
        
        # Create Profiles group - button positioned in title area via absolute positioning
        profile_group = QGroupBox("Profiles")
        profile_group.setObjectName("ProfilesGroup")
        self.profile_group = profile_group
        profile_layout = QVBoxLayout()
        profile_layout.setContentsMargins(6, 6, 6, 6)
        profile_layout.setSpacing(4)
        
        profile_layout.addWidget(self.profile_table_widget)
        profile_group.setLayout(profile_layout)
        content_layout.addWidget(profile_group, stretch=1)

        # Inline Profile Editor (hidden by default)
        self.profile_editor_group = QGroupBox("Edit Profile")
        editor_layout = QVBoxLayout()
        # Name field
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.edit_name_edit = QLineEdit()
        name_row.addWidget(self.edit_name_edit)
        editor_layout.addLayout(name_row)
        # Path field with browse
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Save Path:"))
        self.edit_path_edit = QLineEdit()
        self.edit_browse_button = QPushButton()
        self.edit_browse_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        path_row.addWidget(self.edit_path_edit)
        path_row.addWidget(self.edit_browse_button)
        editor_layout.addLayout(path_row)
        # Overrides toggle and group
        self.overrides_enable_checkbox = QCheckBox("Use profile-specific settings")
        editor_layout.addWidget(self.overrides_enable_checkbox)
        self.overrides_group = QGroupBox("Overrides")
        overrides_form = QFormLayout()
        # Max backups
        self.override_max_backups_spin = QSpinBox()
        self.override_max_backups_spin.setRange(1, 999)
        overrides_form.addRow("Max backups:", self.override_max_backups_spin)
        # Compression mode
        self.override_compression_combo = QComboBox()
        self.override_compression_combo.addItems(["standard", "maximum", "stored"])
        overrides_form.addRow("Compression:", self.override_compression_combo)
        # Max source size MB (match Settings dialog options)
        self.override_size_options = [
            ("50 MB", 50), ("100 MB", 100), ("250 MB", 250), ("500 MB", 500),
            ("1 GB (1024 MB)", 1024), ("2 GB (2048 MB)", 2048),
            ("5 GB (5120 MB)", 5120), ("No Limit", -1)
        ]
        self.override_max_size_combo = QComboBox()
        for display_text, _ in self.override_size_options:
            self.override_max_size_combo.addItem(display_text)
        overrides_form.addRow("Max source size (MB):", self.override_max_size_combo)
        # Check free space
        self.override_check_space_checkbox = QCheckBox("Check free disk space before backup")
        overrides_form.addRow(self.override_check_space_checkbox)
        self.overrides_group.setLayout(overrides_form)
        editor_layout.addWidget(self.overrides_group)
        # Save/Cancel buttons
        buttons_row = QHBoxLayout()
        self.edit_save_button = QPushButton("Save")
        self.edit_cancel_button = QPushButton("Cancel")
        buttons_row.addStretch(1)
        buttons_row.addWidget(self.edit_save_button)
        buttons_row.addWidget(self.edit_cancel_button)
        editor_layout.addLayout(buttons_row)
        self.profile_editor_group.setLayout(editor_layout)
        self.profile_editor_group.setVisible(False)
        content_layout.addWidget(self.profile_editor_group, stretch=1)

        # --- Inline Settings Panel (hidden by default) ---
        self.settings_panel_group = QGroupBox("Application Settings")
        settings_main_layout = QVBoxLayout()
        settings_main_layout.setContentsMargins(8, 4, 8, 8)  # Reduce top margin
        settings_main_layout.setSpacing(8)
        
        # Create grid layout for 2-column layout
        settings_grid = QGridLayout()
        settings_grid.setContentsMargins(4, 4, 4, 4)  # Reduce margins
        settings_grid.setHorizontalSpacing(16)
        settings_grid.setVerticalSpacing(12)
        
        # ROW 0, COL 0-1: Backup Base Path (full width)
        backup_path_group = QGroupBox("Backup Base Path")
        backup_path_layout = QHBoxLayout()
        backup_path_layout.setContentsMargins(8, 8, 8, 8)
        backup_path_layout.setSpacing(6)
        self.settings_path_edit = QLineEdit()
        self.settings_browse_button = QPushButton("Browse...")
        self.settings_browse_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        backup_path_layout.addWidget(self.settings_path_edit)
        backup_path_layout.addWidget(self.settings_browse_button)
        backup_path_group.setLayout(backup_path_layout)
        settings_grid.addWidget(backup_path_group, 0, 0, 1, 2)  # span 2 columns
        
        # ROW 1, COL 0: Portable Mode
        portable_group = QGroupBox("Portable Mode")
        portable_layout = QVBoxLayout()
        portable_layout.setContentsMargins(8, 8, 8, 8)
        portable_layout.setSpacing(6)
        self.settings_portable_checkbox = QCheckBox("Use only JSONs in backup folder (.savestate)")
        portable_layout.addWidget(self.settings_portable_checkbox)
        portable_group.setLayout(portable_layout)
        settings_grid.addWidget(portable_group, 1, 0)
        
        # ROW 1, COL 1: Maximum Source Size
        max_size_group = QGroupBox("Maximum Source Size for Backup")
        max_size_layout = QVBoxLayout()
        max_size_layout.setContentsMargins(8, 8, 8, 8)
        max_size_layout.setSpacing(6)
        self.settings_max_size_combo = QComboBox()
        self.settings_size_options = [
            ("50 MB", 50), ("100 MB", 100), ("250 MB", 250), ("500 MB", 500),
            ("1 GB (1024 MB)", 1024), ("2 GB (2048 MB)", 2048),
            ("5 GB (5120 MB)", 5120), ("No Limit", -1)
        ]
        for display_text, _ in self.settings_size_options:
            self.settings_max_size_combo.addItem(display_text)
        max_size_layout.addWidget(self.settings_max_size_combo)
        max_size_group.setLayout(max_size_layout)
        settings_grid.addWidget(max_size_group, 1, 1)
        
        # ROW 2, COL 0: Max Number of Backups
        max_backups_group = QGroupBox("Maximum Number of Backups per Profile")
        max_backups_layout = QHBoxLayout()
        max_backups_layout.setContentsMargins(8, 8, 8, 8)
        max_backups_layout.setSpacing(6)
        self.settings_max_backups_spin = QSpinBox()
        self.settings_max_backups_spin.setRange(1, 99)
        self.settings_max_backups_spin.setMaximumWidth(80)  # Limit width
        max_backups_layout.addWidget(self.settings_max_backups_spin)
        max_backups_layout.addWidget(QLabel("backups per profile (.zip)"))
        max_backups_layout.addStretch(1)  # Push everything to the left
        max_backups_group.setLayout(max_backups_layout)
        settings_grid.addWidget(max_backups_group, 2, 0)
        
        # ROW 2, COL 1: Backup Compression
        compression_group = QGroupBox("Backup Compression (.zip)")
        compression_layout = QVBoxLayout()
        compression_layout.setContentsMargins(8, 8, 8, 8)
        compression_layout.setSpacing(6)
        self.settings_compression_combo = QComboBox()
        self.settings_compression_options = {
            "standard": "Standard (Recommended)",
            "maximum": "Maximum (Slower)",
            "stored": "None (Faster)"
        }
        for key, text in self.settings_compression_options.items():
            self.settings_compression_combo.addItem(text, key)
        compression_layout.addWidget(self.settings_compression_combo)
        compression_group.setLayout(compression_layout)
        settings_grid.addWidget(compression_group, 2, 1)
        
        # ROW 3, COL 0: Free Disk Space Check
        space_check_group = QGroupBox("Free Disk Space Check")
        space_check_layout = QVBoxLayout()
        space_check_layout.setContentsMargins(8, 8, 8, 8)
        space_check_layout.setSpacing(6)
        self.settings_space_check_checkbox = QCheckBox("Enable space check before backup (minimum 2 GB)")
        space_check_layout.addWidget(self.settings_space_check_checkbox)
        space_check_group.setLayout(space_check_layout)
        settings_grid.addWidget(space_check_group, 3, 0)
        
        # ROW 3, COL 1: UI Settings
        ui_settings_group = QGroupBox("UI Settings")
        ui_settings_layout = QVBoxLayout()
        ui_settings_layout.setContentsMargins(8, 8, 8, 8)
        ui_settings_layout.setSpacing(6)
        self.settings_global_drag_checkbox = QCheckBox("Enable global mouse drag-to-show effect")
        self.settings_shorten_paths_checkbox = QCheckBox("Shorten save paths in selection dialogs")
        ui_settings_layout.addWidget(self.settings_global_drag_checkbox)
        ui_settings_layout.addWidget(self.settings_shorten_paths_checkbox)
        ui_settings_group.setLayout(ui_settings_layout)
        settings_grid.addWidget(ui_settings_group, 3, 1)
        
        # ROW 4, COL 0: System Tray Settings
        tray_settings_group = QGroupBox("System Tray")
        tray_settings_layout = QVBoxLayout()
        tray_settings_layout.setContentsMargins(8, 8, 8, 8)
        tray_settings_layout.setSpacing(6)
        self.settings_minimize_to_tray_checkbox = QCheckBox("Minimize to tray on close")
        tray_settings_layout.addWidget(self.settings_minimize_to_tray_checkbox)
        tray_settings_group.setLayout(tray_settings_layout)
        settings_grid.addWidget(tray_settings_group, 4, 0)
        
        # ROW 4, COL 1: Profile Appearance
        profile_ui_group = QGroupBox("Profile Appearance")
        profile_ui_layout = QVBoxLayout()
        profile_ui_layout.setContentsMargins(8, 8, 8, 8)
        profile_ui_layout.setSpacing(6)
        self.settings_show_icons_checkbox = QCheckBox("Show game icons in profile list")
        profile_ui_layout.addWidget(self.settings_show_icons_checkbox)
        profile_ui_group.setLayout(profile_ui_layout)
        settings_grid.addWidget(profile_ui_group, 4, 1)
        
        settings_main_layout.addLayout(settings_grid)
        # No stretch - let the grid breathe naturally
        
        # Exit and Save buttons
        settings_buttons_row = QHBoxLayout()
        self.settings_exit_button = QPushButton("Exit")
        self.settings_save_button = QPushButton("Save")
        settings_buttons_row.addStretch(1)
        settings_buttons_row.addWidget(self.settings_exit_button)
        settings_buttons_row.addWidget(self.settings_save_button)
        settings_main_layout.addLayout(settings_buttons_row)
        
        self.settings_panel_group.setLayout(settings_main_layout)
        self.settings_panel_group.setVisible(False)
        content_layout.addWidget(self.settings_panel_group, stretch=1)
        # --- End Inline Settings Panel ---

        # --- Inline Controller Settings Panel (hidden by default) ---
        self.controller_panel_group = ControllerPanel(parent=self)
        content_layout.addWidget(self.controller_panel_group, stretch=1)
        # Convenience aliases used by the rest of the class and by gui_handlers
        self.controller_enabled_switch = self.controller_panel_group.controller_enabled_switch
        self.ctrl_mapping_combos       = self.controller_panel_group.ctrl_mapping_combos
        self.controller_exit_button    = self.controller_panel_group.exit_button
        self.controller_save_button    = self.controller_panel_group.save_button
        # --- End Inline Controller Settings Panel ---

        # --- Inline Cloud Save Panel (hidden by default) ---
        self.cloud_panel = CloudSavePanel(
            backup_base_dir=self.current_settings.get("backup_base_dir", ""),
            profiles=self.profiles,
            parent=self
        )
        self.cloud_panel.setVisible(False)
        content_layout.addWidget(self.cloud_panel, stretch=1)
        # --- End Inline Cloud Save Panel ---

        actions_group = QGroupBox("Actions")
        self.actions_group = actions_group
        actions_layout = QHBoxLayout()
        # Use margins to shorten buttons slightly from the edges without making them tiny
        actions_layout.setContentsMargins(20, 8, 20, 8)
        actions_layout.setSpacing(20)

        # Allow buttons to expand naturally — sizes unchanged
        self.backup_button.setMaximumWidth(16777215) # Reset max width to default (QWIDGETSIZE_MAX)
        self.restore_button.setMaximumWidth(16777215)
        self.manage_backups_button.setMaximumWidth(16777215)

        actions_layout.addWidget(self.backup_button)
        actions_layout.addWidget(self.restore_button)
        actions_layout.addWidget(self.manage_backups_button)

        actions_group.setLayout(actions_layout)

        # Add the toggle button as a child of actions_group (not backup_button)
        # This allows it to remain enabled even when backup_button is disabled
        self.backup_mode_toggle.setParent(actions_group)
        self.backup_mode_toggle.raise_()  # Ensure it's on top
        
        # Install event filter on actions_group to reposition toggle when layout changes
        actions_group.installEventFilter(self)
        
        content_layout.addWidget(actions_group)
        general_group = QGroupBox("General")
        self.general_group = general_group
        general_layout = QHBoxLayout()
        general_layout.setContentsMargins(6, 6, 6, 6)
        general_layout.setSpacing(6)
        general_layout.addWidget(self.new_profile_button)
        general_layout.addWidget(self.steam_button)
        general_layout.addWidget(self.open_backup_dir_button) # Moved back here
        general_group.setLayout(general_layout)

        # --- New right-side Cloud group next to General with a light separator ---
        self.cloud_group = QGroupBox("")  # frameless title to visually group the Cloud button
        cloud_layout = QHBoxLayout()
        cloud_layout.setContentsMargins(6, 6, 6, 6)
        cloud_layout.setSpacing(6)
        # Reduce Cloud button width slightly (about 15-20%)
        self.cloud_button.setMaximumWidth(150)  # Limit max width
        self.cloud_button.setStyleSheet("padding-left: 14px; padding-right: 14px;")
        cloud_layout.addWidget(self.cloud_button)
        self.cloud_group.setLayout(cloud_layout)
        # Make the cloud group take minimal space
        self.cloud_group.setMaximumWidth(170)  # Slightly larger than button to account for margins
        self.cloud_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        # Invisible spacer between General and Cloud (replaces visible separator)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.NoFrame)
        separator.setFixedWidth(2)  # Just spacing, no visible line
        separator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        separator.setStyleSheet("QFrame { background: transparent; border: none; }")

        # Row container to place General (left) and Cloud (right of it)
        self.general_cloud_row = QWidget()
        general_cloud_row_layout = QHBoxLayout()
        general_cloud_row_layout.setContentsMargins(0, 0, 0, 0)
        general_cloud_row_layout.setSpacing(6)
        general_cloud_row_layout.addWidget(general_group)
        general_cloud_row_layout.addWidget(separator)
        general_cloud_row_layout.addWidget(self.cloud_group)
        self.general_cloud_row.setLayout(general_cloud_row_layout)

        content_layout.addWidget(self.general_cloud_row)
        
        # --- Layout per Search Bar e Pulsante Log (in basso) ---
        # Wrap in a widget container so we can easily hide it
        self.bottom_controls_widget = QWidget()
        bottom_controls_layout = QHBoxLayout()
        bottom_controls_layout.setContentsMargins(0, 0, 0, 0)
        bottom_controls_layout.setSpacing(6)
        bottom_controls_layout.addWidget(self.search_bar) # Search bar first
        bottom_controls_layout.addStretch(1) # Add stretch to push log button to the right
        bottom_controls_layout.addWidget(self.toggle_log_button) # Log button last
        self.bottom_controls_widget.setLayout(bottom_controls_layout)
        
        # Set fixed height to prevent UI jumping when search bar shows/hides
        # Calculate height based on search bar size hint and add padding
        search_bar_height = self.search_bar.sizeHint().height()
        log_button_height = self.toggle_log_button.sizeHint().height()
        # Use the larger of the two and add 4-6 pixels for vertical spacing (2-3px top + 2-3px bottom)
        fixed_height = max(search_bar_height, log_button_height) + 6
        self.bottom_controls_widget.setFixedHeight(fixed_height)

        content_layout.addWidget(self.bottom_controls_widget)
        
        # Finally add the content container to the main layout (beneath the title bar)
        main_layout.addWidget(content_container, stretch=1)
        # --- FINE Layout Search Bar e Pulsante Log ---
        
        status_bar = QStatusBar()
        status_bar.addWidget(self.status_label, stretch=1)
        status_bar.addPermanentWidget(self.progress_bar)
        try:
            # Add a size grip so the frameless window remains resizable
            self.size_grip = QSizeGrip(self)
            status_bar.addPermanentWidget(self.size_grip)
        except Exception:
            pass
        
        # --- Limita Altezza Status Bar ---
        # Calcola l'altezza di una riga di testo con un po' di margine
        font_metrics = self.status_label.fontMetrics()
        # Prova con altezza per 1 riga + margine, o moltiplica fm.height() * 2 per 2 righe
        max_height = font_metrics.height() + 10 # Esempio: altezza 1 riga + 10px margine
        # Oppure: max_height = (font_metrics.height() * 2) + 6 # Esempio: altezza 2 righe + 6px margine
        status_bar.setMaximumHeight(max_height)
        status_bar.setStyleSheet("QStatusBar { border-top: 1px solid #555555; }") # Opzionale: aggiungi bordo sopra per separarla
        # --- FINE Limita Altezza ---
        
        self.setStatusBar(status_bar)
        
        # --- CREAZIONE DOCK WIDGET PER IL LOG ---
        self.log_dock_widget = QDockWidget("Console Log", self)
        self.log_dock_widget.setObjectName("LogDockWidget") # Utile per QSS
        self.log_dock_widget.setMinimumHeight(150)

        self.log_output = QPlainTextEdit() # Usiamo QPlainTextEdit, più efficiente per tanto testo
        self.log_output.setReadOnly(True)
        # Stile scuro per il log (alternativa a QSS, imposta la palette)
        log_palette = self.log_output.palette()
        log_palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45)) # Sfondo scuro tipo #2D2D2D
        log_palette.setColor(QPalette.ColorRole.Text, QColor(240, 240, 240)) # Testo chiaro tipo #F0F0F0
        self.log_output.setPalette(log_palette)

        self.log_dock_widget.setWidget(self.log_output)
        self.log_dock_widget.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea) # Dove può essere agganciato
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.log_dock_widget) # Posizione iniziale
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock_widget)
        
        self.log_dock_widget.setVisible(False) # Nascondi all'inizio
        # --- FINE CREAZIONE DOCK WIDGET ---

        # --- Connessione Segnale Log ---
        # Connetti il segnale dal gestore log allo slot appendHtml del widget
        if self.qt_log_handler: # <-- Usa il nuovo riferimento
            self.qt_log_handler.log_signal.connect(self.log_output.appendHtml) # <-- Usa il nuovo riferimento
            # Potremmo anche rimuovere il controllo e l'aggiunta dell'handler qui,
            # perché l'handler viene già aggiunto nel blocco main, ma lasciamolo per ora.
            root_logger = logging.getLogger()
            if self.qt_log_handler not in root_logger.handlers:
                root_logger.addHandler(self.qt_log_handler)
        # --- FINE Connessione Segnale ---
        
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # System tray support
        self._allow_close = False
        self._setup_system_tray()

        # Set initial focus to the MainWindow itself to help with keyPressEvent activation
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()

        # Inizializza i gestori delle funzionalità
        self.profile_table_manager = ProfileListManager(self.profile_table_widget, self)
        self.theme_manager = ThemeManager(self.theme_button, self)
        self.profile_creation_manager = ProfileCreationManager(self)
        self.drag_drop_handler = DragDropHandler(self)
        self.current_search_thread = None

        # Create the handlers instance HERE, before connecting signals that use it
        self.handlers = MainWindowHandlers(self)

        # Connessioni ai metodi della classe handlers
        self.backup_button.clicked.connect(self.handlers.handle_backup)
        # Connect toggle for backup mode
        self.backup_mode_toggle.clicked.connect(self.handlers.toggle_backup_mode)
        # self.backup_all_button connection removed (button integrated)
        self.restore_button.clicked.connect(self.handlers.handle_restore)
        self.profile_table_widget.itemSelectionChanged.connect(self.update_action_button_states)
        self.new_profile_button.clicked.connect(self.profile_creation_manager.handle_new_profile)
        self.delete_profile_button.clicked.connect(self.handlers.handle_delete_profile)
        self.steam_button.clicked.connect(self.handlers.handle_steam)
        self.manage_backups_button.clicked.connect(self.handlers.handle_manage_backups)
        self.settings_button.clicked.connect(self.handlers.handle_settings)
        self.open_backup_dir_button.clicked.connect(self.handlers.handle_open_backup_folder)
        self.cloud_button.clicked.connect(self._handle_cloud_button_clicked)
        # Settings panel connections
        self.settings_exit_button.clicked.connect(self.handlers.handle_settings_exit)
        self.settings_save_button.clicked.connect(self.handlers.handle_settings_save)
        self.settings_browse_button.clicked.connect(self.handlers.handle_settings_browse)
        # Controller panel connections
        self.controller_button.clicked.connect(self.handlers.handle_controller)
        self.controller_exit_button.clicked.connect(self.handlers.handle_controller_exit)
        self.controller_save_button.clicked.connect(self.handlers.handle_controller_save)
        # Log button connections use handlers
        self.toggle_log_button.pressed.connect(self.handlers.handle_log_button_pressed)
        self.toggle_log_button.released.connect(self.handlers.handle_log_button_released)
        # Timer timeout connection moved HERE
        self.log_button_press_timer.timeout.connect(self.handlers.handle_developer_mode_toggle)

        # minecraft_button removed - functionality moved to new_profile_menu
        # create_shortcut_button removed - functionality available in context menu
        # Right-click context menu on profile table
        self.profile_table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profile_table_widget.customContextMenuRequested.connect(self._on_profile_table_context_menu)
        # Editor actions
        self.edit_browse_button.clicked.connect(self.handlers.handle_profile_edit_browse)
        self.edit_save_button.clicked.connect(self.handlers.handle_profile_edit_save)
        self.edit_cancel_button.clicked.connect(self.handlers.handle_profile_edit_cancel)
        # Overrides toggle action
        self.overrides_enable_checkbox.toggled.connect(self.handlers.handle_profile_overrides_toggled)

        # Stato Iniziale e Tema
        self.update_action_button_states()
        self.worker_thread = None
        self.updateUiText()
        self.setWindowIcon(QIcon(resource_path("icon.png"))) # Icona finestra principale
        
        # Position backup toggle and controller badges after layout is complete
        QTimer.singleShot(100, self._position_backup_toggle)

        # Initialize controller manager (start only if enabled in settings)
        self.controller_manager = ControllerManager(self)
        if self.current_settings.get("controller_support_enabled", True):
            self.controller_manager.start()
    
    def reset_internal_state(self):
        """Resetta lo stato interno per le operazioni di drag & drop."""
        # Resetta le liste dei thread
        if not hasattr(self, '_detection_threads'):
            self._detection_threads = []
        else:
            self._detection_threads.clear()
            
        if not hasattr(self, 'active_threads'):
            self.active_threads = {}
        else:
            self.active_threads.clear()
            
        # Resetta il flag di cancellazione
        self.processing_cancelled = False
            
        logging.debug("Internal state reset: _detection_threads, active_threads cleared, processing_cancelled reset")
    
    def _position_backup_toggle(self):
        """Position the backup mode toggle button over the backup button."""
        try:
            if not hasattr(self, 'backup_mode_toggle') or not hasattr(self, 'backup_button') or not hasattr(self, 'actions_group'):
                return
            
            # Get backup_button's position relative to actions_group
            btn_pos = self.backup_button.mapTo(self.actions_group, self.backup_button.rect().topLeft())
            btn_size = self.backup_button.size()
            toggle_w = self.backup_mode_toggle.width()
            toggle_h = self.backup_mode_toggle.height()
            
            margin_right = 6  # Distance from the right edge of the button
            
            # Calculate position: right side of button, vertically centered
            new_x = btn_pos.x() + btn_size.width() - toggle_w - margin_right
            new_y = btn_pos.y() + (btn_size.height() - toggle_h) // 2
            
            self.backup_mode_toggle.move(new_x, new_y)
            self.backup_mode_toggle.raise_()  # Ensure it stays on top
        except Exception as e:
            pass  # Fail silently for UI polish

    # --- UI and Event Handling ---
    # Centers the loading label within the overlay widget.
    def _center_loading_label(self):
        """Centra il widget di caricamento all'interno dell'overlay."""
        if hasattr(self, 'overlay_widget') and hasattr(self, 'loading_label') and self.overlay_widget and self.loading_label:
            try:
                # Usa la dimensione fissa che abbiamo impostato
                label_size = self.loading_label.size()

                if label_size.isValid() and label_size.width() > 0:
                    overlay_rect = self.overlay_widget.rect()
                    top_left_x = (overlay_rect.width() - label_size.width()) // 2
                    top_left_y = (overlay_rect.height() - label_size.height()) // 2
                    self.loading_label.move(top_left_x, top_left_y)
                else:
                     logging.warning("Cannot center loading label: invalid size.")
            except Exception as e:
                 logging.error(f"Error centering loading label: {e}")

    # Called when the main window is resized; ensures the overlay and loading label resize correctly.
    def resizeEvent(self, event):
        """Aggiorna la dimensione dell'overlay quando la finestra cambia dimensione."""
        super().resizeEvent(event)
        # Ridimensiona overlay
        if hasattr(self, 'overlay_widget') and self.overlay_widget:
            self.overlay_widget.resize(self.centralWidget().size())
        # Centra label
        self._center_loading_label() # Chiama il metodo helper
        # Reposition backup toggle button
        self._position_backup_toggle()
    # Called when a dragged item enters the window; accepts if it contains valid URLs.
    def dragEnterEvent(self, event: QDragEnterEvent):
        logging.debug("MainWindow.dragEnterEvent: Entered.")
        if event.mimeData().hasUrls():
            urls_debug_list = []
            for url_obj_debug in event.mimeData().urls():
                urls_debug_list.append(
                    f"URL: {url_obj_debug.toString()}, "
                    f"Scheme: {url_obj_debug.scheme()}, "
                    f"IsLocal: {url_obj_debug.isLocalFile()}, "
                    f"LocalPath: {url_obj_debug.toLocalFile() if url_obj_debug.isLocalFile() else 'N/A'}"
                )
            logging.debug(f"  MimeData has URLs: [{', '.join(urls_debug_list)}]")
        if event.mimeData().hasText():
            logging.debug(f"  MimeData has Text (first 200 chars): '{event.mimeData().text()[:200]}'")

        if event.mimeData().hasUrls() or event.mimeData().hasText():
            logging.debug("MainWindow.dragEnterEvent: Potentially valid data. Emitting request_show_overlay and accepting event.")
            
            # Reset the custom overlay message flag to ensure we show "Drop Here" during drag
            if hasattr(self, '_custom_overlay_message_set'):
                self._custom_overlay_message_set = False
                logging.debug("MainWindow.dragEnterEvent: Reset _custom_overlay_message_set to False")
                
            # Force the loading label to show "Drop Here" during drag
            if hasattr(self, 'loading_label') and self.loading_label:
                self.loading_label.setText("Drop Here")
                logging.debug("MainWindow.dragEnterEvent: Set loading_label text to 'Drop Here'")
                
            self.request_show_overlay.emit() # Request to show the "Drop Here" overlay
            event.acceptProposedAction() # Accept the drag operation
        else:
            logging.debug("MainWindow.dragEnterEvent: Invalid data type. Ignoring event.")
            event.ignore() # Ignore if not carrying URLs/Text

    # Gestisce il movimento durante il drag.
    def dragMoveEvent(self, event: QDragMoveEvent):
        """Gestisce il movimento durante il drag."""
        # If dragEnterEvent accepted, then dragMoveEvent should also generally accept.
        # Specific child widgets will handle their own dragMoveEvents if they accept drops.
        event.acceptProposedAction()

    # Gestisce l'uscita del cursore dall'area dell'applicazione durante il drag.
    def dragLeaveEvent(self, event: QDragLeaveEvent):
        # This event is triggered when a drag leaves the widget area.
        logging.debug(f"MainWindow.dragLeaveEvent: Emitting request_hide_overlay.")
        self.request_hide_overlay.emit()
        event.accept() # Accept the event

    def eventFilter(self, watched, event):
        """Enable window dragging from the custom title bar and ignore double-click maximize."""
        try:
            if hasattr(self, 'title_bar') and watched is self.title_bar:
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    # On Linux, try to use native window dragging via startSystemMove()
                    if self._is_linux and hasattr(self, 'windowHandle') and self.windowHandle():
                        try:
                            # Get global position from event
                            if hasattr(event, 'globalPosition'):
                                global_pos = event.globalPosition().toPoint()
                            else:
                                global_pos = event.globalPos()
                            # Use Qt's native window move for better Linux compatibility
                            self.windowHandle().startSystemMove()
                            return True
                        except Exception as e:
                            logging.debug(f"startSystemMove failed on Linux, falling back to manual drag: {e}")
                    
                    # Fallback to manual dragging (for Windows or if startSystemMove fails)
                    pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                    self._drag_pos = pos - self.frameGeometry().topLeft()
                    return True
                    
                if event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                    if self._drag_pos is not None:
                        pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                        new_pos = pos - self._drag_pos
                        self.move(new_pos)
                        return True
                        
                if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                    # Reset drag position on release
                    self._drag_pos = None
                    return True
                    
                if event.type() == QEvent.Type.MouseButtonDblClick:
                    # Do nothing on double click (no maximize toggle)
                    return True
        except Exception as e:
            logging.debug(f"eventFilter exception: {e}")
            
        # Handle manual positioning of the backup toggle button and controller badges
        # Toggle/badges are children of actions_group, positioned over their respective buttons
        try:
            if hasattr(self, 'actions_group') and watched is self.actions_group:
                if event.type() == QEvent.Type.Resize or event.type() == QEvent.Type.Show:
                    self._position_backup_toggle()
            elif hasattr(self, 'backup_button') and watched is self.backup_button:
                if event.type() == QEvent.Type.Resize or event.type() == QEvent.Type.Move or event.type() == QEvent.Type.Show:
                    self._position_backup_toggle()
        except Exception:
            pass  # Fail silently for UI polish

        # ── Mouse usage → exit controller visual mode ─────────────────
        try:
            if event.type() == QEvent.Type.MouseButtonPress:
                if getattr(self, '_ctrl_focus_section', None) is not None:
                    self._ctrl_exit_visual_mode()
        except Exception:
            pass

        return super().eventFilter(watched, event)

    def dropEvent(self, event: QDropEvent):
        """Handles drop events by delegating to the DragDropHandler."""
        logging.debug("MainWindow.dropEvent: Delegating to DragDropHandler.")
        
        # Hide the overlay; the handler will show its own UI if needed.
        self.request_hide_overlay.emit()

        if hasattr(self, 'drag_drop_handler') and self.drag_drop_handler:
            # The handler's own dropEvent will manage everything, including accepting/ignoring the event.
            self.drag_drop_handler.dropEvent(event)
        else:
            logging.error("MainWindow.dropEvent: DragDropHandler not initialized.")
            event.ignore()
    
    def _handle_cloud_button_clicked(self):
        """Open the Cloud Save panel."""
        try:
            # Toggle cloud panel (show if hidden, hide if visible)
            if getattr(self, '_cloud_mode_active', False):
                # Cloud panel is open, close it
                self.exit_cloud_panel()
                logging.debug("Cloud panel toggled OFF (closed).")
            else:
                # Cloud panel is closed, open it
                self.show_cloud_panel()
                logging.debug("Cloud panel toggled ON (opened).")
        except Exception as e:
            logging.error(f"Error toggling cloud panel: {e}")
            if hasattr(self, 'status_label'):
                self.status_label.setText("Error opening Cloud Save panel.")
    
    def updateUiText(self):
        """Updates the UI text"""
        logging.debug(">>> updateUiText: START <<<")
        self.setWindowTitle("SaveState - 2.5")
        if hasattr(self, 'title_label'):
            self.title_label.setText("SaveState - 2.5")
        self.profile_table_manager.retranslate_headers()
        # Keep Settings as icon-only in the title bar
        self.settings_button.setText("")
        self.new_profile_button.setText("New Profile...")
        self.steam_button.setText("Manage Steam")
        self.backup_button.setText("Backup")
        self.restore_button.setText("Restore")
        self.manage_backups_button.setText("Manage Backups")
        self.open_backup_dir_button.setText("Open Backup Folder")
        if hasattr(self, 'cloud_button'):
            self.cloud_button.setText("Cloud Sync")

        if hasattr(self, 'profile_group'): # Check if attribute exists
            self.profile_group.setTitle("Profiles")
        if hasattr(self, 'actions_group'):
            self.actions_group.setTitle("Actions")
        if hasattr(self, 'general_group'):
            self.general_group.setTitle("General")

            # Update animation label placeholder text
            # Check if the label exists and is NOT showing a GIF (movie)
            if hasattr(self, 'loading_label') and self.loading_label and \
            (not hasattr(self, 'loading_movie') or not self.loading_movie or not self.loading_movie.isValid()):
                self.loading_label.setText("Drop Here")
                # --- START OF MODIFIED STYLING ---
                # font = self.loading_label.font()
                # font.setPointSize(24)
                # font.setBold(True)
                # self.loading_label.setFont(font) # Stylesheet handles this now
                self.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; }")
                self.loading_label.adjustSize() # Ensure label resizes to content
                # --- END OF MODIFIED STYLING ---

            logging.debug("Updating profile table after UI text update")
            self.profile_table_manager.update_profile_table()

        # Update editor texts if present
        if hasattr(self, 'profile_editor_group'):
            self.profile_editor_group.setTitle("Edit Profile")
        if hasattr(self, 'edit_save_button'):
            self.edit_save_button.setText("Save")
        if hasattr(self, 'edit_cancel_button'):
            self.edit_cancel_button.setText("Cancel")
        if hasattr(self, 'overrides_group'):
            self.overrides_group.setTitle("Overrides")
        if hasattr(self, 'overrides_enable_checkbox'):
            self.overrides_enable_checkbox.setText("Use profile-specific settings")

        # --- Update Tooltips and Titles ---
        # create_shortcut_button removed - functionality available in context menu
        # minecraft_button tooltip update removed - button integrated into new_profile_menu
        if hasattr(self, 'toggle_log_button'):
            # Set a generic tooltip, will be updated by handle_toggle_log if needed
             is_log_visible = self.log_dock_widget.isVisible() if hasattr(self, 'log_dock_widget') else False
             tooltip_key = "Hide Log" if is_log_visible else "Show Log"
             self.toggle_log_button.setToolTip(tooltip_key)
        if hasattr(self, 'log_dock_widget'):
            self.log_dock_widget.setWindowTitle("Console Log")
        logging.debug(">>> updateUiText: END <<<")

    def show_overlay_message(self, message_text):
        """Shows the overlay with a custom message.
        This method is called from ProfileCreationManager when processing Steam URLs.
        """
        if not hasattr(self, 'loading_label') or not self.loading_label:
            logging.error("show_overlay_message called but loading_label does not exist.")
            return
            
        # Set the custom message text
        self.loading_label.setText(message_text)
        
        # Ensure the label has the right style and text formatting
        self.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; padding: 20px; }") 
        
        # Make sure the label adjusts its size to fit the text
        self.loading_label.adjustSize()
        
        # Ensure the label is visible
        self.loading_label.setVisible(True)
        
        # Emit the signal to show the overlay
        self.request_show_overlay.emit()
        
        logging.info(f"Showing overlay with message: {message_text}")
    
    def _show_overlay(self):
        """Mostra l'overlay con animazione."""
        if not hasattr(self, 'overlay_widget') or not self.overlay_widget:
            logging.error("_show_overlay called but overlay_widget does not exist.")
            return
            
        # If overlay is already active, don't show it again to prevent double fade effects
        if hasattr(self, 'overlay_active') and self.overlay_active:
            logging.debug("_show_overlay: overlay already active, skipping to prevent double fade")
            return
            
        # Set the flag to indicate overlay is now active
        self.overlay_active = True
        logging.debug("_show_overlay: setting overlay_active = True")
        
        # Ensure the overlay is sized correctly.
        # It's parented to self (MainWindow), so it should cover the MainWindow's area or central widget area.
        if self.centralWidget():
            self.overlay_widget.setGeometry(self.centralWidget().rect())
        else:
            logging.warning("Central widget not available for overlay. Overlay will cover the entire main window.")
            self.overlay_widget.setGeometry(self.rect()) # Fallback to main window rect

        # Ensure the overlay itself has the correct dark style every time it's shown
        self.overlay_widget.setStyleSheet("QWidget#BusyOverlay { background-color: rgba(0, 0, 0, 200); }")
        self.overlay_widget.raise_() # Bring to front
        
        # Only set default text if no text is already set
        if not self.loading_label.text() or self.loading_label.text().strip() == "":
            self.loading_label.setText("Drop Here")

        # Ensure font and style are correct if not already set by show_overlay_message
        if "padding" not in self.loading_label.styleSheet():
            self.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; padding: 20px; }")
        
        # Always adjust size and center
        self.loading_label.adjustSize() # Ensure label resizes before centering
        self._center_loading_label() # Center the label
        
        self.loading_label.show()
        self.overlay_widget.show()
        
        if hasattr(self, 'fade_in_animation'):
            self.fade_in_animation.stop() # Stop if already running
            self.fade_in_animation.start()
            logging.debug("Fade-in animation started for overlay.")
        else:
            # Fallback if animation not set up, just show (though we expect it to be)
            self.overlay_opacity_effect.setOpacity(1.0)
            logging.warning("Fade-in animation missing, showing overlay directly.")

    def _hide_overlay(self):
        """Nasconde l'overlay con animazione."""
        # If overlay is locked (forced), ignore hide requests
        if hasattr(self, "_overlay_locked") and self._overlay_locked:
            logging.debug("_hide_overlay: overlay locked, ignoring hide request")
            return
        if not hasattr(self, 'overlay_widget') or not self.overlay_widget:
            logging.error("_hide_overlay called but overlay_widget does not exist.")
            return
            
        # If overlay is not active, no need to hide it
        if hasattr(self, 'overlay_active') and not self.overlay_active:
            logging.debug("_hide_overlay: overlay not active, nothing to hide")
            return
            
        if self.fade_out_animation.state() == QAbstractAnimation.Running:
            logging.debug("_hide_overlay: Already fading out.")
            return

        # Stop any incoming animation if it's running
        if hasattr(self, 'fade_in_animation') and self.fade_in_animation.state() == QAbstractAnimation.Running:
            logging.debug("_hide_overlay: Stopping fade_in_animation.")
            self.fade_in_animation.stop()
            # Ensure opacity is at a known state if fade-in was interrupted early
            # self.overlay_opacity_effect.setOpacity(1.0) # Or current value, but fade_out starts from 1.0

        logging.debug(f"_hide_overlay: Proceeding to hide. Visible: {self.overlay_widget.isVisible()}, Active: {self.overlay_active}")
        if hasattr(self, 'fade_out_animation'):
            # Ensure opacity is 1.0 if we are about to fade out from a visible state
            # This handles cases where fade-in might have been stopped midway by a rapid hide request
            if self.overlay_opacity_effect.opacity() < 1.0:
                 self.overlay_opacity_effect.setOpacity(1.0)
            self.fade_out_animation.start()
            logging.debug("Fade-out animation started for overlay.")
        else:
            # Fallback if animation not set up
            self.overlay_widget.hide()
            if hasattr(self, 'loading_label'): self.loading_label.hide()
            if hasattr(self, 'overlay_opacity_effect'): self.overlay_opacity_effect.setOpacity(0.0)
            self.overlay_active = False # Set directly if no animation
            logging.warning("Fade-out animation missing, hiding overlay directly and setting overlay_active=False.")

    @Slot()
    def _on_overlay_faded_out(self):
        """Called when the fade-out animation of the overlay is finished."""
        logging.debug("_on_overlay_faded_out: Fade-out finished. Setting overlay_active = False.")
        self.overlay_active = False
        # Ensure the label is also hidden if it wasn't part of the overlay_widget's fade directly
        if hasattr(self, 'loading_label'):
            self.loading_label.hide()
        # The overlay_widget itself should be hidden by its fade_out_animation.finished.connect(self.overlay_widget.hide) connection

    # --- Overlay lock helpers (force overlay while a secondary UI is active) ---
    def lock_overlay(self, message_text: str | None = None):
        """Force overlay to stay visible until unlock_overlay is called.
        If a fade-out is in progress, cancel it and restore full opacity.
        """
        try:
            self._overlay_locked = True

            # Cancel in-flight fade-out to prevent the overlay from hiding after we lock it
            try:
                if hasattr(self, 'fade_out_animation') and self.fade_out_animation.state() == QAbstractAnimation.Running:
                    self.fade_out_animation.stop()
                    if hasattr(self, 'overlay_opacity_effect'):
                        self.overlay_opacity_effect.setOpacity(1.0)
            except Exception:
                pass

            # Set message and style
            if hasattr(self, 'loading_label') and self.loading_label:
                if message_text:
                    self.loading_label.setText(message_text)
                if "padding" not in self.loading_label.styleSheet():
                    self.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; padding: 20px; }")
                self.loading_label.adjustSize()

            # Ensure overlay is visible and on top
            if hasattr(self, 'overlay_widget') and self.overlay_widget:
                if self.centralWidget():
                    self.overlay_widget.setGeometry(self.centralWidget().rect())
                else:
                    self.overlay_widget.setGeometry(self.rect())
                self.overlay_widget.setStyleSheet("QWidget#BusyOverlay { background-color: rgba(0, 0, 0, 200); }")
                self.overlay_widget.raise_()
                if hasattr(self, 'loading_label') and self.loading_label:
                    self._center_loading_label()
                    self.loading_label.show()
                self.overlay_widget.show()
                self.overlay_active = True

            logging.debug("Overlay locked (forced visible).")
        except Exception as e:
            logging.error(f"Error locking overlay: {e}", exc_info=True)

    def unlock_overlay(self):
        """Release overlay lock and then hide overlay normally."""
        try:
            self._overlay_locked = False
            self._hide_overlay()
            logging.debug("Overlay unlocked and hide requested.")
        except Exception as e:
            logging.error(f"Error unlocking overlay: {e}", exc_info=True)
    # Handles application-level events
    def changeEvent(self, event):
        """Intercetta eventi di cambio stato."""
        if event.type() == QEvent.Type.LanguageChange:
            logging.debug("MainWindow.changeEvent(LanguageChange) detected")
            pass
        super().changeEvent(event) # Chiama l'implementazione base

    # Retrieves the name of the currently selected profile from the table manager.
    def get_selected_profile_name(self):
        """Helper per ottenere il nome del profilo selezionato dalla tabella."""
        if hasattr(self, 'profile_table_manager') and self.profile_table_manager:
             return self.profile_table_manager.get_selected_profile_name()
        # Fallback or warning if called too early
        logging.warning("get_selected_profile_name called before profile_table_manager exists or reference is missing.")
        return None

    # Updates the enabled state of action buttons based on profile selection.
    def update_action_button_states(self):
        """Aggiorna lo stato abilitato/disabilitato dei pulsanti Azioni."""
        has_selection = self.profile_table_manager.has_selection()
        has_profiles = len(self.profiles) > 0
        
        # Backup button state depends on mode
        backup_mode = getattr(self, 'backup_mode', 'single')
        if backup_mode == 'all':
            self.backup_button.setEnabled(has_profiles)
        else:
            self.backup_button.setEnabled(has_selection)
            # Update button text based on selection count (multi-selection support)
            selection_count = self.profile_table_manager.get_selection_count()
            if selection_count > 1:
                self.backup_button.setText("Backup Selected")
            else:
                self.backup_button.setText("Backup")
        
        # Toggle button should ALWAYS be enabled (if there are profiles)
        # But it should only be VISIBLE when there are 3+ profiles
        if hasattr(self, 'backup_mode_toggle'):
            profile_count = len(self.profiles) if self.profiles else 0
            should_show_toggle = profile_count >= 3
            self.backup_mode_toggle.setVisible(should_show_toggle)
            self.backup_mode_toggle.setEnabled(has_profiles)
            
        # Restore button is always enabled now - can restore from ZIP without a profile
        self.restore_button.setEnabled(True)
        self.manage_backups_button.setEnabled(has_selection)
        # create_shortcut_button removed - functionality available in context menu
        # Cloud and Open Backup Folder require at least one profile to exist
        if hasattr(self, 'cloud_button'):
            self.cloud_button.setEnabled(has_profiles)
        if hasattr(self, 'open_backup_dir_button'):
            self.open_backup_dir_button.setEnabled(has_profiles)

    @Slot(str)
    def _on_main_search_text_changed(self, text):
        """Filters the profile table based on the search text and hides search bar if empty."""
        search_term = text.lower()
        logging.debug(f"Search term: '{search_term}'")

        if not hasattr(self, 'profile_table_widget') or self.profile_table_widget is None:
            logging.warning("_on_main_search_text_changed: profile_table_widget not found.")
            return

        visible_rows = 0
        for i in range(self.profile_table_widget.rowCount()):
            item = self.profile_table_widget.item(i, 1)  # Profile name in the SECOND column (index 1)
            row_should_be_hidden = True # Default to hiding

            if item and item.text():
                profile_name = item.text().lower()
                logging.debug(f"  Row {i}: Profile name '{profile_name}'")
                if search_term:
                    if search_term in profile_name:
                        row_should_be_hidden = False
                        logging.debug(f"    -> Match found. Row {i} will be SHOWN.")
                    else:
                        row_should_be_hidden = True
                        logging.debug(f"    -> No match. Row {i} will be HIDDEN.")
                else: # No search term, so show all valid rows
                    row_should_be_hidden = False
                    logging.debug(f"    -> No search term. Row {i} (valid item) will be SHOWN.")
            else:
                logging.debug(f"  Row {i}: No item or item has no text.")
                if search_term: # If searching and item is invalid, hide it
                    row_should_be_hidden = True
                    logging.debug(f"    -> Invalid item and searching. Row {i} will be HIDDEN.")
                else: # No search term, show even if item is somehow invalid (though ideally shouldn't happen)
                    row_should_be_hidden = False # Or True, depending on desired behavior for empty/invalid rows with no search
                    logging.debug(f"    -> Invalid item, no search term. Row {i} will be SHOWN (or HIDDEN based on policy).")
            
            self.profile_table_widget.setRowHidden(i, row_should_be_hidden)
            if not row_should_be_hidden:
                visible_rows += 1
        
        logging.debug(f"Total visible rows after filter: {visible_rows}")

        if not text:
            logging.debug("Search text is empty, hiding search bar.")
            self.search_bar.hide()
            # Optionally, return focus to the table or main window if needed
            # self.profile_table_widget.setFocus()

    def event(self, event_obj):
        """Handles events for the main window, specifically KeyPress to activate search bar."""
        if event_obj.type() == QEvent.Type.KeyPress:
            # Only act if the search bar is currently hidden and we're not in edit, settings, or cloud mode
            if not self.search_bar.isVisible() and \
               not getattr(self, '_edit_mode_active', False) and \
               not getattr(self, '_settings_mode_active', False) and \
               not getattr(self, '_cloud_mode_active', False):
                key_text = event_obj.text()
                # Check if the key produces a printable character and is not just whitespace
                # Also exclude special keys
                if key_text and key_text.isprintable() and key_text.strip() != '' and \
                   event_obj.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab, 
                                          Qt.Key.Key_Backtab, Qt.Key.Key_Escape):
                    # Show the search bar, set focus to it, and input the typed character
                    self.search_bar.show()
                    self.search_bar.setFocus()
                    self.search_bar.setText(key_text)  # This also triggers _on_search_text_changed
                    return True  # Event handled, stop further processing
            # Handle Escape key when search bar is visible and has focus
            elif self.search_bar.isVisible() and self.search_bar.hasFocus() and \
                 event_obj.key() == Qt.Key.Key_Escape:
                self.search_bar.clear()  # This will trigger textChanged, which will hide it
                self.profile_table_widget.setFocus()  # Return focus to table
                return True  # Event handled
        
        # For all other events or if the key press wasn't handled above,
        # call the base class's event handler
        return super().event(event_obj)

    # Enables or disables main UI controls, typically during background operations.
    def set_controls_enabled(self, enabled):
        """Abilita o disabilita i controlli principali della UI."""
        self.profile_table_widget.setEnabled(enabled)
        has_selection = self.profile_table_manager.has_selection()
        has_profiles = len(self.profiles) > 0
        
        # Backup button state depends on mode
        backup_mode = getattr(self, 'backup_mode', 'single')
        if backup_mode == 'all':
            self.backup_button.setEnabled(enabled and has_profiles)
        else:
            self.backup_button.setEnabled(enabled and has_selection)
        
        # Toggle button should always be enabled (if there are profiles and controls are enabled)
        if hasattr(self, 'backup_mode_toggle'):
            self.backup_mode_toggle.setEnabled(enabled and has_profiles)
            
        # Restore button is always enabled - can restore from ZIP without a profile
        self.restore_button.setEnabled(enabled)
        self.manage_backups_button.setEnabled(enabled and has_selection)
        # create_shortcut_button removed - functionality available in context menu
        self.new_profile_button.setEnabled(enabled)
        self.steam_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
        self.theme_button.setEnabled(enabled)
        # minecraft_button removed - functionality moved to new_profile_menu
        self.toggle_log_button.setEnabled(enabled)
        # Cloud and Open Backup Folder require at least one profile
        self.open_backup_dir_button.setEnabled(enabled and has_profiles)
        if hasattr(self, 'cloud_button'):
            self.cloud_button.setEnabled(enabled and has_profiles)
        self.progress_bar.setVisible(not enabled)
        # Editor controls
        if hasattr(self, 'edit_name_edit'):
            self.edit_name_edit.setEnabled(enabled)
        if hasattr(self, 'edit_path_edit'):
            self.edit_path_edit.setEnabled(enabled)
        if hasattr(self, 'edit_browse_button'):
            self.edit_browse_button.setEnabled(enabled)
        if hasattr(self, 'edit_save_button'):
            self.edit_save_button.setEnabled(enabled)
        if hasattr(self, 'edit_cancel_button'):
            self.edit_cancel_button.setEnabled(enabled)

    # --- Single Instance Activation ---
    # Activates the window of an existing instance when a new instance is launched.
    @Slot()
    def activateExistingInstance(self):
        # Connected to QLocalServer signal in main.py
        logging.info("Received signal to activate existing instance (slot in MainWindow).")
        
        # Get the server that emitted the signal
        server = self.sender()
        if server and hasattr(server, 'nextPendingConnection'):
            # Get the incoming connection
            connection = server.nextPendingConnection()
            if connection:
                # Read the data to confirm it's a 'show' command
                if connection.waitForReadyRead(1000):  # Wait up to 1 second
                    data = connection.readAll().data().decode('utf-8').strip()
                    logging.debug(f"Received data from new instance: '{data}'")
                    
                    if data == 'show':
                        self._bringWindowToFront()
                    
                # Close the connection
                connection.close()
        else:
            # Fallback: just bring window to front
            self._bringWindowToFront()
    
    def _bringWindowToFront(self):
        """Helper method to bring the window to front and activate it.
        Handles both minimized windows and windows hidden in system tray.
        Includes platform-specific handling for Linux/Wayland."""
        try:
            import platform as plat
            is_linux = plat.system() == "Linux"
            
            # If the window is hidden (e.g., in system tray), show it first
            if self.isHidden():
                self.showNormal()
                logging.debug("Window was hidden (system tray), restored to normal state.")
            # If the window is minimized, restore it
            elif self.isMinimized():
                self.showNormal()
                logging.debug("Window was minimized, restored to normal state.")
            
            # Remove minimized state first
            current_state = self.windowState()
            new_state = current_state & ~Qt.WindowState.WindowMinimized
            self.setWindowState(new_state)
            
            # Ensure window is visible
            self.show()
            
            # Standard activation methods (work well on Windows and X11)
            self.raise_()
            self.activateWindow()
            
            # On Linux (especially Wayland), use additional methods
            if is_linux:
                # Use QWindow.requestActivate() which is the proper Wayland way
                window_handle = self.windowHandle()
                if window_handle:
                    window_handle.requestActivate()
                    logging.debug("Used QWindow.requestActivate() for Linux/Wayland.")
                
                # Try to use platform-specific activation via D-Bus for KDE/GNOME
                self._try_dbus_activation()
            
            logging.info("Existing instance window activated and brought to front.")
            
        except Exception as e:
            logging.error(f"Error activating existing instance window: {e}", exc_info=True)
    
    def _try_dbus_activation(self):
        """Try to activate window using D-Bus on Linux desktop environments.
        This is a best-effort attempt for Wayland compositors that support it."""
        try:
            import subprocess
            import os
            
            # Get the window ID for X11 or try activation token for Wayland
            window_handle = self.windowHandle()
            if not window_handle:
                return
            
            # For KDE Plasma, try using kactivities or kwin scripts
            desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
            session_type = os.environ.get('XDG_SESSION_TYPE', '').lower()
            
            if 'kde' in desktop or 'plasma' in desktop:
                # Try KWin D-Bus activation
                try:
                    win_id = int(window_handle.winId())
                    subprocess.run([
                        'dbus-send', '--type=method_call', '--dest=org.kde.KWin',
                        '/KWin', 'org.kde.KWin.activateWindow', f'int32:{win_id}'
                    ], timeout=1, capture_output=True)
                    logging.debug("Attempted KWin D-Bus activation.")
                except Exception:
                    pass
            
            elif 'gnome' in desktop:
                # GNOME doesn't easily allow activation, but we tried
                logging.debug("GNOME detected - window activation may be limited by compositor.")
                
        except Exception as e:
            logging.debug(f"D-Bus activation attempt failed (non-critical): {e}")

    # --- Global Mouse Drag Detection Callbacks (pynput) ---
    def update_global_drag_listener_state(self):
        """Starts or stops the global mouse listener based on settings."""
        if not PYNPUT_AVAILABLE or not mouse:
            if self.mouse_listener and self.mouse_listener.is_alive():
                logging.info("PYNPUT not available/imported, stopping any active mouse listener.")
                self.mouse_listener.stop()
            self.mouse_listener = None
            return

        enable_effect = self.current_settings.get("enable_global_drag_effect")

        if enable_effect:
            if not self.mouse_listener or not self.mouse_listener.is_alive():
                try:
                    # Recreate listener instance if it was set to None
                    self.mouse_listener = mouse.Listener(
                        on_click=self.on_mouse_click,
                        on_move=self.on_mouse_move
                    )
                    self.mouse_listener.start()
                    logging.info("Global mouse listener started (setting enabled).")
                except Exception as e:
                    logging.error(f"Failed to start global mouse listener: {e}", exc_info=True)
                    self.mouse_listener = None
            else:
                logging.debug("Global mouse listener already running (setting enabled).")
        else:  # Setting is disabled
            if self.mouse_listener and self.mouse_listener.is_alive():
                self.mouse_listener.stop()
                # self.mouse_listener.join() # Consider if join is needed
                self.mouse_listener = None # Clear the listener instance
                logging.info("Global mouse listener stopped (setting disabled).")
                
                if self.is_drag_operation_active:
                    logging.debug("Resetting is_drag_operation_active as global effect is disabled.")
                    self.is_drag_operation_active = False
                
                if self.overlay_active: 
                    logging.debug("Requesting overlay hide as global effect is disabled and overlay was active.")
                    self.request_hide_overlay.emit()
            else:
                logging.debug("Global mouse listener already stopped or not initialized (setting disabled).")

    def on_mouse_move(self, x, y):
        """Callback chiamata quando il mouse si muove."""
        if not self.current_settings.get("enable_global_drag_effect", True) or not self.mouse_listener or not self.mouse_listener.is_alive():
            return 
        try:
            if self.mouse_pressed and self.press_position and not self.is_drag_operation_active:
                import time 
                current_time = int(time.time() * 1000)
                
                dx = x - self.press_position[0]
                dy = y - self.press_position[1]
                distance = math.sqrt(dx*dx + dy*dy)
                
                if current_time - self.mouse_press_time > self.min_press_duration and distance > self.min_drag_distance:
                    logging.debug(f"Pynput drag detected! Duration: {current_time - self.mouse_press_time}ms, Distance: {distance:.2f}px. Emitting request to show overlay.")
                    self.is_drag_operation_active = True 
                    self.request_show_overlay.emit()
        except Exception as e:
            logging.error(f"Errore durante la gestione dell'evento move del mouse (pynput): {e}", exc_info=True)

    def on_mouse_click(self, x, y, button, pressed):
        """Callback chiamata quando un pulsante del mouse viene premuto o rilasciato."""
        if not self.current_settings.get("enable_global_drag_effect", True) or not self.mouse_listener or not self.mouse_listener.is_alive():
            return
        try:
            import time 
            current_time = int(time.time() * 1000)
            
            if button == mouse.Button.left:
                if pressed:
                    self.mouse_press_time = current_time
                    self.press_position = (x, y)
                    self.mouse_pressed = True
                    self.is_drag_operation_active = False 
                    logging.debug(f"Pynput: Left mouse PRESSED at ({x}, {y}). Drag state reset.")
                else:  # Rilasciato
                    logging.debug(f"Pynput: Left mouse RELEASED at ({x}, {y}).")
                    self.mouse_pressed = False 
                    
                    if self.is_drag_operation_active:
                        logging.info("Pynput: Mouse release detected during pynput-active drag. Requesting hide overlay.")
                        self.request_hide_overlay.emit()
                    
                    self.is_drag_operation_active = False 
                    self.press_position = None 
        except Exception as e:
            logging.error(f"Errore durante la gestione dell'evento click del mouse (pynput): {e}", exc_info=True)


        if not self.current_settings.get("enable_global_drag_effect") or not self.mouse_listener or not self.mouse_listener.is_alive():
            return # Do nothing if the effect is disabled or listener not active
        try:
            import time # Consider moving to class level
            current_time = int(time.time() * 1000)
            
            if button == mouse.Button.left:
                if pressed:
                    # Quando il pulsante viene premuto, memorizza il tempo e la posizione
                    self.mouse_press_time = current_time
                    self.press_position = (x, y)
                    self.mouse_pressed = True
                    self.is_drag_operation_active = False # Resetta lo stato del drag all'inizio di ogni click
                    logging.debug(f"Tasto sinistro del mouse PREMUTO a ({x}, {y}), press_pos: {self.press_position}. Drag state reset.")
                else:  # Rilasciato
                    press_duration = current_time - self.mouse_press_time # Calcola per logging o altre logiche future
                    logging.debug(f"Tasto sinistro del mouse RILASCIATO a ({x}, {y}), durata pressione: {press_duration}ms")
                    
                    self.mouse_pressed = False # Il pulsante non è più premuto
                    
                    if self.is_drag_operation_active:
                        # Se un'operazione di drag era attiva (overlay mostrato da on_mouse_move)
                        # questo è il momento del "drop".
                        logging.info("Mouse release detected during active drag operation. Emitting request to hide overlay.")
                        self.request_hide_overlay.emit()
                    else:
                        # Se non c'era un drag attivo (click semplice o lungo senza movimento sufficiente),
                        # assicurati che l'overlay sia nascosto se per caso era visibile.
                        if hasattr(self, 'overlay_widget') and self.overlay_widget and self.overlay_widget.isVisible():
                            logging.debug("Mouse rilasciato, nessun drag attivo, ma overlay visibile. Emitting request to hide overlay.")
                            self.request_hide_overlay.emit()

                    self.is_drag_operation_active = False # Resetta sempre lo stato del drag al rilascio
                    self.press_position = None # Resetta la posizione di pressione
                    
        except Exception as e:
            logging.error(f"Errore durante la gestione dell'evento click del mouse: {e}", exc_info=True)

    def closeEvent(self, event):
        """Gestisce l'evento di chiusura della finestra principale."""
        try:
            if not self._allow_close:
                # Check if minimize to tray is enabled (either by setting or periodic sync)
                minimize_to_tray = self.current_settings.get('minimize_to_tray_on_close', False)
                cloud_settings = cloud_settings_manager.load_cloud_settings()
                periodic_sync_enabled = bool(cloud_settings.get('auto_sync_enabled'))
                
                if minimize_to_tray or periodic_sync_enabled:
                    if hasattr(self, 'tray_icon') and self.tray_icon and QSystemTrayIcon.isSystemTrayAvailable():
                        event.ignore()
                        self.hide()
                        try:
                            self.tray_icon.show()
                            if periodic_sync_enabled:
                                self.tray_icon.showMessage("SaveState", "Running in background for periodic sync.", QSystemTrayIcon.MessageIcon.Information, 3000)
                            else:
                                self.tray_icon.showMessage("SaveState", "Minimized to system tray.", QSystemTrayIcon.MessageIcon.Information, 2000)
                        except Exception:
                            pass
                        logging.info(f"SaveState hidden to system tray (minimize_to_tray={minimize_to_tray}, periodic_sync={periodic_sync_enabled}).")
                        return
        except Exception:
            pass

        logging.info("MainWindow closeEvent: Cancelling all running search threads...")
        # Cancella tutti i thread di ricerca in corso
        if hasattr(self, 'cancellation_manager') and self.cancellation_manager:
            self.cancellation_manager.cancel()
        # Ferma il thread di ricerca corrente se esiste
        if hasattr(self, 'current_search_thread') and self.current_search_thread:
            if self.current_search_thread.isRunning():
                logging.info("Waiting for current search thread to finish...")
                self.current_search_thread.wait(3000)  # Aspetta max 3 secondi
        
        # Clean up cloud panel auth threads
        if hasattr(self, 'cloud_panel') and self.cloud_panel:
            try:
                self.cloud_panel.cleanup_on_close()
            except Exception as e:
                logging.error(f"Error cleaning up cloud panel: {e}")
        
        # Chiama il closeEvent della classe base
        super().closeEvent(event)
        logging.info("MainWindow closed.")

    # ---- System tray helpers ----
    def _setup_system_tray(self):
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logging.debug("System tray not available on this system.")
                self.tray_icon = None
                return
            icon_path = resource_path("icon.png")
            tray_icon = QSystemTrayIcon(QIcon(icon_path), self)
            tray_menu = QMenu(self)
            act_show = tray_menu.addAction("Show SaveState")
            act_exit = tray_menu.addAction("Exit")
            act_show.triggered.connect(self._restore_from_tray)
            def _do_exit():
                self._allow_close = True
                try:
                    tray_icon.hide()
                except Exception:
                    pass
                self.close()
                # Ensure the application event loop terminates
                QApplication.quit()
            act_exit.triggered.connect(_do_exit)
            tray_icon.setContextMenu(tray_menu)
            tray_icon.activated.connect(self._on_tray_activated)
            self.tray_icon = tray_icon
        except Exception as e:
            logging.debug(f"System tray setup failed: {e}")
            self.tray_icon = None

    def _on_tray_activated(self, reason):
        try:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                self._restore_from_tray()
        except Exception:
            pass

    def _restore_from_tray(self):
        """Restore window from system tray with platform-specific handling."""
        try:
            self._bringWindowToFront()
        except Exception as e:
            logging.debug(f"Error restoring from tray: {e}")

    # Context menu event handler: show side menu and select row
    def _on_profile_table_context_menu(self, pos):
        try:
            index = self.profile_table_widget.indexAt(pos)
            if index and index.isValid():
                row = index.row()
                
                # Check if the clicked row is already part of the current selection
                # If so, preserve the multi-selection; otherwise, select only the clicked row
                selected_rows = self.profile_table_widget.selectionModel().selectedRows()
                clicked_row_in_selection = any(sel_index.row() == row for sel_index in selected_rows)
                
                if not clicked_row_in_selection:
                    # Clicked on a non-selected row - select only that row
                    self.profile_table_widget.selectRow(row)
                # else: keep the current multi-selection
                
                self.update_action_button_states()
                
                # Check if this is a group profile (only relevant for single selection)
                selection_count = self.profile_table_manager.get_selection_count()
                is_group = selection_count == 1 and self.profile_table_manager.is_selected_profile_group()
                
                # Build and show a context menu like Linux/Ubuntu
                menu = QMenu(self)
                # Enable translucent background to fix rounded corners black box issue
                menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
                
                # Apply modern styling to the menu
                menu.setStyleSheet("""
                    QMenu {
                        background-color: #2d2d2d;
                        border: 1px solid #555555;
                        border-radius: 6px;
                        padding: 3px 2px;
                    }
                    QMenu::item {
                        background-color: transparent;
                        color: #e0e0e0;
                        padding: 5px 12px;
                        margin: 1px 3px;
                        border-radius: 3px;
                        font-size: 9pt;
                    }
                    QMenu::item:selected {
                        background-color: #8B0000;
                        color: #ffffff;
                    }
                    QMenu::separator {
                        height: 1px;
                        background-color: #555555;
                        margin: 3px 6px;
                    }
                    QMenu::icon {
                        padding-left: 4px;
                    }
                """)
                
                if is_group:
                    # --- Group Profile Context Menu ---
                    act_edit_group = QAction("Edit Group", self)
                    act_ungroup = QAction("Ungroup", self)
                    act_shortcut = QAction("Create Backup Shortcut", self)
                    
                    # Set tooltips
                    act_edit_group.setToolTip("Edit the profiles in this group")
                    act_ungroup.setToolTip("Dissolve this group, making member profiles visible again")
                    act_shortcut.setToolTip("Creates a desktop shortcut to quickly backup all profiles in this group")
                    
                    # Set folder icon for group actions
                    try:
                        from PySide6.QtWidgets import QStyle
                        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
                        act_edit_group.setIcon(folder_icon)
                    except Exception:
                        pass
                    
                    try:
                        desktop_icon_path = resource_path("icons/desktop.png")
                        if os.path.exists(desktop_icon_path):
                            act_shortcut.setIcon(QIcon(desktop_icon_path))
                    except Exception:
                        pass
                    
                    # Connect actions
                    act_edit_group.triggered.connect(self.handlers.handle_edit_group)
                    act_ungroup.triggered.connect(self.handlers.handle_ungroup)
                    act_shortcut.triggered.connect(self.handlers.handle_create_shortcut)
                    
                    # Add/Edit Note action for groups
                    profile_name_for_note = self.profile_table_manager.get_selected_profile_name()
                    from gui_components import notes_manager
                    has_note = notes_manager.has_note(profile_name_for_note) if profile_name_for_note else False
                    act_note = QAction("Edit Note" if has_note else "Add Note", self)
                    act_note.setToolTip("Add or edit a text note for this profile")
                    try:
                        note_icon_path = resource_path("icons/note.png")
                        if os.path.exists(note_icon_path):
                            act_note.setIcon(QIcon(note_icon_path))
                    except Exception:
                        pass
                    act_note.triggered.connect(lambda: self.profile_table_manager.show_note_editor(profile_name_for_note))
                    
                    menu.addAction(act_edit_group)
                    menu.addAction(act_ungroup)
                    menu.addSeparator()
                    menu.addAction(act_note)
                    menu.addSeparator()
                    menu.addAction(act_shortcut)
                else:
                    # --- Regular Profile Context Menu ---
                    act_edit = QAction("Edit Profile", self)
                    act_shortcut = QAction("Create Backup Shortcut", self)
                    act_shortcut.setToolTip("Creates a desktop shortcut to quickly run a backup for this profile")
                    act_shortcut.setStatusTip("Creates a desktop shortcut to quickly run a backup for this profile")
                    
                    # Optional icons
                    try:
                        desktop_icon_path = resource_path("icons/desktop.png")
                        if os.path.exists(desktop_icon_path):
                            act_shortcut.setIcon(QIcon(desktop_icon_path))
                    except Exception:
                        pass
                    
                    act_edit.triggered.connect(self.handlers.handle_show_edit_profile)
                    act_shortcut.triggered.connect(self.handlers.handle_create_shortcut)
                    
                    # Add/Edit Note action
                    profile_name_for_note = self.profile_table_manager.get_selected_profile_name()
                    from gui_components import notes_manager
                    has_note = notes_manager.has_note(profile_name_for_note) if profile_name_for_note else False
                    act_note = QAction("Edit Note" if has_note else "Add Note", self)
                    act_note.setToolTip("Add or edit a text note for this profile")
                    try:
                        note_icon_path = resource_path("icons/note.png")
                        if os.path.exists(note_icon_path):
                            act_note.setIcon(QIcon(note_icon_path))
                    except Exception:
                        pass
                    act_note.triggered.connect(lambda: self.profile_table_manager.show_note_editor(profile_name_for_note))
                    
                    menu.addAction(act_edit)
                    menu.addSeparator()
                    menu.addAction(act_note)
                    menu.addSeparator()
                    
                    # Add "Create Group" option when multiple profiles are selected
                    if selection_count > 1:
                        act_create_group = QAction(f"Create Group ({selection_count} profiles)", self)
                        act_create_group.setToolTip("Create a group containing the selected profiles")
                        try:
                            from PySide6.QtWidgets import QStyle
                            folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
                            act_create_group.setIcon(folder_icon)
                        except Exception:
                            pass
                        act_create_group.triggered.connect(self.handlers.handle_create_group_from_selection)
                        menu.addAction(act_create_group)
                        menu.addSeparator()
                    
                    menu.addAction(act_shortcut)
                
                global_pos = self.profile_table_widget.viewport().mapToGlobal(pos)
                menu.exec(global_pos)
        except Exception as e:
            logging.error(f"Error handling profile table context menu: {e}")

    def show_profile_editor(self, profile_name):
        """Show inline editor for the given profile, replacing the profiles UI."""
        try:
            if not profile_name or profile_name not in self.profiles:
                return
            
            # Close settings panel if it's open before showing profile editor
            if getattr(self, '_settings_mode_active', False):
                self.exit_settings_panel()
                logging.debug("Settings panel closed before opening profile editor.")
            
            self._editing_profile_original_name = profile_name
            data = self.profiles.get(profile_name, {})
            # Populate fields
            self.edit_name_edit.setText(profile_name)
            path_value = ""
            if isinstance(data, dict):
                if isinstance(data.get('path'), str):
                    path_value = data.get('path')
                elif isinstance(data.get('paths'), list) and data.get('paths'):
                    first_path = data.get('paths')[0]
                    if isinstance(first_path, str):
                        path_value = first_path
            self.edit_path_edit.setText(path_value)
            
            # Visual warning if path doesn't exist or is inside backup folder
            path_warning = ""
            if path_value:
                import os
                backup_base = self.current_settings.get('backup_base_dir', '')
                backup_base_norm = os.path.normpath(backup_base).lower() if backup_base else ""
                path_norm = os.path.normpath(path_value).lower()
                
                if backup_base_norm and path_norm.startswith(backup_base_norm):
                    path_warning = "⚠️ CRITICAL: Path is inside backup folder! This will cause recursive backups."
                    self.edit_path_edit.setStyleSheet("QLineEdit { border: 2px solid #FF0000; background-color: #3a2020; }")
                elif not os.path.exists(path_value):
                    path_warning = "⚠️ Path does not exist! The game may have been uninstalled."
                    self.edit_path_edit.setStyleSheet("QLineEdit { border: 2px solid #FFA500; background-color: #3a3020; }")
                else:
                    self.edit_path_edit.setStyleSheet("")  # Reset to default
                    
                self.edit_path_edit.setToolTip(path_warning if path_warning else "Save game folder path")
            else:
                self.edit_path_edit.setStyleSheet("")
                self.edit_path_edit.setToolTip("Save game folder path")

            # Populate overrides UI from profile or global settings
            use_overrides = False
            overrides = {}
            if isinstance(data, dict):
                use_overrides = bool(data.get('use_profile_overrides', False))
                if isinstance(data.get('overrides'), dict):
                    overrides = data.get('overrides') or {}
            # Defaults from global settings
            global_max_backups = self.current_settings.get('max_backups', 5)
            global_compression = self.current_settings.get('compression_mode', 'standard')
            global_max_size = self.current_settings.get('max_source_size_mb', 200)
            global_check_space = self.current_settings.get('check_free_space_enabled', True)
            # Apply values
            self.overrides_enable_checkbox.setChecked(use_overrides)
            self.override_max_backups_spin.setValue(int(overrides.get('max_backups', global_max_backups)))
            comp_val = str(overrides.get('compression_mode', global_compression))
            idx = self.override_compression_combo.findText(comp_val)
            self.override_compression_combo.setCurrentIndex(idx if idx >= 0 else 0)
            # Select matching size option; fallback to 500MB if not found
            size_mb = int(overrides.get('max_source_size_mb', global_max_size))
            select_index = next((i for i, (_, v) in enumerate(self.override_size_options) if v == size_mb), -1)
            if select_index == -1:
                select_index = next((i for i, (_, v) in enumerate(self.override_size_options) if v == 500), 0)
            self.override_max_size_combo.setCurrentIndex(select_index)
            self.override_check_space_checkbox.setChecked(bool(overrides.get('check_free_space_enabled', global_check_space)))
            # Enable/disable group according to checkbox (with visual style)
            self.handlers.handle_profile_overrides_toggled(use_overrides)

            # Toggle UI visibility
            self.profile_group.setVisible(False)
            self.profile_editor_group.setVisible(True)
            # Disable main controls while editing
            self.enter_profile_edit_mode()
        except Exception as e:
            logging.error(f"Error showing profile editor: {e}")

    def _set_main_controls_enabled_during_edit(self, enabled):
        try:
            if hasattr(self, 'actions_group') and self.actions_group:
                self.actions_group.setEnabled(enabled)
            if hasattr(self, 'general_group') and self.general_group:
                self.general_group.setEnabled(enabled)
            if hasattr(self, 'cloud_group') and self.cloud_group:
                self.cloud_group.setEnabled(enabled)
            if hasattr(self, 'general_cloud_row') and self.general_cloud_row:
                self.general_cloud_row.setEnabled(enabled)
            if hasattr(self, 'search_bar') and self.search_bar:
                self.search_bar.setEnabled(enabled)
            if hasattr(self, 'profile_table_widget') and self.profile_table_widget:
                self.profile_table_widget.setEnabled(enabled)
            if hasattr(self, 'toggle_log_button') and self.toggle_log_button:
                self.toggle_log_button.setEnabled(enabled)
        except Exception:
            pass

    def enter_profile_edit_mode(self):
        self._edit_mode_active = True
        self._set_main_controls_enabled_during_edit(False)

    def exit_profile_edit_mode(self):
        self._edit_mode_active = False
        self._set_main_controls_enabled_during_edit(True)

    # --- Settings Panel Management ---
    def show_settings_panel(self):
        """Show inline settings panel, replacing the profiles UI."""
        try:
            # Populate settings fields from current settings
            self.settings_path_edit.setText(self.current_settings.get("backup_base_dir", ""))
            self.settings_portable_checkbox.setChecked(self.current_settings.get("portable_config_only", False))
            
            # Max source size
            current_mb_value = self.current_settings.get("max_source_size_mb", 500)
            current_index = next((i for i, (_, v) in enumerate(self.settings_size_options) if v == current_mb_value), -1)
            if current_index != -1:
                self.settings_max_size_combo.setCurrentIndex(current_index)
            else:
                default_index = next((i for i, (_, v) in enumerate(self.settings_size_options) if v == 500), 0)
                self.settings_max_size_combo.setCurrentIndex(default_index)
            
            # Max backups
            self.settings_max_backups_spin.setValue(self.current_settings.get("max_backups", 3))
            
            # Compression
            current_comp_mode = self.current_settings.get("compression_mode", "standard")
            comp_index = self.settings_compression_combo.findData(current_comp_mode)
            if comp_index >= 0:
                self.settings_compression_combo.setCurrentIndex(comp_index)
            
            # Space check
            self.settings_space_check_checkbox.setChecked(self.current_settings.get("check_free_space_enabled", True))
            
            # UI settings
            self.settings_global_drag_checkbox.setChecked(self.current_settings.get("enable_global_drag_effect", True))
            self.settings_shorten_paths_checkbox.setChecked(self.current_settings.get("shorten_paths_enabled", True))
            self.settings_show_icons_checkbox.setChecked(self.current_settings.get("show_profile_icons", True))
            
            # Minimize to tray: check if periodic sync forces this behavior
            try:
                cloud_settings = cloud_settings_manager.load_cloud_settings()
                periodic_sync_enabled = bool(cloud_settings.get('auto_sync_enabled', False))
            except Exception:
                periodic_sync_enabled = False
            
            if periodic_sync_enabled:
                # Periodic sync forces minimize to tray - show as checked and disabled
                self.settings_minimize_to_tray_checkbox.setChecked(True)
                self.settings_minimize_to_tray_checkbox.setEnabled(False)
                self.settings_minimize_to_tray_checkbox.setToolTip("Forced ON because Periodic Sync is enabled in Cloud settings")
            else:
                # Normal behavior - use the saved setting
                self.settings_minimize_to_tray_checkbox.setChecked(self.current_settings.get("minimize_to_tray_on_close", False))
                self.settings_minimize_to_tray_checkbox.setEnabled(True)
                self.settings_minimize_to_tray_checkbox.setToolTip("")
            
            # Toggle UI visibility
            self.profile_group.setVisible(False)
            self.actions_group.setVisible(False)
            self.general_group.setVisible(False)
            if hasattr(self, 'general_cloud_row'):
                self.general_cloud_row.setVisible(False)
            if hasattr(self, 'cloud_group'):
                self.cloud_group.setVisible(False)
            self.bottom_controls_widget.setVisible(False)  # Hide search bar and log button
            self.settings_panel_group.setVisible(True)
            
            # Disable main controls
            self.enter_settings_mode()
        except Exception as e:
            logging.error(f"Error showing settings panel: {e}")

    def exit_settings_panel(self):
        """Exit settings panel and return to normal UI."""
        self.settings_panel_group.setVisible(False)
        self.profile_group.setVisible(True)
        self.actions_group.setVisible(True)
        self.general_group.setVisible(True)
        if hasattr(self, 'general_cloud_row'):
            self.general_cloud_row.setVisible(True)
        if hasattr(self, 'cloud_group'):
            self.cloud_group.setVisible(True)
        self.bottom_controls_widget.setVisible(True)  # Show search bar and log button again
        self.exit_settings_mode()
        self._ctrl_reapply_focus_if_connected()

    def enter_settings_mode(self):
        """Set flag when settings panel is shown."""
        self._settings_mode_active = True

    def exit_settings_mode(self):
        """Clear flag after settings panel is closed."""
        self._settings_mode_active = False

    # --- Controller Panel Management ---
    def show_controller_panel(self):
        """Show inline controller settings panel, replacing the profiles UI."""
        try:
            self.controller_panel_group.populate(self.current_settings)
            self.controller_panel_group.set_profile_count(len(self.profiles))

            # Detect current controller connection and update indicator
            ctrl_connected = False
            cm = getattr(self, 'controller_manager', None)
            if cm is not None and cm.is_running():
                try:
                    import platform as _plat
                    if _plat.system() == "Windows":
                        import ctypes as _ct
                        from controller_manager import XINPUT_STATE
                        _xi = _ct.windll.xinput1_4
                        for i in range(4):
                            st = XINPUT_STATE()
                            if _xi.XInputGetState(i, _ct.byref(st)) == 0:
                                ctrl_connected = True
                                break
                except Exception:
                    pass
            self.controller_panel_group.update_connection_status(ctrl_connected)

            self.profile_group.setVisible(False)
            self.actions_group.setVisible(False)
            self.general_group.setVisible(False)
            if hasattr(self, 'general_cloud_row'):
                self.general_cloud_row.setVisible(False)
            if hasattr(self, 'cloud_group'):
                self.cloud_group.setVisible(False)
            self.bottom_controls_widget.setVisible(False)
            self.controller_panel_group.setVisible(True)
            self._controller_mode_active = True
        except Exception as e:
            logging.error(f"Error showing controller panel: {e}")

    def exit_controller_panel(self):
        """Exit controller settings panel and return to normal UI."""
        self.controller_panel_group.setVisible(False)
        self.profile_group.setVisible(True)
        self.actions_group.setVisible(True)
        self.general_group.setVisible(True)
        if hasattr(self, 'general_cloud_row'):
            self.general_cloud_row.setVisible(True)
        if hasattr(self, 'cloud_group'):
            self.cloud_group.setVisible(True)
        self.bottom_controls_widget.setVisible(True)
        self._controller_mode_active = False
        self._ctrl_reapply_focus_if_connected()

    # --- Cloud Panel Management ---
    def show_cloud_panel(self):
        """Show inline cloud save panel, replacing the profiles UI."""
        try:
            # Update cloud panel with current data
            if hasattr(self, 'cloud_panel') and self.cloud_panel:
                self.cloud_panel.update_backup_dir(self.current_settings.get("backup_base_dir", ""))
                self.cloud_panel.update_profiles(self.profiles)
            
            # Toggle UI visibility
            self.profile_group.setVisible(False)
            self.actions_group.setVisible(False)
            self.general_group.setVisible(False)
            if hasattr(self, 'general_cloud_row'):
                self.general_cloud_row.setVisible(False)
            if hasattr(self, 'cloud_group'):
                self.cloud_group.setVisible(False)
            self.bottom_controls_widget.setVisible(False)  # Hide search bar and log button
            self.cloud_panel.setVisible(True)
            
            # Set flag
            self.enter_cloud_mode()
        except Exception as e:
            logging.error(f"Error showing cloud panel: {e}")

    def exit_cloud_panel(self):
        """Exit cloud panel and return to normal UI."""
        self.cloud_panel.setVisible(False)
        self.profile_group.setVisible(True)
        self.actions_group.setVisible(True)
        self.general_group.setVisible(True)
        if hasattr(self, 'general_cloud_row'):
            self.general_cloud_row.setVisible(True)
        if hasattr(self, 'cloud_group'):
            self.cloud_group.setVisible(True)
        self.bottom_controls_widget.setVisible(True)  # Show search bar and log button again
        self.exit_cloud_mode()
        self._ctrl_reapply_focus_if_connected()

    def enter_cloud_mode(self):
        """Set flag when cloud panel is shown."""
        self._cloud_mode_active = True
        # Change settings icon to cloud settings icon
        if hasattr(self, 'settings_icon_cloud') and self.settings_icon_cloud:
            self.settings_button.setIcon(self.settings_icon_cloud)
            logging.debug("Settings icon changed to cloud settings icon")

    def exit_cloud_mode(self):
        """Clear flag after cloud panel is closed."""
        self._cloud_mode_active = False
        # Restore normal settings icon
        if hasattr(self, 'settings_icon_normal') and self.settings_icon_normal:
            self.settings_button.setIcon(self.settings_icon_normal)
            logging.debug("Settings icon restored to normal icon")

    def _close_active_panel(self):
        """Close whichever inline panel is currently open (if any)."""
        if getattr(self, '_settings_mode_active', False):
            self.exit_settings_panel()
        elif getattr(self, '_controller_mode_active', False):
            self.exit_controller_panel()
        elif getattr(self, '_cloud_mode_active', False):
            self.exit_cloud_panel()
        elif getattr(self, '_edit_mode_active', False):
            if hasattr(self, 'profile_editor_group'):
                self.profile_editor_group.setVisible(False)
            if hasattr(self, 'profile_group'):
                self.profile_group.setVisible(True)
            self.exit_profile_edit_mode()

    # --- Controller input slots ---

    @Slot()
    def _ctrl_nav_up(self):
        """Move selection up — QMenu → dialog → profile list."""
        from PySide6.QtWidgets import QApplication
        if QApplication.activeWindow() is None:
            return
        menu = self._ctrl_active_popup()
        if menu is not None:
            self._ctrl_send_key(menu, Qt.Key.Key_Up)
            return
        dialog = self._ctrl_active_dialog()
        if dialog is not None:
            self._ctrl_dialog_nav(dialog, -1)
            return
        if not self._ctrl_table_is_active():
            return
        table = self.profile_table_widget
        visible = self._ctrl_visible_rows()
        if not visible:
            return
        current = table.currentRow()
        if not table.selectionModel().hasSelection() or current not in visible:
            # Nothing selected yet — select the first visible row
            row = visible[0]
        else:
            row = self._ctrl_prev_visible_row(current)
            if row is None:
                row = current  # Already at top; keep selection (ensures item stays selected)
        table.selectRow(row)
        table.scrollTo(table.model().index(row, 0))

    @Slot()
    def _ctrl_nav_down(self):
        """Move selection down — QMenu → dialog → profile list."""
        from PySide6.QtWidgets import QApplication
        if QApplication.activeWindow() is None:
            return
        menu = self._ctrl_active_popup()
        if menu is not None:
            self._ctrl_send_key(menu, Qt.Key.Key_Down)
            return
        dialog = self._ctrl_active_dialog()
        if dialog is not None:
            self._ctrl_dialog_nav(dialog, +1)
            return
        if not self._ctrl_table_is_active():
            return
        table = self.profile_table_widget
        visible = self._ctrl_visible_rows()
        if not visible:
            return
        current = table.currentRow()
        if not table.selectionModel().hasSelection() or current not in visible:
            # Nothing selected yet — select the first visible row
            row = visible[0]
        else:
            row = self._ctrl_next_visible_row(current)
            if row is None:
                row = current  # Already at bottom; keep selection
        table.selectRow(row)
        table.scrollTo(table.model().index(row, 0))

    # --- Controller physical-button slots (call dispatcher) ---

    @Slot()
    def _ctrl_btn_a(self):
        self._ctrl_dispatch("A")

    @Slot()
    def _ctrl_btn_b(self):
        self._ctrl_dispatch("B")

    @Slot()
    def _ctrl_btn_x(self):
        self._ctrl_dispatch("X")

    @Slot()
    def _ctrl_btn_y(self):
        self._ctrl_dispatch("Y")

    @Slot()
    def _ctrl_btn_start(self):
        self._ctrl_dispatch("Start")

    @Slot()
    def _ctrl_btn_delete(self):
        self._ctrl_dispatch("View/Select")

    @Slot()
    def _ctrl_btn_lb(self):
        self._ctrl_dispatch("LB")

    @Slot()
    def _ctrl_btn_rb(self):
        self._ctrl_dispatch("RB")

    @Slot()
    def _ctrl_btn_l1l2(self):
        self._ctrl_dispatch("LT+RT")

    @Slot()
    def _ctrl_on_lt_hold(self):
        """LT pressed (alone) — switch focus to General section."""
        from PySide6.QtWidgets import QApplication
        if QApplication.activeWindow() is None:
            return
        if (getattr(self, '_settings_mode_active', False) or
                getattr(self, '_controller_mode_active', False) or
                getattr(self, '_cloud_mode_active', False) or
                getattr(self, '_edit_mode_active', False)):
            return
        self._ctrl_set_focus_section('general')

    @Slot()
    def _ctrl_on_lt_release(self):
        """LT released — switch focus back to Actions section."""
        from PySide6.QtWidgets import QApplication
        if QApplication.activeWindow() is None:
            return
        if (getattr(self, '_settings_mode_active', False) or
                getattr(self, '_controller_mode_active', False) or
                getattr(self, '_cloud_mode_active', False) or
                getattr(self, '_edit_mode_active', False)):
            return
        self._ctrl_set_focus_section('actions')


    @Slot()
    def _ctrl_on_any_input(self):
        """Called on any controller button/nav press. Enters controller-focus mode."""
        from PySide6.QtWidgets import QApplication
        if QApplication.activeWindow() is None:
            return
        # If already in controller-focus mode, nothing to do
        if getattr(self, '_ctrl_focus_section', None) is not None:
            return
        # Cooldown: don't re-enter controller mode for 0.5s after mouse was used
        import time
        mouse_at = getattr(self, '_ctrl_mouse_used_at', 0)
        if time.time() - mouse_at < 0.5:
            return
        # Only activate on the main profile view
        if (getattr(self, '_settings_mode_active', False) or
                getattr(self, '_controller_mode_active', False) or
                getattr(self, '_cloud_mode_active', False) or
                getattr(self, '_edit_mode_active', False)):
            return
        # First controller input → focus on "Actions", dim "General"
        self._ctrl_set_focus_section('actions')

    def _ctrl_set_focus_section(self, section: str):
        """Set which section is controller-focused ('actions' or 'general').
        The focused section is at full opacity; the other is heavily dimmed
        using QGraphicsOpacityEffect to grey out everything including icons."""
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._ctrl_focus_section = section

        def _dim(widget):
            eff = QGraphicsOpacityEffect(widget)
            eff.setOpacity(0.25)
            widget.setGraphicsEffect(eff)

        def _undim(widget):
            widget.setGraphicsEffect(None)

        if section == 'actions':
            if hasattr(self, 'actions_group'):
                _undim(self.actions_group)
            if hasattr(self, 'general_group'):
                _dim(self.general_group)
            if hasattr(self, 'cloud_group'):
                _dim(self.cloud_group)
            # Restore badges on Actions buttons, remove from General
            self._ctrl_update_badges()
            self._ctrl_restore_general_icons()
        elif section == 'general':
            if hasattr(self, 'actions_group'):
                _dim(self.actions_group)
            if hasattr(self, 'general_group'):
                _undim(self.general_group)
            if hasattr(self, 'cloud_group'):
                _undim(self.cloud_group)
            # Put badges on General buttons, restore Actions to original
            self._ctrl_restore_button_icons()
            self._ctrl_update_general_badges()

    def _ctrl_update_general_badges(self):
        """Set badge icons on General section buttons when General has focus.
        A→New Profile, X→Steam, Y→Open Backup Folder, Start→Cloud."""
        saved: dict = self.current_settings.get("controller_button_mappings", {})
        mappings: dict = {**CTRL_DEFAULT_MAPPINGS, **saved}
        # Reverse mapping: action → physical button
        action_to_btn: dict[str, str] = {}
        for btn_name, action in mappings.items():
            if action and action not in action_to_btn:
                action_to_btn[action] = btn_name

        # In General mode, these actions map to General buttons
        general_map = {
            "backup":         self.new_profile_button     if hasattr(self, 'new_profile_button') else None,
            "restore":        self.steam_button            if hasattr(self, 'steam_button') else None,
            "manage_backups": self.open_backup_dir_button  if hasattr(self, 'open_backup_dir_button') else None,
            "context_menu":   self.cloud_button            if hasattr(self, 'cloud_button') else None,
        }
        icon_size = QSize(18, 18)
        for action, ui_btn in general_map.items():
            if ui_btn is None:
                continue
            btn_id = id(ui_btn)
            # Save original icon once
            if not hasattr(self, '_ctrl_orig_icons'):
                self._ctrl_orig_icons = {}
            if btn_id not in self._ctrl_orig_icons:
                self._ctrl_orig_icons[btn_id] = ui_btn.icon()
            phys_btn = action_to_btn.get(action, "")
            if phys_btn:
                badge_icon = self._make_ctrl_badge_icon(
                    phys_btn, CTRL_BADGE_COLOR.get(phys_btn, "#555")
                )
                ui_btn.setIcon(badge_icon)
                ui_btn.setIconSize(icon_size)

    def _ctrl_restore_general_icons(self):
        """Restore General section buttons to their original icons."""
        gen_btns = []
        if hasattr(self, 'new_profile_button'):
            gen_btns.append(self.new_profile_button)
        if hasattr(self, 'steam_button'):
            gen_btns.append(self.steam_button)
        if hasattr(self, 'open_backup_dir_button'):
            gen_btns.append(self.open_backup_dir_button)
        if hasattr(self, 'cloud_button'):
            gen_btns.append(self.cloud_button)
        for ui_btn in gen_btns:
            orig = getattr(self, '_ctrl_orig_icons', {}).get(id(ui_btn))
            if orig is not None:
                ui_btn.setIcon(orig)
                ui_btn.setIconSize(QSize(16, 16))

    def _ctrl_clear_focus_section(self):
        """Remove controller-focus dimming from all sections (on disconnect)."""
        self._ctrl_focus_section = None
        for widget_name in ('actions_group', 'general_group', 'cloud_group'):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setGraphicsEffect(None)
        # Restore all icons
        self._ctrl_restore_general_icons()

    def _ctrl_reapply_focus_if_connected(self):
        """Re-apply focus section dimming when returning to main view.
        Only applies if a controller is connected and focus was previously set."""
        focus = getattr(self, '_ctrl_focus_section', None)
        if focus is not None:
            self._ctrl_set_focus_section(focus)

    def _ctrl_exit_visual_mode(self):
        """Exit controller visual mode (called when mouse is used).
        Removes all badges, dimming and resets focus section so the UI
        looks normal for mouse users. Controller mode re-activates
        automatically on the next controller button press."""
        self._ctrl_focus_section = None
        import time
        self._ctrl_mouse_used_at = time.time()  # cooldown to prevent instant re-entry
        # Remove dimming effects from all sections
        for widget_name in ('actions_group', 'general_group', 'cloud_group'):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setGraphicsEffect(None)
        # Restore all button icons to originals (remove badge icons)
        self._ctrl_restore_button_icons()
        self._ctrl_restore_general_icons()

    # --- Controller dispatcher — maps physical button → configured action ---

    def _ctrl_dispatch(self, button: str):
        """Resolve the action assigned to a physical button and execute it.
        Falls back to CTRL_DEFAULT_MAPPINGS for any button not found in saved
        settings (handles renames across app versions gracefully)."""
        from PySide6.QtWidgets import QApplication
        if QApplication.activeWindow() is None:
            return
        
        # ── Shortcut capture intercept ─────────────────────────────────
        # If the controller panel is open and a shortcut row is waiting
        # for a button assignment, deliver the pressed button name there
        # instead of executing any action.
        if getattr(self, '_controller_mode_active', False):
            try:
                panel = self.controller_panel_group
                capturing_row = panel.shortcuts_panel.get_capturing_row()
                if capturing_row is not None:
                    panel.deliver_captured_button(button)
                    return
            except Exception:
                pass

        saved: dict = self.current_settings.get("controller_button_mappings", {})
        action = saved.get(button) or CTRL_DEFAULT_MAPPINGS.get(button, "")

        # ── Priority 1: QMenu popup ────────────────────────────────────────
        menu = self._ctrl_active_popup()
        if menu is not None:
            if action == "back":
                self._ctrl_send_key(menu, Qt.Key.Key_Escape)
            elif action:
                self._ctrl_send_key(menu, Qt.Key.Key_Return)
            return

        # ── Priority 2: Any visible QDialog (QMessageBox, ManageBackups…) ─
        dialog = self._ctrl_active_dialog()
        if dialog is not None:
            self._ctrl_dialog_dispatch(dialog, action)
            return
        if not action:
            return

        # ── Priority 3: General section has focus ──────────────────────────
        if getattr(self, '_ctrl_focus_section', 'actions') == 'general':
            # When General is focused, route primary actions to General buttons
            if action == "back":
                # B always switches back to Actions focus
                self._ctrl_set_focus_section('actions')
            elif action == "backup":
                # A → New Profile
                if hasattr(self, 'new_profile_button') and self.new_profile_button.isEnabled():
                    self.new_profile_button.click()
            elif action == "restore":
                # X → Manage Steam
                if hasattr(self, 'steam_button') and self.steam_button.isEnabled():
                    self.steam_button.click()
            elif action == "manage_backups":
                # Y → Open Backup Folder
                if hasattr(self, 'open_backup_dir_button') and self.open_backup_dir_button.isEnabled():
                    self.open_backup_dir_button.click()
            elif action == "context_menu":
                # Start → Cloud
                if hasattr(self, 'cloud_button') and self.cloud_button.isEnabled():
                    self.cloud_button.click()
            elif action in ("page_up", "page_down"):
                # Page navs still work on profile list even in General mode
                self._ctrl_do_page("up" if action == "page_up" else "down")
            elif action == "backup_all":
                self._ctrl_do_backup_all()
            elif action == "delete":
                self._ctrl_do_delete()
            return

        # ── Priority 4: Actions section (default) ─────────────────────────
        if action == "backup":
            self._ctrl_do_backup()
        elif action == "restore":
            self._ctrl_do_restore()
        elif action == "manage_backups":
            self._ctrl_do_manage_backups()
        elif action == "back":
            self._ctrl_do_back()
        elif action == "delete":
            self._ctrl_do_delete()
        elif action == "page_up":
            self._ctrl_do_page("up")
        elif action == "page_down":
            self._ctrl_do_page("down")
        elif action == "context_menu":
            self._ctrl_do_context_menu()
        elif action == "backup_all":
            self._ctrl_do_backup_all()

    # --- Controller action implementations ---

    def _ctrl_do_backup(self):
        """Backup action: also closes any open inline panel first."""
        if getattr(self, '_controller_mode_active', False):
            self.exit_controller_panel()
            return
        if getattr(self, '_settings_mode_active', False):
            self.exit_settings_panel()
            return
        if self._ctrl_modal_open():
            return
        if self.backup_button.isEnabled():
            self.backup_button.click()

    def _ctrl_do_restore(self):
        if self._ctrl_modal_open():
            return
        if self._ctrl_table_is_active() and self.restore_button.isEnabled():
            self.restore_button.click()

    def _ctrl_do_manage_backups(self):
        if self._ctrl_modal_open():
            return
        if self._ctrl_table_is_active() and self.manage_backups_button.isEnabled():
            self.manage_backups_button.click()

    def _ctrl_do_back(self):
        """Navigate back from an inline panel (dialogs are handled in _ctrl_dispatch)."""
        if getattr(self, '_controller_mode_active', False):
            self.exit_controller_panel()
        elif getattr(self, '_settings_mode_active', False):
            self.exit_settings_panel()
        elif getattr(self, '_cloud_mode_active', False):
            self.exit_cloud_panel()
        elif getattr(self, '_edit_mode_active', False):
            self.profile_editor_group.setVisible(False)
            self.profile_group.setVisible(True)
            self.exit_profile_edit_mode()

    def _ctrl_do_backup_all(self):
        """Backup all profiles — only available when ≥3 profiles exist."""
        if self._ctrl_modal_open() or not self._ctrl_table_is_active():
            return
        if len(self.profiles) < 3:
            return
        self.handlers.handle_backup_all()

    def _ctrl_do_context_menu(self):
        """Open the profile table context menu for the currently selected row."""
        if self._ctrl_modal_open() or not self._ctrl_table_is_active():
            return
        table = self.profile_table_widget
        current_row = table.currentRow()
        if current_row < 0:
            return
        # Compute center of the selected row in viewport coordinates
        rect = table.visualRect(table.model().index(current_row, 1))
        pos = rect.center()
        self._on_profile_table_context_menu(pos)

    def _ctrl_do_delete(self):
        if self._ctrl_modal_open():
            return
        if not self._ctrl_table_is_active():
            return
        if self.delete_profile_button.isEnabled():
            self.delete_profile_button.click()
        elif self.profile_table_widget.currentRow() >= 0:
            self.handlers.handle_delete_profile()

    def _ctrl_do_page(self, direction: str):
        if not self._ctrl_table_is_active():
            return
        table = self.profile_table_widget
        visible = self._ctrl_visible_rows()
        if not visible:
            return
        current = table.currentRow()
        if direction == "up":
            if current not in visible:
                row = visible[0]
            else:
                pos = visible.index(current)
                row = visible[max(0, pos - 5)]
        else:
            if current not in visible:
                row = visible[-1]
            else:
                pos = visible.index(current)
                row = visible[min(len(visible) - 1, pos + 5)]
        table.selectRow(row)
        table.scrollTo(table.model().index(row, 0))

    # --- Controller badge icons (set directly on action buttons via setIcon) ---

    def _make_ctrl_badge_icon(self, letter: str, color: str, size: int = 18) -> QIcon:
        """Generate a circular badge QIcon with a letter, rendered at `size` px."""
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, size, size)
        painter.setPen(QColor("white"))
        font = QFont()
        font.setPixelSize(max(8, size - 6))
        font.setBold(True)
        painter.setFont(font)
        from PySide6.QtCore import QRect
        painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter,
                         letter[:2] if len(letter) > 2 else letter)
        painter.end()
        return QIcon(px)

    def _ctrl_update_badges(self):
        """Set badge icons on action buttons based on the current button mapping.
        Saves original icons the first time so they can be restored on disconnect."""
        saved: dict = self.current_settings.get("controller_button_mappings", {})
        # Merge defaults first so new/renamed buttons always have a value
        mappings: dict = {**CTRL_DEFAULT_MAPPINGS, **saved}
        # Build reverse mapping: action → first physical button assigned to it
        action_to_btn: dict[str, str] = {}
        for btn_name, action in mappings.items():
            if action and action not in action_to_btn:
                action_to_btn[action] = btn_name

        # action → the UI button it controls
        action_btn_map: dict[str, object] = {
            "backup":         self.backup_button,
            "restore":        self.restore_button,
            "manage_backups": self.manage_backups_button,
        }

        icon_size = QSize(18, 18)

        for action, ui_btn in action_btn_map.items():
            btn_id = id(ui_btn)
            # Save original icon once
            if btn_id not in getattr(self, '_ctrl_orig_icons', {}):
                if not hasattr(self, '_ctrl_orig_icons'):
                    self._ctrl_orig_icons = {}
                self._ctrl_orig_icons[btn_id] = ui_btn.icon()

            phys_btn = action_to_btn.get(action, "")
            if phys_btn:
                badge_icon = self._make_ctrl_badge_icon(
                    phys_btn, CTRL_BADGE_COLOR.get(phys_btn, "#555")
                )
                ui_btn.setIcon(badge_icon)
                ui_btn.setIconSize(icon_size)
            else:
                # No button mapped to this action — restore original icon
                orig = getattr(self, '_ctrl_orig_icons', {}).get(btn_id)
                if orig is not None:
                    ui_btn.setIcon(orig)

    def _ctrl_restore_button_icons(self):
        """Restore all action buttons to their original icons (on disconnect/disable)."""
        for ui_btn in (self.backup_button, self.restore_button, self.manage_backups_button):
            orig = getattr(self, '_ctrl_orig_icons', {}).get(id(ui_btn))
            if orig is not None:
                ui_btn.setIcon(orig)
                ui_btn.setIconSize(QSize(16, 16))

    def _ctrl_deactivate(self):
        """Immediately restore button icons when controller support is disabled at runtime."""
        self._ctrl_restore_button_icons()
        self._ctrl_uninstall_dialog_badger()

    def _ctrl_install_dialog_badger(self):
        """Install an app-level event filter that adds A/B badges to QMessageBox buttons."""
        if not hasattr(self, '_ctrl_dialog_badger') or self._ctrl_dialog_badger is None:
            self._ctrl_dialog_badger = _ControllerDialogBadger(self)
            QApplication.instance().installEventFilter(self._ctrl_dialog_badger)

    def _ctrl_uninstall_dialog_badger(self):
        """Remove the dialog badge event filter."""
        badger = getattr(self, '_ctrl_dialog_badger', None)
        if badger is not None:
            QApplication.instance().removeEventFilter(badger)
            self._ctrl_dialog_badger = None

    @Slot(int)
    def _ctrl_on_connected(self, idx: int):
        logging.info(f"Controller {idx} connected.")
        self.status_label.setText(f"Controller {idx + 1} connected.")
        self._ctrl_install_dialog_badger()
        # Update controller panel status indicator
        try:
            self.controller_panel_group.update_connection_status(True)
        except Exception:
            pass
        # Install app-wide event filter to detect mouse usage
        if not getattr(self, '_ctrl_mouse_filter_installed', False):
            QApplication.instance().installEventFilter(self)
            self._ctrl_mouse_filter_installed = True

    @Slot(int)
    def _ctrl_on_disconnected(self, idx: int):
        logging.info(f"Controller {idx} disconnected.")
        # Only restore icons if no other controller is still connected
        from controller_manager import XINPUT_STATE
        any_connected = False
        if hasattr(self, 'controller_manager') and self.controller_manager.is_running():
            import platform as _plat
            if _plat.system() == "Windows":
                try:
                    import ctypes as _ct
                    _xi = _ct.windll.xinput1_4
                    for i in range(4):
                        st = XINPUT_STATE()
                        if _xi.XInputGetState(i, _ct.byref(st)) == 0:
                            any_connected = True
                            break
                except Exception:
                    pass
        if not any_connected:
            self._ctrl_restore_button_icons()
            self._ctrl_uninstall_dialog_badger()
            self._ctrl_clear_focus_section()
            # Update controller panel status indicator
            try:
                self.controller_panel_group.update_connection_status(False)
            except Exception:
                pass
            # Remove app-wide mouse detection filter
            if getattr(self, '_ctrl_mouse_filter_installed', False):
                QApplication.instance().removeEventFilter(self)
                self._ctrl_mouse_filter_installed = False

    # --- Controller dialog helpers ---

    def _ctrl_active_popup(self):
        """Return the active QMenu popup if one is open, else None."""
        popup = QApplication.activePopupWidget()
        if popup is not None and isinstance(popup, QMenu):
            return popup
        return None

    def _ctrl_send_key(self, widget, key: Qt.Key):
        """Synthesize a key-press event and send it to widget."""
        from PySide6.QtGui import QKeyEvent
        ev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, ev)

    def _ctrl_dialog_dispatch(self, dialog, action: str):
        """Route a controller action to the correct button of the open dialog.

        Dispatches per dialog type (identified by attributes), so each dialog's
        buttons are triggered correctly regardless of the generic accept/reject logic.
        """
        from PySide6.QtWidgets import QDialogButtonBox as _DBB

        # Actions that should always REJECT / CLOSE any dialog
        _REJECT = {"back", "delete", "context_menu",
                   "page_up", "page_down", "backup_all"}

        def _click(btn):
            if btn and btn.isEnabled() and btn.isVisible():
                btn.click()

        # ── QMessageBox ────────────────────────────────────────────────
        if isinstance(dialog, QMessageBox):
            if action in _REJECT:
                for sb in (QMessageBox.StandardButton.No,
                           QMessageBox.StandardButton.Cancel,
                           QMessageBox.StandardButton.Close,
                           QMessageBox.StandardButton.Discard,
                           QMessageBox.StandardButton.Abort):
                    btn = dialog.button(sb)
                    if btn:
                        btn.click()
                        return
                dialog.reject()
            else:
                for sb in (QMessageBox.StandardButton.Yes,
                           QMessageBox.StandardButton.Ok,
                           QMessageBox.StandardButton.Open,
                           QMessageBox.StandardButton.Save):
                    btn = dialog.button(sb)
                    if btn:
                        btn.click()
                        return
                dialog.accept()
            return

        # ── ManageBackupsDialog  (delete_button, delete_all_button, close_button)
        if (hasattr(dialog, 'delete_button') and
                hasattr(dialog, 'delete_all_button') and
                hasattr(dialog, 'close_button')):
            if action in _REJECT:
                _click(dialog.close_button)
            elif action == "restore":           # X → Delete All
                _click(dialog.delete_all_button)
            elif action == "backup":            # A → Delete Selected
                _click(dialog.delete_button)
            # Any other action → do nothing (don't close unintentionally)
            return

        # ── SteamDialog  (configure_button, refresh_button, close_button)
        if (hasattr(dialog, 'configure_button') and
                hasattr(dialog, 'refresh_button') and
                hasattr(dialog, 'close_button')):
            if action in _REJECT:
                _click(dialog.close_button)
            elif action == "restore":           # X → Refresh Games List
                _click(dialog.refresh_button)
            elif action == "backup":            # A → Configure Selected Profile
                _click(dialog.configure_button)
            return

        # ── RestoreDialog  (ok_button + button_box with Cancel) ────────
        if hasattr(dialog, 'ok_button') and hasattr(dialog, 'button_box'):
            if action in _REJECT:
                dialog.reject()
            else:
                _click(dialog.ok_button)
            return

        # ── Generic dialog with QDialogButtonBox ───────────────────────
        if hasattr(dialog, 'button_box') and isinstance(dialog.button_box, _DBB):
            bb = dialog.button_box
            if action in _REJECT:
                cancel = bb.button(_DBB.StandardButton.Cancel)
                if cancel:
                    cancel.click()
                else:
                    dialog.reject()
            else:
                ok = bb.button(_DBB.StandardButton.Ok)
                if ok and ok.isEnabled():
                    ok.click()
                else:
                    dialog.accept()
            return

        # ── Last-resort fallback ────────────────────────────────────────
        if action in _REJECT:
            dialog.reject()
        else:
            dialog.accept()

    def _ctrl_active_dialog(self):
        """Return the active visible QDialog, preferring the modal one if present."""
        modal = QApplication.activeModalWidget()
        if modal is not None and isinstance(modal, QDialog) and modal.isVisible():
            return modal
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible():
                return w
        return None

    def _ctrl_dialog_nav(self, dialog, direction: int):
        """Navigate up (direction=-1) or down (+1) inside an open dialog.
        Supports QTableWidget, QListWidget, QTreeWidget (top-level items),
        and QComboBox (e.g. QInputDialog with getItem)."""
        from PySide6.QtWidgets import QTableWidget, QListWidget, QTreeWidget
        # QComboBox first (e.g. Select Steam Profile QInputDialog)
        for combo in dialog.findChildren(QComboBox):
            if combo.isEnabled() and combo.isVisible() and combo.isEditable() == False:
                count = combo.count()
                if count == 0:
                    return
                current = combo.currentIndex()
                if current < 0:
                    combo.setCurrentIndex(0)
                    return
                new_idx = max(0, current + direction) if direction < 0 else min(count - 1, current + direction)
                combo.setCurrentIndex(new_idx)
                return
        # Try QTableWidget
        for table in dialog.findChildren(QTableWidget):
            if table.isEnabled() and table.isVisible():
                count = table.rowCount()
                if count == 0:
                    return
                current = table.currentRow()
                if not table.selectionModel().hasSelection() or current < 0:
                    table.selectRow(0)
                    return
                new_row = max(0, current + direction) if direction < 0 else min(count - 1, current + direction)
                # Always call selectRow — ensures single-item lists get selected too
                table.selectRow(new_row)
                table.scrollTo(table.model().index(new_row, 0))
                return
        # Fallback: QListWidget
        for lst in dialog.findChildren(QListWidget):
            if lst.isEnabled() and lst.isVisible():
                count = lst.count()
                if count == 0:
                    return
                current = lst.currentRow()
                if current < 0:
                    lst.setCurrentRow(0)
                    return
                new_row = max(0, current + direction) if direction < 0 else min(count - 1, current + direction)
                lst.setCurrentRow(new_row)
                return
        # QTreeWidget (e.g. SteamDialog game list)
        for tree in dialog.findChildren(QTreeWidget):
            if tree.isEnabled() and tree.isVisible():
                count = tree.topLevelItemCount()
                if count == 0:
                    return
                current_item = tree.currentItem()
                current = tree.indexOfTopLevelItem(current_item) if current_item else -1
                if current < 0:
                    tree.setCurrentItem(tree.topLevelItem(0))
                    tree.scrollToItem(tree.topLevelItem(0))
                    return
                new_idx = max(0, current + direction) if direction < 0 else min(count - 1, current + direction)
                item = tree.topLevelItem(new_idx)
                tree.setCurrentItem(item)
                tree.scrollToItem(item)
                return

    # --- Controller guard helpers ---

    def _ctrl_modal_open(self) -> bool:
        """True if any QDialog or QMenu popup is currently visible.
        ManageBackupsDialog and similar are opened with show(), not exec(),
        so activeModalWidget() is always None — we scan topLevelWidgets instead.
        QMenu is handled separately (routed, not blocked) so we exclude it here."""
        if QApplication.activePopupWidget() is not None:
            return False  # QMenu popup: handled by _ctrl_dispatch, not blocked
        return any(
            isinstance(w, QDialog) and w.isVisible()
            for w in QApplication.topLevelWidgets()
        )

    # Keep the cooldown helpers for any future use (currently unused by the modal guard)
    def _ctrl_cooldown_active(self) -> bool:
        return getattr(self, '_ctrl_action_cooldown', False)

    def _ctrl_start_cooldown(self, ms: int = 1000):
        self._ctrl_action_cooldown = True
        QTimer.singleShot(ms, self._ctrl_clear_cooldown)

    @Slot()
    def _ctrl_clear_cooldown(self):
        self._ctrl_action_cooldown = False

    # --- Controller navigation helpers ---

    def _ctrl_table_is_active(self) -> bool:
        """True when the main profile table is visible, usable, and no dialog is open."""
        return (
            not self._ctrl_modal_open() and
            not getattr(self, '_settings_mode_active', False) and
            not getattr(self, '_controller_mode_active', False) and
            not getattr(self, '_cloud_mode_active', False) and
            not getattr(self, '_edit_mode_active', False) and
            self.profile_table_widget.isVisible()
        )

    def _ctrl_visible_rows(self) -> list[int]:
        """Return list of non-hidden row indices in the profile table."""
        table = self.profile_table_widget
        return [r for r in range(table.rowCount()) if not table.isRowHidden(r)]

    def _ctrl_next_visible_row(self, current: int) -> int | None:
        visible = self._ctrl_visible_rows()
        if not visible:
            return None
        if current < 0:
            return visible[0]
        for r in visible:
            if r > current:
                return r
        return None

    def _ctrl_prev_visible_row(self, current: int) -> int | None:
        visible = self._ctrl_visible_rows()
        if not visible:
            return None
        if current < 0:
            return visible[-1]
        for r in reversed(visible):
            if r < current:
                return r
        return None


# --- End of MainWindow class definition ---