# -*- coding: utf-8 -*-
from PySide6.QtCore import QThread, Signal, QObject, Qt, QTimer
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QApplication, QStyle
from PySide6.QtGui import QPixmap

# Importa core_logic e logging SOLO per la gestione delle eccezioni nel blocco 'except'
# Se non esistessero quel blocco 'except' specifico, questi import non servirebbero qui.
import core_logic
import logging          # Per loggare eventuali errori interni al thread
import os               # Per os.walk, os.path, ecc.
import configparser     # Per leggere i file .ini
#import sys
#import tempfile
#from datetime import datetime

# --- Thread Worker per Operazioni Lunghe ---

class WorkerThread(QThread):
    finished = Signal(bool, str)
    progress = Signal(str)
    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.setObjectName("WorkerThread")
    def run(self):
        try:
            self.progress.emit("Operation in progress...") # CORRETTO
            success, message = self.function(*self.args, **self.kwargs)
            self.progress.emit("Operation completed.") # CORRETTO
            self.finished.emit(success, message)
        except Exception as e:
            error_msg = f"Critical error in worker thread: {e}" # CORRETTO
            if hasattr(core_logic, 'logging'): core_logic.logging.exception(error_msg)
            else: logging.critical(error_msg, exc_info=True) # Usa critical e aggiunge traceback se possibile
            self.progress.emit("Error.") # CORRETTO
            self.finished.emit(False, error_msg)
            
# --- Thread per Rilevamento Percorsi in Background ---
class DetectionWorkerThread(QThread):
    """
    Thread per eseguire la scansione INI e l'euristica di rilevamento
    del percorso di salvataggio in background.
    """
    progress = Signal(str)
    finished = Signal(bool, dict) # Segnale emesso alla fine: successo(bool), risultati(dict)

    def __init__(self, game_install_dir, profile_name_suggestion, current_settings, installed_steam_games_dict=None, emulator_name=None, steam_app_id=None, cancellation_manager=None):
        super().__init__()
        self.game_install_dir = game_install_dir
        self.profile_name_suggestion = profile_name_suggestion
        self.current_settings = current_settings
        self.installed_steam_games_dict = installed_steam_games_dict if installed_steam_games_dict is not None else {}
        self.emulator_name = emulator_name # Store emulator name
        self.steam_app_id = steam_app_id # Store Steam AppID
        self.is_running = True
        self.cancellation_requested = False  # Add cancellation flag
        self.cancellation_manager = cancellation_manager
        self.setObjectName("DetectionWorkerThread") # Aggiunto ObjectName

    def request_cancellation(self):
        self.cancellation_requested = True

    def run(self):
        """Contiene la logica di scansione INI e euristica."""
        if self.cancellation_requested:
            return
        # --- VARIABILI INIZIALI ---
        final_path_data = [] # Ora conterrà tuple (path, score)
        paths_already_added = set() # Per evitare duplicati di percorsi
        error_message = ""
        status = "not_found" # Default
        profile_name = self.profile_name_suggestion

        INI_SCORE_BONUS = 1000 # Score fittizio alto per percorsi trovati da INI

        try:
            self.progress.emit(f"Starting search for '{profile_name}'...")
            path_found_via_ini = False # Flag specifico per INI

            if self.game_install_dir:
                self.progress.emit("Scanning INI files...") # Messaggio più generico
                # Usa self.current_settings passato nell'init
                ini_whitelist = self.current_settings.get("ini_whitelist", [])
                ini_blacklist = self.current_settings.get("ini_blacklist", [])
                ini_whitelist_lower = {name.lower() for name in ini_whitelist} # Usa set per efficienza
                ini_blacklist_lower = {name.lower() for name in ini_blacklist} # Usa set per efficienza
                keys_to_check = {
                    'SavePath': ['Settings', 'Storage', 'Game'],
                    'AppDataPath': ['Settings', 'Storage'],
                    'Dir_0': ['Settings', 'Directories', 'Paths', 'Location'],
                    'UserDataFolder': ['Settings', 'Storage']
                    # Aggiungi altre chiavi/sezioni comuni se necessario
                }
                parser = configparser.ConfigParser(interpolation=None, allow_no_value=True, comment_prefixes=('#', ';'), inline_comment_prefixes=('#', ';')) # Configurazione parser
                decoded_ini_files = [] # Per fallback

                # --- Inizio Scansione INI (Whitelist) ---
                logging.debug(f"Starting INI scan in {self.game_install_dir}...")
                for root, dirs, files in os.walk(self.game_install_dir, topdown=True):
                    if not self.is_running: break
                    # Ottimizzazione: Non scendere in cartelle comuni non utili (es. '.git', 'engine')
                    dirs[:] = [d for d in dirs if d.lower() not in ['__pycache__', '.git', '.svn', 'engine', 'binaries', 'intermediates', 'logs']]

                    for filename in files:
                        if not self.is_running: break
                        filename_lower = filename.lower()
                        if filename_lower in ini_blacklist_lower: continue

                        # Processa solo se nella whitelist
                        if filename_lower in ini_whitelist_lower:
                            ini_path = os.path.join(root, filename)
                            logging.debug(f"  Processing potential INI: {ini_path}")
                            try:
                                possible_encodings = ['utf-8', 'cp1252', 'latin-1']
                                parsed_successfully = False
                                used_encoding = None
                                ini_content_for_fallback = None # Salva contenuto per fallback

                                for enc in possible_encodings:
                                    if not self.is_running: break
                                    try:
                                        parser.clear()
                                        with open(ini_path, 'r', encoding=enc) as f_content:
                                            ini_content = f_content.read()
                                        parser.read_string(ini_content) # Usa read_string
                                        parsed_successfully = True
                                        used_encoding = enc
                                        ini_content_for_fallback = ini_content # Salva per dopo
                                        logging.debug(f"    Successfully parsed {filename} with encoding '{used_encoding}'")
                                        break # Trovato encoding
                                    except UnicodeDecodeError: continue
                                    except configparser.Error as e_inner_parse:
                                        logging.debug(f"    Parsing error for {filename} with '{enc}': {e_inner_parse}")
                                        parsed_successfully = False
                                        break # Inutile provare altri encoding se il formato è errato

                                if not parsed_successfully: continue

                                # Aggiungi ai file decodificati per eventuale fallback DOPO check chiavi
                                decoded_ini_files.append((ini_path, used_encoding, ini_content_for_fallback))

                                # --- Cerca Chiavi Standard ---
                                found_in_this_file = False # Flag per sapere se abbiamo trovato una chiave in QUESTO file
                                for key, sections in keys_to_check.items():
                                    if not self.is_running: break
                                    possible_value = None
                                    for section in sections:
                                        if parser.has_section(section) and parser.has_option(section, key):
                                            possible_value = parser.get(section, key, fallback=None)
                                            break # Trovato, esci loop sezioni
                                    # Controlla anche nella sezione di default [DEFAULT]
                                    if not possible_value and parser.has_option(configparser.DEFAULTSECT, key):
                                            possible_value = parser.get(configparser.DEFAULTSECT, key, fallback=None)

                                    # --- Blocco che USA resolved_path ---
                                    if possible_value:
                                        expanded_path = os.path.expandvars(possible_value.strip('"\' '))
                                        resolved_path = None # Inizializza a None per sicurezza
                                        try:
                                            if not os.path.isabs(expanded_path):
                                                # Risolvi relativo alla cartella del GIOCO, non dell'INI
                                                resolved_path = os.path.normpath(os.path.join(self.game_install_dir, expanded_path))
                                            else:
                                                resolved_path = os.path.normpath(expanded_path)

                                            # VALIDAZIONE: è una dir esistente e non è radice?
                                            if os.path.isdir(resolved_path) and len(os.path.splitdrive(resolved_path)[1]) > 1:
                                                logging.info(f"    Percorso RILEVATO (Chiave Standard '{key}' in {filename}): {resolved_path}")
                                                norm_path = os.path.normpath(resolved_path)
                                                if norm_path not in paths_already_added:
                                                    final_path_data.append((norm_path, INI_SCORE_BONUS)) # Aggiungi con score alto
                                                    paths_already_added.add(norm_path)
                                                    path_found_via_ini = True # Imposta il flag INI generale
                                                found_in_this_file = True # Trovato in questo file specifico
                                                # Non usciamo dal loop chiavi/sezioni, potremmo trovarne altri in questo file
                                            else:
                                                 logging.debug(f"    Path from key '{key}' ('{resolved_path}') is not a valid directory or is root.")
                                        except ValueError as e_path:
                                             logging.warning(f"    Error processing path '{expanded_path}' from key '{key}': {e_path}")
                                        except Exception as e_resolve:
                                             logging.error(f"    Unexpected error resolving path for key '{key}': {e_resolve}", exc_info=True)
                                    # --- Fine Blocco che USA resolved_path ---
                                # Fine ciclo for key, sections... (check chiavi standard)

                            except FileNotFoundError:
                                logging.warning(f"  INI file vanished during analysis? {ini_path}")
                            except Exception as e_outer:
                                logging.warning(f"  Generic error processing {ini_path}: {e_outer}", exc_info=True)
                        # Fine if filename_lower in ini_whitelist_lower
                    # Fine ciclo for filename in files
                    if not self.is_running: break # Esci da os.walk se interrotto
                # Fine ciclo for root, dirs, files (os.walk)
                logging.debug(f"Finished INI scan (Whitelist). Found paths via standard keys: {path_found_via_ini}")
                # --- Fine Scansione INI (Whitelist) ---

                # --- Logica Fallback (Commenti/Prefissi) ---
                # Esegui solo se il thread è attivo
                if self.is_running:
                    self.progress.emit("Checking INI files for fallback paths...")
                    logging.debug(f"Attempting fallback scan on {len(decoded_ini_files)} successfully decoded INI files...")
                    preferred_inis = ['steam_emu.ini'] # Dai priorità
                    # Ordina mettendo prima i preferiti
                    sorted_decoded_inis = sorted(
                        decoded_ini_files,
                        key=lambda item: os.path.basename(item[0]).lower() not in preferred_inis
                    )
                    fallback_prefixes = { # Prefissi da cercare (chiave: testo, valore: lunghezza)
                        "### Game data is stored at ": len("### Game data is stored at "),
                        "# SavesDir = ": len("# SavesDir = "),
                        "; SavesDir = ": len("; SavesDir = "),
                        "Dir_0=": len("Dir_0="),
                        "Save Path = ": len("Save Path = "),
                        # Aggiungi altri se necessario, es. da diversi emu/config
                    }

                    for ini_path_to_check, encoding_to_use, ini_content in sorted_decoded_inis:
                        if not self.is_running: break
                        logging.debug(f"  Scanning for fallback prefixes in: {os.path.basename(ini_path_to_check)}")
                        try:
                            lines = ini_content.splitlines() # Usa contenuto già letto
                            found_in_this_file_fallback = False
                            for line_num, line in enumerate(lines):
                                if not self.is_running: break
                                cleaned_line = line.strip()
                                if not cleaned_line or cleaned_line.startswith('['): continue # Salta vuote e sezioni

                                for prefix, prefix_len in fallback_prefixes.items():
                                    if cleaned_line.startswith(prefix):
                                        path_from_line = cleaned_line[prefix_len:].strip('"\' ')
                                        logging.debug(f"    -> Line {line_num+1}: Found prefix '{prefix}', extracted path: '{path_from_line}'")
                                        resolved_path = None # Inizializza
                                        try:
                                            expanded_path = os.path.expandvars(path_from_line)
                                            # Risolvi relativo alla cartella GIOCO
                                            if not os.path.isabs(expanded_path):
                                                resolved_path = os.path.normpath(os.path.join(self.game_install_dir, expanded_path))
                                            else:
                                                resolved_path = os.path.normpath(expanded_path)

                                            # VALIDAZIONE
                                            if os.path.isdir(resolved_path) and len(os.path.splitdrive(resolved_path)[1]) > 1:
                                                logging.info(f"    Percorso RILEVATO (Fallback prefisso '{prefix}' in {os.path.basename(ini_path_to_check)}): {resolved_path}")
                                                norm_path = os.path.normpath(resolved_path)
                                                if norm_path not in paths_already_added:
                                                     final_path_data.append((norm_path, INI_SCORE_BONUS)) # Aggiungi con score alto
                                                     paths_already_added.add(norm_path)
                                                     path_found_via_ini = True # Imposta flag generale
                                                found_in_this_file_fallback = True
                                                # Non usciamo dal loop prefissi, potrebbero essercene altri utili
                                            else:
                                                 logging.debug(f"    -> Fallback path '{resolved_path}' is not valid or is root.")
                                        except ValueError as e_path_fb:
                                             logging.warning(f"    Error processing path '{path_from_line}' from fallback: {e_path_fb}")
                                        except Exception as e_resolve_fb:
                                            logging.warning(f"    Error expanding/normalizing fallback path: {e_resolve_fb}", exc_info=True)
                                # Fine ciclo for prefix...
                            # Fine ciclo for line...
                        except Exception as e_fallback_read:
                            logging.warning(f"  Error reading/processing {os.path.basename(ini_path_to_check)} for fallback.", exc_info=True)
                        # Fine try...except lettura fallback
                    # Fine ciclo for ini_path_to_check...
                    logging.debug(f"Finished INI fallback scan. Found paths via fallback: {path_found_via_ini}")
                # --- Fine Logica Fallback ---

            # --- Euristica Aggiuntiva (Ora AGGIUNGE ai risultati INI, non sostituisce) ---
            if self.is_running: # L'euristica si esegue sempre se c'è install dir (e non interrotto)
                if not path_found_via_ini: # Mostra messaggio solo se INI non ha trovato nulla
                    self.progress.emit("Performing heuristic search...")
                    logging.info("No valid paths found via INI scan. Starting generic heuristic search...")
                else:
                    self.progress.emit("Performing additional heuristic search...")
                    logging.info("INI scan found paths. Starting additional heuristic search...")

                try:
                    # Determina se è un gioco Steam basato sulla presenza di steam_app_id
                    is_steam_game = self.steam_app_id is not None
                    
                    # Chiamata a guess_save_path (ora restituisce lista di tuple)
                    c_manager = getattr(self, 'cancellation_manager', None)
                    heuristic_guesses_with_scores = core_logic.guess_save_path(
                        game_name=profile_name,
                        game_install_dir=self.game_install_dir,
                        is_steam_game=is_steam_game, # Usa il flag basato su steam_app_id
                        installed_steam_games_dict=self.installed_steam_games_dict,
                        appid=self.steam_app_id, # Passa l'AppID di Steam quando disponibile
                        cancellation_manager=c_manager
                    )
                    
                    logging.info(f"Heuristic save search for '{profile_name}' (AppID: {self.steam_app_id})")
                    if is_steam_game:
                        logging.info(f"Using Steam AppID: {self.steam_app_id} for heuristic search")
                    logging.debug(f"Heuristic search results (with scores): {heuristic_guesses_with_scores}")

                    # Aggiungi i risultati dell'euristica se non già presenti
                    added_heuristic_count = 0
                    for path, score in heuristic_guesses_with_scores:
                        norm_path = os.path.normpath(path)
                        if norm_path not in paths_already_added:
                             # <<< CORREZIONE: valida di nuovo qui per sicurezza >>>
                             if os.path.isdir(norm_path) and len(os.path.splitdrive(norm_path)[1]) > 1:
                                 logging.info(f"  Adding valid path (Score: {score}) from heuristic: {norm_path}")
                                 final_path_data.append((norm_path, score))
                                 paths_already_added.add(norm_path)
                                 added_heuristic_count += 1
                             else:
                                 logging.warning(f"  Skipping invalid heuristic guess: {norm_path}")
                    logging.info(f"Added {added_heuristic_count} new unique paths from heuristic search.")

                    # Imposta lo stato finale basato sulla presenza di dati
                    if final_path_data:
                        status = "found"
                        # Ordina la lista finale in base allo score (decrescente) prima di emetterla
                        final_path_data.sort(key=lambda item: item[1], reverse=True)
                    elif not path_found_via_ini: # Se INI non ha trovato nulla E neanche euristica
                        status = "not_found"
                        logging.info("Heuristic search did not yield any valid paths.")

                except Exception as e_heuristic:
                    error_message = f"Error during heuristic search: {e_heuristic}"
                    logging.error(f"Error during heuristic search: {e_heuristic}", exc_info=True)
                    # Non cambiare status qui, l'errore è nel messaggio

            elif not self.game_install_dir and self.is_running: # Caso in cui non c'è install dir
                 logging.warning("Unable to perform automatic search: game installation folder not specified.")
                 status = "not_found"

        # --- Gestione Errori Generali ---
        except Exception as e:
            error_message = f"Unexpected error during search: {e}"
            logging.critical(f"Unexpected critical error in detection thread: {e}")
            logging.exception("Error in detection thread:") # Logga traceback completo
            status = "error"

        # --- Blocco Finally per Emettere Risultati ---
        finally:
            if self.is_running:
                # Costruisci il dizionario dei risultati
                results_dict = {
                    'path_data': final_path_data, # Lista di tuple (path, score)
                    'status': status,
                    'message': error_message,
                    'profile_name_suggestion': profile_name, # Aggiungi il nome del profilo usato
                    'emulator_name': self.emulator_name # Add emulator name to results
                }
                self.finished.emit(True, results_dict)

            else:
                 # Se il thread è stato interrotto
                 results_dict = {
                     'status': 'error', # Segnala come errore l'interruzione
                     'path_data': [],
                     'message': "Search interrupted by user.", # Messaggio più specifico
                     'profile_name_suggestion': profile_name,
                     'emulator_name': self.emulator_name # Also include emulator name in error case
                 }
                 self.finished.emit(False, results_dict)

            logging.debug(f"DetectionWorkerThread.run() finished. Status: {status}, PathData Count: {len(final_path_data)}")
            if final_path_data and status == 'found':
                logging.debug(f"Top path found: {final_path_data[0]}")

    def __del__(self):
        try:
            if self.isRunning():
                self.terminate()
                self.wait(100)
        except RuntimeError:  # C++ object already deleted
            pass

    def cancel(self):
        self.is_running = False  # Add cancellation method

    def terminate_immediately(self):
        if self.isRunning():
            self.terminate()
            self.wait(100)  # Wait briefly for thread to stop

# --- Gestore Log Personalizzato per Qt ---
class QtLogHandler(logging.Handler, QObject):
    # Segnale che emette una stringa (il messaggio di log formattato)
    log_signal = Signal(str)

    # __init__ eredita da QObject per poter usare i segnali
    def __init__(self, parent=None):
        logging.Handler.__init__(self)
        QObject.__init__(self, parent) # Chiama __init__ di QObject
        # Opzionale: Imposta un formattatore di default
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S'))

    def emit(self, record):
        """
        Formatta il messaggio e lo emette (con colore HTML se WARNING/ERROR).
        """
        try:
            # Formatta il messaggio base (es. con data, livello, testo)
            msg = self.format(record)

            # --- AGGIUNTA LOGICA COLORE ---
            color = None # Nessun colore di default
            if record.levelno >= logging.ERROR: # ERROR o CRITICAL
                color = "#FF0000" # Rosso acceso (Hex code)
            elif record.levelno == logging.WARNING:
                color = "orange" # Arancione/Giallo (Nome colore HTML)
                # Puoi usare anche un hex code come "#FFA500"

            # Se abbiamo definito un colore, avvolgi il messaggio con i tag HTML <font>
            if color:
                # Nota: Non stiamo facendo escaping HTML complesso qui,
                # sperando che i messaggi di log non contengano '<' o '>'.
                # Se dovessero esserci problemi, potremmo dover usare html.escape(msg).
                colored_msg = f'<font color="{color}">{msg}</font>'
            else:
                # Se è INFO o DEBUG, usa il messaggio normale
                colored_msg = msg
            # --- FINE LOGICA COLORE ---

            # Rimuovi la stampa di debug che avevamo aggiunto prima (opzionale)
            # print(f"DEBUG QtLogHandler: Tentativo di emettere segnale con: '{colored_msg}'")

            # Emette il segnale con il messaggio (potenzialmente colorato)
            self.log_signal.emit(colored_msg)

        except Exception:
            self.handleError(record)

# --- FINE NUOVA CLASSE ---

# --- Widget per Notifiche Personalizzate ---
class NotificationPopup(QWidget):
    def __init__(self, title, message, success, parent=None, icon_path=None): 
        super().__init__(parent)

        # --- Imposta Stile Finestra ---
        # Rende la finestra senza bordi/titolo, sempre in primo piano, tipo Tooltip
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |    # Niente bordi/titolo
            Qt.WindowType.Tool |                 # Non appare nella taskbar (di solito)
            Qt.WindowType.WindowStaysOnTopHint   # Rimane sopra le altre finestre
        )
        # Fa sì che il widget venga eliminato alla chiusura
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # Opzionale: abilita trasparenza se lo sfondo nel QSS lo usa
        # self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # --- Contenuto ---
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10) # Margini interni

        # Icona (Successo o Errore)
        icon_label = QLabel()
        style = QApplication.instance().style() # Ottieni stile per icone standard
        icon_size = 32 # Dimensione icona

        custom_icon_loaded = False
        if icon_path and os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                icon_label.setPixmap(pixmap.scaled(icon_size, icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                custom_icon_loaded = True
            else:
                logging.warning(f"NotificationPopup: Failed to load custom icon from {icon_path}")

        if not custom_icon_loaded:
            if success:
                 icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton) # O SP_MessageBoxInformation
                 # Potresti impostare un objectName per stile QSS specifico: icon_label.setObjectName("SuccessIcon")
            else:
                 icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical) # O SP_MessageBoxWarning
                 # Potresti impostare un objectName per stile QSS specifico: icon_label.setObjectName("ErrorIcon")
            if not icon.isNull():
                 icon_label.setPixmap(icon.pixmap(icon_size, icon_size))
        layout.addWidget(icon_label)

        # Testo Messaggio
        self.message_label = QLabel(f"<b>{title}</b><br>{message}") # Usa HTML per grassetto e a capo
        self.message_label.setWordWrap(True) # Abilita a capo
        # Imposta objectName per stile QSS specifico se serve: self.message_label.setObjectName("NotificationText")
        layout.addWidget(self.message_label, stretch=1) # Stretch per usare spazio

        self.setLayout(layout)

        # --- Timer per Auto-Chiusura ---
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.close)
        self.close_timer.start(6000) # Chiudi dopo 6000 ms = 6 secondi (puoi aggiustare)

    def mousePressEvent(self, event):
        """Chiude la notifica se l'utente ci clicca sopra."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.close() # Chiudi subito
        super().mousePressEvent(event)

    def enterEvent(self, event):
        """Opzionale: Ferma il timer se il mouse entra nella notifica."""
        self.close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Opzionale: Ri-avvia il timer se il mouse esce dalla notifica."""
        self.close_timer.start(6000) # Ri-avvia timer
        super().leaveEvent(event)

# --- FINE CLASSE NotificationPopup ---

class SteamSearchWorkerThread(QThread):
    """
    Thread per eseguire SOLO la ricerca euristica di core_logic.guess_save_path
    per i giochi Steam in background.
    """
    # Segnale emesso alla fine: restituisce la lista di tuple (path, score) trovate
    finished = Signal(list, str)
    # Segnale per messaggi di stato semplici (opzionale)
    progress = Signal(str)

    def __init__(self, game_name, game_install_dir, appid, steam_userdata_path,
                  steam_id3_to_use, installed_steam_games_dict, profile_name_for_results, cancellation_manager=None): 
         super().__init__()
         self.game_name = game_name
         self.game_install_dir = game_install_dir
         self.appid = appid
         self.steam_userdata_path = steam_userdata_path
         self.steam_id3_to_use = steam_id3_to_use
         self.installed_steam_games_dict = installed_steam_games_dict
         self.profile_name_for_results = profile_name_for_results # <-- MEMORIZZA
         self.cancellation_manager = cancellation_manager
         self.setObjectName("SteamSearchWorkerThread")

    def run(self):
        """Esegue la ricerca del percorso."""
        results = [] # Lista vuota di default
        try:
            self.progress.emit(f"Searching path for '{self.game_name}'...") # Messaggio iniziale
            logging.info(f"[Steam Worker] Starting guess_save_path for '{self.game_name}' (AppID: {self.appid})")

            # Chiama la funzione di core_logic con i parametri specifici per Steam
            results = core_logic.guess_save_path(
                game_name=self.game_name,
                game_install_dir=self.game_install_dir,
                appid=self.appid,
                steam_userdata_path=self.steam_userdata_path,
                steam_id3_to_use=self.steam_id3_to_use,
                is_steam_game=True, # Importante per la logica interna di guess_save_path
                installed_steam_games_dict=self.installed_steam_games_dict # <-- NUOVO: passa l'argomento
            )
            logging.info(f"[Steam Worker] guess_save_path finished, found {len(results)} potential paths.")
            self.progress.emit(f"Search complete for '{self.game_name}'.") # Messaggio finale

        except Exception as e:
            error_msg = f"Error during Steam path search thread: {e}"
            logging.error(error_msg, exc_info=True)
            self.progress.emit("Error during search.") # Segnala errore
            # Emettiamo comunque una lista vuota in caso di errore grave nel thread
            results = []
        finally:
            # Emetti il segnale finished con la lista dei risultati (può essere vuota)
            self.finished.emit(results, self.profile_name_for_results)