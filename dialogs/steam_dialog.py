# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QApplication, QInputDialog, QMessageBox, QListWidgetItem
)
from PySide6.QtCore import Signal, Slot, Qt, QTimer

# Importa la logica necessaria
# Assicurati che core_logic sia accessibile (stessa cartella o nel PYTHONPATH)
import core_logic
import logging
import os

# --- Dialogo Gestione Steam ---
class SteamDialog(QDialog):
    """
    Dialogo per visualizzare i giochi Steam installati, selezionarne uno
    e configurare il percorso dei salvataggi associato.
    """
    #profile_configured = Signal(str, str) # Segnale emesso quando un profilo è configurato (nome, percorso)
    game_selected_for_config = Signal(str, str)

    def __init__(self, main_window_ref, parent=None):
        super().__init__(parent)
        self.main_window_ref = main_window_ref
        self.setWindowTitle(self.tr("Gestione dei giochi Steam")) # Traduci titolo
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        # Riferimenti interni
        self.steam_search_thread = None # Non verrà più usato qui
        # Ottieni profiles e steam_games_data dal parent per popolare la lista
        self.profiles = parent.profiles if parent and hasattr(parent, 'profiles') else {}
        self.steam_games_data = parent.steam_games_data if parent and hasattr(parent, 'steam_games_data') else {} # Assumi che MainWindow lo abbia
        self.steam_userdata_info = parent.steam_userdata_info if parent and hasattr(parent, 'steam_userdata_info') else {} # Assumi che MainWindow lo abbia

        # --- Creazione Widget UI (come prima) ---
        self.game_list_widget = QListWidget()
        self.status_label = QLabel(self.tr("Seleziona un gioco e clicca Configura.")) # Testo cambiato
        self.configure_button = QPushButton(self.tr("Configura Profilo Selezionato"))
        self.refresh_button = QPushButton(self.tr("Aggiorna elenco giochi"))
        self.close_button = QPushButton(self.tr("Chiudi"))
        self.configure_button.setEnabled(False)

       # --- Layout (come prima) ---
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Giochi Steam installati:")))
        layout.addWidget(self.game_list_widget)
        layout.addWidget(self.status_label)
        h_layout = QHBoxLayout()
        h_layout.addWidget(self.refresh_button)
        h_layout.addStretch()
        h_layout.addWidget(self.configure_button)
        h_layout.addWidget(self.close_button)
        layout.addLayout(h_layout)


        # # --- Connessioni Segnali/Slot ---
        # configure_button ora chiama un metodo diverso o direttamente l'emissione+accept
        self.configure_button.clicked.connect(self._emit_selection_and_accept) # <-- CAMBIATO
        self.refresh_button.clicked.connect(self.start_steam_scan) # Questo rimane? O la scansione la fa MainWindow? Meglio MainWindow.
        self.close_button.clicked.connect(self.reject)
        self.game_list_widget.currentItemChanged.connect(
            lambda item: self.configure_button.setEnabled(item is not None)
        )

        # Popola subito la lista con i dati passati dal parent
        self.populate_game_list()
    
    @Slot()
    def start_steam_scan(self):
         # ... (Logica di scansione come prima) ...
         # Aggiorna i dati nel parent (MainWindow) se fai Refresh qui!
         parent_window = self.parent()
         if parent_window:
             parent_window.steam_games_data = self.steam_games_data
             parent_window.steam_userdata_info = self.steam_userdata_info
         self.populate_game_list() # Aggiorna la lista in questo dialogo
         self.status_label.setText(self.tr("Elenco aggiornato. {0} giochi trovati.").format(len(self.steam_games_data)))


    def populate_game_list(self):
        self.game_list_widget.clear()
        if not self.steam_games_data:
             self.game_list_widget.addItem(self.tr("Nessun gioco trovato."))
             self.configure_button.setEnabled(False) # Disabilita se non ci sono giochi
             return

        self.configure_button.setEnabled(self.game_list_widget.currentItem() is not None) # Abilita se c'è selezione
        sorted_games = sorted(self.steam_games_data.items(), key=lambda item: item[1]['name'])
        for appid, game_data in sorted_games:
            profile_exists_marker = self.tr("[PROFILO ESISTENTE]") if game_data['name'] in self.profiles else ""
            item_text = f"{game_data['name']} (AppID: {appid}) {profile_exists_marker}".strip()
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, appid)
            self.game_list_widget.addItem(item)
    
    # --- NUOVO METODO per emettere segnale e chiudere ---
    @Slot()
    def _emit_selection_and_accept(self):
        current_item = self.game_list_widget.currentItem()
        if not current_item:
            return

        appid = current_item.data(Qt.ItemDataRole.UserRole)
        game_data = self.steam_games_data.get(appid)

        if not game_data or not appid:
             QMessageBox.warning(self, self.tr("Errore"), self.tr("Impossibile ottenere dati del gioco selezionato."))
             return

        profile_name = game_data['name']
        logging.info(f"[SteamDialog] Game selected: '{profile_name}' (AppID: {appid}). Emitting signal and closing.")
        self.game_selected_for_config.emit(appid, profile_name)
        self.accept() # Chiude il dialogo SUBITO

    @Slot(list, bool)
    def on_steam_search_finished(self, guesses_with_scores, effect_was_shown):
        """Slot chiamato quando SteamSearchWorkerThread ha terminato la ricerca."""
        # Import necessari qui dentro
        from PySide6.QtWidgets import QMessageBox, QInputDialog
        import os
        main_window = self.main_window_ref

        # Prova a importare MainWindow per il controllo del tipo e developer mode
        try:
             from SaveState_gui import MainWindow
        except ImportError:
             MainWindow = None

        # --- LOG INPUT RAW ---
        logging.debug(f"ON_SEARCH_FINISHED: Received {len(guesses_with_scores)} raw guesses from core_logic:")
        if not guesses_with_scores:
             logging.debug("  (List is empty)")
        else:
             max_raw_to_log = 20
             for idx, (raw_p, raw_s) in enumerate(guesses_with_scores[:max_raw_to_log]):
                 logging.debug(f"  Raw Guess {idx}: Path='{raw_p}', Score={raw_s}")
             if len(guesses_with_scores) > max_raw_to_log:
                 logging.debug(f"  (Plus {len(guesses_with_scores) - max_raw_to_log} more raw guesses)")
        # --- FINE LOG INPUT RAW ---

        main_window = self.main_window_ref
        if effect_was_shown and MainWindow is not None and isinstance(main_window, MainWindow):
             logging.debug("[SteamDialog] Deactivating fade effect on MainWindow...")
             try:
                  if hasattr(main_window, 'fade_out_animation'): main_window.fade_out_animation.start()
                  elif hasattr(main_window, 'overlay_widget'): main_window.overlay_widget.hide()
             except Exception as e_fade_stop:
                  logging.error(f"Error stopping fade effect: {e_fade_stop}", exc_info=True)
                  if hasattr(main_window, 'overlay_widget'): main_window.overlay_widget.hide()

        # --- GESTIONE RISULTATI DELLA RICERCA ---
        self.setEnabled(True)

        profile_name = getattr(self, 'current_configuring_profile_name', None)
        if not profile_name:
            logging.error("[SteamDialog] Could not retrieve profile name in on_steam_search_finished. Aborting config.")
            QMessageBox.critical(self, self.tr("Errore Interno"),
                                 self.tr("Impossibile recuperare il nome del profilo in configurazione."))
            self.reject() # Chiude il dialogo Steam con 'rifiuto'
            return

        confirmed_path = None # Percorso finale che verrà salvato
        existing_path = self.profiles.get(profile_name)
        logging.debug(f"ON_SEARCH_FINISHED: Existing path for '{profile_name}' is '{existing_path}'")

        # --- Logica per scegliere/confermare il percorso ---

        # --- INIZIO BLOCCO RIPRISTINATO ---
        if not guesses_with_scores: # La ricerca non ha trovato nulla
            logging.info("ON_SEARCH_FINISHED: No paths guessed by core_logic.")
            if not existing_path:
                # Nessun suggerimento e nessun profilo esistente -> Forza inserimento manuale
                logging.debug("  No existing path found. Forcing manual input.")
                QMessageBox.information(self, self.tr("Percorso Non Trovato"),
                                        self.tr("Impossibile trovare automaticamente un percorso per '{0}'.\n"
                                                "Per favore, inseriscilo manualmente.").format(profile_name))
                confirmed_path = self._ask_for_manual_path(profile_name, existing_path) # Chiamiamo helper per input manuale
            else:
                # Nessun suggerimento, ma profilo esiste -> Chiedi se mantenere o inserire manualmente
                logging.debug(f"  Existing path '{existing_path}' found. Asking user.")
                reply = QMessageBox.question(self, self.tr("Nessun Nuovo Percorso Trovato"),
                                             self.tr("La ricerca automatica non ha trovato nuovi percorsi.\n"
                                                     "Vuoi mantenere il percorso attuale?\n'{0}'")
                                             .format(existing_path),
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    logging.debug("  User chose to keep existing path.")
                    confirmed_path = existing_path
                elif reply == QMessageBox.StandardButton.No:
                     logging.debug("  User chose to enter path manually.")
                     confirmed_path = self._ask_for_manual_path(profile_name, existing_path) # Chiamiamo helper
                else: # Cancel
                    logging.debug("  User cancelled.")
                    self.status_label.setText(self.tr("Configurazione annullata."))
                    self.reject()
                    return # Esce dalla funzione
        # --- FINE BLOCCO RIPRISTINATO ---

        else: # Trovati uno o più suggerimenti (Blocco con deduplicazione)
            path_choices = []
            display_text_to_original_path = {}
            added_normalized_paths_for_display = set()
            original_path_order = [p for p, s in guesses_with_scores]

            show_scores = False
            if MainWindow is not None and isinstance(main_window, MainWindow) and hasattr(main_window, 'developer_mode_enabled'):
                 show_scores = main_window.developer_mode_enabled
            logging.debug(f"ON_SEARCH_FINISHED: Developer mode (show scores): {show_scores}")

            logging.debug(f"ON_SEARCH_FINISHED: --- Start UI Choice Deduplication ---")
            # Ciclo di Deduplicazione...
            for i, (p, score) in enumerate(guesses_with_scores):
                logging.debug(f"ON_SEARCH_FINISHED: Processing guess {i}: Path='{p}', Score={score}")
                try:
                    normalized_path_check = os.path.normpath(p).lower()
                    logging.debug(f"  Normalized path for check: '{normalized_path_check}'")
                except Exception as e_norm:
                    logging.error(f"  Error normalizing path '{p}': {e_norm}. Skipping this guess.")
                    continue

                if normalized_path_check not in added_normalized_paths_for_display:
                    logging.debug(f"  Path '{normalized_path_check}' is NEW for display list.")
                    added_normalized_paths_for_display.add(normalized_path_check)
                    is_current_marker = self.tr("[ATTUALE]") if p == existing_path else ""
                    score_str = f"(Score: {score})" if show_scores else ""
                    display_text = f"{p} {score_str} {is_current_marker}".strip().replace("  ", " ")
                    path_choices.append(display_text)
                    display_text_to_original_path[display_text] = p
                    logging.debug(f"  Added unique UI choice: '{display_text}' (maps to '{p}')")
                else:
                     logging.debug(f"  Path '{normalized_path_check}' ALREADY ADDED. Skipping UI duplicate for: '{p}'")
            logging.debug(f"ON_SEARCH_FINISHED: --- End UI Choice Deduplication ---")
            logging.debug(f"ON_SEARCH_FINISHED: Final unique path_choices list for dialog ({len(path_choices)} items): {path_choices}")

            # Determina indice preselezione...
            current_selection_index = 0
            if existing_path:
                 display_str_for_existing = None
                 for disp_text, orig_path in display_text_to_original_path.items():
                     if orig_path == existing_path: display_str_for_existing = disp_text; break
                 if display_str_for_existing in path_choices:
                      try: current_selection_index = path_choices.index(display_str_for_existing)
                      except ValueError: current_selection_index = 0
                 else: logging.debug(f"  Existing path was likely deduplicated, not preselecting.")

            # Aggiungi opzione manuale
            manual_option_str = self.tr("--- Inserisci percorso manualmente ---")
            path_choices.append(manual_option_str)

            dialog_text = self.tr("Sono stati trovati questi percorsi potenziali per '{0}'.\n"
                                 "Seleziona quello corretto (ordinati per probabilità) o scegli l'inserimento manuale:") \
                                 .format(profile_name)

            # Mostra dialogo scelta
            logging.debug(f"ON_SEARCH_FINISHED: Showing QInputDialog with {len(path_choices)} choices.")
            chosen_display_str, ok = QInputDialog.getItem(
                self, self.tr("Conferma Percorso Salvataggi"), dialog_text,
                path_choices, current_selection_index, False
            )

            # Gestione scelta utente...
            if ok and chosen_display_str:
                if chosen_display_str == manual_option_str:
                    confirmed_path = self._ask_for_manual_path(profile_name, existing_path)
                else:
                    confirmed_path = display_text_to_original_path.get(chosen_display_str)
                    if confirmed_path is None:
                        logging.error(f"Error mapping selected choice '{chosen_display_str}' back to path.")
                        QMessageBox.critical(self, self.tr("Errore Interno"), self.tr("Errore nella selezione del percorso."))
                        self.reject(); return
            else: # Utente ha annullato
                self.status_label.setText(self.tr("Configurazione annullata."))
                self.reject(); return

        # --- Salvataggio del Profilo (come prima) ---
        if confirmed_path:
             logging.info(f"Saving profile '{profile_name}' with path '{confirmed_path}'")
             self.profiles[profile_name] = confirmed_path
             if core_logic.save_profiles(self.profiles):
                  self.status_label.setText(self.tr("Profilo '{0}' configurato.").format(profile_name))
                  # Non serve più il QMessageBox qui, basta emettere il segnale
                  self.profile_configured.emit(profile_name, confirmed_path)
                  self.accept() # Chiude questo dialogo con successo
             else:
                  QMessageBox.critical(self, self.tr("Errore Salvataggio"),
                                         self.tr("Impossibile salvare il file dei profili."))
                  self.status_label.setText(self.tr("Errore durante il salvataggio dei profili."))
                  self.reject() # Chiudi se fallisce
        else:
             # confirmed_path è None (manuale annullato o errore validazione nel blocco 'if not guesses')
             logging.warning(f"Configuration cancelled or failed for profile '{profile_name}' (confirmed_path is empty/None).")
             # Lo status label è già stato impostato nei blocchi sopra in caso di annullamento
             self.reject() # Chiudi senza salvare

    def _get_validator_func(self):
        """Restituisce la funzione di validazione del percorso, prendendola da MainWindow se possibile."""
        main_window = self.main_window_ref
        #main_window = self.parent()
        validator_func = None
        if main_window and hasattr(main_window, 'profile_creation_manager') and \
           hasattr(main_window.profile_creation_manager, 'validate_save_path'):
            validator_func = main_window.profile_creation_manager.validate_save_path
            logging.debug("[SteamDialog] Using MainWindow's profile path validator.")
        else:
            # Fallback a una validazione molto semplice (esiste ed è una directory?)
            logging.warning("[SteamDialog] MainWindow validator not found, using basic os.path.isdir validation.")
            def basic_validator(path_to_validate, _profile_name):
                if not path_to_validate or not os.path.isdir(path_to_validate):
                     QMessageBox.warning(self, self.tr("Errore Percorso"), # Traduci
                                         self.tr("Il percorso specificato non esiste o non è una cartella valida.")) # Traduci
                     return None
                return path_to_validate # Ritorna il percorso se valido
            validator_func = basic_validator
        return validator_func

    def _ask_for_manual_path(self, profile_name, existing_path):
        """Chiede all'utente di inserire manualmente il percorso e lo valida."""
        validator_func = self._get_validator_func()
        manual_path, ok = QInputDialog.getText(
            self, self.tr("Percorso Manuale"), # Traduci
            self.tr("Inserisci il percorso COMPLETO dei salvataggi per '{0}':").format(profile_name), # Traduci
            text=existing_path if existing_path else "" # Precompila con il percorso attuale se esiste
        )

        if ok and manual_path:
            # Usa il validatore per controllare il percorso inserito
            validated_path = validator_func(manual_path, profile_name) # Passa anche il nome profilo
            if validated_path:
                return validated_path # Ritorna il percorso validato
            else:
                # Il validatore ha fallito (e dovrebbe aver mostrato un messaggio)
                # Possiamo riprovare? Per ora ritorniamo None per indicare fallimento/annullamento implicito
                return None
        elif ok and not manual_path: # Input vuoto
             QMessageBox.warning(self, self.tr("Errore Percorso"), self.tr("Il percorso non può essere vuoto.")) # Traduci
             return None # Indica fallimento/annullamento
        else: # Utente ha premuto Annulla su QInputDialog
            return None # Indica annullamento

    # Override reject per assicurarsi che il thread venga gestito se attivo
    def reject(self):
        logging.debug("[SteamDialog] Dialog rejected.")
        super().reject()

    # Override accept per loggare
    def accept(self):
        logging.debug("[SteamDialog] Dialog accepted (configuration successful).")
        super().accept() # Chiama l'implementazione base di accept

# --- FINE CLASSE SteamDialog ---

# Blocco per testare il dialogo standalone (opzionale)
if __name__ == '__main__':
    import sys
    # Configura logging base per vedere output durante test
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    # Simula alcuni dati che la MainWindow passerebbe
    class MockMainWindow:
        def __init__(self):
            self.profiles = {"Gioco Esistente": "C:/Saves/GiocoEsistente"}
            # Simula componenti per effetto fade (ma non l'effetto stesso)
            self.overlay_widget = None # QLabel("Overlay") # Potresti creare widget finti se necessario
            self.loading_label = None # QLabel("Loading...")
            self.fade_in_animation = None # QPropertyAnimation()
            self.fade_out_animation = None # QPropertyAnimation()
            self.developer_mode_enabled = True # Per testare gli score

        def centralWidget(self): # Necessario per resize overlay
             return self # O un altro widget finto

        def _center_loading_label(self): pass # Funzione finta

        # Simula validatore (in un vero ProfileCreationManager)
        class MockProfileManager:
             def validate_save_path(self, path, name):
                 print(f"MockValidator: Validating '{path}' for '{name}'")
                 if os.path.isdir(path):
                     print("MockValidator: Path is valid.")
                     return path
                 else:
                     print("MockValidator: Path is invalid.")
                     QMessageBox.warning(None, "Path Error", f"Mock Validator: Path '{path}' is not a valid directory.")
                     return None
        profile_creation_manager = MockProfileManager()


    # Simula core_logic se non disponibile
    try:
        import core_logic
    except ImportError:
        print("WARNING: core_logic not found, using mock functions.")
        class MockCoreLogic:
            def get_steam_install_path(self): return "C:/FakeSteam"
            def find_steam_libraries(self): return ["C:/FakeSteam"]
            def find_installed_steam_games(self):
                return {
                    "12345": {"name": "Gioco di Prova 1", "installdir": "C:/FakeSteam/steamapps/common/GiocoProva1"},
                    "67890": {"name": "Un Altro Gioco", "installdir": "C:/FakeSteam/steamapps/common/AltroGioco"},
                    "11111": {"name": "Gioco Esistente", "installdir": "C:/FakeSteam/steamapps/common/GiocoEsistente"}
                }
            def find_steam_userdata_info(self):
                # Simula 2 possibili ID utente
                return (
                    "C:/FakeSteam/userdata", # userdata_path
                    "12345678", # likely_id
                    ["12345678", "87654321"], # possible_ids
                    { # id_details
                        "12345678": {"display_name": "Utente Principale", "last_mod_str": "2025-04-19"},
                        "87654321": {"display_name": "Utente Secondario", "last_mod_str": "2024-11-01"}
                    }
                )
            def save_profiles(self, profiles_dict):
                 print("MockCoreLogic: Saving profiles:", profiles_dict)
                 return True # Simula successo
        core_logic = MockCoreLogic()

    # Simula gui_utils se non disponibile
    try:
         from gui_utils import SteamSearchWorkerThread
    except ImportError:
         print("WARNING: gui_utils.SteamSearchWorkerThread not found, using mock thread.")
         from PySide6.QtCore import QThread, Signal, QTimer
         class SteamSearchWorkerThread(QThread):
            finished = Signal(list) # Segnale emette lista di tuple (path, score)
            def __init__(self, game_name, game_install_dir, appid, steam_userdata_path, steam_id3_to_use, parent=None):
                 super().__init__(parent)
                 self.game_name = game_name
                 # Salva altri parametri se necessari per la simulazione
                 print(f"MockThread: Init for {game_name} (AppID: {appid}, UserID: {steam_id3_to_use})")

            def run(self):
                 print(f"MockThread: Simulating search for {self.game_name}...")
                 QThread.msleep(2500) # Simula lavoro
                 # Simula risultati trovati
                 mock_results = [
                     (f"C:/Users/Test/Documents/My Games/{self.game_name}/Saves", 90),
                     (f"C:/Users/Test/AppData/Local/{self.game_name}", 75),
                 ]
                 # Se il gioco è quello esistente, aggiungi il percorso reale come opzione
                 if self.game_name == "Gioco Esistente":
                     mock_results.insert(0, ("C:/Saves/GiocoEsistente", 100)) # Simula punteggio alto per quello giusto

                 print(f"MockThread: Search finished for {self.game_name}. Emitting results.")
                 self.finished.emit(mock_results)


    app = QApplication(sys.argv)
    # Crea la finestra principale finta (necessaria come parent per il dialogo)
    mock_main = MockMainWindow()
    dialog = SteamDialog(parent=mock_main) # Passa la mock main window come parent

    # Connetti il segnale del dialogo per vedere l'output
    dialog.profile_configured.connect(lambda name, path: print(f"SIGNAL profile_configured received: {name} -> {path}"))

    dialog.show()
    sys.exit(app.exec())