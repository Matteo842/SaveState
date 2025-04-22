# -*- coding: utf-8 -*-
import os
from PySide6.QtWidgets import (
    QDialog, QListWidget, QPushButton, QLabel, QHBoxLayout, QVBoxLayout,
    QMessageBox, QApplication, QStyle, QListWidgetItem
)
from PySide6.QtCore import Slot, Qt, QLocale, QCoreApplication

# Importa la logica necessaria
import core_logic
import config
import logging 


class ManageBackupsDialog(QDialog):
    # ... (Codice come prima, sembrava OK con correzioni caratteri) ...
     def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.setWindowTitle(self.tr("Gestisci Backup per {0}").format(self.profile_name))
        self.setMinimumWidth(500)
        # Ottieni lo stile per le icone standard
        style = QApplication.instance().style()
        
        # Widget
        self.backup_list_widget = QListWidget()
        self.delete_button = QPushButton(self.tr("Elimina Selezionato"))
        self.delete_button.setObjectName("DangerButton")
        
        # Imposta icona standard per Elimina
        delete_icon = style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon) # <-- AGGIUNGI
        self.delete_button.setIcon(delete_icon)
        
        self.close_button = QPushButton(self.tr("Chiudi"))
        
        # Imposta icona standard per Chiudi
        close_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton) # <-- AGGIUNGI
        self.close_button.setIcon(close_icon)
        
        self.delete_button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Backup esistenti per '{0}':").format(self.profile_name)))
        layout.addWidget(self.backup_list_widget)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)
        self.backup_list_widget.currentItemChanged.connect(
            lambda item: self.delete_button.setEnabled(item is not None and item.data(Qt.ItemDataRole.UserRole) is not None)
        )
        self.delete_button.clicked.connect(self.delete_selected_backup)
        self.close_button.clicked.connect(self.reject)
        self.populate_backup_list()
     
     # --- Metodo populate_backup_list CORRETTO ---
     @Slot() # Aggiungi Slot se usi connessioni per segnali (buona pratica)
     def populate_backup_list(self):
        self.backup_list_widget.clear()
        self.delete_button.setEnabled(False)

        # --- RECUPERA IMPOSTAZIONI E LOCALE QUI (PRIMA DI USARE LE VARIABILI) ---
        current_backup_base_dir = "" # Default vuoto
        current_lang_code = "en"     # Default lingua
        locale = QLocale(QLocale.Language.English) # Locale di default

        parent_window = self.parent() # Ottieni il parent una sola volta
        if parent_window and hasattr(parent_window, 'current_settings'):
            # Leggi il percorso base del backup dalle impostazioni
            current_backup_base_dir = parent_window.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
            # Leggi la lingua corrente dalle impostazioni
            current_lang_code = parent_window.current_settings.get("language", "en")
            # Crea l'oggetto QLocale corretto basato sulla lingua
            locale = QLocale(QLocale.Language.English if current_lang_code == "en" else QLocale.Language.Italian)
            logging.debug(f"ManageBackupsDialog: Using locale for language '{current_lang_code}'") # Log utile
        else:
            # Fallback se non troviamo le impostazioni nel parent
            logging.warning("ManageBackupsDialog: Impossibile accedere a current_settings dal parent. Uso i default da config.")
            current_backup_base_dir = config.BACKUP_BASE_DIR
            # locale rimane QLocale.Language.English (già impostato come default)
        # --- FINE RECUPERO IMPOSTAZIONI ---

        # Ora puoi chiamare list_available_backups perché current_backup_base_dir è definito
        # Assicurati che list_available_backups restituisca (name, path, dt_obj)
        backups = core_logic.list_available_backups(self.profile_name, current_backup_base_dir)

        if not backups:
            # Gestione nessun backup trovato
            item = QListWidgetItem(self.tr("Nessun backup trovato.")) # Traduci testo
            item.setData(Qt.ItemDataRole.UserRole, None) # Nessun percorso associato
            self.backup_list_widget.addItem(item)
            self.backup_list_widget.setEnabled(False) # Disabilita lista
        else:
            # Ci sono backup, popola la lista
            self.backup_list_widget.setEnabled(True) # Abilita lista

            # Ciclo per aggiungere ogni backup con data formattata
            for name, path, dt_obj in backups: # Itera sulla tupla (name, path, datetime_object)
                # Formatta la data usando l'oggetto 'locale' definito sopra
                date_str_formatted = "???" # Valore fallback
                if dt_obj: # Controlla se l'oggetto datetime è valido
                    try:
                        # Usa QLocale per ottenere il formato breve standard
                        date_str_formatted = locale.toString(dt_obj, QLocale.FormatType.ShortFormat)
                    except Exception as e_fmt:
                        logging.error(f"Error formatting date ({dt_obj}) for backup {name}: {e_fmt}")

                # Pulisci il nome del file di backup (rimuovi timestamp)
                display_name = core_logic.get_display_name_from_backup_filename(name)
                # Crea il testo dell'item con nome pulito e data formattata
                item_text = f"{display_name} ({date_str_formatted})"

                # Crea e aggiungi l'item
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, path) # Salva il percorso completo nell'item
                self.backup_list_widget.addItem(item)
            # Fine ciclo for backups
        # Fine if/else not backups
    # --- Fine populate_backup_list ---
     
     @Slot()
     def delete_selected_backup(self):
        current_item = self.backup_list_widget.currentItem()
        if not current_item: return
        backup_path = current_item.data(Qt.ItemDataRole.UserRole)
        if not backup_path: return
        backup_name = os.path.basename(backup_path)
        
        confirm_title = self.tr("Conferma Eliminazione")
        confirm_text = self.tr(
            "Sei sicuro di voler eliminare PERMANENTEMENTE il file di backup:\n\n"
            "{0}\n\n" # Placeholder per il nome file
            "Questa azione non può essere annullata!"
        ).format(backup_name) # Inserisci il nome file nel placeholder

        confirm = QMessageBox.warning(self, confirm_title, confirm_text,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.setEnabled(False)
            QApplication.processEvents()
            success, message = core_logic.delete_single_backup_file(backup_path)
            self.setEnabled(True)
            if success:
                QMessageBox.information(self, self.tr("Successo"), message)
                self.populate_backup_list()
            else:
                QMessageBox.critical(self, self.tr("Errore Eliminazione"), message)
                self.populate_backup_list() # Aggiorna comunque