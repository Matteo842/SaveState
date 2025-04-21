# SaveState_gui.py
# -*- coding: utf-8 -*-
import sys
import os

import shutil
# --- PySide6 Imports (misuriamo i moduli principali) ---
# Importa il modulo base prima, poi gli elementi specifici
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QMessageBox, QDialog,
    QProgressBar, QGroupBox,
    QStyle, QDockWidget, QPlainTextEdit, QTableWidget, QInputDialog
)
from PySide6.QtCore import ( Slot, Qt, QUrl, QSize, QTranslator, QCoreApplication,
     QEvent, QSharedMemory, QTimer, Property, QPropertyAnimation, QEasingCurve 
)
from PySide6.QtGui import QIcon, QDesktopServices, QPalette, QColor
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from dialogs.settings_dialog import SettingsDialog
from dialogs.restore_dialog import RestoreDialog
from dialogs.manage_backups_dialog import ManageBackupsDialog
from dialogs.steam_dialog import SteamDialog
# --- GUI Utils/Components Imports ---
# Importa tutto il necessario da gui_utils in una volta
from gui_utils import WorkerThread, QtLogHandler, resource_path, SteamSearchWorkerThread
from gui_components.profile_list_manager import ProfileListManager
from gui_components.theme_manager import ThemeManager
from gui_components.profile_creation_manager import ProfileCreationManager
import core_logic
import settings_manager
import config
import logging 
import shortcut_utils
from gui_utils import resource_path

# --- COSTANTI GLOBALI PER IDENTIFICARE L'ISTANZA ---
# Usa stringhe univoche per la tua applicazione
APP_GUID = "SaveState_App_Unique_GUID_6f459a83-4f6a-4e3e-8c1e-7a4d5e3d2b1a" 
SHARED_MEM_KEY = f"{APP_GUID}_SharedMem"
LOCAL_SERVER_NAME = f"{APP_GUID}_LocalServer"
# --- FINE COSTANTI ---

ENGLISH_TRANSLATOR = QTranslator() # Crea l'istanza QUI
CURRENT_TRANSLATOR = None # Questa traccia solo quale è ATTIVO (o None)

# --- Finestra Principale ---
class MainWindow(QMainWindow):  
    def _get_overlay_opacity(self):
        try:
            # Legge l'alpha dal colore di sfondo esistente
            return self.overlay_widget.palette().window().color().alphaF()
        except Exception:
            return 0.0

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
    
    def __init__(self, initial_settings, console_log_handler, qt_log_handler):
        super().__init__()
        self.console_log_handler = console_log_handler # Salva riferimento al gestore console
        self.qt_log_handler = qt_log_handler
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
        self.log_button_press_timer.timeout.connect(self.handle_developer_mode_toggle) # Collega il timeout alla funzione che hai già aggiunto
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
        
        self.backup_button = QPushButton(self.tr("Esegui Backup"))
        backup_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton) # Icona Salva (Floppy)
        self.backup_button.setIcon(backup_icon)
        
        self.restore_button = QPushButton(self.tr("Ripristina da Backup"))
        self.restore_button.setObjectName("DangerButton")
        restore_icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown) # Icona Freccia Giù (Download/Load?)
        self.restore_button.setIcon(restore_icon)
        
        self.manage_backups_button = QPushButton(self.tr("Gestisci Backup"))
        manage_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView) # Icona Vista Dettagliata?
        self.manage_backups_button.setIcon(manage_icon)
        
        self.open_backup_dir_button = QPushButton(self.tr("Apri Cartella Backup"))
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
        self.create_shortcut_button.setToolTip(self.tr("Crea collegamento backup sul desktop"))
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
        profile_group = QGroupBox(self.tr("Profili Salvati"))
        self.profile_group = profile_group
        profile_layout = QVBoxLayout()
        profile_layout.addWidget(self.profile_table_widget)
        profile_group.setLayout(profile_layout)
        main_layout.addWidget(profile_group, stretch=1)
        actions_group = QGroupBox(self.tr("Azioni sul Profilo Selezionato"))
        self.actions_group = actions_group
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        actions_layout.addWidget(self.backup_button)
        actions_layout.addWidget(self.restore_button)
        actions_layout.addWidget(self.manage_backups_button)
        
        # --- Pulsante Minecraft ---
        self.minecraft_button = QPushButton() # Vuoto, senza testo
        self.minecraft_button.setObjectName("MinecraftButton")
        self.minecraft_button.setToolTip(self.tr("Crea profilo da mondo Minecraft")) # Tooltip è importante

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
        general_group = QGroupBox(self.tr("Azioni Generali"))
        self.general_group = general_group
        general_layout = QHBoxLayout()
        general_layout.addWidget(self.new_profile_button)
        general_layout.addWidget(self.steam_button)
        general_layout.addStretch()
        general_layout.addWidget(self.open_backup_dir_button)
        general_layout.addWidget(self.settings_button)
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
        self.log_dock_widget = QDockWidget(self.tr("Console Log"), self)
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
        self.loading_label.setText(self.tr("Ricerca in corso..."))
        # Stile per il testo caricamento
        self.loading_label.setStyleSheet("QLabel#LoadingIndicatorLabel { color: white; font-size: 17pt; background-color: transparent; }")
        # Nascondi la label all'inizio (verrà mostrata dal set_overlay_opacity)
        self.loading_label.hide()
        # --- FINE Label Animazione ---


        # --- NUOVO: Creazione Animazioni Opacità ---
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
        
        # Connessioni
        self.backup_button.clicked.connect(self.handle_backup)
        self.restore_button.clicked.connect(self.handle_restore)
        self.profile_table_widget.itemSelectionChanged.connect(self.update_action_button_states)
        self.new_profile_button.clicked.connect(self.profile_creation_manager.handle_new_profile)
        self.delete_profile_button.clicked.connect(self.handle_delete_profile)
        self.steam_button.clicked.connect(self.handle_steam)
        self.manage_backups_button.clicked.connect(self.handle_manage_backups)
        self.settings_button.clicked.connect(self.handle_settings)
        self.open_backup_dir_button.clicked.connect(self.handle_open_backup_folder)
        #self.toggle_log_button.clicked.connect(self.handle_toggle_log)
        self.toggle_log_button.pressed.connect(self.handle_log_button_pressed) # <-- AGGIUNGI QUESTA
        self.toggle_log_button.released.connect(self.handle_log_button_released)
        self.minecraft_button.clicked.connect(self.profile_creation_manager.handle_minecraft_button)
        self.create_shortcut_button.clicked.connect(self.handle_create_shortcut)

        # Stato Iniziale e Tema
        self.update_action_button_states()
        self.worker_thread = None
        self.retranslateUi()
        self.setWindowIcon(QIcon(resource_path("icon.png"))) # Icona finestra principale
    
    # --- Metodo Helper per Centrare la Label ---
    def _center_loading_label(self):
     """Posiziona loading_label al centro dell'overlay_widget."""
     if hasattr(self, 'loading_label') and self.loading_label and hasattr(self, 'overlay_widget') and self.overlay_widget and self.overlay_widget.isVisible():
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

    # --- Modifica resizeEvent per centrare la label ---
    def resizeEvent(self, event):
        """Sovrascritto per ridimensionare l'overlay E centrare la label."""
        # Ridimensiona overlay
        if hasattr(self, 'overlay_widget') and self.overlay_widget:
            self.overlay_widget.resize(self.centralWidget().size())
        # Centra label
        self._center_loading_label() # Chiama il metodo helper
        super().resizeEvent(event)
    
    def dragEnterEvent(self, event):
        if hasattr(self, 'profile_creation_manager'):
            self.profile_creation_manager.dragEnterEvent(event)
        else:
            super().dragEnterEvent(event) # Chiamata al metodo base

    def dragMoveEvent(self, event):
        if hasattr(self, 'profile_creation_manager'):
            self.profile_creation_manager.dragMoveEvent(event)
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if hasattr(self, 'profile_creation_manager'):
            self.profile_creation_manager.dropEvent(event)
        else:
            super().dropEvent(event)
    
    def retranslateUi(self):
        """Aggiorna il testo di tutti i widget traducibili."""
        logging.debug("MainWindow.retranslateUi() chiamato") # Utile per debug
        self.setWindowTitle("SaveState")
        #self.profile_table_widget.setHorizontalHeaderLabels([self.tr("Profilo"), self.tr("Info Backup")]) # <-- Solo 2 etichette
        self.profile_table_manager.retranslate_headers()
        self.settings_button.setText(self.tr("Impostazioni"))
        self.new_profile_button.setText(self.tr("Nuovo Profilo Manuale"))
        self.steam_button.setText(self.tr("Gestisci Giochi Steam"))
        self.delete_profile_button.setText(self.tr("Elimina Profilo"))
        self.backup_button.setText(self.tr("Esegui Backup"))
        self.restore_button.setText(self.tr("Ripristina da Backup"))
        self.manage_backups_button.setText(self.tr("Gestisci Backup"))
        self.open_backup_dir_button.setText(self.tr("Apri Cartella Backup"))    
        
        if hasattr(self, 'profile_group'): # Controlla se l'attributo esiste
            self.profile_group.setTitle(self.tr("Profili Salvati"))
        if hasattr(self, 'actions_group'):
            self.actions_group.setTitle(self.tr("Azioni sul Profilo Selezionato"))
        if hasattr(self, 'general_group'):
            self.general_group.setTitle(self.tr("Azioni Generali"))
            
            # --- INSERISCI QUI IL NUOVO BLOCCO ---
            # Aggiorna testo placeholder label animazione
            # Controlla se la label esiste e se NON sta mostrando la GIF (movie)
            if hasattr(self, 'loading_label') and self.loading_label and \
            (not hasattr(self, 'loading_movie') or not self.loading_movie or not self.loading_movie.isValid()):
                self.loading_label.setText(self.tr("Ricerca in corso..."))
            # --- FINE NUOVO BLOCCO ---
            
            logging.debug("Aggiornamento tabella profili a seguito di retranslateUi")
            self.profile_table_manager.update_profile_table()

    def changeEvent(self, event):
        """Chiamato quando avvengono eventi nella finestra, inclusi cambi lingua."""
        if event.type() == QEvent.Type.LanguageChange:
            logging.debug("MainWindow.changeEvent(LanguageChange) detected")
            self.retranslateUi() # Richiama la funzione per ri-tradurre tutto
        super().changeEvent(event) # Chiama l'implementazione base
        
    @Slot()
    def handle_toggle_log(self):
        """Mostra o nasconde il pannello di log e aggiorna il tooltip del pulsante."""
        if self.log_dock_widget: # Controlla se esiste per sicurezza
            is_visible = not self.log_dock_widget.isVisible()
            self.log_dock_widget.setVisible(is_visible)

            # Aggiorna il TOOLTIP invece del testo
            if is_visible:
                self.toggle_log_button.setToolTip(self.tr("Nascondi Log"))
            else:
                self.toggle_log_button.setToolTip(self.tr("Mostra Log"))

    @Slot()
    def handle_open_backup_folder(self):
        """Apre la cartella base dei backup in Esplora File."""
        backup_dir = self.current_settings.get("backup_base_dir")

        if not backup_dir:
            QMessageBox.warning(self, "Errore", "Il percorso della cartella base dei backup non è configurato nelle impostazioni.")
            return

        # Normalizza il percorso per sicurezza prima di usarlo
        backup_dir = os.path.normpath(backup_dir)

        if not os.path.isdir(backup_dir):
            # La cartella non esiste, chiedi se crearla
            reply = QMessageBox.question(self, "Cartella Non Trovata", # Modificato da warning a question
                                         f"La cartella dei backup specificata non esiste:\n'{backup_dir}'\n\nVuoi provare a crearla?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                    logging.info(f"Cartella backup creata: {backup_dir}")
                    # Ora che è creata, proviamo ad aprirla
                except Exception as e:
                    QMessageBox.critical(self, "Errore Creazione", f"Impossibile creare la cartella:\n{e}")
                    return # Esce se creazione fallisce
            else:
                return # Non aprire se non esiste e utente non vuole creare

        # Se siamo qui, la cartella dovrebbe esistere
        logging.debug(f"Tentativo di aprire la cartella: {backup_dir}")
        # Usa QDesktopServices per compatibilità (apre con il file manager predefinito)
        url = QUrl.fromLocalFile(backup_dir)
        logging.debug(f"Tentativo di aprire URL: {url.toString()}") # Stampa URL per debug
        if not QDesktopServices.openUrl(url):
             # Fallback per Windows se openUrl fallisce (raro)
             logging.warning(f"QDesktopServices.openUrl fallito per {url.toString()}, tentativo con os.startfile...")
             try:
                 os.startfile(backup_dir)
             except Exception as e_start:
                 QMessageBox.critical(self, "Errore Apertura", f"Impossibile aprire la cartella:\n{e_start}")

    def get_selected_profile_name(self):
        selected_rows = self.profile_table_widget.selectionModel().selectedRows()
        if selected_rows:
            first_row_index = selected_rows[0].row()
            name_item = self.profile_table_widget.item(first_row_index, 0)
            if name_item: return name_item.data(Qt.ItemDataRole.UserRole)
        return None

    def update_action_button_states(self):
        #selected = self.get_selected_profile_name() is not None
        selected = self.profile_table_manager.get_selected_profile_name() is not None
        self.backup_button.setEnabled(selected)
        self.restore_button.setEnabled(selected)
        self.delete_profile_button.setEnabled(selected)
        self.manage_backups_button.setEnabled(selected)
        self.create_shortcut_button.setEnabled(selected)

    def set_controls_enabled(self, enabled):
        self.profile_table_widget.setEnabled(enabled)
        #selected_profile_exists = self.get_selected_profile_name() is not None
        selected_profile_exists = self.profile_table_manager.get_selected_profile_name() is not None
        self.backup_button.setEnabled(enabled and selected_profile_exists)
        self.restore_button.setEnabled(enabled and selected_profile_exists)
        self.delete_profile_button.setEnabled(enabled and selected_profile_exists)
        self.manage_backups_button.setEnabled(enabled and selected_profile_exists)
        self.create_shortcut_button.setEnabled(enabled and selected_profile_exists)
        self.new_profile_button.setEnabled(enabled)
        self.steam_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
        self.progress_bar.setVisible(not enabled)

    def apply_translator(self, lang_code):
        """Rimuove il traduttore corrente e installa quello nuovo se necessario."""
        global CURRENT_TRANSLATOR, ENGLISH_TRANSLATOR # Accediamo/Modifichiamo le globali qui

        logging.debug(f"MainWindow.apply_translator called with lang_code='{lang_code}'")

        # 1. Rimuovi SEMPRE il traduttore CORRENTEMENTE installato
        if CURRENT_TRANSLATOR is not None:
            removed = QCoreApplication.removeTranslator(CURRENT_TRANSLATOR)
            logging.debug(f"Removed previously active translator: {removed}")
            CURRENT_TRANSLATOR = None # Ora nessun traduttore è ufficialmente attivo

        # 2. Installa quello nuovo SE è Inglese
        if lang_code == "en":
            qm_filename = f"SaveState_{lang_code}.qm"
            # Usa resource_path per trovare il percorso corretto
            qm_file_path = resource_path(qm_filename)
            logging.info(f"Attempting to load English translator from: {qm_file_path}")

            # Controllo esplicito se il file esiste nel percorso trovato
            if not os.path.exists(qm_file_path):
                logging.error(f".qm translation file NOT FOUND in: {qm_file_path} (Check .spec and build). The translation will not work.")
                # Mostra errore all'utente
                QMessageBox.warning(self, self.tr("Errore Traduzione"),
                                    self.tr("Impossibile caricare il file di traduzione per l'inglese ({0}).\n"
                                            "L'interfaccia rimarrà in italiano.").format(qm_filename))
                CURRENT_TRANSLATOR = None # Assicurati sia None
                return # Esci se il file non esiste  <--- QUESTA ERA LA RIGA DELL'ERRORE, ORA INDENTATA CORRETTAMENTE

            # Prova a caricare/ricaricare il file QM nell'istanza globale
            # Ho rimosso il controllo duplicato di ENGLISH_TRANSLATOR.load() che avevi nel codice che hai incollato prima
            loaded_ok = ENGLISH_TRANSLATOR.load(qm_file_path) # Usa percorso completo
            if loaded_ok:
                logging.debug(f"QM file '{qm_file_path}' loaded into ENGLISH_TRANSLATOR.")
                # Ora prova ad installare l'istanza globale
                installed = QCoreApplication.installTranslator(ENGLISH_TRANSLATOR)
                if installed:
                    CURRENT_TRANSLATOR = ENGLISH_TRANSLATOR # Aggiorna il tracker globale
                    logging.info("New 'en' translator installed successfully.")
                    # Qt dovrebbe gestire retranslateUi tramite LanguageChange
                else:
                    logging.error("'en' translator installation failed after loading!")
                    QCoreApplication.removeTranslator(ENGLISH_TRANSLATOR) # Tentativo di pulizia
                    CURRENT_TRANSLATOR = None
            else:
                # Load fallito
                logging.warning(f"Loading QM file failed: {qm_file_path}. The 'load' function returned False.")
                CURRENT_TRANSLATOR = None # Assicurati sia None
                # Non mostriamo un altro QMessageBox qui perché l'errore è già stato loggato e
                # un avviso è stato mostrato se il file non esisteva.
        else: # Se la nuova lingua è 'it' (o qualsiasi altra cosa non 'en')
            logging.info("Switching to Italian (or unsupported language), no active translator.")
            # Rimuovi un eventuale traduttore precedente se per caso era rimasto attivo
            if CURRENT_TRANSLATOR is not None:
                QCoreApplication.removeTranslator(CURRENT_TRANSLATOR)
                logging.debug("Removed previous translator that was no longer needed.")
            CURRENT_TRANSLATOR = None # Imposta a None per sicurezzar

        logging.debug("Forcing UI updates after potential language change.")
        if hasattr(self, 'theme_manager') and self.theme_manager:
            self.theme_manager.update_theme() # <-- ASSICURATI CHE CI SIA: Aggiorna tooltip pulsante tema nella nuova lingua
        if hasattr(self, 'profile_table_manager') and self.profile_table_manager:
            self.profile_table_manager.retranslate_headers() # <-- ASSICURATI CHE CI SIA: Aggiorna intestazioni tabella

        
        # Forzare un aggiornamento dell'UI dopo il cambio? Qt dovrebbe farlo con LanguageChange.
        # Se non lo fa, potresti forzarlo qui con self.retranslateUi(), ma di solito non serve.

    
    @Slot()
    def handle_settings(self):
        # Salva la lingua corrente PRIMA di aprire il dialogo
        old_language = self.current_settings.get("language", "it")

        dialog = SettingsDialog(self.current_settings.copy(), self) # Passa una COPIA per permettere l'annullamento
        try:
            logging.debug("Forcing dialog retranslate before exec()...")
            dialog.retranslateUi() # Forza l'aggiornamento dei testi
        except Exception as e_retrans:
            logging.error(f"Error forcing retranslate: {e_retrans}", exc_info=True)
       
        if dialog.exec() == QDialog.Accepted:
            new_settings = dialog.get_settings()
            logging.debug(f"New settings received from dialog: {new_settings}")

            # --- SALVA IMPOSTAZIONI ---
            if settings_manager.save_settings(new_settings):
                self.current_settings = new_settings # Aggiorna le impostazioni attive
                logging.info("Settings saved successfully.") # Info nel log/console

                # --- GESTISCI CAMBIO LINGUA (QUI!) ---
                new_language = new_settings.get("language", "it")
                if new_language != old_language:
                    logging.info(f"Language changed from '{old_language}' to '{new_language}'. Applying translator...")
                    self.apply_translator(new_language) # Chiama una nuova funzione helper per gestire il cambio

                # Mostra messaggio successo all'utente (opzionale, il salvataggio è implicito)
                # QMessageBox.information(self, "Impostazioni", "Impostazioni salvate con successo.") # Forse ridondante
            else:
                QMessageBox.critical(self, "Errore", "Impossibile salvare il file delle impostazioni.")
                # Le impostazioni NON sono state aggiornate se il salvataggio fallisce
        else:
            logging.debug("Settings dialog cancelled by user.") # L'utente ha annullato, non fare nulla  

    @Slot()
    def handle_delete_profile(self):
        profile_name = self.get_selected_profile_name()
        if not profile_name: return
        reply = QMessageBox.warning(self, "Conferma Eliminazione",
                                    f"Sei sicuro di voler eliminare il profilo '{profile_name}'?\n(Questo non elimina i file di backup già creati).",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if core_logic.delete_profile(self.profiles, profile_name):
                if core_logic.save_profiles(self.profiles):
                    self.profile_table_manager.update_profile_table()
                    self.status_label.setText(self.tr("Profilo '{0}' eliminato.").format(profile_name))
                else:
                    QMessageBox.critical(self, "Errore", "Profilo eliminato dalla memoria ma impossibile salvare le modifiche.")
                    self.profiles = core_logic.load_profiles()
                    self.update_profile_table()

    @Slot()
    def handle_steam(self):
        # --- AGGIORNAMENTO: Esegui scansione PRIMA di aprire il dialogo ---
        # Questo assicura che i dati siano pronti per SteamDialog
        try:
            logging.info("Scanning Steam data before opening dialog...")
            # Chiami le funzioni di core_logic per ottenere i dati aggiornati
            core_logic._steam_install_path = None # Forza ri-scansione path? Opzionale
            core_logic._steam_libraries = None
            core_logic._installed_steam_games = None
            core_logic._steam_userdata_path = None
            core_logic._steam_id3 = None
            core_logic._cached_possible_ids = None
            core_logic._cached_id_details = None

            steam_path = core_logic.get_steam_install_path()
            if not steam_path: raise ValueError("Steam installation not found.")
            self.steam_games_data = core_logic.find_installed_steam_games()
            udp, l_id, p_ids, d_ids = core_logic.find_steam_userdata_info()
            self.steam_userdata_info = {'path': udp, 'likely_id': l_id, 'possible_ids': p_ids, 'details': d_ids}
            logging.info("Steam data scan complete.")

        except Exception as e_scan:
            logging.error(f"Error scanning Steam data: {e_scan}", exc_info=True)
            QMessageBox.critical(self, "Errore Scansione Steam", f"Impossibile leggere i dati di Steam:\n{e_scan}")
            return # Non aprire il dialogo se la scansione fallisce

        # --- APERTURA DIALOGO SEMPLIFICATO ---
        # Ora SteamDialog usa i dati già scansionati e memorizzati in self
        dialog = SteamDialog(main_window_ref=self, parent=self)        # Collega il NUOVO segnale al NUOVO slot
        dialog.game_selected_for_config.connect(self.start_steam_configuration)

        dialog.exec() # Questo ritorna SUBITO dopo che l'utente seleziona un gioco

    # --- SLOT per avviare configurazione e ricerca ---
    @Slot(str, str) # Riceve appid, profile_name
    def start_steam_configuration(self, appid, profile_name):
        logging.info(f"Starting configuration process for '{profile_name}' (AppID: {appid}) in MainWindow.")

        # 1. Recupera dati necessari (install_dir, userdata)
        game_data = self.steam_games_data.get(appid)
        if not game_data:
            logging.error(f"Game data for {appid} not found in self.steam_games_data.")
            QMessageBox.critical(self, "Errore Interno", f"Dati gioco mancanti per AppID {appid}.")
            return
        install_dir = game_data.get('installdir')

        steam_userdata_path = self.steam_userdata_info.get('path')
        likely_id3 = self.steam_userdata_info.get('likely_id')
        possible_ids = self.steam_userdata_info.get('possible_ids', [])
        id_details = self.steam_userdata_info.get('details', {})
        steam_id_to_use = likely_id3 # Default

        # 2. Chiedi ID utente se necessario (logica spostata qui da SteamDialog)
        if len(possible_ids) > 1:
            id_choices_display = []
            display_to_id_map = {}
            index_to_select = 0
            for i, uid in enumerate(possible_ids):
                user_details = id_details.get(uid, {})
                display_name = user_details.get('display_name', uid)
                last_mod_str = user_details.get('last_mod_str', 'N/D')
                is_likely_marker = self.tr("(Recente)") if uid == likely_id3 else ""
                choice_str = f"{display_name} {is_likely_marker} [{last_mod_str}]".strip().replace("  ", " ")
                id_choices_display.append(choice_str)
                display_to_id_map[choice_str] = uid
                if uid == likely_id3: index_to_select = i
            # --- Fine Ciclo For ---
                
            dialog_label_text = self.tr(
                "Trovati multipli profili Steam.\n"
                "Seleziona quello corretto (di solito il più recente):"
            )

            # -> Anche questo è indentato sotto l'if
            chosen_display_str, ok = QInputDialog.getItem(
                 self, self.tr("Selezione Profilo Steam"), dialog_label_text,
                 id_choices_display, index_to_select, False
            )

            if ok and chosen_display_str:
                selected_id3 = display_to_id_map.get(chosen_display_str)
                if selected_id3: steam_id_to_use = selected_id3
                else: logging.error("..."); QMessageBox.warning(self, "..."); return # Gestisci errore
            else:
                self.status_label.setText(self.tr("Configurazione annullata (nessun profilo Steam selezionato)."))
                return # Esce se l'utente annulla

        elif not steam_id_to_use and len(possible_ids) == 1: steam_id_to_use = possible_ids[0]
        elif not possible_ids: logging.warning("No Steam user IDs found.")

        # 3. Avvia Effetto Fade
        logging.debug("Attempting to start fade effect from start_steam_configuration...")
        can_show_effect = False
        try:
            # Semplice check attributi
            has_overlay = hasattr(self, 'overlay_widget') and self.overlay_widget is not None
            has_label = hasattr(self, 'loading_label') and self.loading_label is not None
            has_center_func = hasattr(self, '_center_loading_label')
            has_fade_in = hasattr(self, 'fade_in_animation') and self.fade_in_animation is not None
            can_show_effect = (has_overlay and has_label and has_center_func and has_fade_in)
            logging.debug(f"Fade check results: overlay={has_overlay}, label={has_label}, center={has_center_func}, fade_in={has_fade_in}")
        except Exception as e: logging.error(f"Error checking fade components: {e}", exc_info=True)

        if can_show_effect:
            logging.info("Activating fade effect...")
            try:
                self.overlay_widget.resize(self.centralWidget().size())
                self._center_loading_label()
                self.overlay_widget.show()
                self.overlay_widget.raise_()
                self.fade_in_animation.start()
            except Exception as e_fade: logging.error(f"Error starting fade: {e_fade}", exc_info=True)
        else:
            logging.error("Cannot show fade effect (components missing or check failed).")

        # 4. Avvia Thread di Ricerca
        self.status_label.setText(self.tr("Ricerca percorso per '{0}' in corso...").format(profile_name))
        QApplication.processEvents() # Aggiorna status label

        logging.info("Starting SteamSearchWorkerThread from MainWindow...")
        # Passa anche profile_name al thread così lo abbiamo nel risultato
        thread = SteamSearchWorkerThread(
            game_name=profile_name,
            game_install_dir=install_dir,
            appid=appid,
            steam_userdata_path=steam_userdata_path,
            steam_id3_to_use=steam_id_to_use,
            installed_steam_games_dict=self.steam_games_data,
            # Passa il nome profilo per riceverlo indietro con i risultati
            profile_name_for_results=profile_name
        )
        # Collega il finished del thread al gestore risultati
        thread.finished.connect(self.handle_steam_search_results)
        self.current_search_thread = thread
        self.set_controls_enabled(False)
        thread.start()


     # --- NUOVO SLOT per gestire i risultati della ricerca ---
    @Slot(list, str) # Riceve guesses_with_scores (lista di tuple (path, score)) e profile_name_from_thread
    def handle_steam_search_results(self, guesses_with_scores, profile_name_from_thread):
        logging.debug(f"Handling Steam search results for '{profile_name_from_thread}'. Guesses: {len(guesses_with_scores)}")

        # Rilascia il riferimento al thread che ha finito
        self.current_search_thread = None
        self.set_controls_enabled(True)
        
        # 1. Ferma l'effetto Fade sulla MainWindow
        if hasattr(self, 'fade_out_animation') and self.fade_out_animation:
            # Controlla se l'animazione è in esecuzione prima di avviarla (evita start multipli)
            if self.fade_out_animation.state() != QPropertyAnimation.State.Running:
                self.fade_out_animation.start()
                logging.debug("Fade-out animation started.")
            else:
                logging.debug("Fade-out animation already running or finished.")
        elif hasattr(self, 'overlay_widget'):
             # Fallback se l'animazione non c'è ma l'overlay sì
             if self.overlay_widget.isVisible():
                  self.overlay_widget.hide()
                  logging.debug("Overlay hidden via fallback.")

        # 2. Mostra QInputDialog per scelta percorso e salva profilo
        profile_name = profile_name_from_thread # Usa il nome ricevuto dal thread
        confirmed_path = None                   # Percorso finale scelto dall'utente
        existing_path = self.profiles.get(profile_name) # Percorso attuale, se esiste

        # --- Gestione casi: Nessun suggerimento vs Suggerimenti trovati ---
        if not guesses_with_scores:
            # Nessun percorso trovato automaticamente dal thread
            logging.info(f"No paths guessed by search thread for '{profile_name}'.")
            if not existing_path:
                # Nessun suggerimento e nessun profilo esistente -> Chiedi input manuale
                QMessageBox.information(self, self.tr("Percorso Non Trovato"),
                                        self.tr("Impossibile trovare automaticamente un percorso per '{0}'.\n"
                                                "Per favore, inseriscilo manualmente.").format(profile_name))
                # Chiama la funzione helper per chiedere il percorso all'utente
                confirmed_path = self._ask_user_for_path_manually(profile_name, existing_path)
            else:
                # Nessun suggerimento, ma profilo esiste -> Chiedi se mantenere o inserire manualmente
                reply = QMessageBox.question(self, self.tr("Nessun Nuovo Percorso Trovato"),
                                             self.tr("La ricerca automatica non ha trovato nuovi percorsi.\n"
                                                     "Vuoi mantenere il percorso attuale?\n'{0}'")
                                             .format(existing_path),
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    confirmed_path = existing_path # Mantiene quello vecchio
                elif reply == QMessageBox.StandardButton.No:
                    confirmed_path = self._ask_user_for_path_manually(profile_name, existing_path) # Chiede nuovo
                # else: Cancel -> confirmed_path rimane None
        else:
            # Ci sono suggerimenti (guesses_with_scores non è vuota) -> Mostra QInputDialog.getItem
            path_choices = []                       # Lista di stringhe per il dialogo
            display_text_to_original_path = {}    # Mappa per recuperare il percorso vero
            current_selection_index = 0           # Indice preselezionato
            existing_path_found_in_list = False     # Flag

            # Determina se mostrare gli score (modalità sviluppatore)
            show_scores = self.developer_mode_enabled
            logging.debug(f"Preparing QInputDialog items. Show scores: {show_scores}")

            # Crea le stringhe e popola la mappa, trova indice per preselezionare existing_path
            norm_existing = os.path.normpath(existing_path) if existing_path else None
            for i, (p, score) in enumerate(guesses_with_scores):
                norm_p = os.path.normpath(p)
                is_current_marker = self.tr("[ATTUALE]") if norm_existing and norm_p == norm_existing else ""
                score_str = f"(Score: {score})" if show_scores else ""
                display_text = f"{p} {score_str} {is_current_marker}".strip().replace("  ", " ")
                path_choices.append(display_text)
                display_text_to_original_path[display_text] = p
                if norm_existing and norm_p == norm_existing:
                    current_selection_index = i
                    existing_path_found_in_list = True

            if existing_path and not existing_path_found_in_list:
                logging.warning(f"Existing path '{existing_path}' was not found in the suggested paths list.")

            # Aggiungi opzione manuale
            manual_option_str = self.tr("--- Inserisci percorso manualmente ---")
            path_choices.append(manual_option_str)

            # Definisci il testo (label) per il dialogo
            dialog_label_text = self.tr(
                "Sono stati trovati questi percorsi potenziali per '{0}'.\n"
                "Seleziona quello corretto (ordinati per probabilità) o scegli l'inserimento manuale:"
            ).format(profile_name)

            # Mostra il dialogo QInputDialog.getItem
            logging.debug(f"Showing QInputDialog.getItem with {len(path_choices)} choices, pre-selected index: {current_selection_index}")
            chosen_display_str, ok = QInputDialog.getItem(
                self,                                     # parent
                self.tr("Conferma Percorso Salvataggi"), # title
                dialog_label_text,                        # label
                path_choices,                             # items
                current_selection_index,                  # current
                False                                     # editable
            )

            # Gestisci la scelta dell'utente
            if ok and chosen_display_str:
                if chosen_display_str == manual_option_str:
                    # L'utente ha scelto di inserire manualmente
                    confirmed_path = self._ask_user_for_path_manually(profile_name, existing_path)
                else:
                    # L'utente ha scelto un percorso dalla lista
                    confirmed_path = display_text_to_original_path.get(chosen_display_str)
                    if confirmed_path is None:
                        # Errore imprevisto nel recuperare il percorso dalla mappa
                        logging.error(f"Error mapping selected choice '{chosen_display_str}' back to path.")
                        QMessageBox.critical(self, self.tr("Errore Interno"), self.tr("Errore nella selezione del percorso."))
                        confirmed_path = None # Resetta per sicurezza
            # else: L'utente ha premuto Annulla, confirmed_path rimane None

        # --- Fine gestione if/else sui suggerimenti ---

        # 3. Salva il profilo se un percorso valido è stato confermato/inserito
        if confirmed_path:
            # Valida il percorso usando il validator della MainWindow (tramite ProfileCreationManager)
            validator_func = None
            if hasattr(self, 'profile_creation_manager') and self.profile_creation_manager and hasattr(self.profile_creation_manager, 'validate_save_path'):
                 validator_func = self.profile_creation_manager.validate_save_path
            else: # Fallback basico se il manager non c'è
                 logging.warning("ProfileCreationManager validator not found, using basic os.path.isdir validation.")
                 def basic_validator(p, _name): return p if os.path.isdir(p) else None
                 validator_func = basic_validator

            validated_path = validator_func(confirmed_path, profile_name)

            if validated_path:
                # Percorso valido, procedi con salvataggio
                logging.info(f"Saving profile '{profile_name}' with path '{validated_path}' from MainWindow slot.")
                self.profiles[profile_name] = validated_path # Aggiorna dizionario in memoria
                if core_logic.save_profiles(self.profiles): # Salva su file
                    self.status_label.setText(self.tr("Profilo '{0}' configurato.").format(profile_name))
                    self.profile_table_manager.update_profile_table() # Aggiorna tabella nella GUI
                    self.profile_table_manager.select_profile_in_table(profile_name) # Seleziona il profilo appena configurato
                    QMessageBox.information(self, self.tr("Profilo Configurato"), self.tr("Profilo '{0}' salvato con successo.").format(profile_name))
                else:
                    # Errore durante il salvataggio su file
                    QMessageBox.critical(self, self.tr("Errore Salvataggio"), self.tr("Impossibile salvare il file dei profili."))
                    # Rimuovi dal dizionario in memoria per coerenza? O lascia così? Rimuoviamo.
                    if profile_name in self.profiles: del self.profiles[profile_name]
            # else: La funzione validator_func ha già mostrato un messaggio di errore

        else: # confirmed_path è None (l'utente ha annullato o la validazione è fallita)
             self.status_label.setText(self.tr("Configurazione profilo annullata o fallita."))

    # Assicurati che _ask_user_for_path_manually esista o copia/adatta la logica
    # da steam_dialog.py o profile_creation_manager.py
    def _ask_user_for_path_manually(self, profile_name, existing_path):
         # ... (Logica QInputDialog.getText) ...
         # ... (Logica validazione) ...
         # Ritorna path validato o None
         input_path, ok = QInputDialog.getText(self, self.tr("Percorso Manuale"), self.tr("Inserisci il percorso COMPLETO...").format(profile_name), text=existing_path or "")
         if ok and input_path:
              if hasattr(self, 'profile_creation_manager') and self.profile_creation_manager:
                   validated = self.profile_creation_manager.validate_save_path(input_path, profile_name)
                   return validated
              else: return input_path if os.path.isdir(input_path) else None # Fallback
         return None

    
    
    @Slot(str, str)
    def on_steam_profile_configured(self, profile_name, save_path):
        logging.debug(f"Received profile_configured signal: profile '{profile_name}'")
        self.profiles = core_logic.load_profiles()
        self.profile_table_manager.update_profile_table()
        # Seleziona il profilo appena configurato nella tabella
        for row in range(self.profile_table_widget.rowCount()):
             item = self.profile_table_widget.item(row, 0)
             if item and item.data(Qt.ItemDataRole.UserRole) == profile_name:
                  self.profile_table_widget.selectRow(row)
                  break

    @Slot()
    def handle_backup(self):
        profile_name = self.get_selected_profile_name()
        if not profile_name: return

        save_path = self.profiles.get(profile_name)
        if not save_path:
            QMessageBox.critical(self, "Errore", f"Percorso sorgente non trovato per il profilo '{profile_name}'. Verifica profilo.")
            return

        # --- Recupera Impostazioni Necessarie ---
        backup_dir = self.current_settings.get("backup_base_dir")
        max_bk = self.current_settings.get("max_backups")
        max_src_size = self.current_settings.get("max_source_size_mb")
        compression_mode = self.current_settings.get("compression_mode", "standard")
        check_space = self.current_settings.get("check_free_space_enabled", True) # Leggi nuova impostazione
        min_gb_required = config.MIN_FREE_SPACE_GB # Leggi costante da config (o metti 2 qui)

        # Controlli preliminari sulle impostazioni
        if not backup_dir or max_bk is None or max_src_size is None:
            QMessageBox.critical(self, self.tr("Errore Configurazione"), self.tr("Impostazioni necessarie (percorso base, max backup, max dimensione sorgente) non trovate o non valide!"))
            return
        if not os.path.isdir(save_path):
             QMessageBox.critical(self, self.tr("Errore Percorso Sorgente"), self.tr("La cartella sorgente dei salvataggi non esiste o non è valida:\n{0}").format(save_path))
             return

        # --- NUOVO: Controllo Spazio Libero Disco (se abilitato) ---
        if check_space:
            logging.debug(f"Free space check enabled. Threshold: {min_gb_required} GB.")
            min_bytes_required = min_gb_required * 1024 * 1024 * 1024
            try:
                # Assicurati che la cartella base esista o prova a crearla PRIMA del check
                # Questo aiuta shutil.disk_usage se la cartella non esiste ma il drive sì
                os.makedirs(backup_dir, exist_ok=True)

                # Ottieni info sull'uso del disco per il drive che contiene backup_dir
                disk_usage = shutil.disk_usage(backup_dir)
                free_bytes = disk_usage.free
                free_gb = free_bytes / (1024 * 1024 * 1024)
                logging.debug(f"Free space detected on disk for '{backup_dir}': {free_gb:.2f} GB")

                if free_bytes < min_bytes_required:
                    msg = self.tr("Spazio su disco insufficiente per il backup!\n\n"
                                  "Spazio libero: {0:.2f} GB\n"
                                  "Spazio minimo richiesto: {1} GB\n\n"
                                  "Libera spazio sul disco di destinazione ('{2}') o disabilita il controllo nelle impostazioni.").format(free_gb, min_gb_required, backup_dir)
                    QMessageBox.warning(self, self.tr("Spazio Disco Insufficiente"), msg)
                    return # Interrompi l'operazione di backup

            except FileNotFoundError:
                 # Questo non dovrebbe succedere se makedirs funziona, ma per sicurezza
                 msg = self.tr("Errore nel controllo dello spazio: il percorso di backup specificato non sembra essere valido o accessibile:\n{0}").format(backup_dir)
                 QMessageBox.critical(self, self.tr("Errore Percorso Backup"), msg)
                 return
            except Exception as e_space:
                 # Errore generico durante il controllo dello spazio
                 msg = self.tr("Si è verificato un errore durante il controllo dello spazio libero sul disco:\n{0}").format(e_space)
                 QMessageBox.critical(self, self.tr("Errore Controllo Spazio"), msg)
                 logging.error("Error while checking free disk space.", exc_info=True)
                 # Decidiamo se bloccare o continuare con un avviso? Blocchiamo per sicurezza.
                 return
        else:
             logging.debug("Free space check disabled.")
        # --- FINE NUOVO CONTROLLO ---


        # --- Avvio Backup (se tutti i controlli passano) ---
        # Verifica se un altro worker è già attivo
        if hasattr(self, 'worker_thread') and self.worker_thread and self.worker_thread.isRunning():
             QMessageBox.information(self, self.tr("Operazione in Corso"), self.tr("Un backup o ripristino è già in corso. Attendi il completamento."))
             return

        self.status_label.setText(self.tr("Avvio backup per '{0}'...").format(profile_name))
        self.set_controls_enabled(False)

        # Crea e avvia il worker thread per il backup
        self.worker_thread = WorkerThread(
            core_logic.perform_backup, # Funzione da eseguire
            profile_name,              # Argomenti per perform_backup
            save_path,
            backup_dir,
            max_bk,
            max_src_size,
            compression_mode
        )
        self.worker_thread.finished.connect(self.on_operation_finished)
        self.worker_thread.progress.connect(self.status_label.setText)
        self.worker_thread.start()
        logging.debug(f"Started backup thread for profile '{profile_name}'.")

    @Slot()
    def handle_restore(self):
        profile_name = self.get_selected_profile_name()
        if not profile_name: return
        save_path = self.profiles.get(profile_name)
        if not save_path: QMessageBox.critical(self, "Errore", f"Percorso non trovato per il profilo '{profile_name}'."); return
        dialog = RestoreDialog(profile_name, self)
        if dialog.exec():
            archive_to_restore = dialog.get_selected_path()
            if archive_to_restore:
                confirm = QMessageBox.warning(self, "Conferma Ripristino Finale",
                                              f"ATTENZIONE!\nRipristinare '{os.path.basename(archive_to_restore)}' sovrascriverà i file in:\n'{save_path}'\n\nProcedere?",
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                              QMessageBox.StandardButton.No)
                if confirm == QMessageBox.StandardButton.Yes:
                    self.status_label.setText(self.tr("Avvio ripristino per '{0}'...").format(profile_name))
                    self.set_controls_enabled(False)
                    self.worker_thread = WorkerThread(core_logic.perform_restore, profile_name, save_path, archive_to_restore)
                    self.worker_thread.finished.connect(self.on_operation_finished)
                    self.worker_thread.progress.connect(self.status_label.setText)
                    self.worker_thread.start()
                else: self.status_label.setText(self.tr("Ripristino annullato."))
            else: self.status_label.setText(self.tr("Nessun backup selezionato per il ripristino."))
        else: self.status_label.setText(self.tr("Selezione backup annullata."))

    @Slot()
    def handle_manage_backups(self):
        profile_name = self.get_selected_profile_name()
        if not profile_name: QMessageBox.warning(self, "Errore", "Nessun profilo selezionato."); return
        dialog = ManageBackupsDialog(profile_name, self)
        dialog.exec()
        self.profile_table_manager.update_profile_table()

    @Slot(bool, str)
    def on_operation_finished(self, success, message):
        main_message = message.splitlines()[0] if message else self.tr("Operazione terminata senza messaggio.")
        status_text = self.tr("Completato: {0}") if success else self.tr("ERRORE: {0}")
        self.status_label.setText(status_text.format(main_message))
        self.set_controls_enabled(True)
        self.worker_thread = None
        if not success: QMessageBox.critical(self, self.tr("Errore Operazione"), message)
        else: logging.debug("Operation thread worker successful, calling update_profile_table() to update view.")
        self.profile_table_manager.update_profile_table()
                       
    @Slot(str)
    def handle_create_shortcut(self, profile_name):
        """Chiamato quando si clicca il pulsante per creare lo shortcut."""
        
        profile_name = self.get_selected_profile_name() # <-- AGGIUNTO: leggi dalla tabella
        if not profile_name: # <-- AGGIUNTO: controllo se qualcosa è selezionato
             # Non dovrebbe succedere se il pulsante è disabilitato, ma per sicurezza
             logging.warning("handle_create_shortcut called without selected profile.")
             return
        
        logging.info(f"Request to create shortcut for profile: '{profile_name}'")     

        # Chiama la funzione in shortcut_utils passando SOLO il nome del profilo
        success, message = shortcut_utils.create_backup_shortcut(
            profile_name=profile_name
        )

        if success:
            # Mostra il messaggio restituito (che per ora è un avviso)
            QMessageBox.information(self, self.tr("Creazione Collegamento"), message)
        else:
            QMessageBox.warning(self, self.tr("Errore Creazione Collegamento"), message)

    # --- SLOT PER ATTIVARE FINESTRA DA SECONDA ISTANZA ---
    @Slot()
    def activateExistingInstance(self):
        logging.info("Received signal to activate existing instance.")
        # Assicurati che la finestra sia visibile e portata in primo piano
        self.showNormal() # Mostra se era minimizzata
        self.raise_()     # Porta sopra le altre finestre dell'app (se ci fossero dialoghi)
        self.activateWindow() # Attiva la finestra nel sistema operativo
        
    @Slot()
    def handle_developer_mode_toggle(self):
        """Attiva/Disattiva la modalità sviluppatore, aggiorna l'icona e il livello di log."""
        logging.debug(">>> Developer Mode Toggle TIMER TIMEOUT triggered.")
        self.developer_mode_enabled = not self.developer_mode_enabled
        root_logger = logging.getLogger() # Ottieni istanza del root logger

        if self.developer_mode_enabled:
            new_level = logging.DEBUG # Attiva DEBUG
            # Usa getLevelName per un log più leggibile
            logging.info(f"Modalità Sviluppatore ATTIVATA (Log {logging.getLevelName(new_level)} abilitati).")
            # Cambia icona
            if self.log_icon_dev:
                self.toggle_log_button.setIcon(self.log_icon_dev)
            else:
                self.toggle_log_button.setText("D")
        else:
            new_level = logging.INFO # Disattiva DEBUG (torna a INFO)
            # Usa getLevelName per un log più leggibile
            logging.info(f"Modalità Sviluppatore DISATTIVATA (Log {logging.getLevelName(new_level)} disabilitati).")
            # Cambia icona
            if self.log_icon_normal:
                self.toggle_log_button.setIcon(self.log_icon_normal)
            else:
                self.toggle_log_button.setText("L")

        # *** NUOVO: Imposta il livello ANCHE sul root logger ***
        logging.debug(f"   - Setting root logger level to {logging.getLevelName(new_level)}")
        root_logger.setLevel(new_level)
        # *** FINE NUOVO ***

        # Applica il nuovo livello a ENTRAMBI gli handler (come prima)
        if self.console_log_handler:
            logging.debug(f"   - Setting console_handler level to {logging.getLevelName(new_level)}")
            self.console_log_handler.setLevel(new_level)
        if self.qt_log_handler:
            logging.debug(f"   - Setting qt_log_handler level to {logging.getLevelName(new_level)}")
            self.qt_log_handler.setLevel(new_level)

                
    @Slot()
    def handle_log_button_pressed(self):
        """Avvia il timer quando il pulsante log viene premuto."""
        logging.debug(f"Entering handle_log_button_pressed. Timer is: {self.log_button_press_timer}")
        if not self.log_button_press_timer.isActive():
            logging.debug(">>> Log button PRESSED. Starting timer...") # Log
            self.log_button_press_timer.start()
        else:
            logging.debug(">>> Log button PRESSED. Timer already active?") # Log

    @Slot()
    def handle_log_button_released(self):
        """Gestisce il rilascio del pulsante log."""
        logging.debug(">>> Log button RELEASED.") # Log
        if self.log_button_press_timer.isActive():
            # Timer ancora attivo = Click Breve
            logging.debug("   - Timer was active (Short press). Stopping timer and toggling log panel.") # Log
            self.log_button_press_timer.stop()
            self.handle_toggle_log() # Esegui l'azione originale
        else:
            # Timer NON attivo = Click Lungo (l'azione è gestita dal timeout)
            logging.debug("   - Timer was NOT active (Long press detected). Doing nothing on release.") # Log
            # Non fare nulla qui                

# --- Avvio Applicazione GUI ---
if __name__ == "__main__":
    # --- Configurazione Logging ---
    log_level = logging.INFO
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    log_datefmt = '%H:%M:%S'
    log_formatter = logging.Formatter(log_format, log_datefmt)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    qt_log_handler = QtLogHandler()
    qt_log_handler.setFormatter(log_formatter)
    qt_log_handler.setLevel(logging.INFO)
    root_logger.addHandler(qt_log_handler)
    logging.info("Logging configured.")

    # --- Import necessari per argparse e runner ---
    import argparse
    import backup_runner # Importa per la modalità backup

    # --- Parsing Argomenti ---
    parser = argparse.ArgumentParser(description='SaveState GUI or Backup Runner.')
    parser.add_argument("--backup", help="Nome del profilo per cui eseguire un backup silenzioso.")
    args = parser.parse_args() # Gestisci eccezioni se necessario

    # --- Controllo Modalità Esecuzione ---
    if args.backup:
        # === Modalità Backup Silenzioso ===
        profile_to_backup = args.backup
        logging.info(f"Detected argument --backup '{profile_to_backup}'. Starting silent backup...")
        # Esegui direttamente la logica di backup (che ora include la notifica)
        backup_success = backup_runner.run_silent_backup(profile_to_backup)
        logging.info(f"Silent backup completed successfully: {backup_success}")
        sys.exit(0 if backup_success else 1) # Esci subito dopo il backup

    else:
        # === Modalità GUI Normale ===
        logging.info("No --backup argument, starting GUI mode. Checking single instance...")

        # --- Logica Single Instance ---
        shared_memory = QSharedMemory(SHARED_MEM_KEY)
        local_socket = None
        local_server = None
        app_should_run = True # Flag per decidere se avviare la GUI

        # Tenta di creare memoria condivisa. Se fallisce perché esiste già...
        if not shared_memory.create(1, QSharedMemory.AccessMode.ReadOnly):
            if shared_memory.error() == QSharedMemory.SharedMemoryError.AlreadyExists:
                logging.warning("Another instance of SaveState is already running. Attempting to activate it.")
                app_should_run = False # Non avviare questa istanza GUI

                # Connettiti all'altra istanza
                local_socket = QLocalSocket()
                local_socket.connectToServer(LOCAL_SERVER_NAME)
                if local_socket.waitForConnected(500):
                    logging.info("Connected to existing instance. Sending 'show' signal.")
                    local_socket.write(b'show\n')
                    local_socket.waitForBytesWritten(500)
                    local_socket.disconnectFromServer()
                    local_socket.close()
                    logging.info("Signal sent. Exiting new instance.")
                    sys.exit(0) # Esci con successo (l'altra è stata attivata)
                else:
                    logging.error(f"Unable to connect to existing instance: {local_socket.errorString()}")
                    # Qui potremmo decidere di uscire o provare ad avviarsi comunque
                    # se non riusciamo a comunicare, ma uscire è più sicuro.
                    # Rilascia la memoria condivisa che abbiamo solo "attaccato" implicitamente col check
                    if shared_memory.isAttached():
                        shared_memory.detach()
                    sys.exit(1) # Esci con errore
            else:
                # Altro errore con shared memory
                logging.error(f"QSharedMemory error (create): {shared_memory.errorString()}")
                app_should_run = False # Non avviare la GUI
                sys.exit(1) # Esci con errore

        # Se app_should_run è ancora True, siamo la prima istanza GUI
        if app_should_run:
            logging.info("First GUI instance. Creating local server and starting application...")

            # Crea server locale
            local_server = QLocalServer()
            if QLocalServer.removeServer(LOCAL_SERVER_NAME):
                logging.warning(f"Removed orphaned local server '{LOCAL_SERVER_NAME}'")

            if not local_server.listen(LOCAL_SERVER_NAME):
                logging.error(f"Unable to start local server '{LOCAL_SERVER_NAME}': {local_server.errorString()}")
                if shared_memory.isAttached(): shared_memory.detach() # Cleanup
                sys.exit(1) # Esci se il server non parte
            else:
                logging.info(f"Local server listening on: {local_server.fullServerName()}")

                try:
                    app = QApplication(sys.argv)

                    # Funzione di cleanup all'uscita
                    def cleanup_instance_lock():
                        logging.debug("Executing instance cleanup (detach shared memory, close server)...")
                        if local_server: local_server.close(); logging.debug("Local server closed.")
                        if shared_memory.isAttached(): shared_memory.detach(); logging.debug("Shared memory detached.")
                    app.aboutToQuit.connect(cleanup_instance_lock)

                except ImportError:
                     logging.critical("Library 'PySide6' not found!"); cleanup_instance_lock(); sys.exit(1)
                except Exception as e:
                     logging.critical(f"QApplication error: {e}", exc_info=True); cleanup_instance_lock(); sys.exit(1)

                # --- Procedi con il resto dell'inizializzazione GUI ---
                try:
                    # Caricamento traduttore
                    logging.info("Starting translator loading...")
                    current_settings, is_first_launch = settings_manager.load_settings()
                    selected_language = current_settings.get("language", "en")
                    if selected_language == "en":
                        # --- Logica caricamento/installazione per 'en' ---
                        qm_filename = f"SaveState_{selected_language}.qm"
                        qm_file_path = resource_path(qm_filename)
                        logging.info(f"Attempting to load English translator from: {qm_file_path}")
                        if os.path.exists(qm_file_path):
                            if ENGLISH_TRANSLATOR.load(qm_file_path):
                                if QCoreApplication.installTranslator(ENGLISH_TRANSLATOR):
                                    CURRENT_TRANSLATOR = ENGLISH_TRANSLATOR
                                    logging.info("English translator installed.")
                                else: logging.error("Installation of 'en' translator failed.")
                            else: logging.warning(f"Loading QM file '{qm_file_path}' failed.")
                        else: logging.error(f"Translator file '{qm_file_path}' NOT FOUND.")
                        # --- Fine logica 'en' ---
                    else:
                        logging.info("Non-English language, no active translator.")
                        if CURRENT_TRANSLATOR: QCoreApplication.removeTranslator(CURRENT_TRANSLATOR)
                        CURRENT_TRANSLATOR = None

                    # Gestione primo avvio
                    if is_first_launch:
                        logging.info("First launch detected, showing settings dialog.")
                        # Passa None come parent se app non è ancora completamente inizializzata?
                        # Meglio creare window prima e passargli window come parent
                        # Spostiamo la creazione della finestra qui:
                        window = MainWindow(current_settings, console_handler, qt_log_handler) # Crea PRIMA del dialogo
                        settings_dialog = SettingsDialog(current_settings, window) # Passa window come parent
                        if settings_dialog.exec() == QDialog.Accepted:
                            current_settings = settings_dialog.get_settings()
                            if not settings_manager.save_settings(current_settings):
                                QMessageBox.critical(window, "Errore Salvataggio Impostazioni", "Impossibile salvare le impostazioni...")
                            else:
                                # Se le impostazioni sono state cambiate (es. lingua), riapplicale
                                window.current_settings = current_settings # Aggiorna le impostazioni della finestra
                                window.apply_translator(current_settings.get("language", "en")) # Applica traduttore
                                window.update_theme() # Applica tema
                                window.retranslateUi() # Forza ri-traduzione
                                window.update_profile_table() # Aggiorna tabella

                            logging.info("Initial settings configured.")
                        else:
                            reply = QMessageBox.question(window, "Impostazioni Predefinite",
                                                        "Nessuna impostazione salvata, usare quelle predefinite?",
                                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                                        QMessageBox.StandardButton.Yes)
                            if reply != QMessageBox.StandardButton.Yes:
                                logging.info("Exit requested by user on first launch."); sys.exit(0)
                            else: # Salva i default se l'utente accetta
                                if not settings_manager.save_settings(current_settings):
                                     QMessageBox.critical(window, "Errore Salvataggio", "Impossibile salvare le impostazioni predefinite.")
                                # Continua comunque con i default caricati

                    else: # Non è il primo avvio, crea la finestra normalmente
                        window = MainWindow(current_settings, console_handler, qt_log_handler)

                    # Connetti server allo slot della finestra
                    if local_server:
                        local_server.newConnection.connect(window.activateExistingInstance)

                    window.show()
                    exit_code = app.exec() # Avvia loop eventi GUI
                    logging.info(f"GUI application terminated with code: {exit_code}")
                    sys.exit(exit_code) # Esci con il codice dell'applicazione Qt

                except Exception as e_gui_init: # Cattura errori durante l'init della GUI
                    logging.critical(f"Fatal error during GUI initialization: {e_gui_init}", exc_info=True)
                    # Prova a mostrare un messaggio di errore base se possibile
                    try:
                         QMessageBox.critical(None, "Errore Avvio", f"Errore fatale durante l'avvio:\n{e_gui_init}")
                    except: pass # Ignora errori nel mostrare l'errore stesso
                    cleanup_instance_lock() # Prova a pulire
                    sys.exit(1)