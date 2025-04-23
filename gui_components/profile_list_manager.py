# gui_components/profile_list_manager.py
# -*- coding: utf-8 -*-
import logging
import os # Aggiunto import os
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox # Aggiunto QMessageBox
from PySide6.QtCore import Qt, QLocale, QCoreApplication, Slot, QSize # Aggiunto QSize
from PySide6.QtGui import QIcon # Aggiunto QIcon
import core_logic
import config

# Import del nuovo manager e utils
from gui_components import favorites_manager # Assumendo sia in gui_components
from gui_utils import resource_path

class ProfileListManager:
    """Gestisce la QTableWidget dei profili e i pulsanti di azione correlati."""

    def __init__(self, table_widget: QTableWidget, main_window):
        self.table_widget = table_widget
        self.main_window = main_window # Riferimento alla finestra principale
        self.profiles = main_window.profiles # Accediamo ai profili tramite main_window

        # --- Caricamento Icone Preferiti ---
        star_icon_path = resource_path("icons/star.png")
        empty_star_icon_path = resource_path("icons/emptystar.png")
        self.star_icon = QIcon(star_icon_path) if os.path.exists(star_icon_path) else None
        self.empty_star_icon = QIcon(empty_star_icon_path) if os.path.exists(empty_star_icon_path) else None
        if not self.star_icon:
            logging.warning(f"Icona preferiti 'star.png' non trovata in {star_icon_path}")
        if not self.empty_star_icon:
            logging.warning(f"Icona non-preferiti 'emptystar.png' non trovata in {empty_star_icon_path}")
        # --- Fine Caricamento Icone ---

        # Configura la tabella
        self.table_widget.setObjectName("ProfileTable")
        self.table_widget.setColumnCount(3)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_widget.verticalHeader().setVisible(False)
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Impostazioni Header
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Colonna 0: Icona Preferiti
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)        # Colonna 1: Nome Profilo
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Colonna 2: Info Backup
        self.table_widget.verticalHeader().setDefaultSectionSize(32)
        self.table_widget.setColumnWidth(0, 32)

        # Connessioni segnali
        # Cambio selezione riga (gestito da MainWindow)
        self.table_widget.itemSelectionChanged.connect(self.main_window.update_action_button_states)
        # Click su cella (per gestire toggle preferito)
        self.table_widget.cellClicked.connect(self.handle_favorite_toggle) # <-- Aggiunto

        self.retranslate_headers() # Imposta intestazioni iniziali
        # self.update_profile_table() # Verrà chiamato da MainWindow dopo __init__


    def retranslate_headers(self):
        """Aggiorna le etichette delle intestazioni della tabella."""
        self.table_widget.setHorizontalHeaderLabels([
            "", # Header vuoto per colonna preferiti
            QCoreApplication.translate("MainWindow", "Profilo"),
            "Info Backup"
        ])

    def get_selected_profile_name(self):
        """Restituisce il nome del profilo selezionato nella tabella (legge dalla colonna NOME, ora indice 1)."""
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if selected_rows:
            first_row_index = selected_rows[0].row()
            name_item = self.table_widget.item(first_row_index, 1) # <-- Indice 1 per il nome
            if name_item and name_item.data(Qt.ItemDataRole.UserRole):
                return name_item.data(Qt.ItemDataRole.UserRole)
        return None

    def select_profile_in_table(self, profile_name_to_select):
        """Seleziona la riga corrispondente al nome del profilo (cerca in colonna 1)."""
        if not profile_name_to_select:
            return
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 1) # <-- Cerca nome in colonna 1
            if item and item.data(Qt.ItemDataRole.UserRole) == profile_name_to_select:
                self.table_widget.selectRow(row)
                logging.debug(f"Profile '{profile_name_to_select}' selected in table at row {row}.")
                return
        logging.warning(f"Tried to select profile '{profile_name_to_select}', but not found in table.")


    def update_profile_table(self):
        """Aggiorna QTableWidget con i profili (ordinati per preferiti) e le info sui backup."""
        self.profiles = self.main_window.profiles # Ricarica profili da main_window
        selected_profile_name = self.get_selected_profile_name() # Salva selezione corrente
        logging.debug(f"Updating profile table. Previously selected: {selected_profile_name}")

        # --- Carica stato preferiti ---
        favorites_status = favorites_manager.load_favorites()
        # --- Fine Caricamento ---

        self.table_widget.setRowCount(0) # Svuota la tabella

        # --- Ordinamento (Preferiti prima, poi Alfabetico) ---
        profile_names = list(self.profiles.keys())
        sorted_profiles = sorted(
            profile_names,
            key=lambda name: (not favorites_status.get(name, False), name.lower())
        )
        logging.debug(f"Profile list sorted for display (favorites first): {sorted_profiles}")
        # --- Fine Ordinamento ---

        if not sorted_profiles:
            # Mostra riga "Nessun profilo"
            self.table_widget.setRowCount(1)
            item_fav_placeholder = QTableWidgetItem("") # Placeholder colonna 0
            item_nome = QTableWidgetItem(
                QCoreApplication.translate("MainWindow", "Nessun profilo creato.")
            )
            item_info = QTableWidgetItem("")
            # Non impostare UserRole per placeholder fav o impostalo a None
            item_nome.setData(Qt.ItemDataRole.UserRole, None)
            # Rendi la riga non selezionabile
            flags = item_nome.flags() & ~Qt.ItemFlag.ItemIsSelectable
            item_fav_placeholder.setFlags(flags)
            item_nome.setFlags(flags)
            item_info.setFlags(flags)
            # Potresti cambiare il colore del testo
            # Inserisci su 3 colonne
            self.table_widget.setItem(0, 0, item_fav_placeholder)
            self.table_widget.setItem(0, 1, item_nome)
            self.table_widget.setItem(0, 2, item_info)
            self.table_widget.setEnabled(False)
        else:
            # Popola tabella con i profili ordinati
            self.table_widget.setEnabled(True)
            row_to_reselect = -1
            for row_index, profile_name in enumerate(sorted_profiles):
                profile_data = self.profiles.get(profile_name, {})
                is_favorite = favorites_status.get(profile_name, False)
                save_path = profile_data.get('path', '') # Recupera percorso

                # Recupera info backup
                current_backup_base_dir = self.main_window.current_settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
                # Passa save_path a get_profile_backup_summary (assicurati che la funzione lo accetti)
                # Se get_profile_backup_summary non accetta save_path, dovrai usare una logica diversa qui
                count, last_backup_dt = core_logic.get_profile_backup_summary(profile_name, current_backup_base_dir) # Rimuovi save_path se non serve

                info_str = ""
                if count > 0:
                    date_str = "N/D"
                    if last_backup_dt:
                        try:
                            lang_code = self.main_window.current_settings.get("language", "en")
                            locale = QLocale(QLocale.Language.English if lang_code == "en" else QLocale.Language.Italian)
                            date_str = locale.toString(last_backup_dt, QLocale.FormatType.ShortFormat)
                        except Exception as e:
                            logging.error(f"Error formatting last backup date for {profile_name}: {e}", exc_info=True)
                            date_str = "???"

                    backup_label_singular = "Backup"
                    backup_label_plural = "Backups"
                    last_label = QCoreApplication.translate("MainWindow", "Ultimo")
                    backup_label = backup_label_singular if count == 1 else backup_label_plural
                    info_str = f"{backup_label}: {count} | {last_label}: {date_str}"
                else:
                     info_str = QCoreApplication.translate("MainWindow", "Nessun backup")

                # --- Creazione Item Preferiti (Colonna 0) ---
                fav_item = QTableWidgetItem()
                fav_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if is_favorite and self.star_icon:
                    fav_item.setIcon(self.star_icon)
                    fav_item.setToolTip(self.main_window.tr("Rimuovi dai preferiti"))
                elif self.empty_star_icon:
                    fav_item.setIcon(self.empty_star_icon)
                    fav_item.setToolTip(self.main_window.tr("Aggiungi ai preferiti"))
                else:
                     fav_item.setToolTip(self.main_window.tr("Aggiungi/Rimuovi preferito")) # Fallback

                fav_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                fav_item.setData(Qt.ItemDataRole.UserRole, profile_name) # Salva nome per toggle
                fav_item.setSizeHint(QSize(32, 32))
                # --- Fine Creazione Item Preferiti ---

                # --- Creazione Item Nome (Colonna 1) ---
                name_item = QTableWidgetItem(profile_name)
                name_item.setData(Qt.ItemDataRole.UserRole, profile_name) # Salva nome per selezione riga

                # --- Creazione Item Info (Colonna 2) ---
                info_item = QTableWidgetItem(info_str)
                info_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

                # Inserisci riga e item nelle colonne corrette
                self.table_widget.insertRow(row_index)
                self.table_widget.setItem(row_index, 0, fav_item)
                self.table_widget.setItem(row_index, 1, name_item)
                self.table_widget.setItem(row_index, 2, info_item)

                # Controlla se riselezionare la riga
                if profile_name == selected_profile_name:
                    row_to_reselect = row_index

            # Riseleziona la riga
            if row_to_reselect != -1:
                logging.debug(f"Reselecting row {row_to_reselect} for profile '{selected_profile_name}'")
                self.table_widget.selectRow(row_to_reselect)
            elif selected_profile_name:
                 logging.debug(f"Previously selected profile '{selected_profile_name}' not found after update.")

        # Aggiorna stato pulsanti DOPO aver popolato la tabella
        self.main_window.update_action_button_states()
        logging.debug("Profile table update finished.")

    @Slot(int, int)
    def handle_favorite_toggle(self, row, column):
        """Gestisce il click sulla cella per cambiare lo stato preferito."""
        if column == 0: # Solo se clicco sulla prima colonna (Preferiti)
            item = self.table_widget.item(row, 0)
            if not item: return # Sicurezza

            profile_name = item.data(Qt.ItemDataRole.UserRole)
            # Verifica aggiuntiva che il nome sia valido nei profili correnti
            if not profile_name or profile_name not in self.profiles:
                 logging.warning(f"Favorite toggle requested for invalid or non-existent profile: row {row}, name '{profile_name}'")
                 return

            logging.debug(f"Click su colonna Preferiti per: '{profile_name}'")

            # Inverte lo stato usando il manager e controlla il successo
            success = favorites_manager.toggle_favorite(profile_name)

            if success:
                # Rileggi lo stato *appena salvato* per sicurezza
                new_status = favorites_manager.is_favorite(profile_name)

                # Aggiorna l'icona e il tooltip nella cella cliccata
                if new_status and self.star_icon:
                    item.setIcon(self.star_icon)
                    item.setToolTip(self.main_window.tr("Rimuovi dai preferiti"))
                elif self.empty_star_icon: # Usa stella vuota se disponibile
                    item.setIcon(self.empty_star_icon)
                    item.setToolTip(self.main_window.tr("Aggiungi ai preferiti"))
                else: # Fallback senza icona stella vuota
                    item.setIcon(QIcon()) # Rimuovi icona
                    item.setToolTip(self.main_window.tr("Aggiungi/Rimuovi preferito"))

                # --- Aggiorna la tabella per riordinare ---
                logging.debug("Aggiornamento tabella per applicare ordinamento preferiti...")
                self.update_profile_table()
                # Nota: update_profile_table() tenterà di riselezionare l'ultima riga selezionata

            else:
                # Il salvataggio è fallito (manager ha già loggato l'errore)
                QMessageBox.warning(self.main_window,
                                    self.main_window.tr("Errore"),
                                    self.main_window.tr("Impossibile salvare lo stato preferito per '{0}'.").format(profile_name))
                # Non aggiorniamo l'icona nella GUI se il salvataggio non va a buon fine