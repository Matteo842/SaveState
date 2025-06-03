import os
import logging
import platform
import string
import re # Per il parsing degli URL Steam
from pathlib import Path
import configparser # Per il parsing dei file .url

from PySide6.QtWidgets import QMessageBox, QInputDialog, QApplication, QFileDialog, QDialog
from PySide6.QtCore import Qt, Slot, QObject, QTimer, QThread
from PySide6.QtGui import QDropEvent

from dialogs.minecraft_dialog import MinecraftWorldsDialog
from dialogs.emulator_selection_dialog import EmulatorGameSelectionDialog
from gui_components.multi_profile_dialog import MultiProfileDialog

# Importa utility e logica
from gui_utils import DetectionWorkerThread
import minecraft_utils
import core_logic
import shortcut_utils
from emulator_utils import emulator_manager

# Setup logging per questo modulo
logger = logging.getLogger(__name__)

class DragDropHandler(QObject):
    """
    Gestisce le operazioni di drag and drop per la creazione di profili.
    Supporta URL Steam, collegamenti Windows (.lnk), file desktop Linux (.desktop) e cartelle.
    """
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.detection_thread = None
        self.profile_dialog = None  # Riferimento al dialogo dei profili
        
        # Inizializza le variabili di stato che saranno gestite da reset_internal_state
        self.reset_internal_state()
    
    def reset_internal_state(self):
        """Reimposta le variabili di stato interne prima di elaborare un nuovo elemento."""
        self.game_name_suggestion = None
        self.game_install_dir = None
        self.is_steam_game = False
        self.steam_app_id = None
        self.executable_path = None
        self.shortcut_target_path = None
        self.shortcut_game_name = None
        self.original_steam_url_str = None
        self.skip_steam_error_popup = False  # Flag per evitare popup di errore per Steam
        
        logger.debug("DragDropHandler state reset.")
    
    def _get_steam_game_details(self, app_id):
        """
        Recupera il nome del gioco e la directory di installazione per un dato AppID Steam
        da main_window.installed_steam_games_dict.
        Restituisce un dizionario {'name': game_name, 'install_dir': install_dir} o None.
        """
        mw = self.main_window
        if not hasattr(mw, 'installed_steam_games_dict') or not mw.installed_steam_games_dict:
            logger.warning(f"Cannot get Steam game details: main_window.installed_steam_games_dict is not available or empty.")
            return None
        
        # Ensure app_id is string for dict key
        app_id = str(app_id)
        
        game_info = mw.installed_steam_games_dict.get(app_id)
        if game_info and isinstance(game_info, dict) and 'name' in game_info:
            # Check if we have the install_dir directly
            if 'install_dir' in game_info:
                return {'name': game_info['name'], 'install_dir': game_info['install_dir']}
            
            # Otherwise construct it from installdir and library_folder if available
            elif 'installdir' in game_info:
                if 'library_folder' in game_info:
                    install_dir = os.path.join(game_info['library_folder'], 'steamapps', 'common', game_info['installdir'])
                    return {'name': game_info['name'], 'install_dir': install_dir}
                else:
                    logger.warning(f"Game info for {app_id} does not contain 'library_folder': {game_info}")
                    # Still return what we have, using installdir as is
                    return {'name': game_info['name'], 'install_dir': game_info['installdir']}
        else:
            logger.warning(f"Details for Steam AppID {app_id} not found or incomplete in installed_steam_games_dict.")
        
        return None
    
    def _scan_directory_for_executables(self, directory_path):
        """Scansiona una cartella per trovare file eseguibili e potenziali giochi.
        
        Args:
            directory_path: Il percorso della cartella da scansionare
            
        Returns:
            Una lista di percorsi di file potenzialmente validi trovati nella cartella
        """
        valid_files = []
        # Estensioni di file eseguibili e potenziali giochi su Windows
        valid_extensions = [
            # Eseguibili standard
            ".exe", ".bat", ".com", ".lnk", ".url",
            # Altri tipi di file che potrebbero essere giochi o avere salvataggi
            ".msi", ".appx", ".appxbundle", ".msix", ".msixbundle",
            # File di gioco comuni
            ".iso", ".bin", ".cue", ".nds", ".gba", ".gb", ".gbc", ".nes", ".sfc", ".smc",
            ".n64", ".z64", ".v64", ".gcm", ".iso", ".wbfs", ".wad", ".3ds", ".cia",
            ".jar", ".swf"
        ]
        
        try:
            # Scansiona solo i file nella cartella principale, non nelle sottocartelle
            for item in os.listdir(directory_path):
                item_path = os.path.join(directory_path, item)
                
                # Salta le sottocartelle
                if os.path.isdir(item_path):
                    continue
                    
                # Su Windows, controlla le estensioni
                if platform.system() == "Windows":
                    # Controlla se il file ha un'estensione valida
                    file_ext = os.path.splitext(item_path)[1].lower()
                    
                    # Se l'estensione non è nella lista, salta il file
                    if file_ext not in valid_extensions:
                        continue
                        
                    # Per i file .lnk, verifica che non puntino a cartelle
                    if file_ext == ".lnk":
                        try:
                            import winshell
                            shortcut = winshell.shortcut(item_path)
                            target_path = shortcut.path
                            if os.path.isdir(target_path):
                                # Salta i collegamenti a cartelle
                                continue
                                
                            # Verifica se il target è un file valido
                            target_ext = os.path.splitext(target_path)[1].lower()
                            if target_ext not in valid_extensions and not os.access(target_path, os.X_OK):
                                continue
                                
                        except Exception as e:
                            logging.error(f"Error checking .lnk file: {e}")
                            continue
                            
                    # Per i file .url, verifica che siano URL Steam validi
                    if file_ext == ".url":
                        try:
                            config = configparser.ConfigParser()
                            config.read(item_path)
                            if 'InternetShortcut' in config and 'URL' in config['InternetShortcut']:
                                url_from_file = config['InternetShortcut']['URL']
                                # Verifica se è un URL Steam
                                if not ("store.steampowered.com" in url_from_file or "steam://" in url_from_file):
                                    # Salta i file .url non Steam
                                    continue
                                
                                # --- INIZIO LOGICA CONTROLLO INSTALLAZIONE STEAM GAME ---
                                app_id = None
                                # Estrai AppID (gestisce entrambi i formati di URL)
                                match_rungameid = re.search(r'steam://rungameid/(\d+)', url_from_file)
                                match_store_app = re.search(r'store\.steampowered\.com/app/(\d+)', url_from_file)

                                if match_rungameid:
                                    app_id = match_rungameid.group(1)
                                elif match_store_app:
                                    app_id = match_store_app.group(1)
                                
                                if app_id:
                                    game_details = self._get_steam_game_details(app_id)
                                    # Se game_details non esiste o non ha un install_dir valido, il gioco non è considerato installato.
                                    # _get_steam_game_details già logga se i dettagli non sono trovati o incompleti.
                                    if not game_details or not game_details.get('install_dir'):
                                        # Aggiungiamo un log specifico per questo scenario di skip durante la scansione
                                        logging.info(f"Skipping uninstalled/details-missing Steam game (AppID: {app_id}) found in directory scan: {item_path}")
                                        continue # Salta questo file .url e passa al prossimo item
                                    else:
                                        # Verifica esplicita dell'esistenza dell'install_dir per maggiore robustezza
                                        install_dir_path = Path(game_details['install_dir'])
                                        if not install_dir_path.exists() or not install_dir_path.is_dir():
                                            logging.warning(f"Install directory '{install_dir_path}' for Steam game (AppID: {app_id}) not found or not a directory. Skipping: {item_path}")
                                            continue # Salta se la directory di installazione non è valida
                                        logging.debug(f"Steam game (AppID: {app_id}, Name: {game_details.get('name', 'N/A')}) is installed. Adding '{item_path}' to valid files.")
                                else:
                                    logging.warning(f"Could not extract AppID from Steam URL '{url_from_file}' in file {item_path}. Skipping.")
                                    continue # Salta se non si può estrarre l'AppID
                                # --- FINE LOGICA CONTROLLO INSTALLAZIONE STEAM GAME ---
                            else:
                                continue
                        except Exception as e:
                            logging.error(f"Error parsing .url file: {e}")
                            continue
                    
                    # Verifica se il file è un emulatore conosciuto (solo detection, senza scan dei profili)
                    is_emulator = self._is_known_emulator(item_path)
                    if is_emulator:
                        # Se è un emulatore, lo saltiamo immediatamente senza cercare i profili
                        logging.info(f"Skipping emulator in directory: {item_path}")
                        continue
                    
                    # Se arriviamo qui, il file non è un emulatore e può essere aggiunto
                    valid_files.append(item_path)
                else:  # Linux/Mac
                    # Su Linux/Mac, controlla se il file è eseguibile
                    if os.access(item_path, os.X_OK) and os.path.isfile(item_path):
                        valid_files.append(item_path)
                    else:
                        # Controlla anche le estensioni per i file non eseguibili
                        file_ext = os.path.splitext(item_path)[1].lower()
                        if file_ext in valid_extensions:
                            valid_files.append(item_path)
                        
            logging.info(f"Found {len(valid_files)} valid files in directory: {directory_path}")
            return valid_files
        except Exception as e:
            logging.error(f"Error scanning directory for valid files: {e}")
            return []
    
    def _hide_overlay_if_visible(self, main_window):
        """Nasconde l'overlay se è visibile usando l'animazione fade-out."""
        if hasattr(main_window, 'overlay_widget') and main_window.overlay_widget and main_window.overlay_widget.isVisible():
            if hasattr(main_window, 'fade_out_animation') and main_window.fade_out_animation:
                main_window.fade_out_animation.stop()
                main_window.fade_out_animation.start()
                logging.debug("Fade-out animation started for overlay.")
                
    def _handle_profile_analysis(self, profile_data):
        """Gestisce l'analisi di un profilo quando viene richiesto dal dialogo.
        
        Args:
            profile_data: Dizionario con i dati del profilo
        """
        # Verifica se è una richiesta di avvio dell'analisi
        if 'action' in profile_data and profile_data['action'] == 'start_analysis':
            # Ottieni la lista dei file da analizzare
            files_to_analyze = self.profile_dialog.get_files_to_analyze()
            
            # Imposta il cursore di attesa
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            
            # Inizializza la barra di avanzamento
            self.profile_dialog.update_progress(0, f"Preparation of analysis for {len(files_to_analyze)} file...")
            QApplication.processEvents()
            
            # Dizionario per tenere traccia dei thread attivi
            self.active_threads = {}
            
            # Prepara i dati per ogni file
            for i, (profile_name, file_path) in enumerate(files_to_analyze):
                # 'profile_name' is the key from MultiProfileDialog and must be preserved for active_threads.
                # 'name_for_detection_thread' can be updated with the Steam name for better detection if needed.
                name_for_detection_thread = profile_name
                # Aggiorna la barra di avanzamento
                self.profile_dialog.update_progress(i, f"Preparazione: {os.path.basename(file_path)}")
                QApplication.processEvents()
                
                logging.info(f"DragDropHandler._handle_profile_analysis: Preparing file: {file_path}")
                
                # Determina la directory di installazione
                game_install_dir = None
                if os.path.isfile(file_path):
                    game_install_dir = os.path.normpath(os.path.dirname(file_path))
                elif os.path.isdir(file_path):
                    game_install_dir = os.path.normpath(file_path)
                    
                # Risolvi il percorso del collegamento se è un .lnk o .url
                target_path = None
                if file_path.lower().endswith('.lnk') and platform.system() == "Windows":
                    try:
                        from win32com.client import Dispatch
                        shell = Dispatch("WScript.Shell")
                        shortcut = shell.CreateShortCut(file_path)
                        target_path = shortcut.Targetpath
                        logging.debug(f"Resolved shortcut target: {target_path}")
                    except Exception as e:
                        logging.error(f"Error resolving shortcut: {e}")
            
                # Se abbiamo risolto il collegamento, usa la directory del target
                if target_path and os.path.exists(target_path):
                    real_install_dir = os.path.dirname(target_path)
                    logging.info(f"Using resolved target directory: {real_install_dir}")
                    # Usa la directory risolta come directory di installazione
                    game_install_dir = real_install_dir
            
                # Verifica se è un gioco Steam per passare installed_steam_games_dict
                is_steam_game = False
                steam_app_id = None
                if file_path.lower().endswith('.url'):
                    try:
                        config = configparser.ConfigParser()
                        config.read(file_path)
                        if 'InternetShortcut' in config and 'URL' in config['InternetShortcut']:
                            url_from_file = config['InternetShortcut']['URL']
                            if "steam://" in url_from_file:
                                app_id_match = re.search(r'steam://rungameid/(\d+)', url_from_file)
                                if app_id_match:
                                    steam_app_id = app_id_match.group(1)
                                    is_steam_game = True
                                    logging.info(f"Detected Steam game in multi-profile: {profile_name} (AppID: {steam_app_id})")
                    except Exception as e:
                        logging.error(f"Error checking if URL file is a Steam game: {e}")
            
                # Per i giochi Steam, passiamo la lista dei giochi installati di Steam
                steam_games_dict = None
                game_details = None
                if is_steam_game and steam_app_id and hasattr(self.main_window, 'installed_steam_games_dict') and self.main_window.installed_steam_games_dict:
                    steam_games_dict = self.main_window.installed_steam_games_dict
                    logging.debug(f"Using Steam games list with {len(steam_games_dict)} entries for detection in multi-profile")
                
                    # Ottieni i dettagli del gioco Steam
                    game_details = self._get_steam_game_details(steam_app_id)
                    if game_details:
                        # Usa la directory di installazione del gioco Steam
                        game_install_dir = game_details['install_dir']
                        logging.info(f"Using Steam game install directory: {game_install_dir} for {profile_name}")
                    
                        # Usa il nome ufficiale del gioco Steam per il suggerimento al thread di rilevamento,
                        # ma mantieni 'profile_name' (la chiave del dialogo) invariato.
                        name_for_detection_thread = game_details['name']
            
                # Avvia il thread di rilevamento per questo file in modo asincrono
                detection_thread = DetectionWorkerThread(
                    game_install_dir=game_install_dir,
                    profile_name_suggestion=name_for_detection_thread, # Usa il nome (potenzialmente Steam) per il suggerimento
                    current_settings=self.main_window.current_settings.copy(),
                    installed_steam_games_dict=steam_games_dict,
                    emulator_name=None,
                    steam_app_id=steam_app_id if is_steam_game else None
                )
            
                # Salva il riferimento al thread e al nome del profilo
                thread_id = id(detection_thread)
                self.active_threads[thread_id] = {
                    'thread': detection_thread,
                    'profile_name': profile_name,
                    'completed': False
                }
            
                # Colleghiamo il segnale finished alla nostra funzione di callback
                detection_thread.finished.connect(lambda success, results, tid=thread_id: 
                                              self._on_detection_thread_finished(success, results, tid))
            
                # Colleghiamo il segnale progress per aggiornare la UI
                detection_thread.progress.connect(self.on_detection_progress)
            
                # Avvia il thread in modo asincrono
                detection_thread.start()
            
                # Breve pausa per evitare di sovraccaricare il sistema
                QThread.msleep(100)
        
        # Imposta un timer per controllare periodicamente lo stato dei thread
        self.check_threads_timer = QTimer()
        self.check_threads_timer.timeout.connect(self._check_detection_threads_status)
        self.check_threads_timer.start(500)  # Controlla ogni 500ms

    def _on_detection_thread_finished(self, success, results, thread_id):
        """Callback chiamato quando un thread di rilevamento termina.
        
        Args:
            success: True se il rilevamento è riuscito, False altrimenti
            results: Dizionario con i risultati del rilevamento
            thread_id: ID del thread che ha terminato
        """
        if thread_id not in self.active_threads:
            logging.warning(f"Thread ID {thread_id} not found in active_threads")
            return
        
        thread_info = self.active_threads[thread_id]
        profile_name = thread_info['profile_name']
        
        # Marca il thread come completato
        thread_info['completed'] = True
        
        if success and results:
            # Estrai i percorsi di salvataggio
            paths_found = results.get('path_data', [])
        
            # Usa il percorso con lo score più alto
            if paths_found and len(paths_found) > 0:
                # Ordina i percorsi per score (dal più alto al più basso)
                paths_found.sort(key=lambda x: x[1] if isinstance(x, tuple) and len(x) > 1 else 0, reverse=True)
            
                # Usa il primo percorso (quello con lo score più alto)
                best_path, best_score = paths_found[0] if isinstance(paths_found[0], tuple) else (paths_found[0], 0)
            
                # Check if profile dialog still exists before updating
                if self.profile_dialog:
                    self.profile_dialog.update_profile(profile_name, best_path, best_score)
                else:
                    logging.warning(f"Cannot update profile '{profile_name}' - profile dialog has been closed")
            
                # Aggiorna l'applicazione per mostrare i cambiamenti nell'interfaccia
                QApplication.processEvents()
            
                logging.info(f"DragDropHandler._on_detection_thread_finished: Detected profile '{profile_name}' with path: {best_path} (score: {best_score})")
            else:
                logging.warning(f"DragDropHandler._on_detection_thread_finished: No save paths found for: {profile_name}")
        else:
            logging.warning(f"DragDropHandler._on_detection_thread_finished: Detection failed for: {profile_name}")

    def _check_detection_threads_status(self):
        """Controlla lo stato dei thread di rilevamento attivi."""
        if not hasattr(self, 'active_threads'):
            return
        
        # Conta quanti thread sono completati
        completed_count = sum(1 for info in self.active_threads.values() if info['completed'])
        total_count = len(self.active_threads)
        
        # Aggiorna la barra di avanzamento solo se il dialogo esiste ancora
        if self.profile_dialog:
            if total_count > 0:
                # Passa il completed_count effettivo, non una percentuale
                self.profile_dialog.update_progress(
                    completed_count, 
                    f"Analysis in progress... {completed_count}/{total_count} completed"
                )
        
            # Se tutti i thread sono completati, notifica il completamento
            if completed_count == total_count and total_count > 0:
                # Notifica il completamento dell'analisi, passando total_count come valore corrente
                self.profile_dialog.update_progress(total_count, "Analysis completed")
                
                # Emetti un segnale per notificare il completamento dell'analisi
                # Questo segnale potrebbe non essere più strettamente necessario se MultiProfileDialog gestisce
                # il completamento direttamente in update_progress, ma lo lasciamo per ora.
                self.profile_dialog.analysis_completed.emit() 
    
        # Pulizia risorse anche se il dialogo è stato chiuso
        if completed_count == total_count and total_count > 0:
            # Ripristina il cursore
            QApplication.restoreOverrideCursor()
            
            # Ferma il timer
            self.check_threads_timer.stop()
            
            # Pulisci i riferimenti ai thread
            for thread_info in self.active_threads.values():
                if 'thread' in thread_info and thread_info['thread'] is not None:
                    thread_info['thread'].deleteLater()
            
            self.active_threads = {}
            
            logging.info("All detection threads completed.")
            
            # Emetti un segnale per notificare il completamento dell'analisi
            self.profile_dialog.analysis_completed.emit()

    def on_detection_progress(self, message):
        """Aggiorna la barra di stato di main_window con i messaggi dal thread."""
        if hasattr(self.main_window, 'status_label'):
            self.main_window.status_label.setText(message)

    def _check_detection_threads_status(self):
        """Controlla lo stato dei thread di rilevamento attivi."""
        if not hasattr(self, 'active_threads'):
            return
        
        # Conta quanti thread sono completati
        completed_count = sum(1 for info in self.active_threads.values() if info['completed'])
        total_count = len(self.active_threads)
        
        # Aggiorna la barra di avanzamento solo se il dialogo esiste ancora
        if self.profile_dialog:
            if total_count > 0:
                # Passa il completed_count effettivo, non una percentuale
                self.profile_dialog.update_progress(
                    completed_count, 
                    f"Analysis in progress... {completed_count}/{total_count} completed"
                )
            
            # Se tutti i thread sono completati, notifica il completamento
            if completed_count == total_count and total_count > 0:
                # Notifica il completamento dell'analisi, passando total_count come valore corrente
                self.profile_dialog.update_progress(total_count, "Analysis completed")
                
                # Emetti un segnale per notificare il completamento dell'analisi
                self.profile_dialog.analysis_completed.emit()
        
        # Pulizia risorse anche se il dialogo è stato chiuso
        if completed_count == total_count and total_count > 0:
            # Ripristina il cursore
            QApplication.restoreOverrideCursor()
            
            # Ferma il timer
            self.check_threads_timer.stop()
            
            # Pulisci i riferimenti ai thread
            for thread_info in self.active_threads.values():
                if 'thread' in thread_info and thread_info['thread'] is not None:
                    thread_info['thread'].deleteLater()
            
            self.active_threads = {}
            
            logging.info("All detection threads completed.")

    def _is_known_emulator(self, file_path):
        """Verifica solo se il file è un emulatore conosciuto, senza cercare i profili di salvataggio.
        Usa la funzione centralizzata in emulator_manager.
        
        Args:
            file_path: Il percorso del file da verificare
            
        Returns:
            bool: True se è un emulatore conosciuto, False altrimenti
        """
        from emulator_utils.emulator_manager import is_known_emulator
        return is_known_emulator(file_path)
        
    def _check_if_emulator(self, file_path):
        """Verifica se il file è un emulatore supportato e cerca i profili di salvataggio.
        
        Args:
            file_path: Il percorso del file da verificare
        
        Returns:
            tuple: (emulator_key, profiles_data) se è un emulatore, None altrimenti
        """
        try:
            if not os.path.exists(file_path):
                return None
        
            # Risolvi il collegamento .lnk se necessario
            target_path = file_path
            if file_path.lower().endswith('.lnk') and platform.system() == "Windows":
                try:
                    import winshell
                    shortcut = winshell.shortcut(file_path)
                    resolved_target = shortcut.path
                
                    if resolved_target and os.path.exists(resolved_target):
                        target_path = resolved_target
                        logging.info(f"_check_if_emulator: Resolved .lnk target to: {target_path}")
                    else:
                        logging.warning(f"_check_if_emulator: Could not resolve .lnk target or target does not exist: {resolved_target}")
                except Exception as e_lnk:
                    logging.error(f"Error reading .lnk file: {e_lnk}", exc_info=True)
        
            # Verifica se è un emulatore utilizzando emulator_manager
            from emulator_utils import emulator_manager
            emulator_result = emulator_manager.detect_and_find_profiles(target_path)
            return emulator_result
        except Exception as e:
            logging.error(f"Error checking if file is an emulator: {e}", exc_info=True)
            return None
            
    @Slot(bool, dict)
    def on_detection_finished(self, success, results):
        """Gestisce il completamento del thread di rilevamento dei percorsi di salvataggio."""
        logging.debug(f"DragDropHandler.on_detection_finished: Success: {success}, Results: {results}")
        mw = self.main_window
        
        # Ripristina lo stato dell'UI ma mantieni l'overlay attivo
        # Non ripristiniamo il cursore e non abilitiamo i controlli, lo farà il ProfileCreationManager
        self.detection_thread = None # Remove reference to completed thread
        
        # Delega la gestione dei risultati al ProfileCreationManager
        if hasattr(mw, 'profile_creation_manager') and mw.profile_creation_manager:
            # Salva lo stato attuale nel ProfileCreationManager
            pcm = mw.profile_creation_manager
            pcm.game_name_suggestion = self.game_name_suggestion
            pcm.game_install_dir = self.game_install_dir
            pcm.is_steam_game = self.is_steam_game
            pcm.steam_app_id = self.steam_app_id
            pcm.executable_path = self.executable_path
            pcm.shortcut_target_path = self.shortcut_target_path
            pcm.shortcut_game_name = self.shortcut_game_name
            
            # Chiama il metodo on_detection_finished del ProfileCreationManager
            # che gestirà l'overlay e i dialoghi di selezione dei percorsi
            pcm.on_detection_finished(success, results)
        else:
            # Solo in caso di errore nascondiamo l'overlay e ripristiniamo lo stato dell'UI
            self._hide_overlay_if_visible(mw)
            mw.set_controls_enabled(True)
            QApplication.restoreOverrideCursor()
            
            logging.error("DragDropHandler.on_detection_finished: ProfileCreationManager not available")
            QMessageBox.critical(mw, "Error", "Internal error: ProfileCreationManager not available.")
            mw.status_label.setText("Error: ProfileCreationManager not available.")
            return

    # --- Method to handle Steam URL drop ---
    def handle_steam_url_drop(self, steam_url_str):
        """
        Handles a dropped Steam URL string.
        Parses the AppID, checks if the game is installed, and starts detection.
        """
        logger.info(f"Handling Steam URL drop: {steam_url_str}")
        
        # Salva il valore attuale del flag prima di resettare lo stato
        skip_popup = getattr(self, 'skip_steam_error_popup', False)
        
        # Reset dello stato interno
        self.reset_internal_state()
        
        # Ripristina il flag dopo il reset
        self.skip_steam_error_popup = skip_popup

        mw = self.main_window

        app_id_match = re.search(r'steam://rungameid/(\d+)', steam_url_str)
        if not app_id_match:
            # Usa un messaggio non modale invece di QMessageBox.warning
            msg_box = QMessageBox(QMessageBox.Icon.Warning, "Invalid Steam URL", 
                                 "The provided Steam URL is not valid or could not be parsed.", 
                                 QMessageBox.StandardButton.Ok, mw)
            msg_box.setWindowModality(Qt.NonModal)
            msg_box.show()
            mw.status_label.setText("Invalid Steam URL detected.")
            logger.warning(f"Could not parse AppID from Steam URL: {steam_url_str}")
            self._hide_overlay_if_visible(mw)
            return

        app_id = app_id_match.group(1)
        logger.debug(f"Extracted AppID: {app_id} from URL.")

        game_details = self._get_steam_game_details(app_id)

        if game_details:
            self.game_name_suggestion = game_details['name']
            self.game_install_dir = game_details['install_dir'] 
            self.is_steam_game = True
            self.steam_app_id = app_id
            
            logger.info(f"Steam game found: '{self.game_name_suggestion}' (AppID: {self.steam_app_id}), Install Dir: {self.game_install_dir}")
            mw.status_label.setText(f"Processing Steam game: {self.game_name_suggestion}...")

            # Disabilitiamo i controlli e impostiamo il cursore di attesa
            # come facciamo nel metodo dropEvent normale
            mw.set_controls_enabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

            if not hasattr(mw, 'current_settings'):
                logger.error("MainWindow is missing 'current_settings'. Cannot proceed with detection.")
                # Usa un messaggio non modale invece di QMessageBox.critical
                msg_box = QMessageBox(QMessageBox.Icon.Critical, "Internal Error", 
                                     "Required application settings are missing. Cannot start game detection.", 
                                     QMessageBox.StandardButton.Ok, mw)
                msg_box.setWindowModality(Qt.NonModal)
                msg_box.show()
                self._hide_overlay_if_visible(mw)
                # Ripristiniamo i controlli e il cursore normale in caso di errore
                mw.set_controls_enabled(True)
                QApplication.restoreOverrideCursor()
                return
            
            # Utilizziamo lo stesso approccio del metodo start_steam_configuration
            # che funziona correttamente con il fade effect
            if hasattr(mw, 'loading_label') and mw.loading_label:
                mw.loading_label.setText("Searching...") # Set text for search
                mw.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; }")
                mw.loading_label.adjustSize() # Ensure label resizes to content
            
            if hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                mw.overlay_widget.resize(mw.centralWidget().size())
                # Assicuriamoci che l'overlay non sia già attivo
                if hasattr(mw, 'overlay_active'):
                    mw.overlay_active = False
                mw.overlay_widget.show() # Show overlay first
                mw.overlay_widget.raise_() # Ensure it's on top
            
            if hasattr(mw, '_center_loading_label'):
                mw._center_loading_label() # Center label on now-visible overlay
            
            if hasattr(mw, 'loading_label') and mw.loading_label:
                mw.loading_label.show() # Explicitly show the label
            
            if hasattr(mw, 'fade_in_animation') and mw.fade_in_animation:
                mw.fade_in_animation.stop() # Stop if already running
                mw.fade_in_animation.start() # Start the animation
                logging.debug("Fade-in animation started for overlay in handle_steam_url_drop.")

            # Per i link Steam, passiamo la lista dei giochi installati di Steam
            # Questo è necessario solo per i link Steam, non per i giochi normali o gli emulatori
            steam_games_dict = None
            if hasattr(mw, 'installed_steam_games_dict') and mw.installed_steam_games_dict:
                steam_games_dict = mw.installed_steam_games_dict
                logging.debug(f"Using Steam games list with {len(steam_games_dict)} entries for detection")
            else:
                logging.debug("No Steam games list available for detection")
                
            self.detection_thread = DetectionWorkerThread(
                profile_name_suggestion=self.game_name_suggestion,
                game_install_dir=self.game_install_dir,
                current_settings=mw.current_settings,
                installed_steam_games_dict=steam_games_dict
            )
            self.detection_thread.progress.connect(self.on_detection_progress)
            self.detection_thread.finished.connect(self.on_detection_finished)
            self.detection_thread.start()
            
        else:
            # Check if this is a direct call or from dropEvent
            if hasattr(self, 'skip_steam_error_popup') and self.skip_steam_error_popup:
                # Skip showing error popup, just log and update status
                mw.status_label.setText(f"Steam game (AppID: {app_id}) not installed. No profile created.")
                logger.warning(f"Steam game with AppID {app_id} not found in installed_steam_games_dict.")
                self._hide_overlay_if_visible(mw)
            else:
                # Show normal error popup
                # Show normal error popup - make it non-modal
                msg_box = QMessageBox(QMessageBox.Icon.Warning, "Steam Game Not Found", 
                                     f"The Steam game with AppID {app_id} does not appear to be installed, "
                                     "or its details could not be retrieved from your Steam library.\n\n"
                                     "Please ensure the game is installed and that SaveState has correctly "
                                     "identified your Steam installation.", 
                                     QMessageBox.StandardButton.Ok, mw)
                msg_box.setWindowModality(Qt.NonModal)
                msg_box.show()
                mw.status_label.setText(f"Steam game (AppID: {app_id}) not found or not installed.")
                logger.warning(f"Steam game with AppID {app_id} not found in installed_steam_games_dict.")
                self._hide_overlay_if_visible(mw)

   # --- Drag and Drop Management ---
    def dragEnterEvent(self, event):
        """Handles the drag-and-drop event. Accepts if mimeData has URLs or text."""
        mime_data = event.mimeData()
        mw = self.main_window

        # Log detailed MIME data information
        logging.debug(f"PCM.dragEnterEvent: MimeData formats: {mime_data.formats()}")
        if mime_data.hasUrls():
            urls_debug_list = []
            for url_obj_debug in mime_data.urls():
                urls_debug_list.append(
                    f"URL: {url_obj_debug.toString()}, "
                    f"Scheme: {url_obj_debug.scheme()}, "
                    f"IsLocal: {url_obj_debug.isLocalFile()}, "
                    f"LocalPath: {url_obj_debug.toLocalFile() if url_obj_debug.isLocalFile() else 'N/A'}"
                )
            logging.debug(f"  PCM.dragEnterEvent: MimeData has URLs: [{', '.join(urls_debug_list)}]")
        if mime_data.hasText():
            logging.debug(f"  PCM.dragEnterEvent: MimeData has Text (first 200 chars): '{mime_data.text()[:200]}'")

        if mime_data.hasUrls() or mime_data.hasText():
            event.acceptProposedAction()
            logging.debug("PCM.dragEnterEvent: Accepted event due to presence of URLs or Text.")

            # Overlay Management
            if hasattr(mw, 'enable_global_drag_effect') and mw.settings_manager.get_setting('enable_global_drag_effect'):
                logging.debug("PCM.dragEnterEvent: Global drag effect is ON. MainWindow should handle overlay.")
            elif hasattr(mw, 'overlay_active') and mw.overlay_active:
                logging.debug("PCM.dragEnterEvent: Overlay already active (by MainWindow), PCM skipping local overlay.")
            else:
                if hasattr(mw, 'loading_label') and mw.loading_label and \
                   hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                    
                    logging.debug("PCM.dragEnterEvent: Managing local overlay indication.")
                    mw.loading_label.setText("Drop Here to Create Profile")
                    if hasattr(mw, '_center_loading_label'):
                        mw._center_loading_label()
                    
                    mw.overlay_widget.setStyleSheet("QWidget#BusyOverlay { background-color: rgba(0, 0, 0, 200); }")
                    
                    if hasattr(mw, 'overlay_active'):
                        mw.overlay_active = True
                        logging.debug("PCM.dragEnterEvent: setting MainWindow.overlay_active = True for local overlay.")
                    
                    if hasattr(mw, 'overlay_opacity_effect'):
                        mw.overlay_opacity_effect.setOpacity(1.0)
                    
                    mw.overlay_widget.show()
                    mw.loading_label.show()
                else:
                    logging.debug("PCM.dragEnterEvent: MainWindow overlay components not found.")
        else:
            logging.debug("PCM.dragEnterEvent: Rejected event, no URLs or Text.")
            event.ignore()

    def dragMoveEvent(self, event):
        """Handles the movement of a dragged object over the widget."""
        # This event should generally accept if dragEnterEvent accepted.
        # The main purpose is to allow dropEvent to occur.
        # Specific logic for visual feedback during move can be added if needed.
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Handles the drag leave event."""
        # NON nascondiamo più l'overlay quando il drag esce dalla finestra
        # Ora il MainWindow gestisce il rilevamento globale del drag
        logging.debug("dragLeaveEvent: il cursore è uscito dalla finestra ma l'overlay rimane visibile")
        
        # Impostiamo una variabile per indicare che il drag è attivo
        mw = self.main_window
        
        # Manteniamo il flag overlay_active se esiste
        # Questo è importante per evitare che l'overlay venga mostrato di nuovo quando il cursore rientra
        if hasattr(mw, 'overlay_active') and mw.overlay_active:
            logging.debug("dragLeaveEvent: mantengo MainWindow.overlay_active = True")
            # Non facciamo nulla, il flag rimane True
        
        if hasattr(mw, 'is_drag_operation_active'):
            mw.is_drag_operation_active = True
            logging.debug("Impostato is_drag_operation_active = True in dragLeaveEvent")
            
        event.accept()

    def dropEvent(self, event: QDropEvent):
        """Handles the release of a dragged object. Prioritizes Steam URLs, then local files/shortcuts."""
        self.reset_internal_state() # Reset state at the beginning
        mw = self.main_window # Alias for main window
        mime_data = event.mimeData()

        # --- Log MIME Data --- 
        logging.debug(f"PCM.dropEvent: MimeData formats: {mime_data.formats()}")
        if mime_data.hasUrls():
            urls_debug_list = []
            for url_obj_debug in mime_data.urls():
                urls_debug_list.append(url_obj_debug.toString())
            logging.debug(f"PCM.dropEvent: MimeData URLs: {urls_debug_list}")
        # --- End Log MIME Data ---

        # Gestione per URL Steam (priorità alta)
        if mime_data.hasText() or mime_data.hasUrls():
            # Estrai l'URL dal testo o dall'URL
            steam_url_str = None
            
            # Controlla prima il testo
            if mime_data.hasText():
                text = mime_data.text()
                if "store.steampowered.com" in text or "steam://" in text:
                    steam_url_str = text
                    logging.debug(f"PCM.dropEvent: Found Steam URL in text: {steam_url_str}")
            
            # Se non trovato nel testo, controlla gli URL
            if not steam_url_str and mime_data.hasUrls():
                for url_obj in mime_data.urls():
                    url_str = url_obj.toString()
                    
                    # Controlla se è un URL Steam diretto
                    if "store.steampowered.com" in url_str or "steam://" in url_str:
                        steam_url_str = url_str
                        logging.debug(f"PCM.dropEvent: Found Steam URL in URL: {steam_url_str}")
                        break
                    
                    # Controlla se è un file .url che potrebbe contenere un URL Steam
                    if url_str.endswith(".url") and url_obj.isLocalFile():
                        local_path = url_obj.toLocalFile()
                        try:
                            config = configparser.ConfigParser()
                            config.read(local_path)
                            if 'InternetShortcut' in config and 'URL' in config['InternetShortcut']:
                                url_from_file = config['InternetShortcut']['URL']
                                if "store.steampowered.com" in url_from_file or "steam://" in url_from_file:
                                    steam_url_str = url_from_file
                                    logging.debug(f"PCM.dropEvent: Found Steam URL in .url file: {steam_url_str}")
                                    break
                        except Exception as e:
                            logging.error(f"Error parsing .url file: {e}")
            
            # Se abbiamo trovato un URL Steam, gestiscilo
            if steam_url_str:
                # Check if we're in a multi-file drop scenario
                multi_file_drop = False
                file_count = 0
                if mime_data.hasUrls():
                    file_count = len(mime_data.urls())
                    multi_file_drop = file_count > 1
                
                # Extract the AppID
                app_id_match = re.search(r'steam://rungameid/(\d+)', steam_url_str)
                if app_id_match:
                    app_id = app_id_match.group(1)
                    game_details = self._get_steam_game_details(app_id)
                    
                    # Check if the game is installed
                    if not game_details:
                        # Game not installed
                        if multi_file_drop:
                            # In multi-file drop, just log and continue with other files
                            logging.info(f"Steam game with AppID {app_id} not installed, skipping in multi-file drop")
                            # Don't handle this Steam URL, proceed to process all files together
                            # This will allow the multi-file handling code to filter out invalid files
                            # We're not returning here, letting it fall through to the multi-file handling code
                        else:
                            # For single file drop, check if it's a .url file
                            is_url_file = False
                            if mime_data.hasUrls():
                                for url_obj in mime_data.urls():
                                    if url_obj.isLocalFile() and url_obj.toLocalFile().lower().endswith('.url'):
                                        is_url_file = True
                                        break
                            
                            if is_url_file:
                                # For .url files, just show a status message without error popup
                                logging.info(f"Steam game with AppID {app_id} not installed, skipping .url file")
                                mw.status_label.setText(f"Steam game (AppID: {app_id}) not installed. No profile created.")
                                event.acceptProposedAction()
                                return
                            else:
                                # For direct Steam URLs, use the normal handling with error popup
                                self.original_steam_url_str = steam_url_str
                                # Set flag to skip error popup for .url files
                                self.skip_steam_error_popup = True
                                self.handle_steam_url_drop(steam_url_str)
                                # Reset flag after handling
                                self.skip_steam_error_popup = False
                                event.acceptProposedAction()
                                return
                    else:
                        # If it's a multi-file drop and the game is installed, we still want to process all files together
                        if multi_file_drop:
                            # Don't handle this Steam URL separately, proceed to process all files together
                            # This ensures consistent behavior for all multi-file drops
                            logging.info(f"Steam game with AppID {app_id} is installed, but processing it as part of multi-file drop")
                            # We're not returning here, letting it fall through to the multi-file handling code
                        else:
                            # For single file, handle it normally
                            self.original_steam_url_str = steam_url_str
                            self.handle_steam_url_drop(steam_url_str)
                            event.acceptProposedAction()
                            return
                else:
                    # No AppID found
                    if multi_file_drop:
                        # For multi-file drop, process all files together
                        logging.info("No AppID found in Steam URL, processing as part of multi-file drop")
                        # We're not returning here, letting it fall through to the multi-file handling code
                    else:
                        # For single file, handle it normally
                        self.original_steam_url_str = steam_url_str
                        self.handle_steam_url_drop(steam_url_str)
                        event.acceptProposedAction()
                        return
        
        # Gestione per file locali e collegamenti
        if mime_data.hasUrls():
            # Importa winshell solo su Windows (richiesto per i file .lnk)
            if platform.system() == "Windows":
                try:
                    import winshell
                    import pythoncom
                except ImportError:
                    logging.error("The 'winshell' or 'pywin32' library is not installed. Cannot read .lnk files.")
                    QMessageBox.critical(self.main_window, "Dependency Error",
                                        "The 'winshell' and 'pywin32' libraries are required to read shortcuts (.lnk) on Windows.")
                    return

        # Lista per raccogliere i file da processare
        files_to_process = []
        
        if mime_data.hasUrls(): # Raccoglie tutti i file/URL validi
            for url in mime_data.urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    
                    # Verifica se è un collegamento .lnk che punta a una directory
                    is_dir_shortcut = False
                    if file_path.lower().endswith('.lnk') and platform.system() == "Windows":
                        try:
                            import winshell
                            shortcut = winshell.shortcut(file_path)
                            resolved_target = shortcut.path
                            
                            if resolved_target and os.path.exists(resolved_target) and os.path.isdir(resolved_target):
                                logging.info(f"DragDropHandler.dropEvent: Skipping directory shortcut: {file_path} -> {resolved_target}")
                                is_dir_shortcut = True
                        except Exception as e_lnk:
                            logging.error(f"Error reading .lnk file: {e_lnk}", exc_info=True)
                    
                    # Skip directories and directory shortcuts in multi-file processing
                    if os.path.isdir(file_path) or is_dir_shortcut:
                        logging.info(f"DragDropHandler.dropEvent: Skipping directory or directory shortcut: {file_path}")
                        continue
                        
                    # Verifica se è un URL Steam valido
                    if file_path.lower().endswith('.url'):
                        try:
                            config = configparser.ConfigParser()
                            config.read(file_path)
                            if 'InternetShortcut' in config and 'URL' in config['InternetShortcut']:
                                url_from_file = config['InternetShortcut']['URL']
                                # Verifica se è un URL Steam
                                if not ("store.steampowered.com" in url_from_file or "steam://" in url_from_file):
                                    logging.info(f"DragDropHandler.dropEvent: Skipping non-Steam URL file: {file_path}")
                                    continue
                        except Exception as e:
                            logging.error(f"Error parsing .url file: {e}")
                    
                    logging.info(f"DragDropHandler.dropEvent: Added file to process: {file_path}")
                    files_to_process.append(file_path)
        
        # Verifica se abbiamo file da processare
        if not files_to_process:
            logging.warning("DragDropHandler.dropEvent: No valid files to process")
            event.ignore()
            return
        
        # Verifica se è un emulatore
        if len(files_to_process) == 1:
            file_path = files_to_process[0]
            emulator_result = self._check_if_emulator(file_path)
            
            if emulator_result:
                emulator_key, profiles_data = emulator_result
                logging.info(f"DragDropHandler.dropEvent: Detected emulator: {emulator_key}")
                
                # Gestisci l'emulatore in modo specifico
                if emulator_key == "PCSX2" and profiles_data:
                    self._handle_pcsx2_emulator(file_path, profiles_data)
                    event.acceptProposedAction()
                    return
                elif emulator_key == "minecraft" and profiles_data:
                    self._handle_minecraft(file_path, profiles_data)
                    event.acceptProposedAction()
                    return
                else:
                    # Gestione generica per altri emulatori
                    # Implementazione inline invece di chiamare un metodo separato
                    mw = self.main_window
                    logging.info(f"DragDropHandler: Handling emulator: {emulator_key} with {len(profiles_data)} profiles")
                    
                    # Special handling for SameBoy emulator
                    if emulator_key == 'sameboy' and profiles_data is None:
                        # Try to find SameBoy profiles manually
                        try:
                            from emulator_utils import sameboy_manager
                            rom_dir = sameboy_manager.get_sameboy_saves_path()
                            if rom_dir:
                                profiles_data = sameboy_manager.find_sameboy_profiles(rom_dir)
                                if profiles_data:
                                    logging.info(f"Found save files in hardcoded path: {rom_dir}")
                                    logging.info(f"Found {len(profiles_data)} SameBoy profiles in directory '{rom_dir}'.")
                                else:
                                    logging.warning(f"No SameBoy profiles found in directory '{rom_dir}'.")
                            else:
                                logging.warning("Could not determine SameBoy ROM directory.")
                        except Exception as e:
                            logging.error(f"Error finding SameBoy profiles: {e}")
                            QMessageBox.warning(
                                mw, "SameBoy Detection Error",
                                f"An error occurred while trying to detect SameBoy profiles: {e}\n"
                                "You can try adding the emulator again or set the path manually via settings (if available).")
                    
                    # Handle emulator profiles if found
                    if emulator_key and profiles_data is not None:  # Check if profiles_data is not None (it could be an empty list)
                        logging.info(f"Found {emulator_key} profiles: {len(profiles_data)}")
                        
                        # Show dialog for selecting which emulator game to create a profile for
                        selection_dialog = EmulatorGameSelectionDialog(emulator_key, profiles_data, mw)
                        if selection_dialog.exec():
                            selected_profile = selection_dialog.get_selected_profile_data()
                            if selected_profile:
                                # Extract details from the selected profile
                                profile_id = selected_profile.get('id', '')
                                selected_name = selected_profile.get('name', profile_id)
                                save_paths = selected_profile.get('paths', [])
                                
                                # Create a profile name based on the emulator and game
                                profile_name_base = f"{emulator_key} - {selected_name}"
                                profile_name = profile_name_base
                                
                                # Check if profile already exists
                                if profile_name in mw.profiles:
                                    reply = QMessageBox.question(mw, "Existing Profile",
                                                            f"A profile named '{profile_name}' already exists. Overwrite it?",
                                                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                            QMessageBox.StandardButton.No)
                                    if reply == QMessageBox.StandardButton.No:
                                        mw.status_label.setText("Profile creation cancelled.")
                                        event.acceptProposedAction()
                                        return
                                    else:
                                        logging.warning(f"Overwriting existing profile: {profile_name}")
                                
                                # Create the profile with the appropriate data
                                new_profile = {
                                    'name': profile_name,
                                    'paths': save_paths,
                                    'emulator': emulator_key
                                }
                                
                                # Add the profile to the main window's profiles dictionary
                                mw.profiles[profile_name] = new_profile
                                
                                # Save the profiles to disk
                                if mw.core_logic.save_profiles(mw.profiles):
                                    if hasattr(mw, 'profile_table_manager'):
                                        mw.profile_table_manager.update_profile_table()
                                        mw.profile_table_manager.select_profile_in_table(profile_name)
                                    mw.status_label.setText(f"Profile '{profile_name}' created successfully.")
                                    logging.info(f"Emulator game profile '{profile_name}' created/updated with emulator '{emulator_key}'.")
                                else:
                                    logging.error(f"Failed to save profiles after adding '{profile_name}'.")
                                    QMessageBox.critical(mw, "Save Error", "Failed to save the profiles. Check the log for details.")
                        else:
                            logging.info("User cancelled emulator game selection.")
                        
                        # Hide the overlay if it's visible
                        self._hide_overlay_if_visible(mw)
                        mw.set_controls_enabled(True)
                        QApplication.restoreOverrideCursor()
                    elif emulator_key:  # Emulator detected but no profiles found
                        logging.warning(f"{emulator_key} detected, but no profiles found in its standard directory.")
                        QMessageBox.warning(
                            mw, f"{emulator_key.capitalize()} Profiles",
                            f"No game profiles were found for {emulator_key.capitalize()}.\n\n"
                            "This could be because:\n"
                            "- You haven't played any games yet\n"
                            "- The emulator is installed in a non-standard location\n"
                            "- The save files are stored in a custom location")
                        
                        # Hide the overlay if it's visible
                        self._hide_overlay_if_visible(mw)
                        mw.set_controls_enabled(True)
                        QApplication.restoreOverrideCursor()
                    
                    event.acceptProposedAction()
                    return
        else:
            # Processare più file contemporaneamente
            logging.info(f"DragDropHandler.dropEvent: Processing multiple files: {len(files_to_process)}")
            
            # Filter out emulators and uninstalled Steam games from files_to_process
            filtered_files = []
            for file_path in files_to_process:
                # Check if it's an emulator
                emulator_result = self._check_if_emulator(file_path)
                if emulator_result:
                    logging.info(f"DragDropHandler.dropEvent: Skipping emulator: {file_path}")
                    continue
                
                # Check if it's a Steam link to an uninstalled game
                is_uninstalled_steam_game = False
                
                # Check if it's a .url file that might contain a Steam URL
                if file_path.lower().endswith(".url"):
                    try:
                        config = configparser.ConfigParser()
                        config.read(file_path)
                        if 'InternetShortcut' in config and 'URL' in config['InternetShortcut']:
                            url_from_file = config['InternetShortcut']['URL']
                            if "steam://" in url_from_file:
                                app_id_match = re.search(r'steam://rungameid/(\d+)', url_from_file)
                                if app_id_match:
                                    app_id = app_id_match.group(1)
                                    game_details = self._get_steam_game_details(app_id)
                                    if not game_details:
                                        logging.info(f"DragDropHandler.dropEvent: Skipping uninstalled Steam game (AppID: {app_id}): {file_path}")
                                        is_uninstalled_steam_game = True
                    except Exception as e:
                        logging.error(f"Error checking Steam URL in .url file: {e}")
                
                # Add the file only if it's not an emulator and not an uninstalled Steam game
                if not is_uninstalled_steam_game:
                    filtered_files.append(file_path)
            
            # Update files_to_process with filtered list
            files_to_process = filtered_files
            
            # If no files left after filtering, show message and return
            if not files_to_process:
                logging.info("DragDropHandler.dropEvent: No valid files to process after filtering out emulators")
                mw.status_label.setText("No valid game files found (emulators were filtered out).")
                event.ignore()
                return
            
            # Crea il dialogo per la gestione dei profili
            dialog = MultiProfileDialog(files_to_process=files_to_process, parent=mw)
            
            # Connetti il segnale profileAdded al metodo che gestisce l'analisi
            dialog.profileAdded.connect(self._handle_profile_analysis)
            
            # Salva il riferimento al dialogo come attributo dell'istanza
            self.profile_dialog = dialog
            
            # Mostra il dialogo e attendi che l'utente faccia la sua scelta
            result = dialog.exec()
            
            # Ripristina lo stato dell'UI
            mw.set_controls_enabled(True)
            
            # Nascondi l'overlay se visibile
            self._hide_overlay_if_visible(mw)
            
            if result == QDialog.Accepted:
                # Ottieni i profili accettati
                accepted_profiles = dialog.get_accepted_profiles()
                
                # Aggiungi i profili accettati
                for profile_name, profile_data in accepted_profiles.items():
                    mw.profiles[profile_name] = profile_data
                
                # Salva i profili
                if mw.core_logic.save_profiles(mw.profiles):
                    mw.profile_table_manager.update_profile_table()
                    mw.status_label.setText(f"Aggiunti {len(accepted_profiles)} profili.")
                    logging.info(f"Saved {len(accepted_profiles)} profiles.")
                else:
                    mw.status_label.setText("Errore nel salvataggio dei profili.")
                    logging.error("Failed to save profiles.")
                    QMessageBox.critical(mw, "Errore", "Impossibile salvare i profili.")
            else:
                mw.status_label.setText("Creazione profili annullata.")
                logging.info("DragDropHandler.dropEvent: Profile creation cancelled by user.")
                
            # Rimuovi il riferimento al dialogo
            self.profile_dialog = None
            
            event.acceptProposedAction()
            return
            
        # Definiamo le variabili per il tipo di file
        file_path = files_to_process[0]  # A questo punto sappiamo che c'è almeno un file
        is_windows_link = file_path.lower().endswith('.lnk') and platform.system() == "Windows"
        is_linux_desktop = file_path.lower().endswith('.desktop') and platform.system() == "Linux"
        # Ensure it's a file and executable, not a directory
        is_linux_executable = platform.system() == "Linux" and os.path.isfile(file_path) and os.access(file_path, os.X_OK)
        
        if is_windows_link:
            logging.debug("PCM.dropEvent (Fallback): Detected Windows .lnk file, attempting to resolve target...")
            try:
                shortcut = winshell.shortcut(file_path)
                resolved_target = shortcut.path
                working_dir = shortcut.working_directory

                if not resolved_target or not os.path.exists(resolved_target):
                        logging.error(f"Could not resolve .lnk target or target does not exist: {resolved_target}")
                        QMessageBox.critical(mw, "Shortcut Error",
                                            f"Unable to resolve the shortcut path or the target file/folder does not exist:\n'{resolved_target or 'N/A'}'")
                        event.ignore()
                        return

                target_path = resolved_target
                logging.info(f"PCM.dropEvent (Fallback): Resolved .lnk target to: {target_path}")

                if working_dir and os.path.isdir(working_dir):
                    game_install_dir = os.path.normpath(working_dir)
                elif os.path.isfile(target_path):
                    game_install_dir = os.path.normpath(os.path.dirname(target_path))
                elif os.path.isdir(target_path):
                        game_install_dir = os.path.normpath(target_path)
                logging.debug(f"PCM.dropEvent (Fallback): Game folder from resolved shortcut: {game_install_dir}")
            except Exception as e_lnk:
                logging.error(f"Error reading .lnk file: {e_lnk}", exc_info=True)
                QMessageBox.critical(mw, "Shortcut Error", f"Unable to read the .lnk file:\n{e_lnk}")
                event.ignore()
                return
            
        elif is_linux_desktop:
            try:
                # --- BEGIN INLINE .desktop PARSING (Adattato da v1.4, SENZA ICONE) ---
                logging.debug("PCM.dropEvent (Fallback): Parsing Linux .desktop file inline...")
                parsed_exec = None
                parsed_path = None # Corrisponde a 'Path=' nel file .desktop
                # Nessuna variabile parsed_icon qui, perché hai detto che non ti serve

                with open(file_path, 'r', encoding='utf-8') as desktop_file:
                    for line in desktop_file:
                        line = line.strip()
                        if line.startswith('Exec='):
                            exec_cmd = line[5:].strip()
                            if exec_cmd.startswith('"'):
                                end_quote_idx = exec_cmd.find('"', 1)
                                if end_quote_idx != -1:
                                    parsed_exec = exec_cmd[1:end_quote_idx]
                                else: 
                                    parsed_exec = exec_cmd.split()[0]
                            else:
                                parsed_exec = exec_cmd.split()[0]

                        elif line.startswith('Path='):
                            parsed_path = line[5:].strip()
                            if parsed_path.startswith('"') and parsed_path.endswith('"'):
                                parsed_path = parsed_path[1:-1]
                
                if parsed_exec:
                    if not os.path.isabs(parsed_exec):
                        resolved_in_custom_path = False
                        if parsed_path and os.path.isdir(parsed_path):
                            potential_full_path = os.path.join(parsed_path, parsed_exec)
                            if os.path.isfile(potential_full_path) and os.access(potential_full_path, os.X_OK):
                                parsed_exec = os.path.normpath(potential_full_path)
                                resolved_in_custom_path = True
                                logging.debug(f".desktop 'Exec' ('{os.path.basename(parsed_exec)}') resolved using 'Path=' field to: {parsed_exec}")
                        
                        if not resolved_in_custom_path:
                            logging.debug(f".desktop 'Exec' ('{parsed_exec}') is relative. Searching in system PATH...")
                            system_path_dirs = os.environ.get('PATH', '').split(os.pathsep)
                            for path_dir_env in system_path_dirs:
                                full_path_env = os.path.join(path_dir_env, parsed_exec)
                                if os.path.isfile(full_path_env) and os.access(full_path_env, os.X_OK):
                                    parsed_exec = os.path.normpath(full_path_env)
                                    logging.debug(f".desktop 'Exec' resolved via system PATH to: {parsed_exec}")
                                    break 
                            else: 
                                logging.warning(f".desktop 'Exec' ('{parsed_exec}') could not be resolved to an absolute path via 'Path=' field or system PATH.")
                # --- FINE INLINE .desktop PARSING ---

                if not parsed_exec or not os.path.exists(parsed_exec):
                    logging.error(f"Could not parse 'Exec' from .desktop or resolved path does not exist: {parsed_exec}")
                    QMessageBox.critical(mw, "Desktop File Error", f"Unable to parse executable path from .desktop or the path doesn't exist:\n'{parsed_exec or 'N/A'}'")
                    event.ignore(); return

                target_path = parsed_exec 
                logging.info(f"PCM.dropEvent (Fallback): Parsed .desktop 'Exec' to target: {target_path}")

                if parsed_path and os.path.isdir(parsed_path): 
                    game_install_dir = os.path.normpath(parsed_path)
                elif os.path.isfile(target_path): 
                    game_install_dir = os.path.normpath(os.path.dirname(target_path))
                
                logging.debug(f"PCM.dropEvent (Fallback): Game install directory from .desktop: {game_install_dir}")

            except Exception as e_desktop: 
                logging.error(f"Error processing .desktop file '{file_path}': {e_desktop}", exc_info=True)
                QMessageBox.critical(mw, "Desktop File Error", f"Unable to process .desktop file:\n{file_path}\nError: {e_desktop}")
                event.ignore(); return

        elif is_linux_executable: # Already checked it's not a .desktop and is a file
            logging.debug(f"PCM.dropEvent (Fallback): Detected Linux executable: {file_path}")
            target_path = file_path
            game_install_dir = os.path.normpath(os.path.dirname(file_path))
            logging.debug(f"PCM.dropEvent (Fallback): Game folder from Linux executable: {game_install_dir}")

        # Se è un file ma non è un collegamento di Windows (.lnk), un file desktop di Linux (.desktop) o un file eseguibile di Linux
        # lo rifiutiamo per motivi di sicurezza (per evitare che l'applicazione accetti file non validi come immagini)
        elif os.path.isfile(file_path):
            logging.warning(f"PCM.dropEvent: File type not allowed: {file_path}")
            QMessageBox.warning(mw, "File Type Not Supported", 
                                f"Only Windows shortcuts (.lnk), Linux desktop files (.desktop), Linux executables, or Steam links are supported.\n\n"
                                f"The file '{os.path.basename(file_path)}' is not a valid shortcut or executable.")
            event.ignore()
            return
        elif os.path.isdir(file_path):
            logging.debug(f"PCM.dropEvent (Fallback): Processing direct folder drop: {file_path}")
            target_path = file_path # Could be the game folder itself or a folder containing the executable
            game_install_dir = os.path.normpath(file_path)
            # For directories, we might need to search for an executable later if target_path is this directory
            logging.debug(f"PCM.dropEvent (Fallback): Game folder from direct directory: {game_install_dir}")
        
        # Fallback for game_install_dir if not set by specific handlers
        if not game_install_dir and target_path and os.path.exists(target_path):
            if os.path.isfile(target_path):
                potential_dir = os.path.dirname(target_path)
                if os.path.isdir(potential_dir): game_install_dir = os.path.normpath(potential_dir)
            elif os.path.isdir(target_path): # If target_path itself is a directory
                game_install_dir = os.path.normpath(target_path)
            if game_install_dir: logging.debug(f"PCM.dropEvent (Fallback): Game install dir set by general fallback: {game_install_dir}")

        if target_path and os.path.exists(target_path):
            game_name = Path(target_path).stem
            if platform.system() == "Windows" and game_name.lower().endswith('.exe'): game_name = game_name[:-4]
            # Utilizziamo clean_for_comparison da save_path_finder invece di clean_game_name da core_logic
            from save_path_finder import clean_for_comparison
            game_name = clean_for_comparison(game_name)
            logging.info(f"PCM.dropEvent (Fallback): Extracted game name: {game_name} from target: {target_path}")
            
            # --- NOW, call emulator detection using the RESOLVED target_path ---
            # This should happen BEFORE we start the heuristic search
            emulator_result = emulator_manager.detect_and_find_profiles(target_path)
            
            # If an emulator was detected, handle it accordingly
            if emulator_result is not None:
                emulator_key, profiles_data = emulator_result
                
                # Special handling for SameBoy emulator
                if emulator_key == 'sameboy' and profiles_data is None:
                    # Try to find SameBoy profiles manually
                    try:
                        from emulator_utils import sameboy_manager
                        rom_dir = sameboy_manager.get_sameboy_saves_path()
                        if rom_dir:
                            profiles_data = sameboy_manager.find_sameboy_profiles(rom_dir)
                            if profiles_data:
                                logging.info(f"Found save files in hardcoded path: {rom_dir}")
                                logging.info(f"Found {len(profiles_data)} SameBoy profiles in directory '{rom_dir}'.")
                            else:
                                logging.warning(f"No SameBoy profiles found in directory '{rom_dir}'.")
                        else:
                            logging.warning("Could not determine SameBoy ROM directory.")
                    except Exception as e:
                        logging.error(f"Error finding SameBoy profiles: {e}")
                        QMessageBox.warning(
                            mw, "SameBoy Detection Error",
                            f"An error occurred while trying to detect SameBoy profiles: {e}\n"
                            "You can try adding the emulator again or set the path manually via settings (if available).")
                
                # Handle emulator profiles if found
                if emulator_key and profiles_data is not None: # Check if profiles_data is not None (it could be an empty list)
                    logging.info(f"Found {emulator_key} profiles: {len(profiles_data)}")
                    
                    # Show dialog for selecting which emulator game to create a profile for
                    selection_dialog = EmulatorGameSelectionDialog(emulator_key, profiles_data, mw)
                    if selection_dialog.exec():
                        selected_profile = selection_dialog.get_selected_profile_data()
                        logging.debug(f"PCM.dropEvent: Emulator game selected. Raw selected_profile data: {selected_profile}") # ADDED LOG
                        if selected_profile:
                            # Extract details from the selected profile
                            profile_id = selected_profile.get('id', '')
                            selected_name = selected_profile.get('name', profile_id)
                            save_paths = selected_profile.get('paths', [])
                            
                            # Create a profile name based on the emulator and game
                            profile_name_base = f"{emulator_key} - {selected_name}"
                            profile_name = profile_name_base
                            
                            # Check if profile already exists
                            if profile_name in mw.profiles:
                                reply = QMessageBox.question(mw, "Existing Profile",
                                                        f"A profile named '{profile_name}' already exists. Overwrite it?",
                                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                                        QMessageBox.StandardButton.No)
                                if reply == QMessageBox.StandardButton.No:
                                    mw.status_label.setText("Profile creation cancelled.")
                                    return
                                else:
                                    logging.warning(f"Overwriting existing profile: {profile_name}")
                            
                            # Create the profile with the appropriate data
                            new_profile = {
                                'name': profile_name,
                                'paths': save_paths,
                                'emulator': emulator_key
                            }
                            
                            # Add save_dir to new_profile if it was automatically determined and present in selected_profile
                            if 'save_dir' in selected_profile and selected_profile['save_dir']:
                                new_profile['save_dir'] = selected_profile['save_dir']
                                logging.debug(f"PCM.dropEvent: Added 'save_dir': '{selected_profile['save_dir']}' to new_profile for '{profile_name}'.")
                            elif emulator_key == 'PCSX2':
                                logging.warning(f"PCM.dropEvent: PCSX2 profile '{profile_name}' selected, but 'save_dir' was missing or empty in selected_profile data. Selective backup might be affected.")
                            
                            logging.debug(f"PCM.dropEvent: Final new_profile data before saving for '{profile_name}': {new_profile}") # ADDED LOG
                            
                            # Add the profile to the main window's profiles dictionary
                            mw.profiles[profile_name] = new_profile
                            
                            # Save the profiles to disk
                            if mw.core_logic.save_profiles(mw.profiles):
                                mw.profile_table_manager.update_profile_table()
                                mw.status_label.setText(f"Profile '{profile_name}' created successfully.")
                                logging.info(f"Emulator game profile '{profile_name}' created/updated with emulator '{emulator_key}'.")
                                
                                # Select the newly created profile in the table
                                mw.profile_table_manager.select_profile_in_table(profile_name)
                            else:
                                logging.error(f"Failed to save profiles after adding '{profile_name}'.")
                                QMessageBox.critical(mw, "Save Error", "Failed to save the profiles. Check the log for details.")
                    else:
                        logging.info("User cancelled emulator game selection.")
                    
                    # Hide the overlay if it's visible
                    self._hide_overlay_if_visible(mw)
                    mw.set_controls_enabled(True)
                    QApplication.restoreOverrideCursor()
                    event.acceptProposedAction()
                    return # Return after handling emulator profiles
                elif emulator_key: # Emulator detected but no profiles found
                    logging.warning(f"{emulator_key} detected, but no profiles found in its standard directory.")
                    QMessageBox.warning(mw, f"Emulator Detected ({emulator_key})",
                                    f"Detected link to {emulator_key}, but no profiles found in its standard folder.\nCheck the emulator's save location.")
                return # IMPORTANT: Stop further processing if an emulator was detected
            
            logging.debug(f"Path '{target_path}' did not match known emulators, proceeding with standard heuristic path detection.")

            # self.game_name_input.setText(game_name) # Temporarily commented out
            # self.executable_path_input.setText(os.path.normpath(target_path)) # Temporarily commented out
            
            if game_install_dir: 
                # self.game_install_dir_input.setText(os.path.normpath(game_install_dir)) # Temporarily commented out
                pass # Added to satisfy linter for empty if-block
            else: # Final fallback for install directory if still not set
                final_fallback_dir = os.path.dirname(target_path) if os.path.isfile(target_path) else target_path
                # self.game_install_dir_input.setText(os.path.normpath(final_fallback_dir)) # Temporarily commented out
                logging.debug(f"PCM.dropEvent (Fallback): Install dir set to absolute final fallback: {final_fallback_dir}")

            # Icon handling - Temporarily commented out due to missing attributes/methods
            # if not self.current_game_icon_path: # If not set by .desktop parsing
            #     if game_install_dir: self.find_and_set_game_icon(game_install_dir, game_name)
            #     else: self.find_and_set_game_icon(os.path.dirname(self.executable_path_input.text()), game_name)
            # elif self.current_game_icon_path: # Icon was found (e.g. from .desktop)
            #     self.update_icon_preview(self.current_game_icon_path)
            # # If no icon found by any means, it will use the default
            
            # Store values in internal state variables for potential later use
            self.game_name_suggestion = game_name
            self.game_install_dir = game_install_dir
            self.executable_path = target_path
            
            # self.start_detection_process(game_name, os.path.normpath(target_path), game_install_dir) # Method doesn't exist
            logging.info(f"PCM.dropEvent: Successfully processed non-Steam game: {game_name}. Ready for detection.")
            event.acceptProposedAction()
        else:
            logging.warning(f"PCM.dropEvent (Fallback): Target path '{target_path or 'N/A'}' invalid or non-existent. Ignoring drop.")
            QMessageBox.warning(mw, "Path Error", f"Dropped item or target ('{target_path or 'N/A'}') is invalid/not found.")
            event.ignore()

            # This section was removed as it duplicated code from earlier in the method

        # --- If NOT a known Emulator, proceed with heuristic search ---
        logging.debug(f"Path '{target_path}' did not match known emulators, proceeding with standard heuristic path detection.")
        event.acceptProposedAction() # Accept drop for heuristic

        # --- Get and Clean Profile Name (from original dropped file name) ---
        base_name = os.path.basename(file_path) # Use original file_path for name
        profile_name_temp, _ = os.path.splitext(base_name)
        profile_name_original = profile_name_temp.replace('™', '').replace('®', '').strip()
        profile_name = shortcut_utils.sanitize_profile_name(profile_name_original)
        logging.info(f"Original Name (basic clean): '{profile_name_original}', Sanitized Name: '{profile_name}'")

        if not profile_name:
            logging.error(f"Sanitized profile name for '{profile_name_original}' became empty!")
            QMessageBox.warning(mw, "Profile Name Error",
                                "Unable to generate a valid profile name from the dragged shortcut.")
            return

        if profile_name in mw.profiles:
            reply = QMessageBox.question(mw, "Existing Profile",
                                        f"A profile named '{profile_name}' already exists. Overwrite it?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                mw.status_label.setText("Profile creation cancelled.")
                return
            else:
                logging.warning(f"Overwriting existing profile: {profile_name}")

        # --- Start Heuristic Path Search Thread ---
        if self.detection_thread is not None and self.detection_thread.isRunning():
            QMessageBox.information(mw, "Operation in Progress", "Another path search is already in progress. Please wait.")
            return

        mw.set_controls_enabled(False)
        mw.status_label.setText(f"Searching...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        
        # --- Start Fade/Animation Effect ---
        try:
            if hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                mw.overlay_widget.resize(mw.centralWidget().size())
                # Utilizziamo lo stesso approccio del metodo start_steam_configuration
                # che funziona correttamente con il fade effect
                if hasattr(mw, 'loading_label') and mw.loading_label:
                    mw.loading_label.setText("Searching...") # Set text for search
                    mw.loading_label.setStyleSheet("QLabel { color: white; background-color: transparent; font-size: 24pt; font-weight: bold; }")
                    mw.loading_label.adjustSize() # Ensure label resizes to content
                
                if hasattr(mw, 'overlay_widget') and mw.overlay_widget:
                    mw.overlay_widget.resize(mw.centralWidget().size())
                    # Assicuriamoci che l'overlay non sia già attivo
                    if hasattr(mw, 'overlay_active'):
                        mw.overlay_active = False
                    mw.overlay_widget.show() # Show overlay first
                    mw.overlay_widget.raise_() # Ensure it's on top
                
                if hasattr(mw, '_center_loading_label'):
                    mw._center_loading_label() # Center label on now-visible overlay
                
                if hasattr(mw, 'loading_label') and mw.loading_label:
                    mw.loading_label.show() # Explicitly show the label
                
                if hasattr(mw, 'fade_in_animation') and mw.fade_in_animation:
                    mw.fade_in_animation.stop() # Stop if already running
                    mw.fade_in_animation.start() # Start the animation
                    logging.debug("Fade-in animation started for overlay in dropEvent.")
                
                # L'overlay rimarrà visibile fino al completamento della ricerca
                # e verrà nascosto nel metodo on_detection_finished
                
                logging.debug("Fade-in animation started with 'Searching...' text.")
            else:
                logging.warning("Overlay widget or fade animation not found in MainWindow.")
        except Exception as e_fade_start:
            logging.error(f"Error starting fade/animation effect: {e_fade_start}", exc_info=True)
        # --- FINE Start Fade/Animation Effect ---

        # Create and start the path detection thread
        self.detection_thread = DetectionWorkerThread(
            game_install_dir=game_install_dir, # Use derived install dir
            profile_name_suggestion=profile_name,
            current_settings=mw.current_settings.copy(),
            installed_steam_games_dict=None, # Non-Steam game, no need to pass Steam games list
            emulator_name=emulator_result[0] if emulator_result else None # Pass the detected emulator name
        )
        self.detection_thread.progress.connect(self.on_detection_progress)
        self.detection_thread.finished.connect(self.on_detection_finished)
        self.detection_thread.start()
        logging.debug("Heuristic path detection thread started.")
    # --- FINE dropEvent ---