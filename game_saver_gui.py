# game_saver_gui.py
# -*- coding: utf-8 -*-
import sys
import os
import shutil
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStatusBar, QMessageBox, QDialog,
    QProgressBar, QGroupBox, QInputDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QStyle, QDockWidget, QPlainTextEdit
)
from PySide6.QtCore import ( Slot, Qt, QUrl, QSize, QTranslator, QCoreApplication, 
     QEvent, QLocale, QSharedMemory, QSystemSemaphore, QLockFile
)
from PySide6.QtGui import QIcon, QDesktopServices, QPalette, QColor
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from dialogs.settings_dialog import SettingsDialog
from dialogs.restore_dialog import RestoreDialog
from dialogs.manage_backups_dialog import ManageBackupsDialog
from dialogs.steam_dialog import SteamDialog
from dialogs.minecraft_dialog import MinecraftWorldsDialog
from gui_utils import WorkerThread, DetectionWorkerThread, QtLogHandler, resource_path

# Importa logica e configurazione
import core_logic 
import settings_manager 
import config           
import minecraft_utils
import winshell         # Per leggere i collegamenti .lnk
import string           # Necessario per il controllo root drive
import logging
import shortcut_utils # Il nostro nuovo modulo

# --- NUOVE COSTANTI GLOBALI PER IDENTIFICARE L'ISTANZA ---
# Usa stringhe univoche per la tua applicazione
APP_GUID = "SaveState_App_Unique_GUID_6f459a83-4f6a-4e3e-8c1e-7a4d5e3d2b1a" 
SHARED_MEM_KEY = f"{APP_GUID}_SharedMem"
LOCAL_SERVER_NAME = f"{APP_GUID}_LocalServer"
# --- FINE COSTANTI ---

ENGLISH_TRANSLATOR = QTranslator() # Crea l'istanza QUI
CURRENT_TRANSLATOR = None # Questa traccia solo quale è ATTIVO (o None)


CURRENT_TRANSLATOR = None 

# --- Dialogo Gestione Steam ---

# --- Finestra Principale ---
class MainWindow(QMainWindow):
    def __init__(self, initial_settings, log_handler):
        super().__init__()
        self.load_theme_icons()
        self.setGeometry(100, 100, 720, 600)
        self.setAcceptDrops(True)
        self.current_settings = initial_settings
        self.profiles = core_logic.load_profiles()
        
        # Ottieni lo stile per le icone standard
        style = QApplication.instance().style()
        icon_size = QSize(16, 16) # Dimensione comune icone

        # --- Widget ---
        self.profile_table_widget = QTableWidget()
        self.profile_table_widget.setObjectName("ProfileTable")
        self.profile_table_widget.setColumnCount(2)
        self.profile_table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.profile_table_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.profile_table_widget.verticalHeader().setVisible(False)
        self.profile_table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
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
        
        icon_path = resource_path("icons/terminal.png") # Assicurati che il file sia qui
        if os.path.exists(icon_path):
            log_icon = QIcon(icon_path)
            self.toggle_log_button.setIcon(log_icon)
        else:
            logging.warning(f"File icona log non trovato: {icon_path}")
            self.toggle_log_button.setText("L") # Fallback a testo se icona manca
        button_size = QSize(24, 24)
        self.toggle_log_button.setFixedSize(button_size)
        self.toggle_log_button.setToolTip(self.tr("Mostra Log"))

        
        header = self.profile_table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) # Col 0 (Nome Profilo) = Stretch
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Col 1 (Info Backup) = Adatta al contenuto
        icon_path = resource_path("icons/settings.png") # Percorso relativo dell'icona
        if os.path.exists(icon_path): # Controlla se il file esiste
            settings_icon = QIcon(icon_path)
            self.settings_button.setIcon(settings_icon)
            self.settings_button.setIconSize(QSize(16, 16)) # Imposta dimensione se necessario
        else:
            logging.warning(f"File icona impostazioni non trovato: {icon_path}")
            
        # --- PULSANTE TEMA ---
        self.theme_button = QPushButton() # Senza testo
        self.theme_button.setFlat(True)   # Aspetto meno invadente
        self.theme_button.setFixedSize(QSize(24, 24)) # Adatta dimensione se serve
        self.theme_button.setObjectName("ThemeToggleButton")
        # Icona iniziale e tooltip verranno impostati da update_theme()
     
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

        self.update_profile_table()

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
        if log_handler:
            log_handler.log_signal.connect(self.log_output.appendHtml)
            # Aggiungi il gestore al root logger se non è già presente
            root_logger = logging.getLogger()
            if log_handler not in root_logger.handlers:
                root_logger.addHandler(log_handler)
        # --- FINE Connessione Segnale ---
        
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # Connessioni
        self.backup_button.clicked.connect(self.handle_backup)
        self.restore_button.clicked.connect(self.handle_restore)
        self.profile_table_widget.itemSelectionChanged.connect(self.update_action_button_states)
        self.new_profile_button.clicked.connect(self.handle_new_profile)
        self.delete_profile_button.clicked.connect(self.handle_delete_profile)
        self.steam_button.clicked.connect(self.handle_steam)
        self.manage_backups_button.clicked.connect(self.handle_manage_backups)
        self.settings_button.clicked.connect(self.handle_settings)
        self.open_backup_dir_button.clicked.connect(self.handle_open_backup_folder)
        self.theme_button.clicked.connect(self.handle_theme_toggle)
        self.toggle_log_button.clicked.connect(self.handle_toggle_log)
        self.minecraft_button.clicked.connect(self.handle_minecraft_button)
        self.create_shortcut_button.clicked.connect(self.handle_create_shortcut)

        # Stato Iniziale e Tema
        self.update_action_button_states()
        self.worker_thread = None
        self.update_theme()
        self.retranslateUi()
        self.setWindowIcon(QIcon(resource_path("icon.png"))) # Icona finestra principale
    
    def retranslateUi(self):
        """Aggiorna il testo di tutti i widget traducibili."""
        logging.debug("MainWindow.retranslateUi() chiamato") # Utile per debug
        self.setWindowTitle("SaveState")
        self.profile_table_widget.setHorizontalHeaderLabels([self.tr("Profilo"), self.tr("Info Backup")]) # <-- Solo 2 etichette
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
            
        # Aggiorna tooltip pulsante tema
        current_theme = self.current_settings.get('theme', 'dark')
        if current_theme == 'light':
            self.theme_button.setToolTip(self.tr("Passa al tema scuro"))
        else:
            self.theme_button.setToolTip(self.tr("Passa al tema chiaro"))
            
            logging.debug("Aggiornamento tabella profili a seguito di retranslateUi")
            self.update_profile_table() # Così la tabella usa le nuove traduzioni subito

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


    # --- NUOVO SLOT PER PULSANTE MINECRAFT ---
    @Slot()
    def handle_minecraft_button(self):
        """
        Trova i mondi Minecraft, mostra un dialogo per la selezione
        e crea un nuovo profilo per il mondo scelto.
        """
        logging.info("Avvio ricerca mondi Minecraft...")
        self.status_label.setText(self.tr("Ricerca cartella salvataggi Minecraft..."))
        QApplication.processEvents() # Aggiorna GUI per mostrare messaggio

        # 1. Trova cartella saves usando il modulo minecraft_utils
        try:
             # Usiamo try-except qui nel caso minecraft_utils dia problemi
             saves_folder = minecraft_utils.find_minecraft_saves_folder()
        except Exception as e_find:
             logging.error(f"Unexpected error during find_minecraft_saves_folder: {e_find}", exc_info=True)
             QMessageBox.critical(self, self.tr("Errore Minecraft"), self.tr("Errore imprevisto durante la ricerca della cartella Minecraft."))
             self.status_label.setText(self.tr("Errore ricerca Minecraft."))
             return

        if not saves_folder:
            logging.warning("Cartella salvataggi Minecraft non trovata.")
            QMessageBox.warning(self,
                                self.tr("Cartella Non Trovata"),
                                self.tr("Impossibile trovare la cartella dei salvataggi standard di Minecraft (.minecraft/saves).\nAssicurati che Minecraft Java Edition sia installato."))
            self.status_label.setText(self.tr("Cartella Minecraft non trovata."))
            return

        # 2. Lista i mondi usando il modulo minecraft_utils
        self.status_label.setText(self.tr("Lettura mondi Minecraft..."))
        QApplication.processEvents()
        try:
            worlds_data = minecraft_utils.list_minecraft_worlds(saves_folder)
        except Exception as e_list:
            logging.error(f"Unexpected error during list_minecraft_worlds: {e_list}", exc_info=True)
            QMessageBox.critical(self, self.tr("Errore Minecraft"), self.tr("Errore imprevisto durante la lettura dei mondi Minecraft."))
            self.status_label.setText(self.tr("Errore lettura mondi Minecraft."))
            return

        if not worlds_data:
            logging.warning("Nessun mondo trovato in: %s", saves_folder)
            QMessageBox.information(self,
                                   self.tr("Nessun Mondo Trovato"),
                                   self.tr("Nessun mondo trovato nella cartella:\n{0}").format(saves_folder))
            self.status_label.setText(self.tr("Nessun mondo Minecraft trovato."))
            return

        # 3. Mostra Dialogo Selezione (dal modulo dialogs.minecraft_dialog)
        try:
            dialog = MinecraftWorldsDialog(worlds_data, self)
        except Exception as e_dialog_create:
             logging.error(f"Creation error MinecraftWorldsDialog: {e_dialog_create}", exc_info=True)
             QMessageBox.critical(self, self.tr("Errore Interfaccia"), self.tr("Impossibile creare la finestra di selezione dei mondi."))
             return

        self.status_label.setText(self.tr("Pronto.")) # Resetta status mentre dialogo è aperto

        if dialog.exec() == QDialog.Accepted:
            selected_world = dialog.get_selected_world_info()
            if selected_world:
                # Recupera nome e percorso
                # Usiamo 'world_name' (potrebbe venire da NBT) come nome profilo
                profile_name = selected_world.get('world_name', selected_world.get('folder_name')) # Fallback a nome cartella
                world_path = selected_world.get('full_path')

                # Controlla se il nome è valido (non vuoto)
                if not profile_name:
                     logging.error("Name of selected world invalid or missing.")
                     QMessageBox.critical(self, self.tr("Errore Interno"), self.tr("Nome del mondo selezionato non valido."))
                     return
                # Controlla se il percorso è valido
                if not world_path or not os.path.isdir(world_path):
                     logging.error(f"world path '{world_path}' invalid for profile '{profile_name}'.")
                     QMessageBox.critical(self, self.tr("Errore Percorso"), self.tr("Il percorso del mondo selezionato ('{0}') non è valido.").format(world_path))
                     return

                logging.info(f"Mondo Minecraft selezionato: '{profile_name}' - Percorso: {world_path}")

                # 4. Controlla se profilo esiste già
                if profile_name in self.profiles:
                     QMessageBox.warning(self,
                                         self.tr("Profilo Esistente"),
                                         self.tr("Un profilo chiamato '{0}' esiste già.\nScegli un altro mondo o rinomina il profilo esistente.").format(profile_name))
                     return

                # 5. Crea e Salva Nuovo Profilo
                self.profiles[profile_name] = world_path # Usa percorso completo mondo
                if core_logic.save_profiles(self.profiles):
                    logging.info(f"Profilo Minecraft '{profile_name}' creato.")
                    self.update_profile_table()
                    self.select_profile_in_table(profile_name) # Seleziona il nuovo profilo
                    QMessageBox.information(self,
                                            self.tr("Profilo Creato"),
                                            self.tr("Profilo '{0}' creato con successo per il mondo Minecraft.").format(profile_name))
                    self.status_label.setText(self.tr("Profilo '{0}' creato.").format(profile_name))
                else:
                    # Errore salvataggio
                    QMessageBox.critical(self, self.tr("Errore"), self.tr("Impossibile salvare il file dei profili dopo aver aggiunto '{0}'.").format(profile_name))
                    if profile_name in self.profiles: del self.profiles[profile_name] # Rimuovi da memoria se salvataggio fallisce

            else:
                # Dialogo accettato ma nessun mondo restituito?
                logging.warning("Dialogo Minecraft accettato ma nessun dato mondo selezionato restituito.")
                self.status_label.setText(self.tr("Selezione mondo annullata o fallita."))
        else:
            # Dialogo annullato dall'utente
            logging.info("Selezione mondo Minecraft annullata dall'utente.")
            self.status_label.setText(self.tr("Selezione mondo annullata."))
    # --- FINE SLOT ---
    
    # --- Gestione Drag and Drop ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
             urls = event.mimeData().urls()
             if urls and urls[0].toLocalFile().lower().endswith('.lnk'):
                  event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
             urls = event.mimeData().urls()
             if urls and urls[0].toLocalFile().lower().endswith('.lnk'):
                  event.acceptProposedAction()

    def dropEvent(self, event):
        """Chiamato quando l'utente rilascia l'oggetto (.lnk). Avvia la ricerca in background."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            urls = event.mimeData().urls()
            if urls:
                file_path = urls[0].toLocalFile()

                if file_path.lower().endswith('.lnk'):
                    logging.debug(f"Rilasciato collegamento: {file_path}")

                    # --- Lettura .lnk (Veloce, rimane qui) ---
                    shortcut = None
                    game_install_dir = None
                    try:
                        # Importa winshell qui dentro se non è globale o per sicurezza
                        # import winshell
                        shortcut = winshell.shortcut(file_path)
                        target_path = shortcut.path
                        working_dir = shortcut.working_directory
                        # Usa working_dir se esiste E è una cartella valida
                        if working_dir and os.path.isdir(working_dir):
                            game_install_dir = os.path.normpath(working_dir)
                        # Altrimenti, usa la cartella del target se target esiste ED è un file
                        elif target_path and os.path.isfile(target_path):
                             game_install_dir = os.path.normpath(os.path.dirname(target_path))
                        # Altrimenti non abbiamo una cartella valida
                        else:
                            logging.warning(f"Impossibile determinare la cartella del gioco dal collegamento: {file_path}")
                            # game_install_dir rimane None
                        logging.debug(f"Cartella gioco rilevata (o presunta) dal collegamento: {game_install_dir}")

                    except ImportError:
                         logging.error("The 'winshell' library is not installed. Unable to read .lnk files.")
                         QMessageBox.critical(self, "Errore Dipendenza", "La libreria 'winshell' necessaria per leggere i collegamenti non è installata.\nImpossibile creare profilo da .lnk.")
                         return
                    except Exception as e_lnk:
                        logging.error(f"Error while reading the .lnk link: {e_lnk}", exc_info=True)
                        QMessageBox.critical(self, self.tr("Errore Collegamento"), self.tr("Impossibile leggere il file .lnk:\n{0}").format(e_lnk))
                        return # Esce se non possiamo leggere il link

                    base_name = os.path.basename(file_path)
                    profile_name, _ = os.path.splitext(base_name)
                    # Pulisci il nome da caratteri comuni TM, R
                    profile_name = profile_name.replace('™', '').replace('®', '').strip()
                    logging.debug(f"Nome profilo proposto dal nome del collegamento: {profile_name}")

                    # --- Controllo Esistenza Profilo (Veloce, rimane qui) ---
                    # Assumendo che self.profiles sia il dizionario caricato
                    if profile_name in self.profiles:
                        QMessageBox.warning(self, self.tr("Profilo Esistente"), self.tr("Profilo '{0}' esiste già.").format(profile_name))
                        return # Esce se profilo esiste

                    # --- AVVIO THREAD DI RICERCA ---
                    # Verifica se un altro thread di ricerca è già attivo
                    # Assumiamo di salvare il riferimento al thread in self.detection_thread
                    if hasattr(self, 'detection_thread') and self.detection_thread and self.detection_thread.isRunning():
                        QMessageBox.information(self, self.tr("Operazione in Corso"), self.tr("Un'altra ricerca di percorso è già in corso. Attendi."))
                        return

                    # Mostra feedback e disabilita controlli
                    self.set_controls_enabled(False) # Disabilita quasi tutto
                    self.status_label.setText(self.tr("Ricerca percorso per '{0}' in corso...").format(profile_name))
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor) # Cursore di attesa

                    # Crea e avvia il thread di rilevamento
                    # Passiamo una COPIA delle impostazioni per sicurezza
                    # Assicurati che DetectionWorkerThread sia importato da gui_utils
                    self.detection_thread = DetectionWorkerThread(
                        game_install_dir=game_install_dir, # Può essere None se non trovato
                        profile_name_suggestion=profile_name,
                        current_settings=self.current_settings.copy()
                    )

                    # Connetti i segnali agli slot (devono esistere nella classe MainWindow)
                    self.detection_thread.progress.connect(self.on_detection_progress)
                    self.detection_thread.finished.connect(self.on_detection_finished)

                    # Avvia il thread
                    self.detection_thread.start()
                    logging.debug("Avviato il thread di rilevamento percorso.")
                    # --- FINE AVVIO THREAD ---

                    # !!! NOTA BENE: Tutto il codice che prima era qui sotto
                    # (la scansione INI, l'euristica, la richiesta di input,
                    # il salvataggio del profilo) NON deve più essere qui.
                    # Viene gestito da on_detection_finished !!!

                else: # File non .lnk
                    QMessageBox.information(self, self.tr("File Ignorato"), self.tr("Per favore, trascina un collegamento (.lnk) a un gioco."))
            # else: Dati non URL ignorati

    # --- METODO HELPER PER VALIDAZIONE PERCORSO ---
    def validate_save_path(self, path_to_check, context_profile_name="profilo"):
        """
        Controlla se un percorso è valido come cartella di salvataggio.
        Verifica che non sia vuoto, che non sia una radice di drive,
        e che sia una cartella esistente.
        Mostra un QMessageBox in caso di errore.
        Restituisce il percorso normalizzato se valido, altrimenti None.
        """
        if not path_to_check:
            QMessageBox.warning(self, "Errore Percorso", "Il percorso non può essere vuoto.")
            return None

        norm_path = os.path.normpath(path_to_check)

        # --- Controllo Percorso Radice (Metodo Esplicito) ---
        try:
            available_drives = ['%s:' % d for d in string.ascii_uppercase if os.path.exists('%s:' % d)]
            known_roots = []
            for d in available_drives:
                known_roots.append(os.path.normpath(d))
                known_roots.append(os.path.normpath(d + os.sep))
            known_roots = list(set(known_roots))

            logging.debug(f"Validazione percorso: Path='{norm_path}', KnownRoots='{known_roots}', IsRoot={norm_path in known_roots}")
            if norm_path in known_roots:
                 QMessageBox.warning(self, "Errore Percorso",
                                     f"Non è possibile usare una radice del drive ('{norm_path}') come cartella dei salvataggi per '{context_profile_name}'.\n"
                                     "Per favore, scegli o crea una sottocartella specifica.")
                 return None # Percorso radice non valido
        except Exception:
             logging.warning("Controllo percorso radice fallito durante validazione.", exc_info=True)
             # Non blocchiamo per questo errore raro, continuiamo con isdir
             pass

        # --- Controllo Esistenza e Tipo (Directory) ---
        if not os.path.isdir(norm_path):
            QMessageBox.warning(self, "Errore Percorso",
                                 f"Il percorso specificato non esiste o non è una cartella valida:\n'{norm_path}'")
            return None # Non è una directory valida

        # Se tutti i controlli passano, restituisce il percorso normalizzato
        logging.debug(f"Validazione percorso: '{norm_path}' considerato valido.")
        return norm_path
    # --- FINE NUOVO METODO HELPER ---

    def update_profile_table(self):
        """Aggiorna QTableWidget con i profili e le info sui backup."""
        selected_profile_name = self.get_selected_profile_name()
        self.profile_table_widget.setRowCount(0)
        sorted_profiles = sorted(self.profiles.keys())

        if not sorted_profiles:
            self.profile_table_widget.setRowCount(1)
            item_nome = QTableWidgetItem("Nessun profilo creato.")
            item_info = QTableWidgetItem("")
            item_nome.setData(Qt.ItemDataRole.UserRole, None)
            item_nome.setFlags(item_nome.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item_info.setFlags(item_info.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.profile_table_widget.setItem(0, 0, item_nome)
            self.profile_table_widget.setItem(0, 1, item_info)
            self.profile_table_widget.setEnabled(False)
        else:
            self.profile_table_widget.setEnabled(True)
            row_to_select = -1
            for row_index, profile_name in enumerate(sorted_profiles):
                count, last_backup_dt = core_logic.get_profile_backup_summary(profile_name)
                info_str = "" # Inizializza stringa vuota

                if count > 0:
                    date_str = "N/D" # Valore predefinito se non c'è data
                    if last_backup_dt:
                        try:
                            # --- NUOVA LOGICA FORMATTAZIONE DATA ---
                            lang_code = self.current_settings.get("language", "en") # Prendi lingua corrente
                            # Crea oggetto QLocale per la lingua giusta
                            if lang_code == "en":
                                locale = QLocale(QLocale.Language.English)
                            else:
                                locale = QLocale(QLocale.Language.Italian)

                            # Formatta la data usando QLocale (mese abbreviato + giorno)
                            # Esempio: "Apr 11" o "Giu 10"
                            date_str = locale.toString(last_backup_dt, "MMM d")
                            # Se preferisci il mese completo (es. "April 11"), usa:
                            # date_str = locale.toString(last_backup_dt, "MMMM d")
                            # --- FINE NUOVA LOGICA ---
                        except Exception as e:
                            logging.error(f"Error formatting last backup date for {profile_name}", exc_info=True)
                            date_str = "???" # Metti un placeholder diverso in caso di errore

                    # --- NUOVA LOGICA TRADUZIONE ETICHETTE ---
                    # Traduci le etichette che servono
                    backup_label_singular = ("Backup")
                    backup_label_plural = ("Backups")
                    last_label = self.tr("Ultimo")

                    # Scegli singolare o plurale
                    backup_label = backup_label_singular if count == 1 else backup_label_plural

                    # Componi la stringa finale usando le etichette tradotte
                    info_str = f"{backup_label}: {count} | {last_label}: {date_str}"
                    # --- FINE NUOVA LOGICA ---


                name_item = QTableWidgetItem(profile_name)
                name_item.setData(Qt.ItemDataRole.UserRole, profile_name)
                info_item = QTableWidgetItem(info_str)
                info_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                self.profile_table_widget.insertRow(row_index)
                self.profile_table_widget.setItem(row_index, 0, name_item)
                self.profile_table_widget.setItem(row_index, 1, info_item)
                
                if profile_name == selected_profile_name:
                     row_to_select = row_index

            if row_to_select != -1:
                  self.profile_table_widget.selectRow(row_to_select)

        self.update_action_button_states()

    def get_selected_profile_name(self):
        selected_rows = self.profile_table_widget.selectionModel().selectedRows()
        if selected_rows:
            first_row_index = selected_rows[0].row()
            name_item = self.profile_table_widget.item(first_row_index, 0)
            if name_item: return name_item.data(Qt.ItemDataRole.UserRole)
        return None

    def update_action_button_states(self):
        selected = self.get_selected_profile_name() is not None
        self.backup_button.setEnabled(selected)
        self.restore_button.setEnabled(selected)
        self.delete_profile_button.setEnabled(selected)
        self.manage_backups_button.setEnabled(selected)
        self.create_shortcut_button.setEnabled(selected)

    def set_controls_enabled(self, enabled):
        self.profile_table_widget.setEnabled(enabled)
        selected_profile_exists = self.get_selected_profile_name() is not None
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
            qm_filename = f"game_saver_{lang_code}.qm"
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
    def handle_new_profile(self):
        logging.debug("handle_new_profile - START")
        profile_name, ok = QInputDialog.getText(self, "Nuovo Profilo", "Inserisci un nome per il nuovo profilo:")
        logging.debug(f"handle_new_profile - Name entered: '{profile_name}', ok={ok}")

        if ok and profile_name:
            if profile_name in self.profiles:
                logging.debug(f"handle_new_profile - Profile '{profile_name}' already exists.")
                QMessageBox.warning(self, "Errore", f"Un profilo chiamato '{profile_name}' esiste già.")
                return

            logging.debug(f"handle_new_profile - Requesting path for '{profile_name}'...")
            path_prompt = f"Ora inserisci il percorso COMPLETO per i salvataggi del profilo:\n'{profile_name}'"
            input_path, ok2 = QInputDialog.getText(self, "Percorso Salvataggi", path_prompt)
            logging.debug(f"handle_new_profile - Path entered: '{input_path}', ok2={ok2}")

            if ok2:
                # --- USA LA NUOVA FUNZIONE DI VALIDAZIONE ---
                validated_path = self.validate_save_path(input_path, profile_name)
                # --- FINE VALIDAZIONE ---

                if validated_path:
                    logging.debug(f"handle_new_profile - Valid path: '{validated_path}'.")
                    self.profiles[profile_name] = validated_path
                    logging.debug("handle_new_profile - Attempting to save profiles to file...")
                    save_success = core_logic.save_profiles(self.profiles)
                    logging.debug(f"handle_new_profile - Result of core_logic.save_profiles: {save_success}")

                    if save_success:
                        logging.debug("handle_new_profile - Profile save OK. Calling update_profile_table().")
                        try:
                            self.update_profile_table()
                            logging.debug("handle_new_profile - Call to update_profile_table() completed.")
                            QMessageBox.information(self, "Successo", f"Profilo '{profile_name}' creato e salvato.")
                        except Exception as e_update:
                             logging.critical("Critical error during update_profile_table()", exc_info=True)
                             QMessageBox.critical(self, "Errore UI", f"Profilo salvato ma errore aggiornamento lista:\n{e_update}")
                    else:
                        logging.debug("handle_new_profile - core_logic.save_profiles returned False.")
                        QMessageBox.critical(self, "Errore", "Impossibile salvare il file dei profili.")
                        if profile_name in self.profiles:
                             logging.debug("handle_new_profile - Removing unsaved profile from memory.")
                             del self.profiles[profile_name]
            else:
                 logging.debug("handle_new_profile - Path input cancelled (ok2=False).")
        else:
            logging.debug("handle_new_profile - Name input cancelled (ok=False or empty name).")
        logging.debug("handle_new_profile - END")

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
                    self.update_profile_table()
                    self.status_label.setText(f"Profilo '{profile_name}' eliminato.")
                else:
                    QMessageBox.critical(self, "Errore", "Profilo eliminato dalla memoria ma impossibile salvare le modifiche.")
                    self.profiles = core_logic.load_profiles()
                    self.update_profile_table()

    @Slot()
    def handle_steam(self):
        dialog = SteamDialog(parent=self)
        dialog.profile_configured.connect(self.on_steam_profile_configured)
        dialog.exec()

    @Slot(str, str)
    def on_steam_profile_configured(self, profile_name, save_path):
        logging.debug(f"Received profile_configured signal: profile '{profile_name}'")
        self.profiles = core_logic.load_profiles()
        self.update_profile_table()
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
        
    def load_theme_icons(self):
        """Carica le icone sole/luna."""
        sun_icon_path = resource_path("icons/sun.png")
        moon_icon_path = resource_path("icons/moon.png")
        self.sun_icon = QIcon(sun_icon_path) if os.path.exists(sun_icon_path) else None
        self.moon_icon = QIcon(moon_icon_path) if os.path.exists(moon_icon_path) else None
        if not self.sun_icon: logging.warning(f"Sun icon not found: {sun_icon_path}")
        if not self.moon_icon: logging.warning(f"Moon icon not found: {moon_icon_path}")

    def update_theme(self):
        """Applica il tema corrente e aggiorna l'icona del pulsante."""
        theme_name = self.current_settings.get('theme', 'dark')
        qss_to_apply = config.LIGHT_THEME_QSS if theme_name == 'light' else config.DARK_THEME_QSS
        try:
            app_instance = QApplication.instance()
            if app_instance: app_instance.setStyleSheet(qss_to_apply)
            else: logging.error("Unable to apply theme: QApplication instance not found."); return
            logging.info(f"Theme '{theme_name}' applied.")
            icon_size = QSize(16, 16) # Usa la stessa dimensione definita in init
            if theme_name == 'light':
                if self.moon_icon: self.theme_button.setIcon(self.moon_icon); self.theme_button.setIconSize(icon_size)
                else: self.theme_button.setText("D"); self.theme_button.setIcon(QIcon()) # Fallback testo
                self.theme_button.setToolTip("Passa al tema scuro")
            else: # Dark theme
                if self.sun_icon: self.theme_button.setIcon(self.sun_icon); self.theme_button.setIconSize(icon_size)
                else: self.theme_button.setText("L"); self.theme_button.setIcon(QIcon()) # Fallback testo
                self.theme_button.setToolTip("Passa al tema chiaro")
        except Exception: logging.error(f"Error when applying the theme '{theme_name}'", exc_info=True)

    @Slot()
    def handle_theme_toggle(self):
        """Inverte il tema, lo salva e lo applica."""
        current_theme = self.current_settings.get('theme', 'dark')
        new_theme = 'light' if current_theme == 'dark' else 'dark'
        logging.debug(f"Theme change requested from '{current_theme}' to '{new_theme}'")
        self.current_settings['theme'] = new_theme
        if not settings_manager.save_settings(self.current_settings):
            QMessageBox.warning(self, "Errore", "Impossibile salvare l'impostazione del tema.")
            self.current_settings['theme'] = current_theme # Ripristina se salvataggio fallisce
        else:
            self.update_theme() # Applica il nuovo tema solo se salvato con successo
        

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
                    self.status_label.setText(f"Avvio ripristino per '{profile_name}'...")
                    self.set_controls_enabled(False)
                    self.worker_thread = WorkerThread(core_logic.perform_restore, profile_name, save_path, archive_to_restore)
                    self.worker_thread.finished.connect(self.on_operation_finished)
                    self.worker_thread.progress.connect(self.status_label.setText)
                    self.worker_thread.start()
                else: self.status_label.setText("Ripristino annullato.")
            else: self.status_label.setText("Nessun backup selezionato per il ripristino.")
        else: self.status_label.setText("Selezione backup annullata.")

    @Slot()
    def handle_manage_backups(self):
        profile_name = self.get_selected_profile_name()
        if not profile_name: QMessageBox.warning(self, "Errore", "Nessun profilo selezionato."); return
        dialog = ManageBackupsDialog(profile_name, self)
        dialog.exec()
        self.update_profile_table()

    @Slot(bool, str)
    def on_operation_finished(self, success, message):
        main_message = message.splitlines()[0] if message else "Operazione terminata senza messaggio."
        self.status_label.setText(f"{'Completato' if success else 'ERRORE'}: {main_message}")
        self.set_controls_enabled(True)
        self.worker_thread = None
        if not success: QMessageBox.critical(self, "Errore Operazione", message)
        else: logging.debug("Operation thread worker successful, calling update_profile_table() to update view.")
        self.update_profile_table()

    @Slot(str)
    def on_detection_progress(self, message):
        """Aggiorna la status bar con i messaggi dal thread di rilevamento."""
        # Potremmo voler filtrare i messaggi o renderli più user-friendly
        self.status_label.setText(message)

    @Slot(bool, dict)
    def on_detection_finished(self, success, results):
        """Chiamato quando il thread di rilevamento ha finito."""
        logging.debug(f"Detection thread finished. Success: {success}, Results: {results}")
        QApplication.restoreOverrideCursor() # Ripristina cursore normale
        self.set_controls_enabled(True)     # Riabilita controlli
        self.status_label.setText(self.tr("Ricerca percorso completata."))

        # Rimuovi riferimento al thread (importante per permettere nuove ricerche)
        # Controlla se l'attributo esiste prima di provare a impostarlo a None
        if hasattr(self, 'detection_thread'):
             self.detection_thread = None

        # Recupera il nome del profilo dai risultati del thread
        profile_name = results.get('profile_name_suggestion', 'profilo_sconosciuto')

        if not success:
            error_msg = results.get('message', self.tr("Errore sconosciuto durante la ricerca."))
            # Non mostrare l'errore se era solo "Ricerca interrotta" (potrebbe essere voluto)
            if error_msg != "Ricerca interrotta.":
                 QMessageBox.critical(self, self.tr("Errore Ricerca Percorso"), error_msg)
            else:
                 # Se interrotta, mostra solo messaggio in status bar
                 self.status_label.setText(self.tr("Ricerca interrotta."))
            return # Esce in caso di errore o interruzione

        # --- Logica di gestione risultati e interazione utente ---
        final_path_to_use = None
        paths_found = results.get('paths', [])
        status = results.get('status', 'error') # Dovrebbe essere 'found' o 'not_found' se success è True

        if status == 'found':
            logging.debug(f"Paths found by detection thread: {paths_found}")
            if len(paths_found) == 1:
                # Trovato un solo percorso, chiedi conferma semplice
                
                reply = QMessageBox.question(self,
                                             self.tr("Conferma Percorso Automatico"),
                                             self.tr("È stato rilevato questo percorso:\n\n{0}\n\nVuoi usarlo per il profilo '{1}'?").format(paths_found[0], profile_name),
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    final_path_to_use = paths_found[0]
                elif reply == QMessageBox.StandardButton.No:
                     logging.info("User rejected single automatic path. Requesting manual input.")
                     final_path_to_use = None # Forza richiesta manuale sotto
                else: # Cancel
                    self.status_label.setText(self.tr("Creazione profilo annullata."))
                    return # Esce se utente annulla
            
            # --- MODIFICA PER MULTIPLI PERCORSI ---
            elif len(paths_found) > 1: # Trovati multipli percorsi
                logging.debug(f"Found {len(paths_found)} paths, applying priority sorting.")

                # 1. Definisci i nomi di cartella prioritari (in minuscolo)
                #    (Potremmo spostare questa lista in config.py o ottenerla da core_logic in futuro)
                preferred_suffixes = ['saves', 'save', 'savegame', 'savegames',
                                      'saved', 'storage', 'playerdata', 'profile',
                                      'profiles', 'user', 'data', 'savedata']

                # 2. Definisci la funzione chiave per l'ordinamento
                def sort_key(path):
                    basename_lower = os.path.basename(os.path.normpath(path)).lower()
                    # Priorità 0 se finisce con suffisso preferito, 1 altrimenti
                    priority = 0 if basename_lower in preferred_suffixes else 1
                    # Criterio secondario: ordinamento alfabetico del percorso completo
                    return (priority, path.lower())

                # 3. Ordina la lista paths_found usando la chiave
                sorted_paths = sorted(paths_found, key=sort_key)
                logging.debug(f"Paths sorted for selection: {sorted_paths}")

                # 4. Crea le scelte per il dialogo usando la lista ORDINATA
                #    Aggiungi sempre l'opzione manuale alla fine.
                choices = sorted_paths + [self.tr("[Inserisci Manualmente...]")] # <-- Usa sorted_paths qui

                # 5. Mostra il dialogo (il resto rimane uguale)
                chosen_path_str, ok = QInputDialog.getItem(
                    self,
                    self.tr("Conferma Percorso Salvataggi"),
                    self.tr("Sono stati trovati questi percorsi potenziali per '{0}'.\nSeleziona quello corretto o scegli l'inserimento manuale:").format(profile_name),
                    choices, # Passa la lista ordinata con l'opzione manuale
                    0, False # Seleziona il primo (ora quello più probabile)   
                )
                
                if ok and chosen_path_str:
                    if chosen_path_str == self.tr("[Inserisci Manualmente...]"):
                        logging.info("User chose manual input from multiple paths list.")
                        final_path_to_use = None # Forza richiesta manuale sotto
                    else:
                        # L'utente ha scelto un percorso dalla lista
                        final_path_to_use = chosen_path_str # Il percorso è la stringa senza tag aggiunti
                else: # Annullato QInputDialog
                    self.status_label.setText(self.tr("Creazione profilo annullata."))
                    return # Esce se utente annulla

        elif status == 'not_found':
            # Nessun percorso trovato automaticamente
            QMessageBox.information(self, self.tr("Percorso Non Rilevato"), self.tr("Impossibile rilevare automaticamente il percorso dei salvataggi per '{0}'.\nPer favore, inseriscilo manualmente.").format(profile_name))
            final_path_to_use = None # Forza richiesta manuale sotto
        else: # Altro stato inatteso se success era True? Logghiamo e usciamo
             logging.warning(f"Unexpected status '{status}' received from detection thread despite success=True")
             self.status_label.setText(self.tr("Errore interno durante la gestione dei risultati."))
             return

        # --- Richiesta Inserimento Manuale (se final_path_to_use è None a questo punto) ---
        if final_path_to_use is None:
             path_prompt = self.tr("Inserisci il percorso COMPLETO per i salvataggi del profilo:\n'{0}'").format(profile_name)
             input_path, ok_manual = QInputDialog.getText(self, self.tr("Percorso Salvataggi Manuale"), path_prompt)

             if ok_manual and input_path:
                 # Abbiamo ottenuto un percorso manuale dall'utente
                 final_path_to_use = input_path
             elif ok_manual and not input_path:
                  # Utente ha premuto OK ma non ha inserito nulla
                  QMessageBox.warning(self, self.tr("Errore Percorso"), self.tr("Il percorso non può essere vuoto."))
                  self.status_label.setText(self.tr("Creazione profilo annullata (percorso vuoto)."))
                  return # Esce
             else: # Annullato QInputDialog
                 self.status_label.setText(self.tr("Creazione profilo annullata."))
                 return # Esce

        # --- Validazione Finale e Salvataggio Profilo ---
        # Arriviamo qui solo se final_path_to_use contiene un percorso (da selezione o manuale)
        if final_path_to_use:
            # Usa la funzione di validazione esistente nella MainWindow
            validated_path = self.validate_save_path(final_path_to_use, profile_name)

            if validated_path:
                # Il percorso è stato validato con successo
                logging.debug(f"Final path validated: {validated_path}. Saving profile '{profile_name}'")
                self.profiles[profile_name] = validated_path # Aggiorna dizionario in memoria

                # Salva su file
                if core_logic.save_profiles(self.profiles):
                    self.update_profile_table() # Aggiorna la tabella nella GUI
                    self.select_profile_in_table(profile_name) # Prova a selezionare il nuovo profilo
                    QMessageBox.information(self, self.tr("Profilo Creato"), self.tr("Profilo '{0}' creato con successo.").format(profile_name))
                    self.status_label.setText(self.tr("Profilo '{0}' creato.").format(profile_name))
                else:
                    # Errore durante il salvataggio su file
                    QMessageBox.critical(self, self.tr("Errore"), self.tr("Impossibile salvare il file dei profili."))
                    # Rimuovi il profilo aggiunto alla memoria per consistenza
                    if profile_name in self.profiles:
                         del self.profiles[profile_name]
            # else: la validazione è fallita, validate_save_path ha già mostrato l'errore
            #       non facciamo nient'altro, l'utente è stato avvisato.
                       
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

    # --- NUOVO SLOT PER ATTIVARE FINESTRA DA SECONDA ISTANZA ---
    @Slot()
    def activateExistingInstance(self):
        logging.info("Received signal to activate existing instance.")
        # Assicurati che la finestra sia visibile e portata in primo piano
        self.showNormal() # Mostra se era minimizzata
        self.raise_()     # Porta sopra le altre finestre dell'app (se ci fossero dialoghi)
        self.activateWindow() # Attiva la finestra nel sistema operativo
    # --- FINE NUOVO SLOT ---

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
    root_logger.addHandler(console_handler)
    qt_log_handler = QtLogHandler()
    qt_log_handler.setFormatter(log_formatter)
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

                # ---->> SOLO ORA CREIAMO QApplication <<----
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
                        qm_filename = f"game_saver_{selected_language}.qm"
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
                        window = MainWindow(current_settings, qt_log_handler) # Crea PRIMA del dialogo
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
                        window = MainWindow(current_settings, qt_log_handler)

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