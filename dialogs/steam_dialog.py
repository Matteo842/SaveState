# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QApplication, QInputDialog, QMessageBox, QListWidgetItem
)
from PySide6.QtCore import Signal, Slot, Qt, QTimer

# Importa la logica necessaria
import core_logic
import logging

# --- Dialogo Gestione Steam ---
class SteamDialog(QDialog):
    # ... (Codice come prima, sembrava OK con correzioni caratteri) ...
     profile_configured = Signal(str, str)
     def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steam Games Management")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.game_list_widget = QListWidget()
        self.status_label = QLabel("Starting Steam scan...")
        self.configure_button = QPushButton("Configure Selected Profile")
        self.refresh_button = QPushButton("Refresh Games List")
        self.close_button = QPushButton("Close")
        self.configure_button.setEnabled(False)
        self.configure_button.clicked.connect(self.configure_selected_game)
        self.refresh_button.clicked.connect(self.start_steam_scan)
        self.close_button.clicked.connect(self.reject)
        self.game_list_widget.currentItemChanged.connect(lambda: self.configure_button.setEnabled(self.game_list_widget.currentItem() is not None))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Giochi Steam installati:"))
        layout.addWidget(self.game_list_widget)
        layout.addWidget(self.status_label)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.refresh_button)
        h_layout.addStretch()
        h_layout.addWidget(self.configure_button)
        h_layout.addWidget(self.close_button)
        layout.addLayout(h_layout)
        self.profiles = parent.profiles if parent else {}
        self.steam_games_data = {}
        self.steam_userdata_info = {}
        QTimer.singleShot(100, self.start_steam_scan)
     
     @Slot()
     def start_steam_scan(self):
        self.status_label.setText(self.tr("Searching for Steam installation..."))
        QApplication.processEvents()
        steam_path = core_logic.get_steam_install_path()
        if not steam_path: self.status_label.setText(self.tr("Error: Steam installation not found.")); return
        self.status_label.setText(self.tr("Searching for Steam libraries..."))
        QApplication.processEvents()
        libs = core_logic.find_steam_libraries()
        if not libs: self.status_label.setText(self.tr("Error: No Steam libraries found.")); return
        self.status_label.setText(self.tr("Scanning installed games..."))
        QApplication.processEvents()
        self.steam_games_data = core_logic.find_installed_steam_games()
        self.status_label.setText(self.tr("Searching for Steam user data..."))
        QApplication.processEvents()
        userdata_path, likely_id, possible_ids, id_details = core_logic.find_steam_userdata_info()
        self.steam_userdata_info = { 'path': userdata_path, 'likely_id': likely_id, 'possible_ids': possible_ids, 'details': id_details }
        self.populate_game_list()
        self.status_label.setText(self.tr("Found {0} games. Ready.").format(len(self.steam_games_data)))
     def populate_game_list(self):
        self.game_list_widget.clear()
        if not self.steam_games_data: self.game_list_widget.addItem("No games found."); return
        sorted_games = sorted(self.steam_games_data.items(), key=lambda item: item[1]['name'])
        for appid, game_data in sorted_games:
             profile_exists = "[PROFILO ESISTENTE]" if game_data['name'] in self.profiles else ""
             item_text = f"{game_data['name']} (AppID: {appid}) {profile_exists}"
             item = QListWidgetItem(item_text)
             item.setData(Qt.ItemDataRole.UserRole, appid)
             self.game_list_widget.addItem(item)
     
     @Slot()
     def configure_selected_game(self):
        current_item = self.game_list_widget.currentItem()
        if not current_item:
            logging.debug("Attempting to configure Steam game without selection in the list.")
            return # Esci se non c'è selezione
        
        appid = current_item.data(Qt.ItemDataRole.UserRole)
        logging.debug(f"Selected AppID for configuration: {appid}") # AppID ottenuto    

        game_data = self.steam_games_data.get(appid)        

        # Controllo subito dopo se .get() ha trovato qualcosa
        if not game_data:
            logging.error(f"Game data not found for AppID {appid} in internal dictionary self.steam_games_data.")
            QMessageBox.warning(self, "Errore Interno", f"Impossibile trovare i dettagli per l'AppID {appid}.")
            return # Esci se non abbiamo trovato i dati      
        
        profile_name = game_data['name']  # Nome corretto del gioco
        install_dir = game_data['installdir']
        logging.debug(f"Retrieved data for AppID {appid} - Name: {profile_name}, Folder: {install_dir}")
        
        steam_id_to_use = self.steam_userdata_info.get('likely_id')
        possible_ids = self.steam_userdata_info.get('possible_ids', [])
        
        if not game_data: return
        profile_name = game_data['name']; install_dir = game_data['installdir']
        steam_id_to_use = self.steam_userdata_info.get('likely_id')
        possible_ids = self.steam_userdata_info.get('possible_ids', [])
        
        # Se ci sono più ID possibili, chiedi all'utente
        if len(possible_ids) > 1:
            id_choices_display = [] # Lista di stringhe da MOSTRARE nel dialogo
            details = self.steam_userdata_info.get('details', {})
            # --- NUOVO: Mappa per risalire da stringa mostrata a ID3 ---
            display_to_id_map = {}
            index_to_select = 0 # Indice da preselezionare

            # Ciclo per creare le stringhe e la mappa
            for i, uid in enumerate(possible_ids): # uid è lo SteamID3 numerico
                user_details = details.get(uid, {})
                display_name = user_details.get('display_name', uid) # Usa nome o ID3 come fallback
                last_mod_str = user_details.get('last_mod_str', 'N/D')
                is_likely = "(Recente)" if uid == steam_id_to_use else ""

                # Crea la stringa da mostrare nel dialogo
                choice_str = f"{display_name} {is_likely} {last_mod_str}".strip()
                id_choices_display.append(choice_str)

                # Salva la mappatura: stringa visualizzata -> ID3 numerico
                display_to_id_map[choice_str] = uid

                # Salva l'indice se troviamo l'ID recente
                if uid == steam_id_to_use:
                    index_to_select = i

            # Mostra il dialogo QInputDialog.getItem
            chosen_display_str, ok = QInputDialog.getItem(
                self,
                self.tr("Selezione Profilo Steam"), # Titolo aggiornato
                self.tr("Trovati multipli profili Steam.\nSeleziona quello corretto (di solito il più recente):"),
                id_choices_display, # Usa la lista con i NOMI
                index_to_select,    # Indice predefinito (del più recente)
                False               # Non editabile
            )

            # Gestisci la scelta dell'utente
            if ok and chosen_display_str:
                # --- NUOVO: Usa la mappa per trovare l'ID3 corrispondente ---
                selected_id3 = display_to_id_map.get(chosen_display_str)
                if selected_id3:
                    steam_id_to_use = selected_id3 # Aggiorna l'ID da usare
                    print(f"DEBUG: Utente ha selezionato: '{chosen_display_str}' -> SteamID3: {steam_id_to_use}")
                else:
                    # Non dovrebbe succedere se la mappa è costruita correttamente
                    logging.error(f"Error: Unable to map choice '{chosen_display_str}' to original ID3.")
                    QMessageBox.warning(self, "Errore Interno", "Errore nel recuperare l'ID del profilo selezionato.")
                    self.status_label.setText(self.tr("Error selecting profile."))
                    return # Interrompi
            elif not ok: # Utente ha annullato
                self.status_label.setText(self.tr("Configuration cancelled (no profile selected)."))
                return # Interrompi
            # Gestisci caso (improbabile) di scelta vuota
            elif ok and not chosen_display_str:
                 self.status_label.setText(self.tr("Configuration cancelled (empty profile selection?)."))
                 return
        self.status_label.setText(self.tr("Searching path for '{0}'...").format(profile_name))
        
        guesses = core_logic.guess_save_path(
            game_name=profile_name,          # Passa il NOME GIOCO qui
            game_install_dir=install_dir,    # Passa la CARTELLA INSTALLAZIONE qui
            appid=appid,                     # Passa l'APPID qui
            steam_userdata_path=self.steam_userdata_info.get('path'),
            steam_id3_to_use=steam_id_to_use,
            is_steam_game=True               # Indica ricerca Steam
        )

        self.status_label.setText(self.tr("Found {0} possible paths.").format(len(guesses)))
        confirmed_path = None; existing_path = self.profiles.get(profile_name)
        
        # Logica per scegliere/confermare il percorso
        if not guesses and not existing_path:
             QMessageBox.information(self, "Path Not Found", "Unable to automatically find a path. Please enter it manually.")
             confirmed_path = None
        elif not guesses and existing_path:
            reply = QMessageBox.question(self, "No Path Found", f"No new path found automatically.\nDo you want to keep the current one?\n'{existing_path}'", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes: confirmed_path = existing_path
            else: confirmed_path = None
        else:
             path_choices = []
             display_str_to_path_map = {} # Mappa per recuperare il path

             # Accedi alla main window (parent) per controllare la modalità sviluppatore
             main_window = self.parent()
             show_scores = False
             if main_window and hasattr(main_window, 'developer_mode_enabled'):
                  show_scores = main_window.developer_mode_enabled
             logging.debug(f"SteamDialog: Show scores in path selection: {show_scores}")

             # La lista 'guesses' contiene tuple (path, score) ed è già ordinata da core_logic
             logging.debug(f"SteamDialog: Guesses received (sorted): {guesses}")

             # Crea le stringhe per il dialogo
             for i, (p, score) in enumerate(guesses): # Itera sulle tuple
                 display_text = ""
                 # Controlla se questo percorso corrisponde a uno esistente
                 is_current = "[ATTUALE]" if p == existing_path else ""

                 if show_scores:
                     # Mostra path, score e [ATTUALE] se necessario
                     display_text = f"{p} (Score: {score}) {is_current}".strip()
                 else:
                     # Mostra solo path e [ATTUALE] se necessario
                     display_text = f"{p} {is_current}".strip()

                 path_choices.append(display_text)
                 display_str_to_path_map[display_text] = p # Mappa stringa visualizzata -> path originale

             dialog_text = "Select the correct path for saves:"
             if existing_path: dialog_text += f"\n(Current: {existing_path})"

             # Trova l'indice della scelta corrente (se esiste) per preselezionarla
             current_selection_index = 0 # Default al primo (più probabile)
             for idx, choice_str in enumerate(path_choices):
                  # Recupera il path originale dalla mappa per il confronto
                  path_from_choice = display_str_to_path_map.get(choice_str)
                  if path_from_choice == existing_path:
                       current_selection_index = idx
                       break

             # Mostra il dialogo
             chosen_display_str, ok = QInputDialog.getItem(
                 self,
                 "Confirm Save Path",
                 dialog_text,
                 path_choices,
                 current_selection_index, # Usa l'indice trovato o 0
                 False # Non editabile
             )

             if ok and chosen_display_str:
                 # Recupera il path originale usando la mappa dalla stringa scelta
                 confirmed_path = display_str_to_path_map.get(chosen_display_str)
                 logging.debug(f"SteamDialog: User selected path: {confirmed_path}")
                 # Se confirmed_path è None qui, significa che qualcosa è andato storto nella mappa (improbabile)
                 if confirmed_path is None:
                     logging.error(f"Could not map chosen display string '{chosen_display_str}' back to path!")
                     ok = False # Tratta come se l'utente avesse annullato
             elif ok and not chosen_display_str:
                 # Scelta vuota? Tratta come annullato
                 ok = False
             # --- FINE MODIFICHE ---

             if not ok: # Se l'utente ha annullato getItem o la mappatura è fallita
                 manual_reply = QMessageBox.question(self, "Manual Entry?", "Do you want to enter the path manually?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                 if manual_reply == QMessageBox.StandardButton.Yes:
                     confirmed_path = None # Forza inserimento manuale sotto
                 else:
                     self.status_label.setText(self.tr("Configuration cancelled."))
                     return # Esce da configure_selected_game
        
        # Logica per inserimento/validazione manuale
        if confirmed_path is None:
             manual_path, ok = QInputDialog.getText(self, "Manual Path", f"Enter the full path for '{profile_name}':", text=existing_path if existing_path else "")
             if ok:
                 confirmed_path = self.parent().validate_save_path(manual_path, profile_name) # Usa il validatore della MainWindow
                 if confirmed_path is None: # Se la validazione fallisce (mostra già errore)
                       self.status_label.setText(self.tr("Configuration cancelled (invalid manual path)."))
                       return # Esci
             else: # Utente ha annullato QInputDialog
                 self.status_label.setText(self.tr("Configuration cancelled."))
                 return

        # Aggiorna/Salva solo se abbiamo un confirmed_path valido alla fine
        self.profiles[profile_name] = confirmed_path
        if core_logic.save_profiles(self.profiles):
            self.status_label.setText(self.tr("Profile '{0}' configured with path: {1}").format(profile_name, confirmed_path))
            QMessageBox.information(self, "Profile Configured", f"Profile '{profile_name}' saved.")
            self.profile_configured.emit(profile_name, confirmed_path)
            self.accept()
        else:
            QMessageBox.critical(self, "Save Error", "Unable to save profiles file.")
            self.status_label.setText(self.tr("Error saving profiles."))