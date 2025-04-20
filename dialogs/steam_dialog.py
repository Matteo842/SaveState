# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QListWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QApplication, QInputDialog, QMessageBox, QListWidgetItem
)
from PySide6.QtCore import Signal, Slot, Qt, QTimer

# Importa la logica necessaria
import core_logic
import logging
import os

# --- Dialogo Gestione Steam ---
class SteamDialog(QDialog):
    # ... (Codice come prima, sembrava OK con correzioni caratteri) ...
    profile_configured = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steam Games Management")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.steam_search_thread = None
        self.game_list_widget = QListWidget()
        self.status_label = QLabel("Starting Steam scan...")
        self.configure_button = QPushButton(self.tr("Configura Profilo Selezionato"))
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
        self.steam_games_data = core_logic.find_installed_steam_games()
        self.status_label.setText(self.tr("Searching for Steam user data..."))
        QApplication.processEvents()
        userdata_path, likely_id, possible_ids, id_details = core_logic.find_steam_userdata_info()
        self.steam_userdata_info = {'path': userdata_path, 'likely_id': likely_id, 'possible_ids': possible_ids, 'details': id_details}
        self.populate_game_list()
        self.status_label.setText(self.tr("Found {0} games. Ready.").format(len(self.steam_games_data)))

    def populate_game_list(self):
        self.game_list_widget.clear()
        if not self.steam_games_data:
            self.game_list_widget.addItem("No games found.")
            return
        sorted_games = sorted(self.steam_games_data.items(), key=lambda item: item[1]['name'])
        for appid, game_data in sorted_games:
            profile_exists = "[PROFILO ESISTENTE]" if game_data['name'] in self.profiles else ""
            item_text = f"{game_data['name']} (AppID: {appid}) {profile_exists}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, appid)
            self.game_list_widget.addItem(item)

    @Slot()
    def configure_selected_game(self):
        from SaveState_gui import MainWindow
        from gui_utils import SteamSearchWorkerThread
        current_item = self.game_list_widget.currentItem()
        if not current_item:
            logging.debug("Attempting to configure Steam game without selection in the list.")
            return

        appid = current_item.data(Qt.ItemDataRole.UserRole)
        game_data = self.steam_games_data.get(appid)

        if not game_data:
            logging.error(f"Game data not found for AppID {appid} in self.steam_games_data.")
            QMessageBox.warning(self, "Errore Interno", f"Impossibile trovare i dettagli per l'AppID {appid}.")
            return

        profile_name = game_data['name']
        install_dir = game_data['installdir']
        logging.info(f"[SteamDialog] Configuring '{profile_name}' (AppID: {appid})")

        # Ottieni Steam ID (logica esistente per chiedere se multipli ID)
        steam_id_to_use = self.steam_userdata_info.get('likely_id')
        possible_ids = self.steam_userdata_info.get('possible_ids', [])
        if len(possible_ids) > 1:
            # ... (stessa logica di prima per QInputDialog.getItem per scegliere l'ID) ...
            # Assicurati che se l'utente annulla, la funzione esca con 'return'
            # Questa parte rimane invariata rispetto al tuo codice attuale
            id_choices_display = []
            details = self.steam_userdata_info.get('details', {})
            display_to_id_map = {}
            index_to_select = 0
            for i, uid in enumerate(possible_ids):
                user_details = details.get(uid, {})
                display_name = user_details.get('display_name', uid)
                last_mod_str = user_details.get('last_mod_str', 'N/D')
                is_likely = "(Recente)" if uid == steam_id_to_use else ""
                choice_str = f"{display_name} {is_likely} {last_mod_str}".strip()
                id_choices_display.append(choice_str)
                display_to_id_map[choice_str] = uid
                if uid == steam_id_to_use:
                    index_to_select = i

            chosen_display_str, ok = QInputDialog.getItem(
                self, self.tr("Selezione Profilo Steam"),
                self.tr("Trovati multipli profili Steam.\nSeleziona quello corretto (di solito il più recente):"),
                id_choices_display, index_to_select, False
            )
            if ok and chosen_display_str:
                selected_id3 = display_to_id_map.get(chosen_display_str)
                if selected_id3:
                    steam_id_to_use = selected_id3
                    logging.debug(f"User selected SteamID3: {steam_id_to_use}")
                else:
                    logging.error(f"Error: Unable to map choice '{chosen_display_str}' to original ID3.")
                    QMessageBox.warning(self, "Errore Interno", "Errore nel recuperare l'ID del profilo selezionato.")
                    return
            else:  # Utente ha annullato o scelta non valida
                self.status_label.setText(self.tr("Configurazione annullata (nessun profilo Steam selezionato)."))
                return
        elif not steam_id_to_use and possible_ids:  # Se c'è solo un ID, usalo
            steam_id_to_use = possible_ids[0]
        elif not possible_ids:
            logging.warning("No Steam user IDs found for path guessing.")
            # Continua senza ID? O avvisa l'utente? Per ora continuiamo.
            # steam_id_to_use rimarrà None

        # --- AVVIO EFFETTO FADE E THREAD ---
        main_window = self.parent()
        # Controlla se il parent è effettivamente MainWindow (se l'import ha funzionato)
        can_show_effect = (main_window is not None and
                       hasattr(main_window, 'overlay_widget') and
                       hasattr(main_window, 'loading_label') and
                       hasattr(main_window, '_center_loading_label') and
                       hasattr(main_window, 'fade_in_animation'))

        if can_show_effect:
            logging.debug("[SteamDialog] Activating fade effect on MainWindow...") # Log per conferma
            try:
                # ... (codice esistente per attivare effetto) ...
                pass
            except Exception as e_fade_start:
                logging.error(f"Error starting fade effect from SteamDialog: {e_fade_start}", exc_info=True)

        if can_show_effect:
            logging.debug("[SteamDialog] Activating fade effect on MainWindow...")
            try:
                # Prepara e mostra overlay sulla MainWindow
                if hasattr(main_window, 'overlay_widget') and main_window.overlay_widget:
                    main_window.overlay_widget.resize(main_window.centralWidget().size())
                    if hasattr(main_window, '_center_loading_label'):
                        main_window._center_loading_label()  # Centra placeholder
                    main_window.overlay_widget.show()
                    if hasattr(main_window, 'fade_in_animation'):
                        main_window.fade_in_animation.start()
                else:
                    logging.warning("MainWindow overlay components not found, cannot show effect.")
                    can_show_effect = False  # Disabilita effetto se manca qualcosa
            except Exception as e_fade_start:
                logging.error(f"Error starting fade effect from SteamDialog: {e_fade_start}", exc_info=True)
                can_show_effect = False  # Disabilita effetto se c'è errore

        # Disabilita questo dialogo e aggiorna la sua etichetta di stato
        self.setEnabled(False)
        self.status_label.setText(self.tr("Ricerca percorso per '{0}' in corso...").format(profile_name))
        QApplication.processEvents()  # Aggiorna UI dialogo

        # Avvia il thread per la ricerca euristica
        logging.info("[SteamDialog] Starting SteamSearchWorkerThread...")
        self.steam_search_thread = SteamSearchWorkerThread(
            game_name=profile_name,
            game_install_dir=install_dir,
            appid=appid,
            steam_userdata_path=self.steam_userdata_info.get('path'),
            steam_id3_to_use=steam_id_to_use
        )
        # Connetti il segnale finished allo nuovo slot che creeremo
        self.steam_search_thread.finished.connect(self.on_steam_search_finished)
        # Connetti il segnale progress per aggiornare la status label di questo dialogo
        self.steam_search_thread.progress.connect(self.status_label.setText)
        self.steam_search_thread.start()
        # La funzione finisce qui, il resto della logica è in on_steam_search_finished

    @Slot(list)  # Riceve la lista di tuple (path, score) dal segnale 'finished' del thread
    def on_steam_search_finished(self, guesses_with_scores):
        """Chiamato quando SteamSearchWorkerThread ha finito."""
        from SaveState_gui import MainWindow
        logging.info(f"[SteamDialog] Steam search finished. Received {len(guesses_with_scores)} guesses.")
        self.steam_search_thread = None  # Rimuovi riferimento al thread

        # --- STOP EFFETTO FADE ---
        main_window = self.parent()
        can_stop_effect = (main_window is not None and
                        hasattr(main_window, 'fade_out_animation') and
                        hasattr(main_window, 'overlay_widget')) # Basta controllare questi per fermare

        if can_stop_effect:
            logging.debug("[SteamDialog] Deactivating fade effect on MainWindow...") # Questo log dovrebbe apparire ora
            try:
                # Questo blocco dovrebbe ora essere eseguito se can_stop_effect è True
                if hasattr(main_window, 'fade_out_animation'):
                    main_window.fade_out_animation.start()
                elif hasattr(main_window, 'overlay_widget'):
                    main_window.overlay_widget.hide()
            except Exception as e_fade_stop:
                logging.error(f"Error stopping fade effect from SteamDialog: {e_fade_stop}", exc_info=True)
        else:
             # Log se il controllo fallisce
             logging.warning("DEBUG FADEOUT: Condition 'can_stop_effect' was False. Fade-out skipped.")



        # Riabilita questo dialogo
        self.setEnabled(True)
        self.status_label.setText(self.tr("Ricerca completata. Seleziona percorso:"))
        QApplication.processEvents()

        # --- INIZIO LOGICA SPOSTATA DA configure_selected_game ---
        # (Questo codice è quasi identico a quello che avevi prima
        #  dopo la chiamata a guess_save_path, ma usa guesses_with_scores)

        # Recupera nome profilo di nuovo per usarlo nei messaggi/validazione
        # (Potremmo passarlo tramite il thread o recuperarlo dall'item selezionato)
        current_item = self.game_list_widget.currentItem()
        profile_name = ""
        if current_item:
            appid = current_item.data(Qt.ItemDataRole.UserRole)
            game_data = self.steam_games_data.get(appid)
            if game_data:
                profile_name = game_data['name']

        if not profile_name:
            logging.error("Unable to retrieve profile name in on_steam_search_finished.")
            QMessageBox.critical(self, "Errore Interno", "Impossibile recuperare nome profilo.")
            return

        confirmed_path = None
        existing_path = self.profiles.get(profile_name)  # Leggi path esistente

        # Logica per scegliere/confermare il percorso
        if not guesses_with_scores and not existing_path:
            QMessageBox.information(self, self.tr("Percorso Non Trovato"), self.tr("Impossibile trovare automaticamente un percorso. Inseriscilo manualmente."))
            confirmed_path = None  # Forza inserimento manuale
        elif not guesses_with_scores and existing_path:
            reply = QMessageBox.question(self, self.tr("Nessun Percorso Trovato"),
                                        self.tr("Nessun nuovo percorso trovato automaticamente.\nVuoi mantenere quello attuale?\n'{0}'").format(existing_path),
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes:
                confirmed_path = existing_path
            else:
                confirmed_path = None  # Forza inserimento manuale
        else:
            # Mostra dialogo per scegliere tra i percorsi trovati (guesses_with_scores)
            path_choices = []
            display_str_to_path_map = {}

            # Controlla modalità sviluppatore sulla main window
            show_scores = False
            if main_window and hasattr(main_window, 'developer_mode_enabled'):
                show_scores = main_window.developer_mode_enabled

            logging.debug(f"SteamDialog: Guesses received (already sorted by core_logic): {guesses_with_scores}")

            for i, (p, score) in enumerate(guesses_with_scores):  # Itera sulle tuple
                display_text = ""
                is_current = self.tr("[ATTUALE]") if p == existing_path else ""  # Traduci
                if show_scores:
                    display_text = f"{p} (Score: {score}) {is_current}".strip()
                else:
                    display_text = f"{p} {is_current}".strip()
                path_choices.append(display_text)
                display_str_to_path_map[display_text] = p

            dialog_text = self.tr("Seleziona il percorso corretto per i salvataggi:")
            if existing_path:
                dialog_text += f"\n({self.tr('Attuale')}: {existing_path})"  # Traduci

            current_selection_index = 0
            for idx, choice_str in enumerate(path_choices):
                path_from_choice = display_str_to_path_map.get(choice_str)
                if path_from_choice == existing_path:
                    current_selection_index = idx
                    break

            chosen_display_str, ok = QInputDialog.getItem(
                self,
                self.tr("Conferma Percorso Salvataggi"),  # Traduci
                dialog_text,
                path_choices,
                current_selection_index,
                False
            )

            if ok and chosen_display_str:
                confirmed_path = display_str_to_path_map.get(chosen_display_str)
                if confirmed_path is None:
                    ok = False  # Errore mappa?
            else:  # Annullato o scelta vuota
                ok = False

            if not ok:  # Se utente ha annullato getItem o mappatura fallita
                manual_reply = QMessageBox.question(self, self.tr("Inserimento Manuale?"),  # Traduci
                                                    self.tr("Vuoi inserire il percorso manualmente?"),  # Traduci
                                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                    QMessageBox.StandardButton.No)
                if manual_reply == QMessageBox.StandardButton.Yes:
                    confirmed_path = None  # Forza inserimento manuale sotto
                else:
                    self.status_label.setText(self.tr("Configurazione annullata."))
                    return  # Esce da on_steam_search_finished

        # Logica per inserimento/validazione manuale
        if confirmed_path is None:
            # Usa il validatore della MainWindow se possibile
            validator_func = None
            if main_window and hasattr(main_window, 'profile_creation_manager') and \
                    hasattr(main_window.profile_creation_manager, 'validate_save_path'):
                validator_func = main_window.profile_creation_manager.validate_save_path
                logging.debug("Using MainWindow validator.")
            else:  # Fallback a validazione semplice (solo isdir)
                logging.warning("MainWindow validator not found, using basic validation.")
                def basic_validator(p, _): return p if os.path.isdir(p) else None
                validator_func = basic_validator

            manual_path, ok = QInputDialog.getText(self, self.tr("Percorso Manuale"),  # Traduci
                                                   self.tr("Inserisci il percorso COMPLETO per '{0}':").format(profile_name),  # Traduci
                                                   text=existing_path if existing_path else "")
            if ok and manual_path:
                # Chiama il validatore (della main window o quello base)
                validated_manual_path = validator_func(manual_path, profile_name)
                if validated_manual_path is None:
                    # L'errore dovrebbe essere già stato mostrato dal validatore della main window
                    # o semplicemente non è valido se si usa quello base
                    if not (main_window and hasattr(main_window, 'profile_creation_manager')):
                        QMessageBox.warning(self, self.tr("Errore Percorso"), self.tr("Percorso manuale non valido."))  # Traduci
                    self.status_label.setText(self.tr("Configurazione annullata (percorso manuale non valido)."))  # Traduci
                    return  # Esci
                else:
                    confirmed_path = validated_manual_path
            elif ok and not manual_path:  # Percorso vuoto
                QMessageBox.warning(self, self.tr("Errore Percorso"), self.tr("Il percorso non può essere vuoto."))  # Traduci
                self.status_label.setText(self.tr("Configurazione annullata (percorso vuoto)."))  # Traduci
                return
            else:  # Utente ha annullato QInputDialog
                self.status_label.setText(self.tr("Configurazione annullata."))
                return

        # --- Aggiorna/Salva Profilo (se abbiamo un path valido) ---
        if confirmed_path:  # Assicura che non sia None
            self.profiles[profile_name] = confirmed_path
            if core_logic.save_profiles(self.profiles):
                self.status_label.setText(self.tr("Profilo '{0}' configurato.").format(profile_name))  # Traduci
                QMessageBox.information(self, self.tr("Profilo Configurato"),  # Traduci
                                        self.tr("Profilo '{0}' salvato con successo.").format(profile_name))  # Traduci
                # Emetti segnale e chiudi dialogo (come prima)
                self.profile_configured.emit(profile_name, confirmed_path)
                self.accept()  # Chiude il dialogo Steam
            else:
                QMessageBox.critical(self, self.tr("Errore Salvataggio"), self.tr("Impossibile salvare il file dei profili."))  # Traduci
                self.status_label.setText(self.tr("Errore durante il salvataggio dei profili."))  # Traduci
                # Non chiudere il dialogo se il salvataggio fallisce? O sì? Per ora lo lasciamo aperto.
        else:
            # Non dovrebbe succedere se la logica sopra è corretta, ma per sicurezza
            logging.error("Reached end of on_steam_search_finished without a valid confirmed_path.")
            self.status_label.setText(self.tr("Errore interno nel determinare il percorso finale."))  # Traduci

    # --- FINE on_steam_search_finished ---
