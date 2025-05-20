# SaveState_gui.py
# -*- coding: utf-8 -*-
import sys
import os
import logging

# --- PySide6 Imports (misuriamo i moduli principali) ---
# Importa il modulo base prima, poi gli elementi specifici
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QMessageBox,
    QProgressBar, QGroupBox,
    QStyle, QDockWidget, QPlainTextEdit, QTableWidget
)
from PySide6.QtCore import (
    Slot, Qt, QSize, QCoreApplication,
    QEvent,
    QTimer, Property, QPropertyAnimation, QEasingCurve
)
from PySide6.QtGui import QIcon, QPalette, QColor, QCursor

from gui_utils import QtLogHandler
from utils import resource_path
from gui_components.profile_list_manager import ProfileListManager
from gui_components.theme_manager import ThemeManager
from gui_components.profile_creation_manager import ProfileCreationManager
import core_logic # Mantenuto per load_profiles
from gui_handlers import MainWindowHandlers

# --- COSTANTI GLOBALI PER IDENTIFICARE L'ISTANZA ---
# Usa stringhe univoche per la tua applicazione
APP_GUID = "SaveState_App_Unique_GUID_6f459a83-4f6a-4e3e-8c1e-7a4d5e3d2b1a" 
SHARED_MEM_KEY = f"{APP_GUID}_SharedMem"
LOCAL_SERVER_NAME = f"{APP_GUID}_LocalServer"
# --- FINE COSTANTI ---


# --- Finestra Principale ---
class MainWindow(QMainWindow):  
    # --- Overlay Opacity Property ---
    # Getter for the overlay opacity property.
    def _get_overlay_opacity(self):
        try:
            # Legge l'alpha dal colore di sfondo esistente
            return self.overlay_widget.palette().window().color().alphaF()
        except Exception:
            return 0.0

    # Setter for the overlay opacity property.
    def _set_overlay_opacity(self, opacity):
        # Imposta l'opacità usando setStyleSheet con rgba()
        if not hasattr(self, 'overlay_widget'):
            return
        try:
            opacity = max(0.0, min(1.0, opacity)) # Limita tra 0 e 1
            alpha = int(opacity * 255) # Calcola valore alpha (0-255)

            # Imposta lo stile del widget overlay
            # Usiamo nero (0,0,0) con l'alpha calcolato.
            style_sheet = f"QWidget#BusyOverlay {{ background-color: rgba(0, 0, 0, {alpha}); }}"
            self.overlay_widget.setStyleSheet(style_sheet)
            # print(f"DEBUG: Setting stylesheet: {style_sheet}") # Log se serve

            # Gestisci visibilità e posizione della label animazione (come prima)
            if hasattr(self, 'loading_label') and self.loading_label:
                 is_visible = opacity > 0.1
                 self.loading_label.setVisible(is_visible)
                 if is_visible: # Centra solo se sta per essere visibile
                      self._center_loading_label()

            # Potrebbe non servire update() con stylesheet, ma lasciamolo per sicurezza
            self.overlay_widget.update()

        except Exception as e:
             logging.error(f"Error setting overlay opacity via stylesheet: {e}")

    _overlay_opacity = Property(float, _get_overlay_opacity, _set_overlay_opacity)
    
    # --- Initialization ---
    # Initializes the main window, sets up UI elements, managers, and connects signals.
    def __init__(self, initial_settings, console_log_handler, qt_log_handler):
        super().__init__()
        self.console_log_handler = console_log_handler # Salva riferimento al gestore console
        self.qt_log_handler = qt_log_handler
        
        # Variabili per il rilevamento del drag globale
        self.global_drag_detection_timer = QTimer(self)
        self.global_drag_detection_timer.setInterval(200)  # Controlla ogni 200ms
        self.global_drag_detection_timer.timeout.connect(self.check_global_drag_state)
        self.global_drag_detection_timer.start()
        self.is_drag_operation_active = False
        self.last_cursor_pos = QCursor.pos()
        self.drag_movement_threshold = 5  # Soglia di movimento in pixel per considerare un drag
        self.drag_check_counter = 0

        # Translator removed - application is now English-only

        self.setGeometry(650, 250, 720, 600)
        self.setAcceptDrops(True)
        self.current_settings = initial_settings
        self.profiles = core_logic.load_profiles()
        
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
        
        # --- Layout Separato per Pulsante Log ---
        log_button_corner_layout = QHBoxLayout()
        log_button_corner_layout.addStretch() # Spinge a destra
        log_button_corner_layout.addWidget(self.toggle_log_button) # Solo il pulsante Log

        main_layout.addLayout(log_button_corner_layout)
        # --- FINE Layout Separato ---
        
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

        
        # --- NUOVO: Creazione Overlay Widget ---
        self.overlay_widget = QWidget(self.centralWidget())
        self.overlay_widget.setObjectName("BusyOverlay")
        # Imposta un colore di base (qui verrà applicato l'alpha da _set_overlay_opacity)
        base_palette = self.overlay_widget.palette()
        base_palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0)) # Nero, alpha 0 iniziale
        self.overlay_widget.setPalette(base_palette)
        self.overlay_widget.setAutoFillBackground(True)
        self.overlay_widget.hide()
        # --- FINE Overlay ---


        # --- Creazione Label per Animazione/Placeholder ---
        self.loading_label = QLabel(self.overlay_widget) # Figlio dell'overlay!
        self.loading_label.setObjectName("LoadingIndicatorLabel")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        loading_indicator_size = QSize(200, 200) 
        self.loading_label.setFixedSize(loading_indicator_size)
        self.loading_label.setText("Searching...")
        # Stile per il testo caricamento
        self.loading_label.setStyleSheet("QLabel#LoadingIndicatorLabel { color: white; font-size: 17pt; background-color: transparent; }")
        # Nascondi la label all'inizio (verrà mostrata dal set_overlay_opacity)
        self.loading_label.hide()
        # --- FINE Label Animazione ---


        # --- Creazione Animazioni Opacità ---
        fade_duration = 250 # Durata animazione in ms

        self.fade_in_animation = QPropertyAnimation(self, b"_overlay_opacity", self)
        self.fade_in_animation.setDuration(fade_duration)
        self.fade_in_animation.setStartValue(0.0)
        self.fade_in_animation.setEndValue(0.6) # Opacità 60%
        self.fade_in_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.fade_out_animation = QPropertyAnimation(self, b"_overlay_opacity", self)
        self.fade_out_animation.setDuration(fade_duration)
        self.fade_out_animation.setStartValue(0.6)
        self.fade_out_animation.setEndValue(0.0)
        self.fade_out_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Nasconde l'overlay (e quindi la label figlia) quando il fade-out finisce
        self.fade_out_animation.finished.connect(self.overlay_widget.hide)
        # --- FINE Animazioni ---
        
        self.profile_table_manager = ProfileListManager(self.profile_table_widget, self)
        self.profile_table_manager.update_profile_table()
        self.theme_manager = ThemeManager(self.theme_button, self)
        self.profile_creation_manager = ProfileCreationManager(self)
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

        # Stato Iniziale e Tema
        self.update_action_button_states()
        self.worker_thread = None
        self.updateUiText()
        self.setWindowIcon(QIcon(resource_path("icon.png"))) # Icona finestra principale
    
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
        super().resizeEvent(event)
        event.accept()

    # Called when a dragged item enters the window; accepts if it contains valid URLs.
    def dragEnterEvent(self, event):
        """Accetta l'evento se contiene URL (per drag-and-drop cartelle)."""
        if hasattr(self, 'profile_creation_manager'):
            self.profile_creation_manager.dragEnterEvent(event)
        else:
            super().dragEnterEvent(event) # Chiamata al metodo base

    # Gestisce il movimento durante il drag (attualmente ignorato).
    def dragMoveEvent(self, event):
        """Gestisce il movimento durante il drag (attualmente ignorato)."""
        if hasattr(self, 'profile_creation_manager'):
            self.profile_creation_manager.dragMoveEvent(event)
        else:
            super().dragMoveEvent(event)

    # Gestisce l'uscita del cursore dall'area dell'applicazione durante il drag.
    def dragLeaveEvent(self, event):
        """Gestisce l'uscita del cursore dall'area dell'applicazione durante il drag."""
        if hasattr(self, 'profile_creation_manager'):
            self.profile_creation_manager.dragLeaveEvent(event)
        else:
            # Nascondi comunque l'overlay se esiste
            if hasattr(self, 'overlay_widget') and self.overlay_widget:
                self.overlay_widget.hide()
                if hasattr(self, 'loading_label'):
                    self.loading_label.hide()
            super().dragLeaveEvent(event)

    # Called when a dragged item is dropped; handles dropped folders for new profiles.
    def dropEvent(self, event):
        """Gestisce il rilascio di elementi (cartelle) sulla finestra."""
        if hasattr(self, 'profile_creation_manager'):
            self.profile_creation_manager.dropEvent(event)
        else:
            super().dropEvent(event)
    
    # Sets up the UI text for all components
    def updateUiText(self):
        """Updates the UI text"""
        logging.debug(">>> updateUiText: START <<<")
        self.setWindowTitle("SaveState - 1.4.0")
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
                self.loading_label.setText("Searching...")

            logging.debug("Updating profile table after UI text update")
            self.profile_table_manager.update_profile_table()

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

    # Handles application-level events
    def changeEvent(self, event):
        """Intercetta eventi di cambio stato."""
        if event.type() == QEvent.Type.LanguageChange:
            logging.debug("MainWindow.changeEvent(LanguageChange) detected")
            # Ensure retranslateUi is NOT called here to avoid double calls
            # self.retranslateUi() # Keep this commented or remove
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
        self.restore_button.setEnabled(has_selection)
        self.delete_profile_button.setEnabled(has_selection)
        self.manage_backups_button.setEnabled(has_selection)
        self.create_shortcut_button.setEnabled(has_selection)

    # Enables or disables main UI controls, typically during background operations.
    def set_controls_enabled(self, enabled):
        """Abilita o disabilita i controlli principali della UI."""
        self.profile_table_widget.setEnabled(enabled)
        has_selection = self.profile_table_manager.has_selection()
        self.backup_button.setEnabled(enabled and has_selection)
        self.restore_button.setEnabled(enabled and has_selection)
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

    # --- Single Instance Activation ---
    # Activates the window of an existing instance when a new instance is launched.
    @Slot()
    def activateExistingInstance(self):
        # Connected to QLocalServer signal in main.py
        logging.info("Received signal to activate existing instance (slot in MainWindow).")
        self.showNormal()
        self.raise_()
        self.activateWindow()
        
    def check_global_drag_state(self):
        """Controlla se è in corso un'operazione di drag a livello di sistema."""
        try:
            # Ottieni la posizione corrente del cursore
            current_pos = QCursor.pos()
            
            # Calcola la distanza dal punto precedente
            distance = ((current_pos.x() - self.last_cursor_pos.x()) ** 2 + 
                        (current_pos.y() - self.last_cursor_pos.y()) ** 2) ** 0.5
            
            # Aggiorna l'ultima posizione conosciuta
            self.last_cursor_pos = current_pos
            
            # Incrementa il contatore per il controllo periodico
            self.drag_check_counter += 1
            
            # Ottieni lo stato dei pulsanti del mouse
            from PySide6.QtGui import QGuiApplication
            modifiers = QGuiApplication.queryKeyboardModifiers()
            mouse_buttons = QGuiApplication.mouseButtons()
            from PySide6.QtCore import Qt
            left_button_pressed = bool(mouse_buttons & Qt.MouseButton.LeftButton)
            
            # Verifica se sembra essere in corso un'operazione di drag
            potential_drag = left_button_pressed and distance > self.drag_movement_threshold
            
            # Resetta il contatore ogni 10 controlli
            if self.drag_check_counter >= 10:
                self.drag_check_counter = 0
                
                # Controlla se c'è un'operazione di drag in corso
                if potential_drag and not self.is_drag_operation_active:
                    logging.debug("Rilevata possibile operazione di drag globale")
                    self.is_drag_operation_active = True
                    
                    # Mostra l'overlay con animazione fade-in
                    if hasattr(self, 'overlay_widget') and self.overlay_widget:
                        self.overlay_widget.resize(self.centralWidget().size())
                        # Imposta il testo della label a "Drop Here"
                        if hasattr(self, 'loading_label') and self.loading_label:
                            self.loading_label.setText("Drop Here")
                        if hasattr(self, '_center_loading_label'): 
                            self._center_loading_label()
                        # Imposta lo stile per il drag (opacità 30%)
                        self.overlay_widget.setStyleSheet("QWidget#BusyOverlay { background-color: rgba(0, 0, 0, 77); }")
                        self.overlay_widget.show()
                        if hasattr(self, 'loading_label'):
                            self.loading_label.show()
                        if hasattr(self, 'fade_in_animation'): 
                            self.fade_in_animation.start()
                        logging.debug("Avviata animazione fade-in per drag globale")
                
                # Se non c'è più un'operazione di drag in corso, nascondi l'overlay
                elif not potential_drag and self.is_drag_operation_active:
                    logging.debug("Operazione di drag globale terminata")
                    self.is_drag_operation_active = False
                    
                    # Nascondi l'overlay con animazione fade-out
                    if hasattr(self, 'overlay_widget') and self.overlay_widget and self.overlay_widget.isVisible():
                        if hasattr(self, 'fade_out_animation'): 
                            self.fade_out_animation.start()
                        logging.debug("Avviata animazione fade-out per drag globale terminato")
        except Exception as e:
            logging.error(f"Errore durante il controllo dello stato di drag globale: {e}")
            # Disattiva il timer in caso di errori ripetuti
            self.drag_check_counter += 1
            if self.drag_check_counter > 50:  # Dopo 50 errori, disattiva il timer
                self.global_drag_detection_timer.stop()
                logging.error("Timer di rilevamento drag globale disattivato dopo errori ripetuti")

# --- End of MainWindow class definition ---