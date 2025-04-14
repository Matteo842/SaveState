# -*- coding: utf-8 -*-
from PySide6.QtCore import QThread, Signal, QObject, Qt, QTimer # Aggiungi Qt, QTimer, QPoint
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QApplication, QStyle # Aggiungi QWidget, QLabel, QHBoxLayout, QApplication, QStyle

# Importa core_logic e logging SOLO per la gestione delle eccezioni nel blocco 'except'
# Se non esistessero quel blocco 'except' specifico, questi import non servirebbero qui.
import core_logic
import logging          # Per loggare eventuali errori interni al thread
import os               # Per os.walk, os.path, ecc.
import configparser     # Per leggere i file .ini
import sys
import tempfile
from datetime import datetime

DEBUG_LOG_FILE = os.path.join(tempfile.gettempdir(), "savestate_resource_path_debug.log")
try: # Pulisci log vecchio
    if os.path.exists(DEBUG_LOG_FILE): os.remove(DEBUG_LOG_FILE)
    print(f"Pulito vecchio file log debug: {DEBUG_LOG_FILE}")
except Exception as e_del:
    print(f"WARN: Impossibile pulire vecchio file log debug: {e_del}")

def write_debug_log(message):
    try:
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} - {message}\n")
    except Exception as e:
        print(f"!!! ERRORE SCRITTURA DEBUG LOG: {e}")

def resource_path(relative_path):
    """ Trova il percorso assoluto della risorsa, funziona sia in sviluppo che con PyInstaller """
    write_debug_log(f"--- resource_path called with: {relative_path}")
    base_path = None # Inizializza per sicurezza
    try:
        # Metodo standard per PyInstaller (_MEIPASS) o sviluppo (directory script)
        base_path = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(sys.argv[0])))
        write_debug_log(f"--- base_path determined as: {base_path}")    
    except Exception as e:
        write_debug_log(f"--- EXCEPTION determining base_path: {e}")
        logging.error(f"Errore nel calcolare base_path per resource_path: {e}", exc_info=True)
        base_path = os.path.abspath(".")
        write_debug_log(f"--- base_path fallback (CWD): {base_path}")

    path = os.path.join(base_path, relative_path)
    write_debug_log(f"--- resource_path returning: {path}")

    # Controllo opzionale se il percorso generato esiste
    if not os.path.exists(path):
        logging.warning(f"resource_path: Il percorso calcolato NON ESISTE: {path}")
        write_debug_log(f"--- WARNING! Path does NOT exist: {path}")

    return path
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
            self.progress.emit("Operazione in corso...") # CORRETTO
            success, message = self.function(*self.args, **self.kwargs)
            self.progress.emit("Operazione terminata.") # CORRETTO
            self.finished.emit(success, message)
        except Exception as e:
            error_msg = f"Errore critico nel thread worker: {e}" # CORRETTO
            if hasattr(core_logic, 'logging'): core_logic.logging.exception(error_msg)
            else: logging.critical(error_msg, exc_info=True) # Usa critical e aggiunge traceback se possibile
            self.progress.emit("Errore.") # CORRETTO
            self.finished.emit(False, error_msg)
            
# --- Thread per Rilevamento Percorsi in Background ---
class DetectionWorkerThread(QThread):
    """
    Thread per eseguire la scansione INI e l'euristica di rilevamento
    del percorso di salvataggio in background.
    """
    progress = Signal(str)
    finished = Signal(bool, dict) # Segnale emesso alla fine: successo(bool), risultati(dict)

    def __init__(self, game_install_dir, profile_name_suggestion, current_settings):
        super().__init__()
        self.game_install_dir = game_install_dir
        self.profile_name_suggestion = profile_name_suggestion
        self.current_settings = current_settings
        self.is_running = True
        self.setObjectName("DetectionWorkerThread") # Aggiunto ObjectName

    def run(self):
        """Contiene la logica di scansione INI e euristica."""
        detected_save_path = None
        final_paths = []
        error_message = ""
        status = "not_found" # Default
        profile_name = self.profile_name_suggestion # Usa il nome passato

        try:
            self.progress.emit(f"Avvio ricerca per '{profile_name}'...")

            # --- INIZIO LOGICA ESTRATTA E ADATTATA ---

            if self.game_install_dir:
                self.progress.emit("Scansione file INI...") # Messaggio più generico
                # Usa self.current_settings passato nell'init
                ini_whitelist = self.current_settings.get("ini_whitelist", [])
                ini_blacklist = self.current_settings.get("ini_blacklist", [])
                ini_whitelist_lower = [name.lower() for name in ini_whitelist]
                ini_blacklist_lower = [name.lower() for name in ini_blacklist]
                keys_to_check = {
                    'SavePath': ['Settings', 'Storage', 'Game'],
                    'AppDataPath': ['Settings', 'Storage'],
                    'Dir_0': ['Settings', 'Directories', 'Paths', 'Location'],
                    'UserDataFolder': ['Settings', 'Storage']
                }
                parser = configparser.ConfigParser(interpolation=None)
                path_found_flag = False
                decoded_ini_files = []

                # Scansione INI (Whitelist)
                #print(f"THREAD DEBUG: Inizio scansione INI in {self.game_install_dir}...")
                logging.debug(f"Inizio scansione INI in {self.game_install_dir}...")

                for root, dirs, files in os.walk(self.game_install_dir):
                    if not self.is_running: break
                    if path_found_flag: break
                    # Limita la profondità? Potrebbe essere un'ottimizzazione futura
                    # depth = root[len(self.game_install_dir):].count(os.sep)
                    # if depth > MAX_SCAN_DEPTH: dirs[:] = []; continue

                    for filename in files:
                        if not self.is_running: break
                        if path_found_flag: break
                        filename_lower = filename.lower()
                        if filename_lower in ini_blacklist_lower: continue
                        # Processa solo se nella whitelist
                        if filename_lower in ini_whitelist_lower:
                            ini_path = os.path.join(root, filename)
                            #print(f"THREAD DEBUG: Trovato potenziale file INI: {ini_path}") # Forse troppo verboso
                            try:
                                possible_encodings = ['utf-8', 'cp1252', 'latin-1']
                                parsed_successfully = False; used_encoding = None
                                for enc in possible_encodings:
                                    if not self.is_running: break
                                    try:
                                        parser.clear()
                                        # Leggi contenuto per evitare errori strani con parser.read a volte
                                        with open(ini_path, 'r', encoding=enc) as f_content:
                                            ini_content = f_content.read()
                                        parser.read_string(ini_content) # Usa read_string
                                        parsed_successfully = True; used_encoding = enc
                                        # Aggiungi ai decodificati solo se il parsing va a buon fine
                                        decoded_ini_files.append((ini_path, used_encoding))
                                        #print(f"THREAD DEBUG: Letto {ini_path} con encoding '{used_encoding}'")
                                        break # Trovato encoding
                                    except UnicodeDecodeError: continue
                                    except configparser.Error:
                                        #print(f"THREAD WARN: Errore parsing INI (con '{enc}') {ini_path}: {e_inner_parse}")
                                        parsed_successfully = False
                                        break # Inutile provare altri encoding se il formato è errato
                                if not parsed_successfully: continue

                                # Cerca Chiavi Standard
                                for key, sections in keys_to_check.items():
                                    if path_found_flag: break
                                    possible_value = None
                                    for section in sections:
                                        if parser.has_section(section) and parser.has_option(section, key):
                                            possible_value = parser.get(section, key); break
                                    if not possible_value and parser.has_option(configparser.DEFAULTSECT, key):
                                            possible_value = parser.get(configparser.DEFAULTSECT, key)

                                    if possible_value:
                                        expanded_path = os.path.expandvars(possible_value.strip('"\' '))
                                        if not os.path.isabs(expanded_path):
                                            # Risolvi relativo alla cartella del GIOCO, non dell'INI
                                            resolved_path = os.path.normpath(os.path.join(self.game_install_dir, expanded_path))
                                        else:
                                            resolved_path = os.path.normpath(expanded_path)

                                        # VALIDAZIONE: è una dir esistente e non è radice?
                                        if os.path.isdir(resolved_path) and len(os.path.splitdrive(resolved_path)[1]) > 1:
                                            logging.info(f"THREAD INFO: Percorso RILEVATO (Chiave Standard '{key}' in {os.path.basename(ini_path)}): {resolved_path}")
                                            detected_save_path = resolved_path
                                            path_found_flag = True; break # Esce dal loop chiavi
                                        #else:
                                            #print(f"THREAD DEBUG: Percorso da chiave '{key}' ('{resolved_path}') non è dir valido o è radice.")
                            except FileNotFoundError:
                                logging.warning(f"THREAD WARN: File INI scomparso durante analisi? {ini_path}")
                            except Exception as e_outer:
                                logging.warning(f"THREAD WARN: Errore generico processando {ini_path}: {e_outer}")
                        if path_found_flag: break # Esce dal loop file
                    if path_found_flag: break # Esce dal loop os.walk
                logging.debug(f"Fine scansione INI (Whitelist). Trovato path da chiave standard: {detected_save_path is not None}")

                # Fallback Logic (Commenti/Prefissi) - Esegui solo se non trovato con chiavi e thread attivo
                if not path_found_flag and self.is_running:
                    self.progress.emit("Ricerca fallback in file INI...")
                    logging.debug(f"Nessuna chiave standard trovata. Tento fallback su {len(decoded_ini_files)} file INI decodificati...")
                    preferred_inis = ['steam_emu.ini'] # Dai priorità
                    sorted_decoded_inis = sorted(
                        decoded_ini_files,
                        key=lambda item: os.path.basename(item[0]).lower() not in preferred_inis
                    )
                    fallback_prefixes = { # Prefissi da cercare
                        "### Game data is stored at ": len("### Game data is stored at "),
                        "Dir_0=": len("Dir_0=")
                        # Aggiungi altri se necessario
                    }

                    for ini_path_to_check, encoding_to_use in sorted_decoded_inis:
                        if not self.is_running: break
                        if detected_save_path: break # Se trovato nel frattempo
                        #print(f"THREAD DEBUG: Tento fallback commenti in: {ini_path_to_check}")
                        try:
                            with open(ini_path_to_check, 'r', encoding=encoding_to_use) as f:
                                for line_num, line in enumerate(f):
                                    if not self.is_running: break
                                    cleaned_line = line.strip()
                                    if not cleaned_line or cleaned_line.startswith('['): continue # Salta vuote e sezioni

                                    for prefix, prefix_len in fallback_prefixes.items():
                                        if cleaned_line.startswith(prefix):
                                            path_from_line = cleaned_line[prefix_len:].strip('"\' ')
                                            #print(f"THREAD DEBUG:  -> Riga {line_num+1}: Trovato prefisso '{prefix}', path estratto: '{path_from_line}'")
                                            try:
                                                expanded_path = os.path.expandvars(path_from_line)
                                                # Risolvi relativo alla cartella GIOCO
                                                if not os.path.isabs(expanded_path):
                                                    resolved_path = os.path.normpath(os.path.join(self.game_install_dir, expanded_path))
                                                else:
                                                    resolved_path = os.path.normpath(expanded_path)

                                                # VALIDAZIONE
                                                if os.path.isdir(resolved_path) and len(os.path.splitdrive(resolved_path)[1]) > 1:
                                                    logging.info(f"Percorso RILEVATO (Fallback prefisso '{prefix}' in {os.path.basename(ini_path_to_check)}): {resolved_path}")
                                                    detected_save_path = resolved_path
                                                    path_found_flag = True # Segna trovato anche qui
                                                    break # Trovato, esci loop prefissi
                                                #else:
                                                    #print(f"THREAD WARN:   -> Il percorso da fallback '{resolved_path}' NON è valido o è radice.")
                                            except Exception as e_resolve:
                                                logging.warning(f"Errore durante espansione/normalizzazione percorso da fallback: {e_resolve}")
                                    if path_found_flag: break # Esci loop righe
                        except FileNotFoundError:
                            logging.warning(f"File INI scomparso durante ricerca fallback? Path: {ini_path_to_check}")
                        except Exception:
                            logging.warning(f"Errore lettura file {ini_path_to_check} per fallback.", exc_info=True) # Aggiunto exc_info per dettagli errore lettura
                        if path_found_flag: break # Esci loop file INI
                    logging.debug(f"Fine ricerca fallback. Trovato path: {detected_save_path is not None}")


            # Se trovato percorso da INI (chiave o fallback), aggiungilo ai risultati
            # Usiamo path_found_flag per sicurezza
            if path_found_flag and detected_save_path and self.is_running:
                norm_path = os.path.normpath(detected_save_path)
                if norm_path not in final_paths:
                    final_paths.append(norm_path)
                status = "found" # Aggiorna stato

            # Euristica Aggiuntiva (se INI fallisce o non applicabile E thread attivo)
            if not path_found_flag and self.game_install_dir and self.is_running:
                self.progress.emit("Ricerca euristica generica...")
                logging.info("Ricerca INI fallita o non applicabile. Avvio ricerca euristica generica...")
                try:
                    # Chiamiamo guess_save_path qui dentro il thread
                    heuristic_guesses = core_logic.guess_save_path(
                        game_name=profile_name, # Usa il nome profilo passato
                        game_install_dir=self.game_install_dir,
                        is_steam_game=False # Ricerca generica per drag-drop
                    )
                    logging.debug(f"Risultati ricerca euristica: {heuristic_guesses}")
                    # Aggiungi i risultati validi dell'euristica (se non già presenti)
                    for guess in heuristic_guesses:
                         norm_guess = os.path.normpath(guess)
                         # guess_save_path dovrebbe già validare, ma doppio check
                         if os.path.isdir(norm_guess) and len(os.path.splitdrive(norm_guess)[1]) > 1:
                             if norm_guess not in final_paths:
                                 logging.info(f"Aggiunto percorso valido trovato tramite euristica: {norm_guess}")
                                 final_paths.append(norm_guess)
                         #else:
                         #     print(f"THREAD WARN: Scarto guess euristico non valido restituito da core_logic: {norm_guess}")

                    if final_paths: # Se abbiamo trovato qualcosa (da INI o euristica)
                        status = "found" # Conferma lo stato 'found'
                    else:
                        logging.info("La ricerca euristica non ha prodotto percorsi validi aggiuntivi.")
                        status = "not_found" # Rimane 'not_found' se anche euristica fallisce

                except Exception as e_heuristic:
                    error_message = f"Errore durante ricerca euristica: {e_heuristic}"
                    logging.error(f"Errore durante ricerca euristica: {e_heuristic}", exc_info=True) # Usa direttamente l'eccezione e aggiungi traceback
                    # Non impostare status="error" qui a meno che non sia fatale?
                    # Se l'euristica fallisce ma INI aveva trovato qualcosa, status dovrebbe rimanere 'found'.
                    # Se INI non aveva trovato nulla, status rimane 'not_found'.
                    # Aggiungiamo l'errore al messaggio finale.
                    error_message = f"Errore euristica: {e_heuristic}" # Sovrascrive eventuali errori precedenti? Meglio accumulare?

            elif not self.game_install_dir:
                 # Questo caso dovrebbe essere gestito prima di avviare il thread, ma per sicurezza...
                 logging.warning("Impossibile eseguire ricerca automatica: cartella di installazione del gioco non specificata.")
                 status = "not_found"

            # --- FINE LOGICA ESTRATTA E ADATTATA ---

        except Exception as e:
            error_message = f"Errore imprevisto durante la ricerca: {e}"
            logging.critical(f"Errore critico imprevisto nel thread di rilevamento: {e}") # Il logging.exception successivo cattura già il traceback
            logging.exception("Errore nel thread di rilevamento:") # Logga traceback
            status = "error" # Errore generale impedisce di continuare

        finally:
            # Alla fine, emetti il segnale 'finished' con i risultati
            if self.is_running:
                results = {
                    'status': status,
                    'paths': final_paths, # Lista dei percorsi trovati
                    'message': error_message, # Eventuale messaggio di errore
                    'profile_name_suggestion': profile_name # Passiamo indietro il nome
                }
                self.finished.emit(status != "error", results) # successo è True se non ci sono stati errori critici
            else:
                 # Thread interrotto
                 results = {
                     'status': 'error', # Segnala come errore l'interruzione
                     'paths': [],
                     'message': "Ricerca interrotta.",
                     'profile_name_suggestion': profile_name
                 }
                 self.finished.emit(False, results)
            logging.debug(f"DetectionWorkerThread.run() terminato. Status: {status}, Paths: {final_paths}")

    def stop(self):
        self.is_running = False
        self.progress.emit("Interruzione ricerca...")
        logging.info("Richiesta interruzione per DetectionWorkerThread.")
        
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
    def __init__(self, title, message, success, parent=None):
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