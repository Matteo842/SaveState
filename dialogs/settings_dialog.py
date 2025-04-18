# dialogs/settings_dialog.py
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QGroupBox,
    QComboBox, QSpinBox, QDialogButtonBox, QFileDialog, QStyle, QApplication,
    QCheckBox, QMessageBox
)
from PySide6.QtCore import Slot, QEvent

# Importa il modulo per salvare/caricare impostazioni
import logging
# Import config per accedere alla costante MIN_FREE_SPACE_GB
try:
    import config
except ImportError:
    # Fallback se config.py non è trovabile (improbabile ma sicuro)
    class config:
        MIN_FREE_SPACE_GB = 2
    logging.warning("Modulo config.py non trovato, uso valore di default per MIN_FREE_SPACE_GB.")


class SettingsDialog(QDialog):

    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Impostazioni Applicazione"))
        self.setMinimumWidth(500)
        self.settings = current_settings.copy()

        # Ottieni lo stile per le icone standard
        style = QApplication.instance().style()

        layout = QVBoxLayout(self)

        # --- Gruppo Percorso Base Backup ---
        self.path_group = QGroupBox(self.tr("Percorso Base Backup")) # Riferimento salvato
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(self.settings.get("backup_base_dir", ""))
        self.browse_button = QPushButton() # Riferimento salvato
        browse_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        self.browse_button.setIcon(browse_icon)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_button)
        self.path_group.setLayout(path_layout)
        layout.addWidget(self.path_group)

        # --- Gruppo Dimensione Massima Sorgente ---
        self.max_src_group = QGroupBox() # Riferimento salvato
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
        # ... (logica per selezionare valore corrente) ...
        current_mb_value = self.settings.get("max_source_size_mb", 500)
        current_index = next((i for i, (_, v) in enumerate(self.size_options) if v == current_mb_value), -1)
        if current_index != -1:
            self.max_src_combobox.setCurrentIndex(current_index)
        else: # Fallback se valore salvato non è tra le opzioni
            default_index = next((i for i, (_, v) in enumerate(self.size_options) if v == 500), 0)
            self.max_src_combobox.setCurrentIndex(default_index)

        max_src_layout.addWidget(self.max_src_combobox)
        max_src_layout.addStretch()
        self.max_src_group.setLayout(max_src_layout)
        layout.addWidget(self.max_src_group)

        # --- Gruppo Numero Massimo Backup ---
        self.max_group = QGroupBox() # Riferimento salvato
        max_layout = QHBoxLayout()
        self.max_spinbox = QSpinBox()
        self.max_spinbox.setMinimum(1)
        self.max_spinbox.setMaximum(99)
        self.max_spinbox.setValue(self.settings.get("max_backups", 3))
        max_layout.addWidget(self.max_spinbox)
        max_layout.addStretch()
        self.max_group.setLayout(max_layout)
        layout.addWidget(self.max_group)

        # --- Gruppo Lingua ---
        self.lang_group = QGroupBox() # Riferimento salvato
        lang_layout = QHBoxLayout()
        self.lang_combobox = QComboBox()
        self.lang_combobox.addItem("Italiano", "it")
        self.lang_combobox.addItem("English", "en")
        current_lang_code = self.settings.get("language", "it")
        index_to_select_lang = self.lang_combobox.findData(current_lang_code)
        if index_to_select_lang != -1:
            self.lang_combobox.setCurrentIndex(index_to_select_lang)
        lang_layout.addWidget(self.lang_combobox)
        lang_layout.addStretch()
        self.lang_group.setLayout(lang_layout)
        layout.addWidget(self.lang_group)

        # --- Gruppo Compressione ---
        self.comp_group = QGroupBox() # Riferimento salvato
        comp_layout = QHBoxLayout()
        self.comp_combobox = QComboBox()
        # (La mappa self.compression_options verrà aggiornata in retranslateUi)
        current_comp_mode = self.settings.get("compression_mode", "standard")
        # (La selezione verrà ripristinata in retranslateUi dopo aver popolato)
        comp_layout.addWidget(self.comp_combobox)
        comp_layout.addStretch()
        self.comp_group.setLayout(comp_layout)
        layout.addWidget(self.comp_group)

        # --- Controllo Spazio Libero ---
        self.space_check_group = QGroupBox() # Riferimento salvato
        space_check_layout = QHBoxLayout()
        self.space_check_checkbox = QCheckBox() # Riferimento salvato
        self.space_check_checkbox.setChecked(self.settings.get("check_free_space_enabled", True))
        space_check_layout.addWidget(self.space_check_checkbox)
        space_check_layout.addStretch()
        self.space_check_group.setLayout(space_check_layout)
        layout.addWidget(self.space_check_group)

        layout.addStretch()

        # --- Pulsanti Dialogo ---
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel) # Riferimento salvato
        self.buttons.accepted.connect(self.accept_settings)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # Connetti segnali
        self.browse_button.clicked.connect(self.browse_backup_dir)

        # Chiama retranslateUi alla fine per impostare testi iniziali
        self.retranslateUi()

    def get_settings(self):
        """Restituisce il dizionario interno delle impostazioni modificate."""
        return self.settings

    def retranslateUi(self):
        """Aggiorna il testo dei widget traducibili nel dialogo."""
        logging.debug("SettingsDialog.retranslateUi() called")
        self.setWindowTitle(self.tr("Impostazioni Applicazione"))
        self.path_group.setTitle(self.tr("Percorso Base Backup"))
        self.max_src_group.setTitle(self.tr("Dimensione Massima Sorgente per Backup"))
        self.max_group.setTitle(self.tr("Numero Massimo Backup per Profilo"))
        self.lang_group.setTitle("Lingua / Language") # Già bilingue
        self.comp_group.setTitle(self.tr("Compressione Backup (.zip)"))
        self.space_check_group.setTitle(self.tr("Controllo Spazio Libero Disco"))
        self.space_check_checkbox.setText(self.tr("Abilita controllo spazio prima del backup (minimo {0} GB)").format(config.MIN_FREE_SPACE_GB))

        # Aggiorna testi nella combobox compressione
        current_key_comp = self.comp_combobox.currentData() # Salva chiave attuale
        self.comp_combobox.clear()
        self.compression_options = { # Ricrea mappa con testi tradotti
             "standard": self.tr("Standard (Consigliato)"),
             "maximum": self.tr("Massima (Più Lento)"),
             "stored": self.tr("Nessuna (Più Veloce)")
        }
        for key, text in self.compression_options.items(): # Ripopola
            self.comp_combobox.addItem(text, key)
        index_to_select_comp = self.comp_combobox.findData(current_key_comp)
        if index_to_select_comp != -1: # Riseleziona
            self.comp_combobox.setCurrentIndex(index_to_select_comp)

        # Aggiorna testo pulsanti
        self.browse_button.setText(self.tr("Sfoglia..."))
        save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button: save_button.setText(self.tr("Salva"))
        cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button: cancel_button.setText(self.tr("Annulla"))

    # !!! CORREZIONE: Spostato fuori da retranslateUi !!!
    def changeEvent(self, event):
        """Gestisce eventi, incluso cambio lingua."""
        if event.type() == QEvent.Type.LanguageChange:
            logging.debug("SettingsDialog.changeEvent(LanguageChange) detected")
            self.retranslateUi() # Richiama la funzione corretta
        super().changeEvent(event) # Chiama l'implementazione base

    @Slot()
    def browse_backup_dir(self):
        """Apre dialogo per selezionare cartella backup."""
        directory = QFileDialog.getExistingDirectory(
            self, self.tr("Seleziona Cartella Base per i Backup"), self.path_edit.text() # Usa self.tr()
        )
        if directory:
             self.path_edit.setText(os.path.normpath(directory))

    @Slot()
    def accept_settings(self):
        """Valida e aggiorna il dizionario delle impostazioni."""
        new_path = os.path.normpath(self.path_edit.text())
        new_max_backups = self.max_spinbox.value()
        selected_size_index = self.max_src_combobox.currentIndex()
        new_language = self.lang_combobox.currentData()
        new_compression_mode = self.comp_combobox.currentData()
        new_check_free_space = self.space_check_checkbox.isChecked()

        new_max_src_size_mb = -1
        if 0 <= selected_size_index < len(self.size_options):
            _, new_max_src_size_mb = self.size_options[selected_size_index]

        # --- VALIDAZIONE PERCORSO (Ora usa ProfileCreationManager) ---
        main_window = self.parent()
        # Controlla se main_window e il suo profile_creation_manager esistono,
        # e se quest'ultimo ha il metodo validate_save_path.
        if not main_window or \
           not hasattr(main_window, 'profile_creation_manager') or \
           not main_window.profile_creation_manager or \
           not hasattr(main_window.profile_creation_manager, 'validate_save_path'):
            logging.error("Impossibile validare il percorso: main_window o profile_creation_manager o metodo mancante.")
            QMessageBox.critical(self, self.tr("Errore Interno"), self.tr("Impossibile validare il percorso."))
            return

        context_name = self.tr("Impostazioni")
        # Chiama il metodo tramite il manager
        validated_new_path = main_window.profile_creation_manager.validate_save_path(
            new_path, context_profile_name=context_name
        )
        if validated_new_path is None:
             return # La validazione è fallita e ha già mostrato un messaggio

        # Aggiorna il dizionario self.settings con i nuovi valori validati
        self.settings["backup_base_dir"] = validated_new_path
        self.settings["max_backups"] = new_max_backups
        self.settings["max_source_size_mb"] = new_max_src_size_mb
        self.settings["language"] = new_language
        self.settings["compression_mode"] = new_compression_mode
        self.settings["check_free_space_enabled"] = new_check_free_space

        # Accetta il dialogo
        super().accept()