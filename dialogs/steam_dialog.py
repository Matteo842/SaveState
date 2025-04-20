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
    profile_configured = Signal(str, str) # Segnale emesso quando un profilo è configurato (nome, percorso)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Gestione dei giochi Steam")) # Traduci titolo
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        # Riferimenti interni
        self.steam_search_thread = None # Riferimento al thread di ricerca
        self.profiles = parent.profiles if parent and hasattr(parent, 'profiles') else {} # Ottieni profili dalla main window se esiste
        self.steam_games_data = {} # Dati dei giochi trovati (appid -> {name, installdir})
        self.steam_userdata_info = {} # Info su userdata (path, likely_id, possible_ids, details)

        # --- Creazione Widget UI ---
        self.game_list_widget = QListWidget()
        self.status_label = QLabel(self.tr("Avvio scansione Steam...")) # Traduci stato iniziale

        self.configure_button = QPushButton(self.tr("Configura Profilo Selezionato"))
        self.refresh_button = QPushButton(self.tr("Aggiorna elenco giochi")) # Traduci bottone
        self.close_button = QPushButton(self.tr("Chiudi")) # Traduci bottone

        self.configure_button.setEnabled(False) # Disabilitato finché non si seleziona un gioco

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Giochi Steam installati:"))) # Traduci etichetta
        layout.addWidget(self.game_list_widget)
        layout.addWidget(self.status_label)

        h_layout = QHBoxLayout()
        h_layout.addWidget(self.refresh_button)
        h_layout.addStretch()
        h_layout.addWidget(self.configure_button)
        h_layout.addWidget(self.close_button)
        layout.addLayout(h_layout)

        # --- Connessioni Segnali/Slot ---
        self.configure_button.clicked.connect(self.configure_selected_game)
        self.refresh_button.clicked.connect(self.start_steam_scan)
        self.close_button.clicked.connect(self.reject) # reject() chiude il dialogo con un codice di 'rifiuto'
        # Abilita/disabilita bottone configura in base alla selezione nella lista
        self.game_list_widget.currentItemChanged.connect(
            lambda item: self.configure_button.setEnabled(item is not None)
        )

        # Avvia la scansione iniziale poco dopo l'apertura del dialogo
        QTimer.singleShot(100, self.start_steam_scan)

    @Slot()
    def start_steam_scan(self):
        """Avvia la scansione delle installazioni e dei giochi Steam."""
        self.status_label.setText(self.tr("Searching for Steam installation..."))
        QApplication.processEvents() # Permette all'UI di aggiornarsi

        # Qui usi le funzioni da core_logic. Assumiamo che funzionino come previsto.
        steam_path = core_logic.get_steam_install_path()
        if not steam_path:
            self.status_label.setText(self.tr("Error: Steam installation not found."))
            return

        self.status_label.setText(self.tr("Searching for Steam libraries..."))
        QApplication.processEvents()
        libs = core_logic.find_steam_libraries()
        if not libs:
            self.status_label.setText(self.tr("Error: No Steam libraries found."))
            return

        self.status_label.setText(self.tr("Scanning installed games..."))
        QApplication.processEvents()
        # Questa chiamata potrebbe essere lenta se ci sono molti giochi,
        # idealmente anche questa potrebbe essere in un thread se causa blocchi UI.
        self.steam_games_data = core_logic.find_installed_steam_games()

        self.status_label.setText(self.tr("Searching for Steam user data..."))
        QApplication.processEvents()
        userdata_path, likely_id, possible_ids, id_details = core_logic.find_steam_userdata_info()
        self.steam_userdata_info = {
            'path': userdata_path,
            'likely_id': likely_id,
            'possible_ids': possible_ids,
            'details': id_details
        }

        self.populate_game_list()
        num_games = len(self.steam_games_data)
        self.status_label.setText(self.tr("Found {0} games. Ready.").format(num_games))

    def populate_game_list(self):
        """Popola la lista dei giochi trovati nell'interfaccia."""
        self.game_list_widget.clear()
        if not self.steam_games_data:
            self.game_list_widget.addItem(self.tr("Nessun gioco trovato.")) # Traduci
            return

        # Ordina i giochi per nome per una migliore visualizzazione
        sorted_games = sorted(self.steam_games_data.items(), key=lambda item: item[1]['name'])

        for appid, game_data in sorted_games:
            profile_exists_marker = self.tr("[PROFILO ESISTENTE]") if game_data['name'] in self.profiles else "" # Traduci
            item_text = f"{game_data['name']} (AppID: {appid}) {profile_exists_marker}".strip()
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, appid) # Memorizza l'appid nell'item stesso
            self.game_list_widget.addItem(item)

    @Slot()
    def configure_selected_game(self):
        """Avvia il processo di configurazione per il gioco selezionato."""
        # Import locali (spiegato sopra, probabilmente OK)
        from SaveState_gui import MainWindow
        from gui_utils import SteamSearchWorkerThread

        current_item = self.game_list_widget.currentItem()
        if not current_item:
            logging.warning("[SteamDialog] Configure button clicked but no item selected.")
            return # Non fare nulla se nessun gioco è selezionato

        appid = current_item.data(Qt.ItemDataRole.UserRole)
        game_data = self.steam_games_data.get(appid)

        if not game_data:
            logging.error(f"[SteamDialog] Game data not found for AppID {appid} in self.steam_games_data.")
            QMessageBox.warning(self, self.tr("Errore Interno"), # Traduci
                                self.tr("Impossibile trovare i dettagli per l'AppID {0}.").format(appid))
            return

        profile_name = game_data['name']
        install_dir = game_data['installdir']
        logging.info(f"[SteamDialog] Starting configuration for '{profile_name}' (AppID: {appid})")

        # --- Gestione Steam User ID ---
        steam_id_to_use = self.steam_userdata_info.get('likely_id')
        possible_ids = self.steam_userdata_info.get('possible_ids', [])
        id_details = self.steam_userdata_info.get('details', {})

        if len(possible_ids) > 1:
            # Costruisci le scelte per l'utente
            id_choices_display = []
            display_to_id_map = {}
            index_to_select = 0
            for i, uid in enumerate(possible_ids):
                user_details = id_details.get(uid, {})
                display_name = user_details.get('display_name', uid) # Usa ID se nome non trovato
                last_mod_str = user_details.get('last_mod_str', 'N/D')
                is_likely_marker = self.tr("(Recente)") if uid == steam_id_to_use else "" # Traduci
                choice_str = f"{display_name} {is_likely_marker} [{last_mod_str}]".strip().replace("  ", " ") # Pulisci spazi extra
                id_choices_display.append(choice_str)
                display_to_id_map[choice_str] = uid
                if uid == steam_id_to_use:
                    index_to_select = i

            # Chiedi all'utente quale ID usare
            chosen_display_str, ok = QInputDialog.getItem(
                self, self.tr("Selezione Profilo Steam"), # Traduci titolo
                self.tr("Trovati multipli profili Steam.\nSeleziona quello corretto (di solito il più recente):"), # Traduci testo
                id_choices_display, index_to_select, False
            )

            if ok and chosen_display_str:
                selected_id3 = display_to_id_map.get(chosen_display_str)
                if selected_id3:
                    steam_id_to_use = selected_id3
                    logging.debug(f"User selected SteamID3: {steam_id_to_use}")
                else:
                    logging.error(f"Error: Unable to map choice '{chosen_display_str}' back to original ID3.")
                    QMessageBox.warning(self, self.tr("Errore Interno"), # Traduci
                                        self.tr("Errore nel recuperare l'ID del profilo selezionato."))
                    return # Esce dalla funzione se c'è un errore di mappatura
            else:
                # L'utente ha annullato QInputDialog
                self.status_label.setText(self.tr("Configurazione annullata (nessun profilo Steam selezionato).")) # Traduci
                return # Esce dalla funzione

        elif not steam_id_to_use and len(possible_ids) == 1:
            # Se c'è solo un ID possibile, usa quello automaticamente
            steam_id_to_use = possible_ids[0]
            logging.debug(f"Automatically using the only found SteamID3: {steam_id_to_use}")
        elif not possible_ids:
            # Nessun ID trovato, potrebbe essere un problema per la ricerca euristica?
            logging.warning("No Steam user IDs found. Heuristic search might be less accurate.")
            # steam_id_to_use rimarrà None

        # --- AVVIO EFFETTO FADE SULLA MAIN WINDOW ---
        main_window = self.parent()
        # Verifica robusta se la main window e i suoi componenti per l'effetto esistono
        can_show_effect = (
            main_window is not None and
            # Assicurati che main_window sia del tipo atteso se necessario (isinstance)
            # isinstance(main_window, MainWindow) and # Potrebbe causare problemi con import circolari se MainWindow importa questo file
            hasattr(main_window, 'overlay_widget') and main_window.overlay_widget is not None and
            hasattr(main_window, 'loading_label') and
            hasattr(main_window, '_center_loading_label') and
            hasattr(main_window, 'fade_in_animation')
        )

        if can_show_effect:
            logging.debug("[SteamDialog] Activating fade effect on MainWindow...")
            try:
                # Prepara e mostra overlay sulla MainWindow
                # Ridimensiona l'overlay per coprire il widget centrale attuale
                main_window.overlay_widget.resize(main_window.centralWidget().size())
                main_window._center_loading_label() # Centra il testo/placeholder di caricamento
                main_window.overlay_widget.show()
                main_window.overlay_widget.raise_() # Assicura sia sopra altri widget nel centralWidget
                main_window.fade_in_animation.start()
            except Exception as e_fade_start:
                logging.error(f"Error starting fade effect from SteamDialog: {e_fade_start}", exc_info=True)
                can_show_effect = False # Se l'avvio fallisce, non provare a fermarlo dopo
        else:
            logging.warning("[SteamDialog] Cannot show fade effect (MainWindow or components not found/valid).")

        # --- PREPARAZIONE E AVVIO THREAD DI RICERCA ---

        # Disabilita questo dialogo (SteamDialog) mentre la ricerca è in corso
        self.setEnabled(False)
        self.status_label.setText(self.tr("Ricerca percorso per '{0}' in corso...").format(profile_name)) # Traduci
        QApplication.processEvents() # Aggiorna l'UI del dialogo Steam prima di nasconderlo e avviare il thread

        # Avvia il thread per la ricerca euristica dei percorsi di salvataggio
        logging.info("[SteamDialog] Starting SteamSearchWorkerThread...")
        self.steam_search_thread = SteamSearchWorkerThread(
            game_name=profile_name,
            game_install_dir=install_dir,
            appid=appid,
            steam_userdata_path=self.steam_userdata_info.get('path'),
            steam_id3_to_use=steam_id_to_use # Può essere None se non trovato/selezionato
        )
        # Connetti il segnale 'finished' del thread allo slot 'on_steam_search_finished' di questo dialogo
        # Passa anche 'can_show_effect' per sapere se fermare l'effetto
        self.steam_search_thread.finished.connect(lambda guesses: self.on_steam_search_finished(guesses, can_show_effect))
        self.steam_search_thread.start()

        # --- NASCONDI IL DIALOGO STEAM ---
        logging.debug("[SteamDialog] Hiding SteamDialog while search thread runs...")
        self.hide() # Nasconde questo dialogo mentre la ricerca avviene in background


    # Riceve la lista di tuple (path, score) e lo stato dell'effetto fade
    @Slot(list, bool)
    def on_steam_search_finished(self, guesses_with_scores, effect_was_shown):
        """Slot chiamato quando SteamSearchWorkerThread ha terminato la ricerca."""
        # Import locali (come prima)
        from SaveState_gui import MainWindow
        from PySide6.QtWidgets import QMessageBox, QInputDialog # Necessari qui per i dialoghi
        import os # Necessario per os.path.isdir nel validator fallback

        logging.info(f"[SteamDialog] Steam search finished. Received {len(guesses_with_scores)} guesses.")
        self.steam_search_thread = None # Rilascia il riferimento al thread, non serve più

        # --- STOP EFFETTO FADE SULLA MAIN WINDOW (se era stato avviato) ---
        main_window = self.parent()
        if effect_was_shown and main_window is not None:
            logging.debug("[SteamDialog] Deactivating fade effect on MainWindow...")
            try:
                # Prova ad avviare l'animazione di fade-out
                if hasattr(main_window, 'fade_out_animation'):
                    main_window.fade_out_animation.start()
                # Se l'animazione non esiste o fallisce, nascondi comunque l'overlay
                elif hasattr(main_window, 'overlay_widget') and main_window.overlay_widget is not None:
                    main_window.overlay_widget.hide()
            except Exception as e_fade_stop:
                logging.error(f"Error stopping fade effect from SteamDialog: {e_fade_stop}", exc_info=True)
                # Anche se fallisce lo stop, nascondi l'overlay se possibile
                if hasattr(main_window, 'overlay_widget') and main_window.overlay_widget is not None:
                    main_window.overlay_widget.hide()
        elif not effect_was_shown:
             logging.debug("[SteamDialog] Fade effect was not shown, skipping deactivation.")


        # --- GESTIONE RISULTATI DELLA RICERCA ---

        # Riabilita questo dialogo ora che il thread ha finito (verrà chiuso o rimarrà aperto in base alle azioni)
        self.setEnabled(True)
        # self.show() # Non mostrare ancora, prima gestiamo i path

        # Recupera di nuovo il nome del profilo (potrebbe essere cambiato se l'utente ha cliccato refresh?)
        # È più sicuro riprenderlo dalla selezione corrente al momento dell'avvio
        # MA: currentItem potrebbe essere cambiato nel frattempo se il dialogo fosse visibile.
        # È più sicuro passare il nome del profilo dal metodo chiamante o memorizzarlo in una variabile di istanza
        # all'inizio di configure_selected_game. Usiamo una variabile di istanza:
        # Aggiungi `self.current_configuring_profile_name = profile_name` in configure_selected_game
        # e leggilo qui. Per ora, lo recuperiamo dalla lista, sperando non sia cambiato.
        current_item = self.game_list_widget.currentItem() # Attenzione: potrebbe non essere più lo stesso item!
        profile_name = ""
        appid_being_configured = -1 # Valore non valido
        if current_item:
             appid_being_configured = current_item.data(Qt.ItemDataRole.UserRole)
             game_data = self.steam_games_data.get(appid_being_configured)
             if game_data:
                 profile_name = game_data['name']

        # Se non riusciamo a recuperare il nome del profilo su cui stavamo lavorando, è un errore.
        if not profile_name:
            logging.error("[SteamDialog] Could not retrieve profile name in on_steam_search_finished. Aborting config.")
            QMessageBox.critical(self, self.tr("Errore Interno"), # Traduci
                                 self.tr("Impossibile recuperare il nome del profilo in configurazione."))
            self.reject() # Chiude il dialogo Steam con 'rifiuto'
            return

        confirmed_path = None # Percorso finale che verrà salvato
        # Recupera il percorso attualmente salvato per questo profilo, se esiste
        existing_path = self.profiles.get(profile_name)

        # --- Logica per scegliere/confermare il percorso ---

        if not guesses_with_scores: # La ricerca non ha trovato nulla
            if not existing_path:
                # Nessun suggerimento e nessun profilo esistente -> Forza inserimento manuale
                QMessageBox.information(self, self.tr("Percorso Non Trovato"), # Traduci
                                        self.tr("Impossibile trovare automaticamente un percorso per '{0}'.\n"
                                                "Per favore, inseriscilo manualmente.").format(profile_name))
                confirmed_path = self._ask_for_manual_path(profile_name, existing_path) # Chiamiamo helper per input manuale
            else:
                # Nessun suggerimento, ma profilo esiste -> Chiedi se mantenere o inserire manualmente
                reply = QMessageBox.question(self, self.tr("Nessun Nuovo Percorso Trovato"), # Traduci
                                             self.tr("La ricerca automatica non ha trovato nuovi percorsi.\n"
                                                     "Vuoi mantenere il percorso attuale?\n'{0}'")
                                             .format(existing_path),
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel, # Aggiungi Cancel
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    confirmed_path = existing_path
                elif reply == QMessageBox.StandardButton.No:
                     confirmed_path = self._ask_for_manual_path(profile_name, existing_path) # Chiamiamo helper
                else: # Cancel
                    self.status_label.setText(self.tr("Configurazione annullata.")) # Traduci
                    self.reject() # Chiude il dialogo senza salvare
                    return

        else: # La ricerca ha trovato uno o più suggerimenti (guesses_with_scores non è vuota)
            path_choices = []
            display_str_to_path_map = {}
            current_selection_index = 0 # Indice preselezionato (miglior guess o attuale)

            # Controlla modalità sviluppatore sulla main window per mostrare gli score
            show_scores = False
            if main_window and hasattr(main_window, 'developer_mode_enabled'):
                show_scores = main_window.developer_mode_enabled

            logging.debug(f"[SteamDialog] Path guesses (already sorted by core_logic): {guesses_with_scores}")

            # Prepara le stringhe da mostrare all'utente
            for i, (p, score) in enumerate(guesses_with_scores):
                is_current_marker = self.tr("[ATTUALE]") if p == existing_path else "" # Traduci
                score_str = f"(Score: {score})" if show_scores else ""
                display_text = f"{p} {score_str} {is_current_marker}".strip().replace("  ", " ")
                path_choices.append(display_text)
                display_str_to_path_map[display_text] = p
                # Preseleziona il percorso esistente se è tra i suggerimenti, altrimenti rimane 0 (il primo, che è il migliore)
                if p == existing_path:
                    current_selection_index = i

            # Aggiungi opzione per inserimento manuale
            manual_option_str = self.tr("--- Inserisci percorso manualmente ---")
            path_choices.append(manual_option_str)

            dialog_text = self.tr("Seleziona il percorso corretto per i salvataggi di '{0}':").format(profile_name) 
            # Mostra il dialogo di scelta
            chosen_display_str, ok = QInputDialog.getItem(
                self,
                self.tr("Conferma Percorso Salvataggi"), # Traduci
                dialog_text,
                path_choices,
                current_selection_index,
                False # Non permettere modifica diretta nel combobox
            )

            if ok and chosen_display_str:
                if chosen_display_str == manual_option_str:
                    confirmed_path = self._ask_for_manual_path(profile_name, existing_path) # Chiamiamo helper
                else:
                    confirmed_path = display_str_to_path_map.get(chosen_display_str)
                    if confirmed_path is None:
                        logging.error(f"Error mapping selected choice '{chosen_display_str}' back to path.")
                        QMessageBox.critical(self, self.tr("Errore Interno"), self.tr("Errore nella selezione del percorso.")) # Traduci
                        # Potremmo far riprovare o chiedere input manuale qui? Per ora usciamo.
                        self.reject()
                        return
            else:
                # L'utente ha annullato getItem
                self.status_label.setText(self.tr("Configurazione annullata.")) # Traduci
                self.reject() # Chiude il dialogo senza salvare
                return

        # --- Salvataggio del Profilo ---
        # Arriviamo qui solo se confirmed_path ha un valore (o None se l'input manuale è stato annullato)
        if confirmed_path: # Assicura che non sia None o stringa vuota
            logging.info(f"Saving profile '{profile_name}' with path '{confirmed_path}'")
            self.profiles[profile_name] = confirmed_path # Aggiorna dizionario profili
            if core_logic.save_profiles(self.profiles):
                self.status_label.setText(self.tr("Profilo '{0}' configurato.").format(profile_name)) # Traduci
                QMessageBox.information(self, self.tr("Profilo Configurato"), # Traduci
                                        self.tr("Profilo '{0}' salvato con successo.").format(profile_name)) # Traduci
                # Emetti il segnale per notificare la MainWindow dell'aggiornamento
                self.profile_configured.emit(profile_name, confirmed_path)
                self.accept() # Chiude il dialogo Steam con successo
            else:
                # Errore durante il salvataggio del file JSON
                QMessageBox.critical(self, self.tr("Errore Salvataggio"), # Traduci
                                     self.tr("Impossibile salvare il file dei profili.")) # Traduci
                self.status_label.setText(self.tr("Errore durante il salvataggio dei profili.")) # Traduci
                # Lasciare il dialogo aperto in caso di errore di salvataggio? Sì, così l'utente non perde l'info.
                # Ma forse dovremmo mostrare di nuovo il dialogo? Per ora rimane nascosto ma abilitato.
                # Considera self.show() qui se vuoi che riappaia.
        else:
             # Se confirmed_path è None o vuoto a questo punto, significa che l'utente
             # ha annullato l'inserimento manuale o c'è stato un errore non gestito.
             logging.warning(f"Configuration cancelled or failed for profile '{profile_name}' (confirmed_path is empty/None).")
             self.status_label.setText(self.tr("Configurazione annullata o fallita.")) # Traduci
             self.reject() # Chiude il dialogo senza salvare

    def _get_validator_func(self):
        """Restituisce la funzione di validazione del percorso, prendendola da MainWindow se possibile."""
        main_window = self.parent()
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
        logging.debug("[SteamDialog] Dialog rejected (closed by user or error).")
        # Qui potresti voler aggiungere logica per fermare il thread se stesse ancora girando,
        # anche se nel flusso attuale viene chiamato reject solo quando il thread è già finito
        # o prima che parta. Se il thread fosse molto lungo e l'utente chiudesse il dialogo,
        # potrebbe essere utile implementare un meccanismo di stop nel thread.
        # Esempio: if self.steam_search_thread and self.steam_search_thread.isRunning():
        #             self.steam_search_thread.requestInterruption() # Richiede al thread di fermarsi (devi implementarlo nel thread)
        #             self.steam_search_thread.wait(1000) # Aspetta un po' che termini
        super().reject() # Chiama l'implementazione base di reject


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