import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QGroupBox,
    QComboBox, QSpinBox, QDialogButtonBox, QFileDialog, QStyle, QApplication,
    QCheckBox
)
from PySide6.QtCore import Slot, QEvent

# Importa il modulo per salvare/caricare impostazioni
import logging


# NOTA: Rimuoveremo la logica di gestione diretta dei traduttori da qui.
#       Le variabili globali CURRENT_TRANSLATOR/ENGLISH_TRANSLATOR NON
#       dovrebbero essere importate/usate direttamente qui.

class SettingsDialog(QDialog):
    
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Impostazioni Applicazione"))
        self.setMinimumWidth(500)
        self.settings = current_settings.copy()
        
        # Ottieni lo stile per le icone standard
        style = QApplication.instance().style()

        layout = QVBoxLayout(self)

        path_group = QGroupBox(self.tr("Percorso Base Backup"))
        self.path_group = path_group
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(self.settings.get("backup_base_dir", ""))
        browse_button = QPushButton()
        self.browse_button = browse_button
        browse_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        browse_button.setIcon(browse_icon)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(browse_button)
        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        max_src_group = QGroupBox()
        self.max_src_group = max_src_group
        max_src_layout = QHBoxLayout()
        self.size_options = [
            ("50 MB", 50), ("100 MB", 100), ("250 MB", 250), ("500 MB", 500),
            ("1 GB (1024 MB)", 1024), ("2 GB (2048 MB)", 2048),
            ("5 GB (5120 MB)", 5120), ("10 GB (10240 MB)", 10240),
            ("Nessun Limite", -1)
        ]
        self.max_src_combobox = QComboBox()
        for display_text, _ in self.size_options:
            self.max_src_combobox.addItem(display_text)

        current_mb_value = self.settings.get("max_source_size_mb", 500)
        current_index = -1
        for i, (_, mb_value) in enumerate(self.size_options):
            if mb_value == current_mb_value:
                current_index = i
                break
        if current_index != -1: self.max_src_combobox.setCurrentIndex(current_index)
        else:
            default_value_to_find = 500
            for i, (_, mb_value) in enumerate(self.size_options):
                if mb_value == default_value_to_find:
                     self.max_src_combobox.setCurrentIndex(i); break

        max_src_layout.addWidget(self.max_src_combobox)
        max_src_layout.addStretch()
        max_src_group.setLayout(max_src_layout)
        layout.addWidget(max_src_group)

        max_group = QGroupBox()
        self.max_group = max_group
        max_layout = QHBoxLayout()
        self.max_spinbox = QSpinBox()
        self.max_spinbox.setMinimum(1)
        self.max_spinbox.setMaximum(99)
        self.max_spinbox.setValue(self.settings.get("max_backups", 3))
        max_layout.addWidget(self.max_spinbox)
        max_layout.addStretch()
        max_group.setLayout(max_layout)
        layout.addWidget(max_group)
        
        # --- NUOVO: Gruppo Lingua ---
        lang_group = QGroupBox()
        self.lang_group = lang_group
        lang_layout = QHBoxLayout()
        self.lang_combobox = QComboBox()
        # Aggiungiamo le lingue. Salviamo il codice ('it', 'en') come UserData
        self.lang_combobox.addItem("Italiano", "it")
        self.lang_combobox.addItem("English", "en")

        # Seleziona la lingua corrente
        current_lang_code = self.settings.get("language", "it")
        index_to_select = self.lang_combobox.findData(current_lang_code)
        if index_to_select != -1:
            self.lang_combobox.setCurrentIndex(index_to_select)

        lang_layout.addWidget(self.lang_combobox)
        lang_layout.addStretch()
        lang_group.setLayout(lang_layout)
        layout.addWidget(lang_group)
        # --- FINE NUOVO ---

        # --- NUOVO: Gruppo Compressione ---
        comp_group = QGroupBox() # Testo impostato da retranslateUi
        self.comp_group = comp_group # Salva riferimento

        comp_layout = QHBoxLayout()
        self.comp_combobox = QComboBox()
        # Mappatura: Chiave interna -> Testo da mostrare (verrà tradotto)
        self.compression_options = {
            "standard": self.tr("Standard (Consigliato)"),
            "maximum": self.tr("Massima (Più Lento)"),
            "stored": self.tr("Nessuna (Più Veloce)")
        }
        # Popola la combobox
        for key, text in self.compression_options.items():
            self.comp_combobox.addItem(text, key) # Salva la chiave 'standard', 'maximum', 'stored' come UserData

        # Seleziona la modalità corrente dalle impostazioni
        current_comp_mode = self.settings.get("compression_mode", "standard")
        index_to_select = self.comp_combobox.findData(current_comp_mode)
        if index_to_select != -1:
            self.comp_combobox.setCurrentIndex(index_to_select)

        comp_layout.addWidget(self.comp_combobox)
        comp_layout.addStretch()
        comp_group.setLayout(comp_layout)
        layout.addWidget(comp_group)
  
        # --- Controllo Spazio Libero ---
        space_check_group = QGroupBox() # Titolo impostato da retranslateUi
        self.space_check_group = space_check_group # Salva riferimento
        space_check_layout = QHBoxLayout()
        self.space_check_checkbox = QCheckBox() # Testo impostato da retranslateUi
        # Imposta stato iniziale checkbox
        self.space_check_checkbox.setChecked(self.settings.get("check_free_space_enabled", True))
        space_check_layout.addWidget(self.space_check_checkbox)
        space_check_layout.addStretch()
        space_check_group.setLayout(space_check_layout)
        layout.addWidget(space_check_group)
        # --- FINE GRUPPO ---

        
        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons = buttons
        #buttons.button(QDialogButtonBox.StandardButton.Save).setText("Salva")
        buttons.accepted.connect(self.accept_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Connetti il segnale del pulsante Sfoglia (ora accessibile tramite self)
        self.browse_button.clicked.connect(self.browse_backup_dir)

        # --- Chiama retranslateUi alla fine per impostare testi iniziali ---
        self.retranslateUi()

        browse_button.clicked.connect(self.browse_backup_dir)

    def get_settings(self):
        """Restituisce il dizionario interno delle impostazioni modificate."""
        # Questo metodo restituisce semplicemente il dizionario self.settings
        # che contiene i valori aggiornati dai widget del dialogo dopo
        # che l'utente ha cliccato "Salva" (e accept_settings è stato chiamato).
        return self.settings
    
    def retranslateUi(self):
        """Aggiorna il testo dei widget traducibili nel dialogo."""
        logging.debug("SettingsDialog.retranslateUi() called")
        self.setWindowTitle(self.tr("Impostazioni Applicazione"))
        # Assumiamo di aver salvato i riferimenti ai groupbox in __init__
        if hasattr(self, 'path_group'):
             self.path_group.setTitle(self.tr("Percorso Base Backup"))
        if hasattr(self, 'max_src_group'):
             self.max_src_group.setTitle(self.tr("Dimensione Massima Sorgente per Backup"))
        if hasattr(self, 'max_group'):
             self.max_group.setTitle(self.tr("Numero Massimo Backup per Profilo"))
        if hasattr(self, 'lang_group'):
             self.lang_group.setTitle("Lingua / Language") # Titolo già con tr() in __init__, ma riapplicare è più sicuro
        
        # Aggiorna titolo gruppo compressione
        if hasattr(self, 'comp_group'):
            self.comp_group.setTitle(self.tr("Compressione Backup (.zip)"))

        if hasattr(self, 'space_check_group'):
            self.space_check_group.setTitle(self.tr("Controllo Spazio Libero Disco"))
        if hasattr(self, 'space_check_checkbox'):
            self.space_check_checkbox.setText(self.tr("Abilita controllo spazio prima del backup (minimo {0} GB)").format(config.MIN_FREE_SPACE_GB if 'config' in globals() and hasattr(config, 'MIN_FREE_SPACE_GB') else 2)) # Usa la costante se possibile, altrimenti 2

        
        # Aggiorna testi nella combobox compressione
        if hasattr(self, 'comp_combobox'):
            # Ricrea la mappa con testi tradotti
            self.compression_options = {
                 "standard": self.tr("Standard (Consigliato)"),
                 "maximum": self.tr("Massima (Più Lento)"),
                 "stored": self.tr("Nessuna (Più Veloce)")
            }
            current_key = self.comp_combobox.currentData() # Salva la chiave selezionata
            self.comp_combobox.clear() # Svuota
            for key, text in self.compression_options.items(): # Ripopola
                self.comp_combobox.addItem(text, key)
            # Riseleziona l'elemento giusto
            index_to_select = self.comp_combobox.findData(current_key)
            if index_to_select != -1:
                self.comp_combobox.setCurrentIndex(index_to_select)   
        
        # Aggiorna testo pulsanti Sfoglia, Salva, Annulla
        if hasattr(self, 'browse_button'): # Salva riferimento in __init__: self.browse_button = browse_button
             self.browse_button.setText(self.tr("Sfoglia..."))
        
        # I pulsanti Salva/Annulla sono dentro QDialogButtonBox
        if hasattr(self, 'buttons'): # Salva riferimento in __init__: self.buttons = buttons
             save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
             if save_button: save_button.setText(self.tr("Salva"))
             cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
             if cancel_button: cancel_button.setText(self.tr("Annulla")) # Testo standard di Qt, ma meglio essere espliciti
         
        def changeEvent(self, event):
            """Gestisce eventi, incluso cambio lingua."""
            if event.type() == QEvent.Type.LanguageChange:
                logging.debug("SettingsDialog.changeEvent(LanguageChange) detected")
                self.retranslateUi()
            super().changeEvent(event)
      
    @Slot()
    def browse_backup_dir(self):
        """Apre dialogo per selezionare cartella backup."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Base Folder for Backups", self.path_edit.text()
        )
        if directory: self.path_edit.setText(os.path.normpath(directory))

    @Slot()
    def accept_settings(self):
        """Valida e aggiorna il dizionario delle impostazioni."""
        # --- Ottieni i nuovi valori dai widget ---
        new_path = os.path.normpath(self.path_edit.text())
        new_max_backups = self.max_spinbox.value()
        selected_index = self.max_src_combobox.currentIndex()
        new_language = self.lang_combobox.currentData() # Ottieni 'it' o 'en'
        new_max_src_size_mb = -1
        if 0 <= selected_index < len(self.size_options):
            _, new_max_src_size_mb = self.size_options[selected_index]
        # old_language = self.settings.get("language", "it") # Non più necessario qui
        new_compression_mode = self.comp_combobox.currentData()
        new_check_free_space = self.space_check_checkbox.isChecked()

        # --- VALIDAZIONE PERCORSO (Come prima, usando self.parent()) ---
        main_window = self.parent()
        validated_new_path = None
        if main_window and hasattr(main_window, 'validate_save_path'):
            # Usa self.tr() per i messaggi dentro validate_save_path se necessario
            context_name = self.tr("Impostazioni") if hasattr(self, 'tr') else "Impostazioni"
            validated_new_path = main_window.validate_save_path(new_path, context_profile_name=context_name)
            if validated_new_path is None: return # Esci se validazione fallisce
            new_path = validated_new_path
        else:
            logging.warning("Funzione validate_save_path non trovata o non eseguita nella finestra parent.")
            # Considera se mostrare un errore generico o procedere con cautela
            # Per ora, procediamo ma sarebbe meglio assicurarsi che esista sempre
            # QMessageBox.critical(self, self.tr("Errore Interno"), self.tr("Funzione di validazione percorso mancante."))
            # return

        # --- CAMBIO TRADUTTORE (RIMOSSO DA QUI) ---
        # Tutta la logica che installava/rimuoveva QTranslator è stata tolta.

        # Aggiorna il dizionario self.settings con i nuovi valori
        self.settings["backup_base_dir"] = new_path
        self.settings["max_backups"] = new_max_backups
        if selected_index != -1:
            self.settings["max_source_size_mb"] = new_max_src_size_mb
        self.settings["language"] = new_language # Salva la nuova lingua scelta
        self.settings["compression_mode"] = new_compression_mode
        self.settings["check_free_space_enabled"] = new_check_free_space

        # Non salviamo più le impostazioni su file da qui, lo farà la MainWindow
        # if not settings_manager.save_settings(self.settings):
        #    QMessageBox.critical(self, self.tr("Errore"), self.tr("Impossibile salvare il file delle impostazioni."))
        #    return # Potrebbe essere meglio non accettare se il salvataggio fallisce?

        # Accetta il dialogo (restituisce i settings aggiornati tramite get_settings())
        super().accept()