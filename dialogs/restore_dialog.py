# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QDialogButtonBox, QVBoxLayout,
    QListWidgetItem
)
from PySide6.QtCore import Qt

# Importa la logica necessaria
import core_logic
import config
import logging


class RestoreDialog(QDialog):
    # ... (Codice come prima, sembrava OK con correzioni caratteri) ...
     def __init__(self, profile_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Ripristina Backup per {profile_name}")
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
        backups = core_logic.list_available_backups(profile_name, current_backup_base_dir) # <-- Riga Nuova
        if not backups:
            no_backup_label = QLabel("Nessun backup trovato per questo profilo.")
            self.backup_list_widget.setEnabled(False)
        else:
            for name, path, date_str in backups:
                item = QListWidgetItem(f"{name} ({date_str})")
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.backup_list_widget.addItem(item)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Ripristina Selezionato")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Seleziona il backup da cui ripristinare:"))
        if no_backup_label: layout.addWidget(no_backup_label)
        layout.addWidget(self.backup_list_widget)
        layout.addWidget(buttons)
        self.backup_list_widget.currentItemChanged.connect(self.on_selection_change)
     def on_selection_change(self, current_item, previous_item):
        ok_button = self.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        if current_item and current_item.data(Qt.ItemDataRole.UserRole) is not None:
            self.selected_backup_path = current_item.data(Qt.ItemDataRole.UserRole)
            ok_button.setEnabled(True)
        else:
            self.selected_backup_path = None
            ok_button.setEnabled(False)
     def get_selected_path(self): return self.selected_backup_path

# --- Dialogo Gestione/Eliminazione Backup ---