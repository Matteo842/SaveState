# -*- coding: utf-8 -*-
import os
from PySide6.QtWidgets import (
    QDialog, QListWidget, QPushButton, QLabel, QHBoxLayout, QVBoxLayout,
    QMessageBox, QApplication, QStyle, QListWidgetItem
)
from PySide6.QtCore import Slot, Qt

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
     def populate_backup_list(self):
        self.backup_list_widget.clear()
        self.delete_button.setEnabled(False)
       
        # Recupera il percorso base CORRENTE dalle impostazioni del parent
        current_backup_base_dir = "" # Default vuoto
        parent_window = self.parent() # Ottieni il parent una sola volta
        if parent_window and hasattr(parent_window, 'current_settings'):
            current_backup_base_dir = parent_window.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
        else:
            logging.warning("ManageBackupsDialog: Impossibile accedere a current_settings dal parent. Uso il default da config.")
            current_backup_base_dir = config.BACKUP_BASE_DIR

        # Chiama la funzione passando il percorso recuperato
        backups = core_logic.list_available_backups(self.profile_name, current_backup_base_dir) # <-- Riga Nuova
        if not backups:
            item = QListWidgetItem(self.tr("Nessun backup trovato."))
            item.setData(Qt.ItemDataRole.UserRole, None)
            self.backup_list_widget.addItem(item)
            self.backup_list_widget.setEnabled(False)
        else:
            self.backup_list_widget.setEnabled(True)
            for name, path, date_str in backups:
                display_name = core_logic.get_display_name_from_backup_filename(name)
                item_text = f"{display_name} ({date_str})" # Usa il nome pulito
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.backup_list_widget.addItem(item)
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