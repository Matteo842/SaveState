# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QDialogButtonBox, QVBoxLayout,
    QListWidgetItem
)
from PySide6.QtCore import Qt

import core_logic
import config
import logging


class RestoreDialog(QDialog):
    def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Ripristina Backup per {}").format(profile_name))
        self.setMinimumWidth(450)
        self.backup_list_widget = QListWidget()
        self.selected_backup_path = None
        no_backup_label = None

        # Recupera il percorso base CORRENTE dalle impostazioni del parent
        current_backup_base_dir = "" # Default vuoto
        if parent and hasattr(parent, 'current_settings'): # Controlla se parent e settings esistono
            current_backup_base_dir = parent.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        else:
            # Fallback se non riusciamo a ottenere le impostazioni (improbabile)
            logging.warning("RestoreDialog: Impossibile accedere a current_settings dal parent. Uso il default da config.")
            current_backup_base_dir = config.BACKUP_BASE_DIR

        # Chiama la funzione passando il percorso recuperato
        backups = core_logic.list_available_backups(profile_name, current_backup_base_dir)
        if not backups:
            # CORRETTO: Usa self.tr() per il testo dell'etichetta
            no_backup_label = QLabel(self.tr("Nessun backup trovato per questo profilo."))
            self.backup_list_widget.setEnabled(False)
        else:
            for name, path, date_str in backups:
                display_name = core_logic.get_display_name_from_backup_filename(name)
                item_text = f"{display_name} ({date_str})" # Usa il nome pulito
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.backup_list_widget.addItem(item)

        # Usa la traduzione standard per OK e Cancel se possibile, altrimenti sovrascrivi)
        # Scegliamo di personalizzare OK e usare il Cancel standard
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(self.tr("Ripristina Selezionato"), QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel) # Qt gestisce la traduzione di "Cancel"

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button.setEnabled(False) # Disabilita OK all'inizio

        layout = QVBoxLayout(self)
        # CORRETTO: Usa self.tr() per il testo dell'etichetta
        layout.addWidget(QLabel(self.tr("Seleziona il backup da cui ripristinare:")))
        if no_backup_label: layout.addWidget(no_backup_label)
        layout.addWidget(self.backup_list_widget)
        layout.addWidget(buttons)

        self.backup_list_widget.currentItemChanged.connect(self.on_selection_change)

    def on_selection_change(self, current_item, previous_item):
        # Trova il pulsante OK tramite il suo ruolo o riferimento
        button_box = self.findChild(QDialogButtonBox)
        ok_button = button_box.button(QDialogButtonBox.ButtonRole.AcceptRole) # Trova tramite ruolo

        if ok_button: # Aggiunto controllo per sicurezza
            if current_item and current_item.data(Qt.ItemDataRole.UserRole) is not None:
                self.selected_backup_path = current_item.data(Qt.ItemDataRole.UserRole)
                ok_button.setEnabled(True)
            else:
                self.selected_backup_path = None
                ok_button.setEnabled(False)
        else:
             logging.error("Pulsante OK non trovato in RestoreDialog!")


    def get_selected_path(self):
        return self.selected_backup_path
