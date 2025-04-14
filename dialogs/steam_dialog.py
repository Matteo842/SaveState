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
        self.setWindowTitle("Gestione Giochi Steam")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.game_list_widget = QListWidget()
        self.status_label = QLabel("Avvio scansione Steam...")
        self.configure_button = QPushButton("Configura Profilo Selezionato")
        self.refresh_button = QPushButton("Aggiorna Lista Giochi")
        self.close_button = QPushButton("Chiudi")
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
        self.status_label.setText("Ricerca installazione Steam...")
        QApplication.processEvents()
        steam_path = core_logic.get_steam_install_path()
        if not steam_path: self.status_label.setText("Errore: Installazione Steam non trovata."); return
        self.status_label.setText("Ricerca librerie Steam...")
        QApplication.processEvents()
        libs = core_logic.find_steam_libraries()
        if not libs: self.status_label.setText("Errore: Nessuna libreria Steam trovata."); return
        self.status_label.setText("Scansione giochi installati...")
        QApplication.processEvents()
        self.steam_games_data = core_logic.find_installed_steam_games()
        self.status_label.setText("Ricerca dati utente Steam...")
        QApplication.processEvents()
        userdata_path, likely_id, possible_ids, id_details = core_logic.find_steam_userdata_info()
        self.steam_userdata_info = { 'path': userdata_path, 'likely_id': likely_id, 'possible_ids': possible_ids, 'details': id_details }
        self.populate_game_list()
        self.status_label.setText(f"Trovati {len(self.steam_games_data)} giochi. Pronto.")
     def populate_game_list(self):
        self.game_list_widget.clear()
        if not self.steam_games_data: self.game_list_widget.addItem("Nessun gioco trovato."); return
        sorted_games = sorted(self.steam_games_data.items(), key=lambda item: item[1]['name'])
        for appid, game_data in sorted_games:
             profile_exists = "[PROFILO ESISTENTE]" if game_data['name'] in self.profiles else ""
             item_text = f"{game_data['name']} (AppID: {appid}) {profile_exists}"
             item = QListWidgetItem(item_text)
             item.setData(Qt.ItemDataRole.UserRole, appid)
             self.game_list_widget.addItem(item)
     
     @Slot()
     def configure_selected_game(self):
        current_item = self.game_list_widget.currentItem();
        if not current_item:
            logging.debug("Tentativo di configurare gioco Steam senza selezione nella lista.")
            return # Esci se non c'è selezione
        
        appid = current_item.data(Qt.ItemDataRole.UserRole)
        logging.debug(f"AppID selezionato per la configurazione: {appid}") # AppID ottenuto    

        game_data = self.steam_games_data.get(appid)        

        # Controllo subito dopo se .get() ha trovato qualcosa
        if not game_data:
            logging.error(f"Dati del gioco non trovati per AppID {appid} nel dizionario interno self.steam_games_data.")
            QMessageBox.warning(self, "Errore Interno", f"Impossibile trovare i dettagli per l'AppID {appid}.")
            return # Esci se non abbiamo trovato i dati      
        
        profile_name = game_data['name']  # Nome corretto del gioco
        install_dir = game_data['installdir']
        logging.debug(f"Dati recuperati per AppID {appid} - Nome: {profile_name}, Cartella: {install_dir}")
        
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
                    logging.error(f"Errore: Impossibile mappare la scelta '{chosen_display_str}' all'ID3 originale.")
                    QMessageBox.warning(self, "Errore Interno", "Errore nel recuperare l'ID del profilo selezionato.")
                    self.status_label.setText(self.tr("Errore selezione profilo."))
                    return # Interrompi
            elif not ok: # Utente ha annullato
                self.status_label.setText(self.tr("Configurazione annullata (nessun profilo selezionato)."))
                return # Interrompi
            # Gestisci caso (improbabile) di scelta vuota
            elif ok and not chosen_display_str:
                 self.status_label.setText(self.tr("Configurazione annullata (selezione profilo vuota?)."))
                 return
        self.status_label.setText(f"Ricerca percorso per '{profile_name}'..."); QApplication.processEvents()
        
        guesses = core_logic.guess_save_path(
            game_name=profile_name,          # Passa il NOME GIOCO qui
            game_install_dir=install_dir,    # Passa la CARTELLA INSTALLAZIONE qui
            appid=appid,                     # Passa l'APPID qui
            steam_userdata_path=self.steam_userdata_info.get('path'),
            steam_id3_to_use=steam_id_to_use,
            is_steam_game=True               # Indica ricerca Steam
        )

        self.status_label.setText(f"Trovati {len(guesses)} percorsi possibili.")
        confirmed_path = None; existing_path = self.profiles.get(profile_name)
        
        # Logica per scegliere/confermare il percorso
        if not guesses and not existing_path:
             QMessageBox.information(self, "Percorso Non Trovato", "Impossibile trovare automaticamente un percorso. Inseriscilo manually."); confirmed_path = None
        elif not guesses and existing_path:
            reply = QMessageBox.question(self, "Nessun Percorso Trovato", f"Nessun nuovo percorso trovato automaticamente.\nVuoi mantenere quello attuale?\n'{existing_path}'", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes: confirmed_path = existing_path
            else: confirmed_path = None
        else:
             path_choices = []; current_path_index = -1
             for i, p in enumerate(guesses): is_current = "[ATTUALE]" if p == existing_path else ""; path_choices.append(f"{p} {is_current}");
             if p == existing_path: current_path_index = i
             dialog_text = "Seleziona il percorso corretto per i salvataggi:";
             if existing_path: dialog_text += f"\n(Attuale: {existing_path})"
             chosen_path_str, ok = QInputDialog.getItem(self, "Conferma Percorso Salvataggi", dialog_text, path_choices, current_path_index if current_path_index != -1 else 0, False)
             if ok and chosen_path_str: confirmed_path = chosen_path_str.split(" [ATTUALE]")[0].strip()
             elif ok and not chosen_path_str: ok = False
             if not ok:
                 manual_reply = QMessageBox.question(self, "Inserimento Manuale?", "Vuoi inserire il percorso manualmente?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                 if manual_reply == QMessageBox.StandardButton.Yes: confirmed_path = None
                 else: self.status_label.setText("Configurazione annullata."); return
        
        # Logica per inserimento/validazione manuale
        if confirmed_path is None:
             manual_path, ok = QInputDialog.getText(self, "Percorso Manuale", f"Inserisci il percorso completo per '{profile_name}':", text=existing_path if existing_path else "")
             if ok:
                 confirmed_path = self.parent().validate_save_path(manual_path, profile_name) # Usa il validatore della MainWindow
                 if confirmed_path is None: # Se la validazione fallisce (mostra già errore)
                       self.status_label.setText("Configurazione annullata (percorso manuale non valido).")
                       return # Esci
             else: # Utente ha annullato QInputDialog
                 self.status_label.setText("Configurazione annullata.")
                 return

        # Aggiorna/Salva solo se abbiamo un confirmed_path valido alla fine
        self.profiles[profile_name] = confirmed_path
        if core_logic.save_profiles(self.profiles):
            self.status_label.setText(f"Profilo '{profile_name}' configurato con percorso: {confirmed_path}")
            QMessageBox.information(self, "Profilo Configurato", f"Profilo '{profile_name}' salvato.")
            self.profile_configured.emit(profile_name, confirmed_path)
            self.accept()
        else:
            QMessageBox.critical(self, "Errore Salvataggio", "Impossibile salvare il file dei profili.")
            self.status_label.setText("Errore nel salvataggio dei profili.")