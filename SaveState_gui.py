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
    QPushButton, QLabel, QStatusBar,
    QProgressBar, QGroupBox, QLineEdit,
    QStyle, QDockWidget, QPlainTextEdit, QTableWidget, QGraphicsOpacityEffect,
    QDialog, QFileDialog, QMenu, QSpinBox, QComboBox, QCheckBox, QFormLayout
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
     QIcon, QColor, QDragEnterEvent, QDropEvent, QDragLeaveEvent, QDragMoveEvent, QPalette, QAction
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
import core_logic # Mantenuto per load_profiles
from gui_handlers import MainWindowHandlers

# --- COSTANTI GLOBALI PER IDENTIFICARE L'ISTANZA ---
# Usa stringhe univoche per la tua applicazione
def sanitize_server_name(name):
    """
    Sanitizes server name to be compatible with Linux/Unix systems.
    Removes or replaces problematic characters that can cause issues with local sockets.
    """
    import re
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    # Remove or replace other problematic characters, keeping only alphanumeric, underscores, hyphens, and dots
    name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', name)
    # Remove multiple consecutive underscores
    name = re.sub(r'_+', '_', name)
    # Remove leading/trailing underscores
    name = name.strip('_')
    return name

APP_GUID = "SaveState_App_Unique_GUID_6f459a83-4f6a-4e3e-8c1e-7a4d5e3d2b1a" 
SHARED_MEM_KEY = sanitize_server_name(f"{APP_GUID}_SharedMem")
LOCAL_SERVER_NAME = sanitize_server_name(f"{APP_GUID}_LocalServer")
# --- FINE COSTANTI ---


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
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.new_profile_button = QPushButton()
        self.steam_button = QPushButton()
        self.delete_profile_button = QPushButton() # Crea pulsante Elimina Profilo
        self.backup_button = QPushButton()         # Crea pulsante Backup
        self.restore_button = QPushButton()        # Crea pulsante Ripristina
        self.manage_backups_button = QPushButton() # Crea pulsante Gestisci Backup
        self.open_backup_dir_button = QPushButton() # Crea pulsante Apri Cartella

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
            settings_icon = QIcon(icon_path)
            self.settings_button.setIcon(settings_icon)
            self.settings_button.setIconSize(QSize(16, 16)) # Imposta dimensione se necessario
        else:
            logging.warning(f"File icona impostazioni non trovato: {icon_path}")
            
        self.theme_button = QPushButton()
        
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
        backup_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton) # Icona Salva (Floppy)
        self.backup_button.setIcon(backup_icon)
        
        self.restore_button = QPushButton("Restore...")
        self.restore_button.setObjectName("DangerButton")
        restore_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown) # Icona Freccia Giù (Download/Load?)
        self.restore_button.setIcon(restore_icon)
        
        self.manage_backups_button = QPushButton("Manage Backups")
        manage_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView) # Icona Vista Dettagliata?
        self.manage_backups_button.setIcon(manage_icon)
        
        self.open_backup_dir_button = QPushButton("Open Backup Folder")
        open_folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon) # Icona Apri Cartella
        self.open_backup_dir_button.setIcon(open_folder_icon)
        
        # --- NUOVO PULSANTE COLLEGAMENTO (Stile Minecraft) ---
        self.create_shortcut_button = QPushButton() # SENZA TESTO
        self.create_shortcut_button.setObjectName("MinecraftButton") # <-- USA LO STESSO ObjectName!

        # Icona (Usa la stessa icona 'desktop.png')
        shortcut_icon_path = resource_path("icons/desktop.png")
        if os.path.exists(shortcut_icon_path):
            self.create_shortcut_button.setIcon(QIcon(shortcut_icon_path))
        else:
            # Se icona manca, mettiamo un testo fallback ma SENZA impostare dimensione icona
             self.create_shortcut_button.setText("SC") # Shortcut Fallback
             print(f"WARN: Icona desktop non trovata: {shortcut_icon_path}, uso testo SC.")

        # Dimensioni e icona come pulsante Minecraft
        mc_button_size = QSize(30, 30) # <-- Dimensione 30x30
        self.create_shortcut_button.setFixedSize(mc_button_size)
        self.create_shortcut_button.setIconSize(QSize(24, 24)) # <-- Dimensione icona 24x24

        # Tooltip (Importante perché non c'è testo)
        self.create_shortcut_button.setToolTip("Create a desktop shortcut to launch the selected profile's game/emulator.")
        # --- FINE NUOVO PULSANTE (Stile Minecraft) ---
        
        # Imposta dimensione icone (opzionale, regola i px se necessario)
        icon_size = QSize(16, 16) # Larghezza, Altezza in pixel
        self.new_profile_button.setIconSize(icon_size)
        self.delete_profile_button.setIconSize(icon_size)
        self.backup_button.setIconSize(icon_size)
        self.restore_button.setIconSize(icon_size)
        self.manage_backups_button.setIconSize(icon_size)
        self.open_backup_dir_button.setIconSize(icon_size)
        # self.settings_button.setIconSize(icon_size)
        # self.steam_button.setIconSize(icon_size)

        #self.update_profile_table()

        # --- Layout ---
        main_layout = QVBoxLayout()
        profile_group = QGroupBox("Profiles")
        self.profile_group = profile_group
        profile_layout = QVBoxLayout()
        profile_layout.addWidget(self.profile_table_widget)
        profile_group.setLayout(profile_layout)
        main_layout.addWidget(profile_group, stretch=1)

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
        main_layout.addWidget(self.profile_editor_group, stretch=1)

        actions_group = QGroupBox("Actions")
        self.actions_group = actions_group
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        actions_layout.addWidget(self.backup_button)
        actions_layout.addWidget(self.restore_button)
        actions_layout.addWidget(self.manage_backups_button)
        
        # --- Pulsante Minecraft ---
        self.minecraft_button = QPushButton() # Vuoto, senza testo
        self.minecraft_button.setObjectName("MinecraftButton")
        self.minecraft_button.setToolTip("Create a profile from a Minecraft world") # Tooltip è importante

        # Carica icona Minecraft
        mc_icon_path = resource_path("icons/minecraft.png")
        if os.path.exists(mc_icon_path):
            mc_icon = QIcon(mc_icon_path)
            self.minecraft_button.setIcon(mc_icon)
        else:
            print(f"WARN: Icona Minecraft non trovata: {mc_icon_path}")
            self.minecraft_button.setText("MC") # Fallback testo

        # Imposta dimensione fissa quadrata (es. 30x30, un po' più grande dei flat)
        mc_button_size = QSize(30, 30)
        self.minecraft_button.setFixedSize(mc_button_size)
        # Adatta dimensione icona dentro il pulsante
        self.minecraft_button.setIconSize(QSize(24, 24)) # Icona 24x24 in pulsante 30x30
        
        actions_layout.addWidget(self.create_shortcut_button)
        actions_layout.addWidget(self.minecraft_button)
        actions_layout.addWidget(self.delete_profile_button)
        actions_group.setLayout(actions_layout)
        main_layout.addWidget(actions_group)
        general_group = QGroupBox("General")
        self.general_group = general_group
        general_layout = QHBoxLayout()
        general_layout.addWidget(self.new_profile_button)
        general_layout.addWidget(self.steam_button)
        general_layout.addWidget(self.open_backup_dir_button) # Moved back here
        general_layout.addWidget(self.settings_button)

        # Theme button setup
        general_layout.addWidget(self.theme_button)
        general_group.setLayout(general_layout)
        main_layout.addWidget(general_group)
        
        # --- Layout per Search Bar e Pulsante Log (in basso) ---
        bottom_controls_layout = QHBoxLayout()
        bottom_controls_layout.addWidget(self.search_bar) # Search bar first
        bottom_controls_layout.addStretch(1) # Add stretch to push log button to the right
        bottom_controls_layout.addWidget(self.toggle_log_button) # Log button last

        main_layout.addLayout(bottom_controls_layout)
        # --- FINE Layout Search Bar e Pulsante Log ---
        
        status_bar = QStatusBar()
        status_bar.addWidget(self.status_label, stretch=1)
        status_bar.addPermanentWidget(self.progress_bar)
        
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
        self.restore_button.clicked.connect(self.handlers.handle_restore)
        self.profile_table_widget.itemSelectionChanged.connect(self.update_action_button_states)
        self.new_profile_button.clicked.connect(self.profile_creation_manager.handle_new_profile) # Stays with manager
        self.delete_profile_button.clicked.connect(self.handlers.handle_delete_profile)
        self.steam_button.clicked.connect(self.handlers.handle_steam)
        self.manage_backups_button.clicked.connect(self.handlers.handle_manage_backups)
        self.settings_button.clicked.connect(self.handlers.handle_settings)
        self.open_backup_dir_button.clicked.connect(self.handlers.handle_open_backup_folder)
        # Log button connections use handlers
        self.toggle_log_button.pressed.connect(self.handlers.handle_log_button_pressed)
        self.toggle_log_button.released.connect(self.handlers.handle_log_button_released)
        # Timer timeout connection moved HERE
        self.log_button_press_timer.timeout.connect(self.handlers.handle_developer_mode_toggle)

        self.minecraft_button.clicked.connect(self.profile_creation_manager.handle_minecraft_button) # Stays with manager
        self.create_shortcut_button.clicked.connect(self.handlers.handle_create_shortcut)
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
        # Ridimensiona overlay
        if hasattr(self, 'overlay_widget') and self.overlay_widget:
            self.overlay_widget.resize(self.centralWidget().size())
        # Centra label
        self._center_loading_label() # Chiama il metodo helper
        event.accept()
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
    
    def updateUiText(self):
        """Updates the UI text"""
        logging.debug(">>> updateUiText: START <<<")
        self.setWindowTitle("SaveState - 1.4.6")
        self.profile_table_manager.retranslate_headers()
        self.settings_button.setText("Settings...")
        self.new_profile_button.setText("New Profile...")
        self.steam_button.setText("Manage Steam")
        self.delete_profile_button.setText("Delete Profile")
        self.backup_button.setText("Backup")
        self.restore_button.setText("Restore...")
        self.manage_backups_button.setText("Manage Backups")
        self.open_backup_dir_button.setText("Open Backup Folder")

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
        if hasattr(self, 'create_shortcut_button'):
            self.create_shortcut_button.setToolTip("Create a desktop shortcut to launch the selected profile's game/emulator")
        if hasattr(self, 'minecraft_button'):
            self.minecraft_button.setToolTip("Create a profile from a Minecraft world")
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
        self.backup_button.setEnabled(has_selection)
        # Restore button is always enabled now - can restore from ZIP without a profile
        self.restore_button.setEnabled(True)
        self.delete_profile_button.setEnabled(has_selection)
        self.manage_backups_button.setEnabled(has_selection)
        self.create_shortcut_button.setEnabled(has_selection)

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

    def keyPressEvent(self, event: QKeyEvent):
        """Handles key presses to show/hide and interact with the search bar."""
        if self.search_bar.isHidden():
            # Show search bar on typing a letter or number
            # Check for actual character input (letters, numbers, common symbols), no modifiers like Ctrl/Alt
            # and ensure it's not an action key like Enter, Tab, Escape itself.
            if event.text() and event.text().isprintable() and len(event.text()) == 1 and \
               not event.modifiers() and \
               event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Escape):
                self.search_bar.show()
                self.search_bar.setFocus()
                self.search_bar.setText(event.text()) # Start with the typed character
                # To prevent the character from being processed by other widgets if the search bar is now active:
                # event.accept() # Careful: this might interfere with the QLineEdit getting the event.
                return # Event handled by showing search bar
        elif self.search_bar.isVisible() and self.search_bar.hasFocus():
            if event.key() == Qt.Key.Key_Escape:
                self.search_bar.clear() # This will trigger textChanged, which will hide it
                self.profile_table_widget.setFocus() # Return focus to table
                event.accept()
                return # Event handled
            # Let QLineEdit handle other keys like backspace, delete, arrows, etc.
            # No need to explicitly call super().keyPressEvent(event) if QLineEdit handles it.

        # If the search bar is visible but doesn't have focus, or if it's hidden and the key wasn't for activation,
        # or if QLineEdit didn't handle the event, pass it to the base class.
        super().keyPressEvent(event)

    # Enables or disables main UI controls, typically during background operations.
    def set_controls_enabled(self, enabled):
        """Abilita o disabilita i controlli principali della UI."""
        self.profile_table_widget.setEnabled(enabled)
        has_selection = self.profile_table_manager.has_selection()
        self.backup_button.setEnabled(enabled and has_selection)
        # Restore button is always enabled - can restore from ZIP without a profile
        self.restore_button.setEnabled(enabled)
        self.delete_profile_button.setEnabled(enabled and has_selection)
        self.manage_backups_button.setEnabled(enabled and has_selection)
        self.create_shortcut_button.setEnabled(enabled and has_selection)
        self.new_profile_button.setEnabled(enabled)
        self.steam_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
        self.theme_button.setEnabled(enabled)
        self.minecraft_button.setEnabled(enabled)
        self.toggle_log_button.setEnabled(enabled)
        self.open_backup_dir_button.setEnabled(enabled)
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
        """Helper method to bring the window to front and activate it."""
        try:
            # If the window is minimized, restore it
            if self.isMinimized():
                self.showNormal()
                logging.debug("Window was minimized, restored to normal state.")
            
            # Bring window to front and activate it
            self.raise_()  # Bring window to front
            self.activateWindow()  # Give focus to the window
            self.show()  # Ensure window is visible
            
            # On some systems, we need to force the window to be on top temporarily
            # This is especially important on Linux and some Windows configurations
            current_state = self.windowState()
            # Remove minimized state and ensure window is active
            new_state = current_state & ~Qt.WindowState.WindowMinimized
            self.setWindowState(new_state)
            
            logging.info("Existing instance window activated and brought to front.")
            
        except Exception as e:
            logging.error(f"Error activating existing instance window: {e}", exc_info=True)

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
        logging.info("MainWindow closeEvent: Cancelling all running search threads...")
        
        # Cancella tutti i thread di ricerca in corso
        if hasattr(self, 'cancellation_manager') and self.cancellation_manager:
            self.cancellation_manager.cancel()
            
        # Ferma il thread di ricerca corrente se esiste
        if hasattr(self, 'current_search_thread') and self.current_search_thread:
            if self.current_search_thread.isRunning():
                logging.info("Waiting for current search thread to finish...")
                self.current_search_thread.wait(3000)  # Aspetta max 3 secondi
                
        # Chiama il closeEvent della classe base
        super().closeEvent(event)
        logging.info("MainWindow closed.")

    # Context menu event handler: show side menu and select row
    def _on_profile_table_context_menu(self, pos):
        try:
            index = self.profile_table_widget.indexAt(pos)
            if index and index.isValid():
                row = index.row()
                self.profile_table_widget.selectRow(row)
                self.update_action_button_states()
                # Build and show a context menu like Linux/Ubuntu
                menu = QMenu(self)
                # Actions
                act_edit = QAction("Edit Profile", self)
                act_shortcut = QAction("Create Desktop Shortcut", self)
                # Optional icons
                try:
                    desktop_icon_path = resource_path("icons/desktop.png")
                    if os.path.exists(desktop_icon_path):
                        act_shortcut.setIcon(QIcon(desktop_icon_path))
                except Exception:
                    pass
                act_edit.triggered.connect(self.handlers.handle_show_edit_profile)
                act_shortcut.triggered.connect(self.handlers.handle_create_shortcut)
                menu.addAction(act_edit)
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
            # Enable/disable group according to checkbox
            self.overrides_group.setEnabled(use_overrides)

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

# --- End of MainWindow class definition ---