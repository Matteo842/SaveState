import logging
import os
import platform
import re
import configparser
from pathlib import Path
import shortcut_utils  # Import shortcut utilities

from PySide6.QtWidgets import QMessageBox, QApplication, QDialog  # Import QApplication and QDialog
from PySide6.QtGui import QDropEvent
from PySide6.QtCore import Qt  # Import Qt
from dialogs.emulator_selection_dialog import EmulatorGameSelectionDialog
from gui_utils import DetectionWorkerThread  # Import DetectionWorkerThread
from shortcut_utils import sanitize_profile_name  # Import sanitize_profile_name
from .multi_profile_dialog import MultiProfileDialog

# It's assumed that DetectionWorkerThread, shortcut_utils, emulator_manager, 
# EmulatorGameSelectionDialog, and MultiProfileDialog will be accessed via handler_instance.main_window or handler_instance directly.

class DropEventMixin:
    def dropEvent(self, event: QDropEvent):
        """Handles the release of a dragged object. Prioritizes Steam URLs, then local files/shortcuts."""
        handler_instance = self
        handler_instance.reset_internal_state() # Reset state at the beginning
        # Defensive check: Ensure _detection_threads exists and is a list after reset_internal_state()
        if not hasattr(handler_instance, '_detection_threads') or not isinstance(handler_instance._detection_threads, list):
            logging.warning("'_detection_threads' was missing or not a list after reset_internal_state(). Re-initializing.")
            handler_instance._detection_threads = []
        mw = handler_instance.main_window # Alias for main window
        mime_data = event.mimeData()

        # --- Log MIME Data --- 

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
                    
                    # Controlla se è un file .url che potrebbe contenere un URL Steam o di altri launcher
                    if url_str.endswith(".url") and url_obj.isLocalFile():
                        local_path = url_obj.toLocalFile()
                        try:
                            config = configparser.ConfigParser()
                            config.read(local_path)
                            if 'InternetShortcut' in config and 'URL' in config['InternetShortcut']:
                                url_from_file = config['InternetShortcut']['URL']
                                # Controlla se è un URL Steam
                                if "store.steampowered.com" in url_from_file or "steam://" in url_from_file:
                                    steam_url_str = url_from_file
                                    logging.debug(f"PCM.dropEvent: Found Steam URL in .url file: {steam_url_str}")
                                    break
                                # Se non è Steam, potrebbe essere un altro launcher, quindi non impostiamo
                                # steam_url_str e lasciamo che la logica successiva gestisca il file come un normale eseguibile.
                                # Questo permette a _handle_dropped_files di processarlo.
                                else:
                                    # È un URL ma non di Steam, non fare nulla qui, sarà gestito dopo
                                    logging.debug(f"PCM.dropEvent: Found non-Steam URL in .url file: {url_from_file}. Will be handled by generic file processing.")

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
                    game_details = handler_instance._get_steam_game_details(app_id)
                    
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
                                handler_instance.original_steam_url_str = steam_url_str
                                # Set flag to skip error popup for .url files
                                handler_instance.skip_steam_error_popup = True
                                handler_instance.handle_steam_url_drop(steam_url_str)
                                # Reset flag after handling
                                handler_instance.skip_steam_error_popup = False
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
                            handler_instance.original_steam_url_str = steam_url_str
                            handler_instance.handle_steam_url_drop(steam_url_str)
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
                        handler_instance.original_steam_url_str = steam_url_str
                        handler_instance.handle_steam_url_drop(steam_url_str)
                        event.acceptProposedAction()
                        return True
        
        # Gestione per file locali e collegamenti
        if mime_data.hasUrls():
            # Importa winshell solo su Windows (richiesto per i file .lnk)
            if platform.system() == "Windows":
                try:
                    import winshell
                    import pythoncom
                except ImportError:
                    logging.error("The 'winshell' or 'pywin32' library is not installed. Cannot read .lnk files.")
                    QMessageBox.critical(handler_instance.main_window, "Dependency Error",
                                        "The 'winshell' and 'pywin32' libraries are required to read shortcuts (.lnk) on Windows.")
                    return

        # Lista per raccogliere i file da processare
        files_to_process = []
        
        if mime_data.hasUrls(): # Raccoglie tutti i file/URL validi
            urls = mime_data.urls()

            # Gestione per drop singolo (file, cartella, o collegamento a cartella)
            if len(urls) == 1 and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                
                # Controlla se è un collegamento a una cartella
                is_dir_shortcut = False
                if path.lower().endswith('.lnk') and platform.system() == "Windows":
                    try:
                        import winshell
                        shortcut = winshell.shortcut(path)
                        resolved_target = shortcut.path
                        if resolved_target and os.path.exists(resolved_target) and os.path.isdir(resolved_target):
                            logging.info(f"DragDropHandler.dropEvent: Ignoring single directory shortcut: {path}")
                            is_dir_shortcut = True
                    except Exception as e_lnk:
                        logging.error(f"Error reading .lnk file: {e_lnk}", exc_info=True)
                
                if is_dir_shortcut:
                    QMessageBox.warning(mw, "Folder Shortcut Not Supported",
                                        "Shortcuts pointing to folders are not supported.\n\n"
                                        "Please drag and drop the game's executable, its shortcut, or a launcher's .url file directly.")
                    event.ignore()
                    return False

                # Se è una cartella vera e propria, scansionala
                if os.path.isdir(path):
                    logging.info(f"DragDropHandler.dropEvent: Single directory dropped: {path}")
                    executables = self._scan_directory_for_executables(path)
                    if executables:
                        logging.info(f"DragDropHandler.dropEvent: Found {len(executables)} executables in directory.")
                        files_to_process.extend(executables)
                    else:
                        logging.warning(f"DragDropHandler.dropEvent: No executables found in directory: {path}")
                        event.ignore()
                        return False
                else:
                    # Altrimenti, è un singolo file
                    files_to_process.append(path)

            else: # Gestione per file multipli
                for url in urls:
                    if url.isLocalFile():
                        file_path = url.toLocalFile()
                        
                        # Salta le cartelle nel multi-drop
                        if os.path.isdir(file_path):
                            logging.info(f"DragDropHandler.dropEvent: Skipping directory in multi-file drop: {file_path}")
                            continue

                        # Salta i collegamenti a cartelle
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
                        if is_dir_shortcut:
                            continue
                        
                        files_to_process.append(file_path)
        
        # Se dopo il filtraggio non ci sono file validi, esci
        if not files_to_process:
            logging.warning("DragDropHandler.dropEvent: No valid files to process after filtering.")
            event.ignore()
            return False

        # --- GESTIONE DROP SINGOLO O MULTIPLO ---
        
        # Se c'è un solo file, procedi con la logica di rilevamento per singolo profilo
        if len(files_to_process) == 1:
            file_path = files_to_process[0]

            # Controlla prima se è un emulatore conosciuto ma non supportato
            emulator_status, emulator_name = handler_instance._is_known_emulator(file_path)
            if emulator_status == 'unsupported':
                QMessageBox.information(handler_instance.main_window,
                                        "Emulator Recognized",
                                        f"The emulator '{emulator_name}' is recognized but not yet supported by SaveState.\n\n"
                                        "Support for new emulators is added regularly.")
                event.acceptProposedAction()
                return

            # Se non è 'unsupported', procedi con la normale verifica per emulatori supportati
            emulator_result = handler_instance._check_if_emulator(file_path)
            
            if emulator_result:
                emulator_key, profiles_data = emulator_result
                logging.info(f"DragDropHandler.dropEvent: Detected emulator: {emulator_key}")
                
                # Gestione generica per emulatori
                # Implementazione inline invece di chiamare un metodo separato
                mw = handler_instance.main_window
                logging.info(f"DragDropHandler: Handling emulator: {emulator_key} with {len(profiles_data) if profiles_data else 'no'} profiles")
                    
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
                    event.acceptProposedAction()
                    return True # Handled emulator case (profiles found or dialog cancelled)
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
                    return True
        else:
            # Processare più file contemporaneamente
            logging.info(f"DragDropHandler.dropEvent: Processing multiple files: {len(files_to_process)}")
            
            # Filter out emulators and uninstalled Steam games from files_to_process
            filtered_files = []
            for file_path in files_to_process:
                # Controlla se è un emulatore (supportato o meno) per escluderlo
                emulator_status, emulator_name = handler_instance._is_known_emulator(file_path)
                if emulator_status in ['supported', 'unsupported']:
                    logging.info(f"DragDropHandler.dropEvent: Skipping emulator '{emulator_name}' in multi-file drop: {file_path}")
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
                                    game_details = handler_instance._get_steam_game_details(app_id)
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
                logging.warning("DragDropHandler.dropEvent: No valid files to process")
                mw.status_label.setText("No valid game files found (emulators were filtered out).")
                event.ignore()
                return False
            
            # Crea il dialogo per la gestione dei profili
            dialog = MultiProfileDialog(files_to_process, parent=mw)
            
            # Connetti il segnale profileAdded al metodo che gestisce l'analisi
            dialog.profileAdded.connect(self._handle_profile_analysis)
            
            # Connetti il segnale di chiusura del dialogo alla cancellazione dei thread
            # dialog.finished.connect(self._cancel_detection_threads)
            # dialog.rejected.connect(self._cancel_detection_threads)
            
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
                
                # Aggiungi i profili accettati, sanificando i nomi
                added_count = 0
                for profile_name, profile_data in accepted_profiles.items():
                    # Applica la stessa sanificazione usata per i profili singoli
                    sanitized_name = sanitize_profile_name(profile_name)
                    
                    # Gestisci nomi duplicati
                    final_name = sanitized_name
                    counter = 2
                    while final_name in mw.profiles:
                        final_name = f"{sanitized_name} ({counter})"
                        counter += 1
                    
                    mw.profiles[final_name] = profile_data
                    added_count += 1
                
                # Salva i profili
                if mw.core_logic.save_profiles(mw.profiles):
                    mw.profile_table_manager.update_profile_table()
                    mw.status_label.setText(f"Aggiunti {added_count} profili.")
                    logging.info(f"Saved {added_count} profiles.")
                else:
                    mw.status_label.setText("Errore nel salvataggio dei profili.")
                    logging.error("Failed to save profiles.")
                    QMessageBox.critical(mw, "Errore", "Impossibile salvare i profili.")
            else:
                # This 'else' corresponds to dialog.exec() != QDialog.Accepted
                mw.status_label.setText("Creazione profili annullata.")
                logging.info("DragDropHandler.dropEvent: Profile creation cancelled by user.")
            
            # Rimuovi il riferimento al dialogo
            self.profile_dialog = None

            # Whether dialog was accepted or cancelled, or profiles saved/not saved,
            # the multi-file drop event was handled by DragDropHandler.
            event.acceptProposedAction()
            return True

            # If no specific handling caught the event, DragDropHandler did not handle it.
            
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
            # Prepara il nome del gioco suggerito, pulendolo per ottenere un risultato migliore
            # specialmente per i collegamenti .url (es. "Alan Wake 2.url" -> "Alan Wake 2")
            profile_name = sanitize_profile_name(Path(file_path).stem)
            game_install_dir = os.path.dirname(file_path)
            logging.debug(f"PCM.dropEvent (Fallback): Game folder from Linux executable: {game_install_dir}")

        # Gestisce i file .url non-Steam
        elif file_path.lower().endswith('.url'):
            target_path = file_path
            game_install_dir = os.path.normpath(os.path.dirname(file_path))
            
            # Prepara il nome del gioco suggerito, pulendolo
            profile_name = sanitize_profile_name(Path(file_path).stem)
            logging.debug(f"PCM.dropEvent (Fallback): Game name from .url file: {profile_name}")

        # Se è un file ma non è un tipo supportato, lo rifiutiamo per motivi di sicurezza
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
            from emulator_utils import emulator_manager  # Import emulator manager
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
        logging.debug(f"Preparing DetectionWorkerThread for single file: game_install_dir='{game_install_dir}', profile_name_suggestion='{profile_name}', current emulator_result='{emulator_result}'")
        if self.detection_thread is not None and self.detection_thread.isRunning():
            QMessageBox.information(mw, "Operation in Progress", "Another path search is already in progress. Please wait.")
            return

        mw.set_controls_enabled(False)
        mw.status_label.setText(f"Searching...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        
        # Create cancellation manager for this search
        from cancellation_utils import CancellationManager
        cancellation_manager = CancellationManager()
        
        # Create thread
        self.detection_thread = DetectionWorkerThread(
            game_install_dir=game_install_dir,
            profile_name_suggestion=profile_name,
            current_settings=mw.current_settings.copy(),
            installed_steam_games_dict=None, # Non-Steam game
            emulator_name=None, # Explicitly None for generic heuristic search
            cancellation_manager=cancellation_manager
        )
        self.detection_thread.progress.connect(self.on_detection_progress)
        self.detection_thread.finished.connect(self.on_detection_finished)
        
        # Store manager in thread
        self.detection_thread.cancellation_manager = cancellation_manager
        
        # Store thread
        self._detection_threads.append(self.detection_thread)
        
        self.detection_thread.start()
        logging.debug("Heuristic path detection thread started.")
        
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
        return True

    def _cancel_detection_threads(self):
        if hasattr(self, '_detection_threads') and self._detection_threads:
            for thread in self._detection_threads:
                thread.terminate_immediately()
            self._detection_threads = []

class DragDropHandler:
    def __init__(self, parent=None):
        self._detection_threads = []
