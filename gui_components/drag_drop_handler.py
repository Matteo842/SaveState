import os
import logging
import platform
import re # Per il parsing degli URL Steam
from pathlib import Path
import configparser # Per il parsing dei file .url
import shlex
import shutil

from PySide6.QtWidgets import QMessageBox, QApplication
from PySide6.QtCore import Qt, Slot, QObject, QTimer, QThread

# Importa utility e logica
from gui_utils import DetectionWorkerThread

# Setup logging per questo modulo
logger = logging.getLogger(__name__)

from .drop_event_logic import DropEventMixin  # Import the mixin

class DragDropHandler(QObject, DropEventMixin):  # Add mixin to inheritance
    """
    Gestisce le operazioni di drag and drop per la creazione di profili.
    Supporta URL Steam, collegamenti Windows (.lnk), file desktop Linux (.desktop) e cartelle.
    """
    def __init__(self, main_window):
        super().__init__()  # Questo chiamerà sia QObject.__init__ che DropEventMixin.__init__
        self.main_window = main_window
        self.detection_thread = None
        # self.profile_dialog è già inizializzato in DropEventMixin.__init__
        
        # Inizializza le variabili di stato che saranno gestite da reset_internal_state
        self.reset_internal_state()
    
    def reset_internal_state(self):
        """Reimposta le variabili di stato interne prima di elaborare un nuovo elemento."""
        # Prima chiama il reset del mixin per resettare processing_cancelled
        super().reset_internal_state()
        
        # Poi resetta le variabili specifiche del DragDropHandler
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
                            
                    # Per i file .url, verifica che siano URL di launcher validi
                    if file_ext == ".url":
                        try:
                            config = configparser.ConfigParser()
                            config.read(item_path)
                            if 'InternetShortcut' in config and 'URL' in config['InternetShortcut']:
                                url_from_file = config['InternetShortcut']['URL']
                                
                                is_steam_url = "store.steampowered.com" in url_from_file or "steam://" in url_from_file
                                # Aggiungi altri launcher qui per il riconoscimento
                                is_known_launcher = is_steam_url or any(proto in url_from_file for proto in [
                                    "com.epicgames.launcher://", "uplay://", "goggalaxy://", "battlenet://", "origin://"
                                ])

                                if not is_known_launcher:
                                    # Salta i file .url non riconosciuti
                                    continue

                                # Se è un URL Steam, esegui il controllo di installazione
                                if is_steam_url:
                                    # --- INIZIO LOGICA CONTROLLO INSTALLAZIONE STEAM GAME ---
                                    app_id = None
                                    # Estrai AppID (gestisce entrambi i formati di URL)
                                    match = re.search(r'steam://rungameid/(\d+)|store\.steampowered\.com/app/(\d+)', url_from_file)

                                    if match:
                                        app_id = match.group(1) or match.group(2)
                                    
                                    if app_id:
                                        game_details = self._get_steam_game_details(app_id)
                                        # Se game_details non esiste o non ha un install_dir valido, il gioco non è installato.
                                        if not game_details or not game_details.get('install_dir'):
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
                                # Per gli altri launcher, per ora li accettiamo senza controlli aggiuntivi.
                                # L'esecuzione continua e il file verrà aggiunto a valid_files.
                            else:
                                continue
                        except Exception as e:
                            logging.error(f"Error parsing .url file: {e}")
                            continue
                    
                    # Verifica se il file è un emulatore conosciuto (solo detection, senza scan dei profili)
                    # Verifica se il file è un emulatore conosciuto per escluderlo dalla scansione
                    emulator_status, _ = self._is_known_emulator(item_path)
                    if emulator_status in ['supported', 'unsupported']:
                        logging.info(f"Skipping emulator file found during directory scan: {item_path}")
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
        # Controlla se l'elaborazione è stata cancellata (controlla sia self che main_window)
        if (hasattr(self, 'processing_cancelled') and self.processing_cancelled) or \
           (hasattr(self.main_window, 'processing_cancelled') and self.main_window.processing_cancelled):
            logging.info("_handle_profile_analysis: Processing cancelled, skipping file analysis")
            return
            
        # Verifica se è una richiesta di avvio dell'analisi
        if 'action' in profile_data and profile_data['action'] == 'start_analysis':
            # Assicurati che il CancellationManager non sia in stato cancellato da una run precedente
            try:
                if hasattr(self.main_window, 'cancellation_manager') and self.main_window.cancellation_manager:
                    self.main_window.cancellation_manager.reset()
                    logging.debug("DragDropHandler: cancellation_manager.reset() before starting multi-profile analysis")
            except Exception as e:
                logging.warning(f"DragDropHandler: Failed to reset cancellation_manager before analysis: {e}")
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
                # Controlla se l'elaborazione è stata cancellata prima di ogni file
                if (hasattr(self, 'processing_cancelled') and self.processing_cancelled) or \
                   (hasattr(self.main_window, 'processing_cancelled') and self.main_window.processing_cancelled):
                    logging.info(f"_handle_profile_analysis: Processing cancelled, stopping file processing at file {i+1}/{len(files_to_analyze)}")
                    break
                
                # 'profile_name' is the key from MultiProfileDialog and must be preserved for active_threads.
                # 'name_for_detection_thread' can be updated with the Steam name for better detection if needed.
                name_for_detection_thread = profile_name
                # Aggiorna la barra di avanzamento
                self.profile_dialog.update_progress(i, f"Preparazione: {os.path.basename(file_path)}")
                QApplication.processEvents()
                
                # Controlla di nuovo dopo processEvents (potrebbero essere arrivati segnali)
                if (hasattr(self, 'processing_cancelled') and self.processing_cancelled) or \
                   (hasattr(self.main_window, 'processing_cancelled') and self.main_window.processing_cancelled):
                    logging.info(f"_handle_profile_analysis: Processing cancelled after processEvents, stopping at file {i+1}/{len(files_to_analyze)}")
                    break
                
                logging.info(f"DragDropHandler._handle_profile_analysis: Preparing file: {file_path}")
                
                # Determina la directory di installazione
                game_install_dir = None
                # Caso speciale Linux: se è un .desktop, risolvi 'Exec' come nel flow singolo
                if platform.system() == "Linux" and file_path.lower().endswith('.desktop') and os.path.isfile(file_path):
                    try:
                        parsed_exec = None
                        parsed_path_field = None
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as fdesk:
                            for raw_line in fdesk:
                                line = raw_line.strip()
                                if not line or line.startswith('#'):
                                    continue
                                if line.startswith('Path=') and parsed_path_field is None:
                                    parsed_path_field = line[len('Path='):].strip().strip('"')
                                elif line.startswith('Exec=') and parsed_exec is None:
                                    parsed_exec = line[len('Exec='):].strip()
                                    # Rimuovi placeholder tipo %u, %U, %f, %F
                                    parsed_exec = re.sub(r'%[fFuUdDnNkvVmMic]', '', parsed_exec).strip()
                        if parsed_exec:
                            # Usa shlex per gestire quote/spazi
                            parts = shlex.split(parsed_exec)
                            if parts:
                                cand = parts[0]
                                # Espandi variabili/tilde
                                cand = os.path.expandvars(os.path.expanduser(cand))
                                # Se relativo e Path= presente, risolvi rispetto a Path
                                if not os.path.isabs(cand) and parsed_path_field:
                                    base_dir = os.path.expandvars(os.path.expanduser(parsed_path_field))
                                    cand = os.path.normpath(os.path.join(base_dir, cand))
                                # Se ancora non assoluto, prova PATH
                                if not os.path.isabs(cand):
                                    which = shutil.which(cand)
                                    if which:
                                        cand = which
                                if os.path.isabs(cand) and os.path.exists(cand):
                                    game_install_dir = os.path.normpath(os.path.dirname(cand))
                                    logging.info(f"DragDropHandler: .desktop Exec resolved to '{cand}'. Using install dir: '{game_install_dir}' for '{profile_name}'")
                    except Exception as e_desktop_multi:
                        logging.warning(f"Error resolving .desktop Exec in multi analysis for '{file_path}': {e_desktop_multi}")

                # Fallback generico
                if game_install_dir is None:
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
                            is_steam_url = "store.steampowered.com" in url_from_file or "steam://" in url_from_file
                            
                            if is_steam_url:
                                is_steam_game = True
                                # Estrai AppID (gestisce entrambi i formati di URL)
                                match = re.search(r'steam://rungameid/(\d+)|store\.steampowered\.com/app/(\d+)', url_from_file)
                                if match:
                                    # group(1) è per rungameid, group(2) per store/app.
                                    steam_app_id = match.group(1) or match.group(2)
                                    if steam_app_id:
                                        logging.info(f"Detected Steam game in multi-profile: {profile_name} (AppID: {steam_app_id})")
                                else:
                                    logging.warning(f"Could not extract AppID from Steam URL '{url_from_file}' in multi-profile analysis.")
                            # Per altri URL di launcher (Epic, Ubi, etc.), is_steam_game rimane False.
                            # Il file verrà processato dal thread di rilevamento senza logica specifica per Steam,
                            # che è il comportamento desiderato.
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
            
                # Se non Steam e il nome profilo è troppo breve (acronimo), prova a usare la cartella padre come nome per detection
                name_for_detection_thread = name_for_detection_thread
                try:
                    if not is_steam_game and name_for_detection_thread and len(name_for_detection_thread) <= 4:
                        # Deriva un nome più descrittivo dalla cartella di installazione (se CamelCase o contiene cifre)
                        base_install = os.path.basename(game_install_dir) if game_install_dir else ''
                        if base_install and len(base_install) > len(name_for_detection_thread):
                            name_for_detection_thread = base_install
                except Exception:
                    pass

                # Controlla di nuovo prima di creare il thread
                if (hasattr(self, 'processing_cancelled') and self.processing_cancelled) or \
                   (hasattr(self.main_window, 'processing_cancelled') and self.main_window.processing_cancelled):
                    logging.info(f"_handle_profile_analysis: Processing cancelled before creating thread for file {i+1}/{len(files_to_analyze)}")
                    break
                
                # Avvia il thread di rilevamento per questo file in modo asincrono
                detection_thread = DetectionWorkerThread(
                    game_install_dir=game_install_dir,
                    profile_name_suggestion=name_for_detection_thread, # Usa il nome (potenzialmente Steam) per il suggerimento
                    current_settings=self.main_window.current_settings.copy(),
                    installed_steam_games_dict=steam_games_dict,
                    emulator_name=None,
                    steam_app_id=steam_app_id if is_steam_game else None,
                    cancellation_manager=getattr(self.main_window, 'cancellation_manager', None)  # <-- FIX: passa il cancellation_manager
                )
            
                # Salva il riferimento al thread e al nome del profilo
                thread_id = id(detection_thread)
                self.active_threads[thread_id] = {
                    'thread': detection_thread,
                    'profile_name': profile_name,
                    'completed': False
                }
                
                # IMPORTANTE: Aggiungi il thread anche alle liste del DropEventMixin per la cancellazione
                if hasattr(self.main_window, '_detection_threads'):
                    self.main_window._detection_threads.append(detection_thread)
                    logging.debug(f"Added thread to _detection_threads list (total: {len(self.main_window._detection_threads)})")
                else:
                    logging.warning("_detection_threads not found in main_window, thread won't be tracked for cancellation")
                
                if hasattr(self.main_window, 'active_threads'):
                    if self.main_window.active_threads is None:
                        self.main_window.active_threads = {}
                    self.main_window.active_threads[thread_id] = {
                        'thread': detection_thread,
                        'profile_name': profile_name
                    }
                    logging.debug(f"Added thread to main_window.active_threads (total: {len(self.main_window.active_threads)})")
                else:
                    logging.warning("active_threads not found in main_window, thread won't be tracked for cancellation")
            
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

    def _on_detection_thread_finished(self, success: bool, results: dict, thread_id: str):
        """
        Handles the completion of a detection thread.
        Args:
            success: True if detection succeeded, False otherwise
            results: Dictionary with detection results
            thread_id: ID of the thread that finished
        """
        if thread_id not in self.active_threads:
            logging.warning(f"Thread ID {thread_id} not found in active_threads")
            return
        
        thread_info = self.active_threads[thread_id]
        profile_name = thread_info['profile_name']
        
        # Mark thread as completed
        thread_info['completed'] = True
        
        if success and results:
            # Store paths specifically for this profile
            thread_info['paths_found'] = results.get('path_data', [])
            
            if thread_info['paths_found']:
                # Sort paths by score (highest first)
                thread_info['paths_found'].sort(key=lambda x: x[1] if isinstance(x, tuple) and len(x) > 1 else 0, reverse=True)
                
                # Get best path for this profile
                best_path, best_score = thread_info['paths_found'][0] if isinstance(thread_info['paths_found'][0], tuple) else (thread_info['paths_found'][0], 0)
                
                # Update profile dialog
                if self.profile_dialog:
                    self.profile_dialog.update_profile(profile_name, best_path, best_score)
                else:
                    logging.warning(f"Cannot update profile '{profile_name}' - profile dialog has been closed")
                
                QApplication.processEvents()
                logging.info(f"Detected profile '{profile_name}' with path: {best_path} (score: {best_score})")
            else:
                logging.warning(f"No save paths found for: {profile_name}")
        else:
            logging.warning(f"Detection failed for: {profile_name}")

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

    def _is_known_emulator(self, file_path) -> tuple[str, str | None]:
        """Controlla se il file è un emulatore conosciuto e restituisce il suo stato."""
        try:
            from emulator_utils.emulator_manager import is_known_emulator
            return is_known_emulator(file_path)
        except ImportError:
            logging.error("Failed to import is_known_emulator. Check circular dependencies or project structure.")
            return 'not_found', None

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
                installed_steam_games_dict=steam_games_dict,
                cancellation_manager=getattr(mw, 'cancellation_manager', None)  # <-- FIX: passa il cancellation_manager
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