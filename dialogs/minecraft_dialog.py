# dialogs/minecraft_dialog.py
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QLabel, QVBoxLayout,
    QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt, Slot

class MinecraftWorldsDialog(QDialog):
    """
    Dialogo per mostrare e selezionare un mondo Minecraft da una lista.
    """
    def __init__(self, worlds_data, parent=None):
        """
        Inizializza il dialogo.

        Args:
            worlds_data (list): Lista di dizionari dei mondi, prodotta da
                                 minecraft_utils.list_minecraft_worlds.
                                 Es: [{'folder_name': ..., 'world_name': ..., 'full_path': ...}, ...]
            parent (QWidget, optional): Widget genitore. Default None.
        """
        super().__init__(parent)
        self.setWindowTitle(self.tr("Seleziona Mondo Minecraft"))
        self.setMinimumWidth(400)
        self.selected_world = None # Memorizza le info del mondo selezionato

        layout = QVBoxLayout(self)

        label = QLabel(self.tr("Seleziona il mondo per cui creare un profilo:"))
        layout.addWidget(label)

        self.worlds_list_widget = QListWidget()

        if not worlds_data:
            # Caso in cui non vengono trovati mondi
            info_label = QLabel(self.tr("Nessun mondo trovato nella cartella 'saves' di Minecraft.\nVerifica che Minecraft Java Edition sia installato correttamente."))
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info_label)
            self.worlds_list_widget.setVisible(False) # Nascondi la lista vuota
        else:
            # Popola la lista
            for world_info in worlds_data:
                # Mostra il nome letto da NBT (o nome cartella se NBT fallisce)
                display_text = world_info.get('world_name', world_info.get('folder_name', 'Nome Sconosciuto'))
                item = QListWidgetItem(display_text)
                # Memorizza l'INTERO dizionario world_info nell'item
                item.setData(Qt.ItemDataRole.UserRole, world_info)
                self.worlds_list_widget.addItem(item)
            layout.addWidget(self.worlds_list_widget)

        # Pulsanti OK / Annulla
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Disabilita OK all'inizio (se ci sono mondi)
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
             ok_button.setEnabled(False if worlds_data else False) # Disabilita se lista vuota o all'inizio

        layout.addWidget(self.button_box)

        # Connetti cambio selezione per abilitare/disabilitare OK
        self.worlds_list_widget.currentItemChanged.connect(self._update_button_state)
        # Connetti doppio click per accettare subito
        self.worlds_list_widget.itemDoubleClicked.connect(self.accept)

    @Slot()
    def _update_button_state(self):
        """Abilita il pulsante OK solo se un item è selezionato."""
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            ok_button.setEnabled(self.worlds_list_widget.currentItem() is not None)

    def accept(self):
        """Sovrascrive accept per salvare l'item selezionato prima di chiudere."""
        current_item = self.worlds_list_widget.currentItem()
        if current_item:
            self.selected_world = current_item.data(Qt.ItemDataRole.UserRole)
            # Controlla che abbiamo effettivamente recuperato i dati
            if self.selected_world:
                 super().accept() # Chiama l'accept originale di QDialog
            else:
                 # Non dovrebbe succedere se UserRole è impostato correttamente
                 QMessageBox.warning(self, self.tr("Errore Selezione"), self.tr("Impossibile recuperare i dati del mondo selezionato."))
        # else: Nessun item selezionato (non dovrebbe succedere se il pulsante OK era abilitato)

    def get_selected_world_info(self):
        """
        Restituisce il dizionario con le informazioni del mondo selezionato
        dopo che il dialogo è stato accettato.
        """
        return self.selected_world