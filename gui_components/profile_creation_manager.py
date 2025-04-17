# gui_components/profile_creation_manager.py
# -*- coding: utf-8 -*-
import os
#import sys
import logging
import string
#import shutil # Per shutil.disk_usage nel futuro? Non usato qui direttamente ora.

from PySide6.QtWidgets import QMessageBox, QInputDialog, QApplication
from PySide6.QtCore import Qt, QUrl, Slot

# Importa dialoghi specifici se servono (es. Minecraft)
from dialogs.minecraft_dialog import MinecraftWorldsDialog

# Importa utility e logica
from gui_utils import DetectionWorkerThread, resource_path # Assumiamo siano qui
import minecraft_utils
import core_logic
from shortcut_utils import sanitize_profile_name # O importa shortcut_utils

class ProfileCreationManager:
    """
    Gestisce la creazione di nuovi profili utente tramite input manuale,
    drag & drop di collegamenti (.lnk), o selezione di mondi Minecraft.
    """
    def __init__(self, main_window):
        """
        Inizializza il gestore.

        Args:
            main_window: Riferimento all'istanza di MainWindow per accedere
                         a UI elements, settings, profiles, methods, etc.
        """
        self.main_window = main_window
        self.detection_thread = None # Gestisce il proprio worker per il rilevamento

    # --- METODO HELPER PER VALIDAZIONE PERCORSO (Spostato qui) ---
    def validate_save_path(self, path_to_check, context_profile_name="profilo"):
        """
        Controlla se un percorso è valido come cartella di salvataggio.
        Verifica che non sia vuoto, che non sia una radice di drive,
        e che sia una cartella esistente.
        Mostra un QMessageBox in caso di errore usando il parent main_window.
        Restituisce il percorso normalizzato se valido, altrimenti None.
        """
        mw = self.main_window # Abbreviazione per leggibilità
        if not path_to_check:
            QMessageBox.warning(mw, mw.tr("Errore Percorso"), mw.tr("Il percorso non può essere vuoto."))
            return None

        norm_path = os.path.normpath(path_to_check)

        # Controllo Percorso Radice
        try:
            # Ottieni lettere drive disponibili (solo Windows per ora)
            available_drives = ['%s:' % d for d in string.ascii_uppercase if os.path.exists('%s:' % d)]
            # Crea lista percorsi radice normalizzati (es. C:\, D:\)
            known_roots = [os.path.normpath(d + os.sep) for d in available_drives]
            logging.debug(f"Path validation: Path='{norm_path}', KnownRoots='{known_roots}', IsRoot={norm_path in known_roots}")

            if norm_path in known_roots:
                QMessageBox.warning(mw, mw.tr("Errore Percorso"),
                                    mw.tr("Non è possibile usare una radice del drive ('{0}') come cartella dei salvataggi per '{1}'.\n"
                                        "Per favore, scegli o crea una sottocartella specifica.").format(norm_path, context_profile_name))
                return None
        except Exception as e_root:
            logging.warning(f"Root path check failed during validation: {e_root}", exc_info=True)
            # Non bloccare per questo errore, procedi con isdir

        # Controllo Esistenza e Tipo (Directory)
        if not os.path.isdir(norm_path):
            QMessageBox.warning(mw, mw.tr("Errore Percorso"),
                                mw.tr("Il percorso specificato non esiste o non è una cartella valida:\n'{0}'").format(norm_path))
            return None

        # Se tutti i controlli passano, restituisce il percorso normalizzato
        logging.debug(f"Path validation: '{norm_path}' considered valid.")
        return norm_path
    # --- FINE validate_save_path ---

    # --- Gestione Nuovo Profilo Manuale (Spostato qui) ---
    @Slot()
    def handle_new_profile(self):
        """Gestisce la creazione di un profilo con input manuale."""
        mw = self.main_window
        logging.debug("ProfileCreationManager.handle_new_profile - START")
        profile_name, ok = QInputDialog.getText(mw, mw.tr("Nuovo Profilo"), mw.tr("Inserisci un nome per il nuovo profilo:"))
        logging.debug(f"ProfileCreationManager.handle_new_profile - Name entered: '{profile_name}', ok={ok}")

        if ok and profile_name:
            # Pulisci il nome inserito
            profile_name_original = profile_name # Conserva originale per messaggi
            profile_name = sanitize_profile_name(profile_name) # Applica sanificazione
            if not profile_name:
                 QMessageBox.warning(mw, mw.tr("Errore Nome Profilo"),
                                     mw.tr("Il nome del profilo ('{0}') contiene caratteri non validi o è vuoto dopo la pulizia.").format(profile_name_original))
                 return

            if profile_name in mw.profiles:
                logging.warning(f"Profile '{profile_name}' already exists.")
                QMessageBox.warning(mw, mw.tr("Errore"), mw.tr("Un profilo chiamato '{0}' esiste già.").format(profile_name))
                return

            logging.debug(f"ProfileCreationManager.handle_new_profile - Requesting path for '{profile_name}'...")
            path_prompt = mw.tr("Ora inserisci il percorso COMPLETO per i salvataggi del profilo:\n'{0}'").format(profile_name)
            input_path, ok2 = QInputDialog.getText(mw, mw.tr("Percorso Salvataggi"), path_prompt)
            logging.debug(f"ProfileCreationManager.handle_new_profile - Path entered: '{input_path}', ok2={ok2}")

            if ok2:
                # Usa la funzione di validazione (ora parte di questa classe)
                validated_path = self.validate_save_path(input_path, profile_name)

                if validated_path:
                    logging.debug(f"handle_new_profile - Valid path: '{validated_path}'.")
                    mw.profiles[profile_name] = validated_path # Modifica dizionario in MainWindow
                    logging.debug("handle_new_profile - Attempting to save profiles to file...")
                    save_success = core_logic.save_profiles(mw.profiles) # Salva usando core_logic
                    logging.debug(f"handle_new_profile - Result of core_logic.save_profiles: {save_success}")

                    if save_success:
                        logging.info(f"Profile '{profile_name}' created manually.")
                        # Aggiorna la tabella TRAMITE il manager della tabella in MainWindow
                        if hasattr(mw, 'profile_table_manager'):
                            mw.profile_table_manager.update_profile_table()
                            mw.profile_table_manager.select_profile_in_table(profile_name) # Seleziona il nuovo
                        QMessageBox.information(mw, mw.tr("Successo"), mw.tr("Profilo '{0}' creato e salvato.").format(profile_name))
                        mw.status_label.setText(mw.tr("Profilo '{0}' creato.").format(profile_name))
                    else:
                        logging.error("handle_new_profile - core_logic.save_profiles returned False.")
                        QMessageBox.critical(mw, mw.tr("Errore"), mw.tr("Impossibile salvare il file dei profili."))
                        # Rimuovi da memoria se salvataggio fallisce
                        if profile_name in mw.profiles:
                            del mw.profiles[profile_name]
                # else: validate_save_path ha già mostrato l'errore
            else:
                 logging.debug("handle_new_profile - Path input cancelled (ok2=False).")
        else:
            logging.debug("handle_new_profile - Name input cancelled (ok=False or empty name).")
        logging.debug("handle_new_profile - END")
    # --- FINE handle_new_profile ---

    # --- Gestione Pulsante Minecraft (Spostato qui) ---
    @Slot()
    def handle_minecraft_button(self):
        """
        Trova i mondi Minecraft, mostra un dialogo per la selezione
        e crea un nuovo profilo per il mondo scelto.
        """
        mw = self.main_window
        logging.info("Starting Minecraft world search...")
        mw.status_label.setText(mw.tr("Ricerca cartella salvataggi Minecraft..."))
        QApplication.processEvents()

        try:
            saves_folder = minecraft_utils.find_minecraft_saves_folder()
        except Exception as e_find:
            logging.error(f"Unexpected error during find_minecraft_saves_folder: {e_find}", exc_info=True)
            QMessageBox.critical(mw, mw.tr("Errore Minecraft"), mw.tr("Errore imprevisto durante la ricerca della cartella Minecraft."))
            mw.status_label.setText(mw.tr("Errore ricerca Minecraft."))
            return

        if not saves_folder:
            logging.warning("Minecraft saves folder not found.")
            QMessageBox.warning(mw, mw.tr("Cartella Non Trovata"),
                                mw.tr("Impossibile trovare la cartella dei salvataggi standard di Minecraft (.minecraft/saves).\nAssicurati che Minecraft Java Edition sia installato."))
            mw.status_label.setText(mw.tr("Cartella Minecraft non trovata."))
            return

        mw.status_label.setText(mw.tr("Lettura mondi Minecraft..."))
        QApplication.processEvents()
        try:
            worlds_data = minecraft_utils.list_minecraft_worlds(saves_folder)
        except Exception as e_list:
            logging.error(f"Unexpected error during list_minecraft_worlds: {e_list}", exc_info=True)
            QMessageBox.critical(mw, mw.tr("Errore Minecraft"), mw.tr("Errore imprevisto durante la lettura dei mondi Minecraft."))
            mw.status_label.setText(mw.tr("Errore lettura mondi Minecraft."))
            return

        if not worlds_data:
            logging.warning("No worlds found in: %s", saves_folder)
            QMessageBox.information(mw, mw.tr("Nessun Mondo Trovato"),
                                    mw.tr("Nessun mondo trovato nella cartella:\n{0}").format(saves_folder))
            mw.status_label.setText(mw.tr("Nessun mondo Minecraft trovato."))
            return

        try:
            dialog = MinecraftWorldsDialog(worlds_data, mw) # Usa mw come parent
        except Exception as e_dialog_create:
            logging.error(f"Creation error MinecraftWorldsDialog: {e_dialog_create}", exc_info=True)
            QMessageBox.critical(mw, mw.tr("Errore Interfaccia"), mw.tr("Impossibile creare la finestra di selezione dei mondi."))
            return

        mw.status_label.setText(mw.tr("Pronto.")) # Resetta status

        if dialog.exec(): # Usa exec() bloccante standard per dialoghi modali
            selected_world = dialog.get_selected_world_info()
            if selected_world:
                profile_name = selected_world.get('world_name', selected_world.get('folder_name'))
                world_path = selected_world.get('full_path')

                if not profile_name:
                    logging.error("Name of selected Minecraft world invalid or missing.")
                    QMessageBox.critical(mw, mw.tr("Errore Interno"), mw.tr("Nome del mondo selezionato non valido."))
                    return

                # Sanifica anche il nome del mondo Minecraft
                profile_name_original = profile_name
                profile_name = sanitize_profile_name(profile_name)
                if not profile_name:
                    QMessageBox.warning(mw, mw.tr("Errore Nome Profilo"),
                                        mw.tr("Il nome del mondo ('{0}') contiene caratteri non validi o è vuoto dopo la pulizia.").format(profile_name_original))
                    return

                if not world_path or not os.path.isdir(world_path):
                    logging.error(f"World path '{world_path}' invalid for profile '{profile_name}'.")
                    QMessageBox.critical(mw, mw.tr("Errore Percorso"), mw.tr("Il percorso del mondo selezionato ('{0}') non è valido.").format(world_path))
                    return

                logging.info(f"Minecraft world selected: '{profile_name}' - Path: {world_path}")

                if profile_name in mw.profiles:
                    QMessageBox.warning(mw, mw.tr("Profilo Esistente"),
                                        mw.tr("Un profilo chiamato '{0}' esiste già.\nScegli un altro mondo o rinomina il profilo esistente.").format(profile_name))
                    return

                # Crea e Salva Nuovo Profilo
                mw.profiles[profile_name] = world_path
                if core_logic.save_profiles(mw.profiles):
                    logging.info(f"Minecraft profile '{profile_name}' created.")
                     # Aggiorna la tabella TRAMITE il manager della tabella in MainWindow
                    if hasattr(mw, 'profile_table_manager'):
                        mw.profile_table_manager.update_profile_table()
                        mw.profile_table_manager.select_profile_in_table(profile_name) # Seleziona il nuovo
                    QMessageBox.information(mw, mw.tr("Profilo Creato"),
                                            mw.tr("Profilo '{0}' creato con successo per il mondo Minecraft.").format(profile_name))
                    mw.status_label.setText(mw.tr("Profilo '{0}' creato.").format(profile_name))
                else:
                    QMessageBox.critical(mw, mw.tr("Errore"), mw.tr("Impossibile salvare il file dei profili dopo aver aggiunto '{0}'.").format(profile_name))
                    if profile_name in mw.profiles: del mw.profiles[profile_name]
            else:
                logging.warning("Minecraft dialog accepted but no selected world data returned.")
                mw.status_label.setText(mw.tr("Selezione mondo annullata o fallita."))
        else:
            logging.info("Minecraft world selection cancelled by user.")
            mw.status_label.setText(mw.tr("Selezione mondo annullata."))
    # --- FINE handle_minecraft_button ---

    # --- Gestione Drag and Drop (Spostato qui) ---
    def dragEnterEvent(self, event):
        """Gestisce l'ingresso di un oggetto trascinato."""
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            # Accetta solo se è UN SINGOLO file .lnk
            if urls and len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith('.lnk'):
                event.acceptProposedAction()
                logging.debug("DragEnterEvent: Accepted .lnk file.")
            else:
                 logging.debug("DragEnterEvent: Rejected (not a single .lnk file).")
                 event.ignore()
        else:
             event.ignore()

    def dragMoveEvent(self, event):
        """Gestisce il movimento di un oggetto trascinato sopra il widget."""
        # La logica di accettazione è la stessa di dragEnterEvent
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if urls and len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith('.lnk'):
                event.acceptProposedAction()
            else:
                 event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Gestisce il rilascio di un oggetto .lnk e avvia la ricerca del percorso."""
        import winshell # Necessario per .lnk
        mw = self.main_window
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        urls = event.mimeData().urls()
        if not (urls and len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith('.lnk')):
            event.ignore()
            return

        event.acceptProposedAction()
        file_path = urls[0].toLocalFile()
        logging.info(f"DropEvent: Accepted .lnk file: {file_path}")

        # --- Lettura .lnk ---
        shortcut = None
        game_install_dir = None
        target_path = None
        try:
            shortcut = winshell.shortcut(file_path)
            target_path = shortcut.path
            working_dir = shortcut.working_directory
            if working_dir and os.path.isdir(working_dir):
                game_install_dir = os.path.normpath(working_dir)
            elif target_path and os.path.isfile(target_path):
                game_install_dir = os.path.normpath(os.path.dirname(target_path))
            else:
                logging.warning(f"Unable to determine game folder from shortcut: {file_path}")
            logging.debug(f"Game folder detected (or assumed) from shortcut: {game_install_dir}")
        except ImportError:
            logging.error("The 'winshell' library is not installed. Cannot read .lnk files.")
            QMessageBox.critical(mw, mw.tr("Errore Dipendenza"), mw.tr("La libreria 'winshell' necessaria non è installata."))
            return
        except Exception as e_lnk:
            logging.error(f"Error reading .lnk file: {e_lnk}", exc_info=True)
            QMessageBox.critical(mw, mw.tr("Errore Collegamento"), mw.tr("Impossibile leggere il file .lnk:\n{0}").format(e_lnk))
            return

        # --- Ottieni e Pulisci Nome Profilo ---
        base_name = os.path.basename(file_path)
        profile_name_temp, _ = os.path.splitext(base_name)
        profile_name_original = profile_name_temp.replace('™', '').replace('®', '').strip()
        profile_name = sanitize_profile_name(profile_name_original)
        logging.info(f"Original Name (basic clean): '{profile_name_original}', Sanitized Name: '{profile_name}'")

        if not profile_name:
            logging.error(f"Sanitized profile name for '{profile_name_original}' became empty!")
            QMessageBox.warning(mw, mw.tr("Errore Nome Profilo"),
                                mw.tr("Impossibile generare un nome profilo valido dal collegamento trascinato."))
            return

        if profile_name in mw.profiles:
            QMessageBox.warning(mw, mw.tr("Profilo Esistente"), mw.tr("Profilo '{0}' esiste già.").format(profile_name))
            return

        # --- AVVIO THREAD DI RICERCA ---
        if self.detection_thread and self.detection_thread.isRunning():
            QMessageBox.information(mw, mw.tr("Operazione in Corso"), mw.tr("Un'altra ricerca di percorso è già in corso. Attendi."))
            return

        mw.set_controls_enabled(False) # Disabilita controlli in MainWindow
        mw.status_label.setText(mw.tr("Ricerca percorso per '{0}' in corso...").format(profile_name))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor) # Cursore di attesa

        # Crea e avvia il thread di rilevamento
        self.detection_thread = DetectionWorkerThread(
            game_install_dir=game_install_dir,
            profile_name_suggestion=profile_name,
            current_settings=mw.current_settings.copy() # Passa copia impostazioni
        )
        # Connetti i segnali ai metodi DI QUESTA CLASSE (ProfileCreationManager)
        self.detection_thread.progress.connect(self.on_detection_progress)
        self.detection_thread.finished.connect(self.on_detection_finished)
        self.detection_thread.start()
        logging.debug("Path detection thread started.")
    # --- FINE dropEvent ---


    # --- Slot per Progresso Rilevamento (Spostato qui) ---
    @Slot(str)
    def on_detection_progress(self, message):
        """Aggiorna la status bar della main_window con i messaggi dal thread."""
        # Potrebbe essere utile filtrare/semplificare i messaggi qui
        self.main_window.status_label.setText(message)
    # --- FINE on_detection_progress ---


    # --- Slot per Fine Rilevamento (Spostato qui) ---
    @Slot(bool, dict)
    def on_detection_finished(self, success, results):
        """Chiamato quando il thread di rilevamento percorso ha finito."""
        mw = self.main_window
        logging.debug(f"Detection thread finished. Success: {success}, Results: {results}")
        QApplication.restoreOverrideCursor() # Ripristina cursore
        mw.set_controls_enabled(True)      # Riabilita controlli in MainWindow
        mw.status_label.setText(mw.tr("Ricerca percorso completata."))

        self.detection_thread = None # Rimuovi riferimento al thread completato

        profile_name = results.get('profile_name_suggestion', 'profilo_sconosciuto')

        if not success:
            error_msg = results.get('message', mw.tr("Errore sconosciuto durante la ricerca."))
            if "interrotta" not in error_msg.lower(): # Non mostrare popup se interrotto
                QMessageBox.critical(mw, mw.tr("Errore Ricerca Percorso"), error_msg)
            else:
                mw.status_label.setText(mw.tr("Ricerca interrotta."))
            return

        # --- Logica gestione risultati ---
        final_path_to_use = None
        paths_found = results.get('paths', [])
        status = results.get('status', 'error')

        if status == 'found':
            logging.debug(f"Paths found by detection thread: {paths_found}")
            if len(paths_found) == 1:
                # Un solo percorso trovato
                reply = QMessageBox.question(mw, mw.tr("Conferma Percorso Automatico"),
                                             mw.tr("È stato rilevato questo percorso:\n\n{0}\n\nVuoi usarlo per il profilo '{1}'?").format(paths_found[0], profile_name),
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    final_path_to_use = paths_found[0]
                elif reply == QMessageBox.StandardButton.No:
                    logging.info("User rejected single automatic path. Requesting manual input.")
                    final_path_to_use = None # Forza richiesta manuale sotto
                else: # Cancel
                    mw.status_label.setText(mw.tr("Creazione profilo annullata."))
                    return
            elif len(paths_found) > 1:
                # Multipli percorsi trovati, ordina e chiedi
                logging.debug(f"Found {len(paths_found)} paths, applying priority sorting.")
                preferred_suffixes = ['saves', 'save', 'savegame', 'savegames', 'saved', 'storage',
                                      'playerdata', 'profile', 'profiles', 'user', 'data', 'savedata']
                def sort_key(path):
                    basename_lower = os.path.basename(os.path.normpath(path)).lower()
                    priority = 0 if basename_lower in preferred_suffixes else 1
                    return (priority, path.lower())
                sorted_paths = sorted(paths_found, key=sort_key)
                logging.debug(f"Paths sorted for selection: {sorted_paths}")

                choices = sorted_paths + [mw.tr("[Inserisci Manualmente...]")]
                chosen_path_str, ok = QInputDialog.getItem(mw, mw.tr("Conferma Percorso Salvataggi"),
                                                           mw.tr("Sono stati trovati questi percorsi potenziali per '{0}'.\nSeleziona quello corretto o scegli l'inserimento manuale:").format(profile_name),
                                                           choices, 0, False)
                if ok and chosen_path_str:
                    if chosen_path_str == mw.tr("[Inserisci Manualmente...]"):
                        logging.info("User chose manual input from multiple paths list.")
                        final_path_to_use = None # Forza richiesta manuale
                    else:
                        final_path_to_use = chosen_path_str
                else: # Annullato
                    mw.status_label.setText(mw.tr("Creazione profilo annullata."))
                    return
        elif status == 'not_found':
            # Nessun percorso trovato automaticamente
            QMessageBox.information(mw, mw.tr("Percorso Non Rilevato"), mw.tr("Impossibile rilevare automaticamente il percorso dei salvataggi per '{0}'.\nPer favore, inseriscilo manualmente.").format(profile_name))
            final_path_to_use = None # Forza richiesta manuale
        else:
            logging.error(f"Unexpected status '{status}' from detection thread with success=True")
            mw.status_label.setText(mw.tr("Errore interno durante la gestione dei risultati."))
            return

        # --- Richiesta Inserimento Manuale (se necessario) ---
        if final_path_to_use is None:
            path_prompt = mw.tr("Inserisci il percorso COMPLETO per i salvataggi del profilo:\n'{0}'").format(profile_name)
            input_path, ok_manual = QInputDialog.getText(mw, mw.tr("Percorso Salvataggi Manuale"), path_prompt)
            if ok_manual and input_path:
                final_path_to_use = input_path
            elif ok_manual and not input_path:
                QMessageBox.warning(mw, mw.tr("Errore Percorso"), mw.tr("Il percorso non può essere vuoto."))
                mw.status_label.setText(mw.tr("Creazione profilo annullata (percorso vuoto)."))
                return
            else: # Annullato
                mw.status_label.setText(mw.tr("Creazione profilo annullata."))
                return

        # --- Validazione Finale e Salvataggio Profilo ---
        if final_path_to_use:
            # Usa la funzione di validazione (ora parte di questa classe)
            validated_path = self.validate_save_path(final_path_to_use, profile_name)

            if validated_path:
                logging.debug(f"Final path validated: {validated_path}. Saving profile '{profile_name}'")
                mw.profiles[profile_name] = validated_path # Aggiorna dizionario in MainWindow
                if core_logic.save_profiles(mw.profiles):
                    # Aggiorna la tabella TRAMITE il manager della tabella in MainWindow
                    if hasattr(mw, 'profile_table_manager'):
                        mw.profile_table_manager.update_profile_table()
                        mw.profile_table_manager.select_profile_in_table(profile_name)
                    QMessageBox.information(mw, mw.tr("Profilo Creato"), mw.tr("Profilo '{0}' creato con successo.").format(profile_name))
                    mw.status_label.setText(mw.tr("Profilo '{0}' creato.").format(profile_name))
                else:
                    QMessageBox.critical(mw, mw.tr("Errore"), mw.tr("Impossibile salvare il file dei profili."))
                    if profile_name in mw.profiles: del mw.profiles[profile_name]
            # else: validate_save_path ha già mostrato l'errore
    # --- FINE on_detection_finished ---