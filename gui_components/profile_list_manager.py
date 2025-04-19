# gui_components/profile_list_manager.py
# -*- coding: utf-8 -*-
import logging
import os
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QPushButton, QMessageBox
from PySide6.QtCore import Qt, QLocale
import core_logic
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QPushButton, QMessageBox, QHeaderView
import config
class ProfileListManager:
    """Gestisce la QTableWidget dei profili e i pulsanti di azione correlati."""

    def __init__(self, table_widget: QTableWidget, main_window):
        self.table_widget = table_widget
        self.main_window = main_window # Riferimento alla finestra principale per accedere a self.tr, self.profiles, self.current_settings
        self.profiles = main_window.profiles # Accediamo ai profili tramite main_window

        # Configura la tabella (questo potrebbe essere fatto anche in MainWindow __init__)
        self.table_widget.setObjectName("ProfileTable")
        self.table_widget.setColumnCount(2)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_widget.verticalHeader().setVisible(False)
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) # Usa QHeaderView qui
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # Usa QHeaderView qui

        # Connetti il segnale di cambio selezione INTERNAMENTE al manager
        self.table_widget.itemSelectionChanged.connect(self.main_window.update_action_button_states) # Chiama il metodo aggiornato in MainWindow

        self.retranslate_headers() # Imposta le intestazioni iniziali
        #self.update_profile_table() # Popola la tabella inizialmente


    def retranslate_headers(self):
        """Aggiorna le etichette delle intestazioni della tabella."""
        self.table_widget.setHorizontalHeaderLabels([
            self.main_window.tr("Profilo"),
            "Info Backup"
        ])

    def get_selected_profile_name(self):
        """Restituisce il nome del profilo selezionato nella tabella."""
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if selected_rows:
            first_row_index = selected_rows[0].row()
            name_item = self.table_widget.item(first_row_index, 0)
            # Controlla che l'item esista e che contenga dati utente (potrebbe essere la riga "Nessun profilo")
            if name_item and name_item.data(Qt.ItemDataRole.UserRole):
                return name_item.data(Qt.ItemDataRole.UserRole)
        return None

    def select_profile_in_table(self, profile_name_to_select):
        """Seleziona la riga corrispondente al nome del profilo."""
        if not profile_name_to_select:
            return
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == profile_name_to_select:
                self.table_widget.selectRow(row)
                logging.debug(f"Profile '{profile_name_to_select}' selected in table at row {row}.")
                return # Trovato e selezionato
        logging.warning(f"Tried to select profile '{profile_name_to_select}', but not found in table.")


    def update_profile_table(self):
        """Aggiorna QTableWidget con i profili e le info sui backup."""
        # Ricarica i profili da main_window in caso siano cambiati esternamente
        self.profiles = self.main_window.profiles
        selected_profile_name = self.get_selected_profile_name() # Salva selezione corrente
        logging.debug(f"Updating profile table. Previously selected: {selected_profile_name}")
        self.table_widget.setRowCount(0) # Svuota la tabella

        sorted_profiles = sorted(self.profiles.keys())

        if not sorted_profiles:
            # Mostra riga "Nessun profilo"
            self.table_widget.setRowCount(1)
            item_nome = QTableWidgetItem(self.main_window.tr("Nessun profilo creato."))
            item_info = QTableWidgetItem("")
            # Importante: Non impostare UserRole qui o impostalo a None
            item_nome.setData(Qt.ItemDataRole.UserRole, None)
            # Rendi la riga non selezionabile e grigia?
            flags = item_nome.flags() & ~Qt.ItemFlag.ItemIsSelectable
            item_nome.setFlags(flags)
            item_info.setFlags(flags)
            # Potresti anche cambiare il colore del testo per renderlo più ovvio
            # item_nome.setForeground(self.table_widget.palette().color(QPalette.ColorRole.Disabled, QPalette.ColorGroup.Text))
            self.table_widget.setItem(0, 0, item_nome)
            self.table_widget.setItem(0, 1, item_info)
            self.table_widget.setEnabled(False) # Disabilita intera tabella
        else:
            # Popola tabella con i profili
            self.table_widget.setEnabled(True) # Assicura che la tabella sia abilitata
            row_to_reselect = -1
            for row_index, profile_name in enumerate(sorted_profiles):
                # Righe 98-101 riscritte:
                current_backup_base_dir = self.main_window.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
                count, last_backup_dt = core_logic.get_profile_backup_summary(profile_name, current_backup_base_dir)
                info_str = ""
                # La riga successiva dovrebbe essere l'if (riga 103 nello screenshot)
                if count > 0:
                    date_str = "N/D"
                    if last_backup_dt:
                        try:
                            # Usa le impostazioni correnti della main_window per la lingua
                            lang_code = self.main_window.current_settings.get("language", "en")
                            locale = QLocale(QLocale.Language.English if lang_code == "en" else QLocale.Language.Italian)
                            # Formato data/ora breve appropriato per la locale
                            date_str = locale.toString(last_backup_dt, QLocale.FormatType.ShortFormat)
                            # Formato personalizzato (Mese abbreviato + giorno)
                            # date_str = locale.toString(last_backup_dt, "MMM d")
                        except Exception as e:
                            logging.error(f"Error formatting last backup date for {profile_name}: {e}", exc_info=True)
                            date_str = "???"

                    # Traduzione etichette
                    backup_label_singular = "Backup"
                    backup_label_plural = "Backups"
                    last_label = self.main_window.tr("Ultimo")
                    backup_label = backup_label_singular if count == 1 else backup_label_plural
                    info_str = f"{backup_label}: {count} | {last_label}: {date_str}"
                else:
                     info_str = self.main_window.tr("Nessun backup") # O lascia vuoto ""

                name_item = QTableWidgetItem(profile_name)
                name_item.setData(Qt.ItemDataRole.UserRole, profile_name) # Memorizza nome profilo nell'item
                info_item = QTableWidgetItem(info_str)
                info_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                self.table_widget.insertRow(row_index)
                self.table_widget.setItem(row_index, 0, name_item)
                self.table_widget.setItem(row_index, 1, info_item)

                # Controlla se questo era il profilo selezionato prima dell'aggiornamento
                if profile_name == selected_profile_name:
                    row_to_reselect = row_index

            # Riseleziona la riga che era selezionata, se esiste ancora
            if row_to_reselect != -1:
                logging.debug(f"Reselecting row {row_to_reselect} for profile '{selected_profile_name}'")
                self.table_widget.selectRow(row_to_reselect)
            elif selected_profile_name: # Se c'era una selezione ma il profilo non c'è più
                 logging.debug(f"Previously selected profile '{selected_profile_name}' not found after update.")
                 # La selezione verrà resettata automaticamente


        # Aggiorna stato pulsanti DOPO aver popolato la tabella e (ri)selezionato la riga
        self.main_window.update_action_button_states()
        logging.debug("Profile table update finished.")