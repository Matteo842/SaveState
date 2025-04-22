# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QDialogButtonBox, QVBoxLayout,
    QListWidgetItem
)
from PySide6.QtCore import Qt, QLocale, QCoreApplication

import core_logic
import config
import logging


class RestoreDialog(QDialog):
    def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        # Titolo tradotto e formattato
        self.setWindowTitle(self.tr("Ripristina Backup per {}").format(profile_name))
        self.setMinimumWidth(450)
        self.backup_list_widget = QListWidget()
        self.selected_backup_path = None
        no_backup_label = None

        # --- Recupera il percorso base CORRENTE dalle impostazioni del parent ---
        current_backup_base_dir = "" # Default vuoto
        if parent and hasattr(parent, 'current_settings'): # Controlla se parent e settings esistono
            current_backup_base_dir = parent.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        else:
            # Fallback se non riusciamo a ottenere le impostazioni (improbabile)
            logging.warning("RestoreDialog: Impossibile accedere a current_settings dal parent. Uso il default da config.")
            current_backup_base_dir = config.BACKUP_BASE_DIR

        # --- Chiama core_logic (ora restituisce lista con datetime object) ---
        # La funzione list_available_backups deve essere già stata modificata
        # per restituire (name, path, datetime_obj)
        backups = core_logic.list_available_backups(profile_name, current_backup_base_dir)

        if not backups:
            # Gestione nessun backup trovato
            no_backup_label = QLabel(self.tr("Nessun backup trovato per questo profilo."))
            self.backup_list_widget.setEnabled(False)
        else:
            # --- Logica per formattazione data localizzata ---
            current_lang_code = "en" # Default fallback
            if parent and hasattr(parent, 'current_settings'):
                current_lang_code = parent.current_settings.get("language", "en")
            locale = QLocale(QLocale.Language.English if current_lang_code == "en" else QLocale.Language.Italian)
            # --- Fine logica localizzazione ---

            # --- Ciclo per popolare la lista CON FORMATTAZIONE DATA ---
            # Ora iteriamo su (name, path, dt_obj)
            for name, path, dt_obj in backups:
                # Formatta la data usando QLocale
                date_str_formatted = "???" # Fallback
                if dt_obj:
                    try:
                        date_str_formatted = locale.toString(dt_obj, QLocale.FormatType.ShortFormat)
                    except Exception as e_fmt:
                        logging.error(f"Error formatting date ({dt_obj}) for backup {name}: {e_fmt}")

                # Pulisci il nome file (usa la funzione da core_logic)
                display_name = core_logic.get_display_name_from_backup_filename(name)
                item_text = f"{display_name} ({date_str_formatted})" # Usa nome pulito e data formattata

                # Crea e aggiungi l'item alla lista
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, path) # Salva il percorso completo
                self.backup_list_widget.addItem(item)
            # --- Fine ciclo popolamento lista ---

        # --- Pulsanti Dialogo (come prima) ---
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(self.tr("Ripristina Selezionato"), QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button.setEnabled(False) # Disabilita OK all'inizio

        # --- Layout (come prima) ---
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Seleziona il backup da cui ripristinare:")))
        if no_backup_label: layout.addWidget(no_backup_label)
        layout.addWidget(self.backup_list_widget)
        layout.addWidget(buttons)

        # Connetti segnale cambio selezione (come prima)
        self.backup_list_widget.currentItemChanged.connect(self.on_selection_change)
    # --- Fine metodo __init__ ---

    # Il resto della classe RestoreDialog (on_selection_change, get_selected_path) rimane invariato...
    # ... (assicurati che il resto della classe sia presente nel tuo file)

    def on_selection_change(self, current_item, previous_item):
        # Trova il pulsante OK (AcceptRole)
        button_box = self.findChild(QDialogButtonBox)
        if not button_box:
            # Logga solo se non troviamo il contenitore dei pulsanti
            logging.error("RestoreDialog: QDialogButtonBox non trovato in on_selection_change!")
            return
        ok_button = button_box.button(QDialogButtonBox.ButtonRole.AcceptRole)

        if ok_button:
            # Recupera i dati associati all'item selezionato
            item_data = None
            if current_item:
                try:
                    # Tentativo di recuperare il percorso salvato come UserRole
                    item_data = current_item.data(Qt.ItemDataRole.UserRole)
                except Exception as e_data:
                    # Logga solo se c'è un errore nel recuperare i dati
                    logging.error(f"Errore nel recuperare i dati dall'item selezionato: {e_data}")

            # Abilita il pulsante SOLO se un item è selezionato E ha dati validi (non None)
            if current_item and item_data is not None:
                self.selected_backup_path = item_data # Salva il percorso valido
                ok_button.setEnabled(True)
            else:
                # Altrimenti, disabilita il pulsante e resetta il percorso selezionato
                self.selected_backup_path = None
                ok_button.setEnabled(False)
        else:
            # Logga solo se non troviamo il pulsante specifico OK/Accetta
            logging.error("Pulsante OK (AcceptRole) non trovato in RestoreDialog!")
        
    def get_selected_path(self):
        return self.selected_backup_path
