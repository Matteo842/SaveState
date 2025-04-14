import os
import subprocess
import json
from datetime import datetime
import time
import winreg  # Per leggere il registro di Windows
import vdf     # Per leggere i file VDF/ACF di Steam (installa con: pip install vdf)

# --- CONFIGURAZIONE ---
# Assicurati che questo percorso sia corretto per la tua installazione di WinRAR
WINRAR_PATH = r"C:\Program Files\WinRAR\rar.exe"
# Cartella base dove verranno salvati tutti i backup (una sottocartella per profilo)
BACKUP_BASE_DIR = r"D:\GameSaveBackups"
# File dove verranno memorizzati i profili
PROFILE_FILE = "game_save_profiles.json"
# Numero massimo di backup da mantenere per profilo
MAX_BACKUPS = 3
# --- FINE CONFIGURAZIONE ---

# Variabili globali per caching dati Steam (opzionale, per performance)
steam_install_path = None
steam_libraries = None
installed_steam_games = None # Dizionario {appid: {'name': '...', 'installdir': '...'}}
steam_userdata_path = None
steam_id3 = None

# --- FUNZIONI ESISTENTI (check_winrar, load_profiles, save_profiles, ecc.) ---
# ... (Includi qui tutte le funzioni dello script precedente:
# check_winrar, load_profiles, save_profiles, manage_backups, perform_backup,
# perform_restore, profile_menu ) ...
# Le riporto qui per completezza, senza modifiche sostanziali, tranne dove indicato

def check_winrar():
    """Verifica se il percorso di WinRAR è valido."""
    if not os.path.exists(WINRAR_PATH):
        print(f"ERRORE: Impossibile trovare WinRAR.exe nel percorso specificato: {WINRAR_PATH}")
        print("Per favore, modifica la variabile 'WINRAR_PATH' nello script con il percorso corretto.")
        input("Premi Invio per uscire.")
        exit(1)
    # print(f"WinRAR trovato in: {WINRAR_PATH}") # Rimosso per output più pulito

def load_profiles():
    """Carica i profili dal file JSON."""
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, 'r', encoding='utf-8') as f: # Aggiunto encoding
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Attenzione: Il file dei profili '{PROFILE_FILE}' è corrotto. Verrà creato un nuovo file.")
            return {}
        except Exception as e:
            print(f"Errore durante il caricamento dei profili: {e}")
            return {}
    return {}

def save_profiles(profiles):
    """Salva i profili nel file JSON."""
    try:
        with open(PROFILE_FILE, 'w', encoding='utf-8') as f: # Aggiunto encoding
            json.dump(profiles, f, indent=4, ensure_ascii=False) # ensure_ascii=False per nomi giochi
    except Exception as e:
        print(f"Errore durante il salvataggio dei profili: {e}")

def create_profile(profiles, profile_name=None, save_folder_path=None, skip_save=False):
    """Crea un nuovo profilo, opzionalmente con valori pre-forniti."""
    print("\n--- Creazione/Modifica Profilo ---")
    if profile_name is None:
        while True:
            profile_name_input = input("Inserisci un nome per il profilo (es. Cyberpunk2077): ")
            if not profile_name_input:
                print("Il nome del profilo non può essere vuoto.")
            # Permetti di sovrascrivere se viene passato un nome
            # elif profile_name_input in profiles:
            #     print(f"Un profilo con il nome '{profile_name_input}' esiste già.")
            else:
                profile_name = profile_name_input
                break
    else:
        print(f"Nome profilo: {profile_name}")

    if save_folder_path is None or not os.path.isdir(save_folder_path):
        if save_folder_path: # Se era fornito ma non valido
             print(f"Il percorso suggerito '{save_folder_path}' non è valido o non trovato.")
        while True:
            save_folder_path_input = input(f"Inserisci il percorso completo della cartella dei salvataggi per '{profile_name}': ")
            if not os.path.isdir(save_folder_path_input):
                print(f"ERRORE: Il percorso '{save_folder_path_input}' non è una cartella valida o non esiste.")
            else:
                save_folder_path = save_folder_path_input
                break
    else:
         print(f"Percorso salvataggi: {save_folder_path}")

    profiles[profile_name] = save_folder_path
    if not skip_save:
        save_profiles(profiles)
    print(f"Profilo '{profile_name}' configurato con successo!")
    # time.sleep(1) # Pausa ridotta/rimossa
    return profile_name, save_folder_path # Restituisce i dati usati

def select_profile(profiles):
    """Seleziona un profilo esistente."""
    if not profiles:
        print("\nNessun profilo esistente. Creane uno prima.")
        time.sleep(2)
        return None, None

    print("\n--- Seleziona Profilo ---")
    profile_list = list(profiles.keys())
    for i, name in enumerate(profile_list):
        # Tronca percorso lungo per leggibilità
        path_display = profiles[name]
        if len(path_display) > 60:
            path_display = path_display[:25] + "..." + path_display[-30:]
        print(f"{i + 1}. {name} ({path_display})")

    while True:
        try:
            choice = input(f"Scegli un numero (1-{len(profile_list)}) o 0 per annullare: ")
            choice_num = int(choice)
            if choice_num == 0:
                return None, None
            if 1 <= choice_num <= len(profile_list):
                profile_name = profile_list[choice_num - 1]
                return profile_name, profiles[profile_name]
            else:
                print("Scelta non valida.")
        except ValueError:
            print("Inserisci un numero valido.")

def manage_backups(profile_backup_dir):
    """Elimina i backup più vecchi se superano il limite."""
    try:
        # Trova tutti i file .rar nella cartella di backup del profilo
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".rar")]
        
        # Ordina i file per data di modifica (dal più vecchio al più recente)
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)))

        num_backups = len(backup_files)
        # print(f"Trovati {num_backups} backup per questo profilo (limite: {MAX_BACKUPS}).") # Meno verboso

        if num_backups > MAX_BACKUPS:
            num_to_delete = num_backups - MAX_BACKUPS
            print(f"Eliminazione dei {num_to_delete} backup più vecchi...")
            for i in range(num_to_delete):
                file_to_delete = os.path.join(profile_backup_dir, backup_files[i])
                try:
                    print(f"  Elimino: {backup_files[i]}")
                    os.remove(file_to_delete)
                except Exception as e:
                    print(f"  ERRORE durante l'eliminazione di {backup_files[i]}: {e}")
        # else:
        #      print("Nessun backup vecchio da eliminare.") # Meno verboso

    except FileNotFoundError:
        # Non è un errore grave se la cartella non esiste ancora
        # print(f"La cartella di backup '{profile_backup_dir}' non è stata trovata per la gestione dei backup.")
        pass
    except Exception as e:
        print(f"Errore durante la gestione dei backup: {e}")


def perform_backup(profile_name, save_folder_path):
    """Esegue il backup per il profilo specificato."""
    print(f"\n--- Backup per '{profile_name}' ---")
    profile_backup_dir = os.path.join(BACKUP_BASE_DIR, profile_name)

    # Crea la cartella di backup specifica per il profilo se non esiste
    os.makedirs(profile_backup_dir, exist_ok=True)

    # Crea nome file backup con data e ora
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"Backup_{profile_name}_{timestamp}.rar"
    archive_path = os.path.join(profile_backup_dir, archive_name)

    print(f"Salvataggi da backuppare: {save_folder_path}")
    print(f"Archivio di destinazione: {archive_path}")

    source_path_for_rar = os.path.join(save_folder_path, '*') # Backup del *contenuto*

    command = [ WINRAR_PATH, "a", "-r", "-ep1", "-o+", archive_path, source_path_for_rar ]

    try:
        print("Avvio di WinRAR...")
        # Mostra output di rar per più info, ma nasconde finestra console
        result = subprocess.run(command, check=True, capture_output=False, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        print("Backup completato con successo!")
        manage_backups(profile_backup_dir) # Pulisce i backup vecchi dopo un successo
    except subprocess.CalledProcessError as e:
        print(f"ERRORE durante l'esecuzione di WinRAR (Codice: {e.returncode}).")
        print(f"Comando: {' '.join(command)}")
        # L'output di errore viene già stampato da run se capture_output=False
    except FileNotFoundError:
         print(f"ERRORE: Impossibile eseguire il comando. Assicurati che WinRAR sia installato e che '{WINRAR_PATH}' sia corretto.")
    except Exception as e:
        print(f"Si è verificato un errore imprevisto durante il backup: {e}")

    input("Premi Invio per continuare...")

def perform_restore(profile_name, save_folder_path):
    """Ripristina i salvataggi da un backup selezionato."""
    print(f"\n--- Ripristino per '{profile_name}' ---")
    profile_backup_dir = os.path.join(BACKUP_BASE_DIR, profile_name)

    if not os.path.isdir(profile_backup_dir):
        print(f"Nessuna cartella di backup trovata per '{profile_name}' in '{profile_backup_dir}'.")
        input("Premi Invio per continuare...")
        return

    try:
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith(f"Backup_{profile_name}_") and f.endswith(".rar")]
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)), reverse=True)

        if not backup_files:
            print(f"Nessun file di backup (.rar) trovato per '{profile_name}' in '{profile_backup_dir}'.")
            input("Premi Invio per continuare...")
            return

        print("Backup disponibili per il ripristino (dal più recente):")
        for i, fname in enumerate(backup_files):
            # Mostra data/ora del backup per facilitare scelta
            try:
                mtime = os.path.getmtime(os.path.join(profile_backup_dir, fname))
                dt_object = datetime.fromtimestamp(mtime)
                date_str = dt_object.strftime("%Y-%m-%d %H:%M:%S")
                print(f"{i + 1}. {fname} ({date_str})")
            except Exception:
                 print(f"{i + 1}. {fname}") # Fallback se data non leggibile


        while True:
            try:
                choice = input(f"Scegli un numero (1-{len(backup_files)}) per ripristinare, o 0 per annullare: ")
                choice_num = int(choice)
                if choice_num == 0:
                    print("Ripristino annullato.")
                    input("Premi Invio per continuare...")
                    return # Annulla
                if 1 <= choice_num <= len(backup_files):
                    selected_backup_file = backup_files[choice_num - 1]
                    archive_to_restore = os.path.join(profile_backup_dir, selected_backup_file)
                    break # Scelta valida
                else:
                    print("Scelta non valida.")
            except ValueError:
                print("Inserisci un numero valido.")

        print("\nATTENZIONE!!!")
        print(f"Stai per ripristinare il backup '{selected_backup_file}'.")
        print("Questo SOVRASCRIVERÀ qualsiasi file esistente nella cartella:")
        print(f"'{save_folder_path}'")
        # Aggiungi un consiglio extra
        print("\nConsiglio: Se non sei sicuro, fai prima un backup manuale dei file correnti!")
        confirm = input("Sei assolutamente sicuro di voler procedere? (sì/no): ").lower()

        if confirm == 'sì' or confirm == 'si' or confirm == 's':
            # Crea la cartella di destinazione se non esiste (importante!)
            os.makedirs(save_folder_path, exist_ok=True)
            print(f"Ripristino da '{archive_to_restore}' a '{save_folder_path}'...")

            command = [ WINRAR_PATH, "x", "-o+", archive_to_restore, save_folder_path ]

            try:
                print("Avvio di WinRAR per l'estrazione...")
                result = subprocess.run(command, check=True, capture_output=False, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                print("Ripristino completato con successo!")
            except subprocess.CalledProcessError as e:
                print(f"ERRORE durante l'esecuzione di WinRAR (Codice: {e.returncode}).")
                print(f"Comando: {' '.join(command)}")
            except FileNotFoundError:
                 print(f"ERRORE: Impossibile eseguire il comando. Assicurati che WinRAR sia installato e che '{WINRAR_PATH}' sia corretto.")
            except Exception as e:
                print(f"Si è verificato un errore imprevisto durante il ripristino: {e}")
        else:
            print("Ripristino annullato.")

    except Exception as e:
        print(f"Errore durante la ricerca/selezione dei backup: {e}")

    input("Premi Invio per continuare...")

def profile_menu(profile_name, save_folder_path):
    """Menu delle azioni per un profilo selezionato."""
    while True:
        print(f"\n--- Profilo: {profile_name} ---")
        path_display = save_folder_path
        if len(path_display) > 70:
             path_display = path_display[:30] + "..." + path_display[-35:]
        print(f"Cartella salvataggi: {path_display}")
        print("1. Effettua Backup")
        print("2. Ripristina da Backup")
        print("0. Torna al menu principale")

        choice = input("Scegli un'opzione: ")

        if choice == '1':
            perform_backup(profile_name, save_folder_path)
        elif choice == '2':
            perform_restore(profile_name, save_folder_path)
        elif choice == '0':
            break
        else:
            print("Scelta non valida.")

# --- NUOVE FUNZIONI PER STEAM ---

def get_steam_install_path():
    """Trova il percorso di installazione di Steam dal registro di Windows."""
    global steam_install_path
    if steam_install_path:
        return steam_install_path
    try:
        # Prova prima HKEY_CURRENT_USER (installazione utente singolo)
        key_path = r"Software\Valve\Steam"
        try:
            hkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            steam_install_path = winreg.QueryValueEx(hkey, "SteamPath")[0]
            winreg.CloseKey(hkey)
            print(f"Trovata installazione Steam (HKCU): {steam_install_path}")
            return steam_install_path.replace('/', '\\') # Normalizza slash
        except FileNotFoundError:
             # Se non trovato in HKCU, prova HKEY_LOCAL_MACHINE (installazione per tutti gli utenti)
             # Nota: richiede accesso a HKLM, potrebbe non funzionare per utenti standard
            try:
                hkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                steam_install_path = winreg.QueryValueEx(hkey, "SteamPath")[0]
                winreg.CloseKey(hkey)
                print(f"Trovata installazione Steam (HKLM): {steam_install_path}")
                return steam_install_path.replace('/', '\\') # Normalizza slash
            except FileNotFoundError:
                 print("ERRORE: Impossibile trovare la chiave di registro di Steam (HKCU o HKLM). Steam è installato?")
                 return None
        except Exception as e:
             print(f"Errore durante la lettura del registro per Steam: {e}")
             return None

    except ImportError:
        print("ERRORE: Modulo 'winreg' non trovato. Questo script richiede Windows per rilevare Steam.")
        return None
    except Exception as e:
        print(f"Errore imprevisto durante la ricerca di Steam: {e}")
        return None

def parse_vdf(file_path):
    """Legge e decodifica un file VDF."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return vdf.load(f)
    except FileNotFoundError:
        # print(f"File VDF non trovato: {file_path}") # Troppo verboso
        return None
    except Exception as e:
        print(f"Errore durante la lettura/parsing di {file_path}: {e}")
        return None

def find_steam_libraries(steam_path):
    """Trova tutte le cartelle libreria di Steam."""
    global steam_libraries
    if steam_libraries:
        return steam_libraries

    if not steam_path:
        return []

    libraries = [os.path.join(steam_path)] # La cartella principale è sempre una libreria potenziale
    vdf_path = os.path.join(steam_path, 'steamapps', 'libraryfolders.vdf')
    data = parse_vdf(vdf_path)

    if data and 'libraryfolders' in data: # Formato VDF aggiornato
        for key, value in data['libraryfolders'].items():
            if isinstance(value, dict) and 'path' in value:
                 lib_path = value['path'].replace('\\\\', '\\') # Correggi doppi backslash
                 if os.path.isdir(lib_path) and lib_path not in libraries:
                     libraries.append(lib_path)
    elif data: # Vecchio formato VDF (numeri come chiavi)
        for key in data:
            if key.isdigit() and 'path' in data[key]:
                 lib_path = data[key]['path'].replace('\\\\', '\\')
                 if os.path.isdir(lib_path) and lib_path not in libraries:
                     libraries.append(lib_path)

    print(f"Trovate {len(libraries)} librerie Steam.")
    steam_libraries = libraries
    return libraries

def find_installed_steam_games(library_paths):
    """Trova tutti i giochi Steam installati analizzando i file ACF."""
    global installed_steam_games
    if installed_steam_games is not None: # Controlla se già calcolato (anche se vuoto)
        return installed_steam_games

    games = {}
    if not library_paths:
        return {}

    print("Scansione librerie per giochi installati...")
    for lib_path in library_paths:
        steamapps_path = os.path.join(lib_path, 'steamapps')
        if not os.path.isdir(steamapps_path):
            continue

        try:
            for filename in os.listdir(steamapps_path):
                if filename.startswith('appmanifest_') and filename.endswith('.acf'):
                    acf_path = os.path.join(steamapps_path, filename)
                    data = parse_vdf(acf_path)
                    if data and 'AppState' in data:
                        app_state = data['AppState']
                        if 'appid' in app_state and 'name' in app_state and 'installdir' in app_state:
                            # Controlla se è installato (StateFlags 4 indica installato)
                            # A volte manca StateFlags, controlla almeno che installdir esista
                            is_installed = ('StateFlags' in app_state and app_state['StateFlags'] == '4') or \
                                           (os.path.isdir(os.path.join(steamapps_path, 'common', app_state['installdir'])))

                            if is_installed:
                                appid = app_state['appid']
                                name = app_state['name']
                                # Rimuovi simboli di marchio registrato ™ ® dal nome
                                name = name.replace('™', '').replace('®', '').strip()
                                installdir_relative = app_state['installdir']
                                installdir_absolute = os.path.join(steamapps_path, 'common', installdir_relative)

                                if appid not in games: # Aggiungi solo se non già trovato
                                     games[appid] = {'name': name, 'installdir': installdir_absolute}
                                     # print(f"  Trovato: {name} (AppID: {appid})") # Meno verboso
        except FileNotFoundError:
            print(f"  Attenzione: Impossibile accedere a {steamapps_path}")
        except Exception as e:
            print(f"  Errore durante la scansione di {steamapps_path}: {e}")

    print(f"Trovati {len(games)} giochi Steam installati.")
    installed_steam_games = games
    return games

def find_steam_userdata_info(steam_path):
    """Trova la cartella userdata e tenta di identificare lo SteamID3 dell'utente."""
    global steam_userdata_path, steam_id3
    if steam_userdata_path and steam_id3:
        return steam_userdata_path, steam_id3
    if not steam_path:
        return None, None

    userdata_base = os.path.join(steam_path, 'userdata')
    if not os.path.isdir(userdata_base):
        print("Cartella 'userdata' di Steam non trovata.")
        return None, None

    possible_ids = []
    last_modified_time = 0
    likely_id = None

    try:
        for entry in os.listdir(userdata_base):
            if entry.isdigit() and entry != '0': # ID sono numerici, escludi '0' (config generica)
                user_path = os.path.join(userdata_base, entry)
                if os.path.isdir(user_path):
                    possible_ids.append(entry)
                    # Tenta di trovare l'utente più recente controllando config/localconfig.vdf
                    local_config_path = os.path.join(user_path, 'config', 'localconfig.vdf')
                    if os.path.exists(local_config_path):
                         try:
                             mtime = os.path.getmtime(local_config_path)
                             if mtime > last_modified_time:
                                 last_modified_time = mtime
                                 likely_id = entry
                         except Exception:
                             pass # Ignora errori nel leggere la data
                    # Fallback: usa la data della cartella ID se localconfig non c'è
                    elif likely_id is None:
                        try:
                             mtime = os.path.getmtime(user_path)
                             if mtime > last_modified_time:
                                 last_modified_time = mtime
                                 likely_id = entry
                        except Exception:
                            pass


    except Exception as e:
        print(f"Errore durante la scansione di 'userdata': {e}")
        return userdata_base, None # Restituisci almeno il percorso base

    if len(possible_ids) == 1:
        steam_userdata_path = userdata_base
        steam_id3 = possible_ids[0]
        print(f"Trovato un singolo SteamID3: {steam_id3}")
    elif len(possible_ids) > 1:
        print("\nTrovati multipli SteamID3 in 'userdata':")
        for i, uid in enumerate(possible_ids):
            print(f"{i+1}. {uid} {'(Probabile ultimo utente)' if uid == likely_id else ''}")

        while True:
            try:
                choice = input(f"Quale ID utente vuoi usare? (1-{len(possible_ids)}) (Premi Invio per usare il probabile [{possible_ids.index(likely_id)+1 if likely_id else 'N/A'}]): ")
                if not choice and likely_id:
                     chosen_id = likely_id
                     break
                elif not choice and not likely_id:
                     print("Nessun utente probabile trovato. Per favore scegli un numero.")
                     continue

                choice_num = int(choice)
                if 1 <= choice_num <= len(possible_ids):
                    chosen_id = possible_ids[choice_num - 1]
                    break
                else:
                    print("Scelta non valida.")
            except ValueError:
                 if choice: # Se l'utente ha scritto qualcosa non numerico
                    print("Inserisci un numero valido.")
            except IndexError: # Se likely_id non è in possible_ids (improbabile)
                 print("Errore interno nella selezione dell'utente probabile.")
                 likely_id = None # Resetta e chiedi di nuovo


        steam_userdata_path = userdata_base
        steam_id3 = chosen_id
        print(f"SteamID3 selezionato: {steam_id3}")
    else:
        print("Nessuno SteamID3 valido trovato in 'userdata'.")
        steam_userdata_path = userdata_base # Restituisci base path anche se ID non trovato
        steam_id3 = None

    return steam_userdata_path, steam_id3

def guess_save_path(appid, game_name, steam_userdata_path, steam_id3, game_install_dir):
    """Tenta di indovinare la cartella dei salvataggi per un gioco Steam."""
    guesses = []

    # 1. Steam Userdata (Cloud Saves) - La più probabile
    if steam_userdata_path and steam_id3 and appid:
        path = os.path.join(steam_userdata_path, steam_id3, appid, 'remote')
        if os.path.isdir(path):
            guesses.append(path)
            # A volte i salvataggi sono in una sottocartella di remote (es. 'SaveGames')
            try:
                 content = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
                 if len(content) == 1 and ('save' in content[0].lower() or 'profile' in content[0].lower()):
                      sub_path = os.path.join(path, content[0])
                      if sub_path not in guesses:
                          guesses.append(sub_path)
            except Exception: pass # Ignora errori di listing


    # 2. Cartelle Comuni Utente
    user_profile = os.path.expanduser('~') # Equivalente a %USERPROFILE%
    common_folders = [
        os.path.join(user_profile, 'Documents', 'My Games'),
        os.path.join(user_profile, 'Documents'),
        os.path.join(user_profile, 'Saved Games'),
        os.getenv('LOCALAPPDATA'), # %LOCALAPPDATA%
        os.getenv('APPDATA') # %APPDATA% (Roaming)
    ]

    # Pulisci nome gioco per usarlo nei path (rimuovi caratteri non validi per cartelle)
    safe_game_name = "".join(c for c in game_name if c.isalnum() or c in (' ', '_', '-')).strip()
    # Alcuni giochi usano varianti (es. con 'Games')
    game_name_variants = [safe_game_name, game_name] # Usa sia pulito che originale
    if ' ' in safe_game_name: # Prova anche senza spazi
        game_name_variants.append(safe_game_name.replace(' ', ''))
    game_name_variants = list(dict.fromkeys(game_name_variants)) # Rimuovi duplicati


    for base_folder in common_folders:
        if base_folder: # AppData potrebbe essere None se variabile non settata
            for name_variant in game_name_variants:
                path = os.path.join(base_folder, name_variant)
                if os.path.isdir(path) and path not in guesses:
                    guesses.append(path)
                # Alcuni giochi creano un'ulteriore sottocartella 'Saves', 'SaveGames', ecc.
                common_save_subdirs = ['Saves', 'Save', 'SaveGame', 'SaveGames', 'Saved']
                for subdir in common_save_subdirs:
                    sub_path = os.path.join(path, subdir)
                    if os.path.isdir(sub_path) and sub_path not in guesses:
                         guesses.append(sub_path)


    # 3. Dentro la cartella di installazione (meno comune, ma possibile)
    if game_install_dir and os.path.isdir(game_install_dir):
        common_install_subdirs = ['Save', 'Saves', 'Saved', 'SaveGame', 'SaveGames', 'UserData', 'Profile', 'Profiles']
        try:
            # Cerca direttamente sottocartelle comuni
            for entry in os.listdir(game_install_dir):
                if entry in common_install_subdirs:
                     path = os.path.join(game_install_dir, entry)
                     if os.path.isdir(path) and path not in guesses:
                          guesses.append(path)
            # Cerca anche una cartella con lo stesso nome del gioco dentro l'installazione
            install_sub_path = os.path.join(game_install_dir, safe_game_name)
            if os.path.isdir(install_sub_path) and install_sub_path not in guesses:
                 guesses.append(install_sub_path)

        except Exception as e:
            print(f"  Nota: errore durante scansione cartella installazione {game_install_dir}: {e}")

    # Rimuovi duplicati mantenendo l'ordine
    unique_guesses = []
    for g in guesses:
        norm_g = os.path.normpath(g) # Normalizza per confronto
        if norm_g not in [os.path.normpath(ug) for ug in unique_guesses]:
             unique_guesses.append(g)

    return unique_guesses


def steam_menu(profiles):
    """Menu per rilevare e gestire giochi Steam."""
    global installed_steam_games, steam_userdata_path, steam_id3 # Usa cache globale

    print("\n--- Gestione Giochi Steam ---")

    # Fasi di rilevamento (solo se non già fatto)
    if steam_install_path is None:
        get_steam_install_path()
        if steam_install_path is None:
            input("Impossibile procedere senza percorso Steam. Premi Invio...")
            return

    if steam_libraries is None:
        find_steam_libraries(steam_install_path)
        if not steam_libraries:
             input("Impossibile trovare librerie Steam valide. Premi Invio...")
             return

    if installed_steam_games is None:
        installed_steam_games = find_installed_steam_games(steam_libraries)
        if not installed_steam_games:
             input("Nessun gioco Steam installato trovato. Premi Invio...")
             return

    if steam_userdata_path is None or steam_id3 is None:
         # Cerca userdata solo se necessario (se non già trovato)
         find_steam_userdata_info(steam_install_path)
         # Non è un errore bloccante se userdata non viene trovato, si useranno altri metodi


    # Mostra lista giochi
    game_list = sorted(installed_steam_games.items(), key=lambda item: item[1]['name']) # Ordina per nome
    print("\nGiochi Steam installati trovati:")
    for i, (appid, game_data) in enumerate(game_list):
        print(f"{i + 1}. {game_data['name']} (AppID: {appid})")

    while True:
        try:
            choice = input(f"Scegli un gioco (1-{len(game_list)}) per configurare il profilo, o 0 per annullare: ")
            choice_num = int(choice)
            if choice_num == 0:
                return # Annulla
            if 1 <= choice_num <= len(game_list):
                selected_appid, selected_game_data = game_list[choice_num - 1]
                profile_name = selected_game_data['name'] # Usa il nome del gioco come nome profilo
                game_install_dir = selected_game_data['installdir']

                print(f"\nAnalisi per '{profile_name}' (AppID: {selected_appid})...")

                # Tenta di indovinare il percorso
                save_path_guesses = guess_save_path(selected_appid, profile_name, steam_userdata_path, steam_id3, game_install_dir)

                confirmed_path = None
                if not save_path_guesses:
                    print("ATTENZIONE: Impossibile trovare automaticamente la cartella dei salvataggi.")
                    confirmed_path = None # Forza la creazione manuale
                else:
                    print("Possibili percorsi trovati (il primo è il più probabile):")
                    for idx, p in enumerate(save_path_guesses):
                         print(f"  {idx+1}) {p}")

                    while True:
                         path_choice = input(f"Il percorso {save_path_guesses[0]} è corretto? (s=sì / n=no / 1-{len(save_path_guesses)}=usa un altro / m=manuale): ").lower()
                         if path_choice == 's' or path_choice == 'si' or path_choice == '': # Invio conferma il primo
                             confirmed_path = save_path_guesses[0]
                             break
                         elif path_choice == 'n':
                             confirmed_path = None # Forza inserimento manuale
                             break
                         elif path_choice == 'm':
                              confirmed_path = None # Forza inserimento manuale
                              break
                         else:
                             try:
                                 path_idx = int(path_choice)
                                 if 1 <= path_idx <= len(save_path_guesses):
                                     confirmed_path = save_path_guesses[path_idx - 1]
                                     break
                                 else:
                                     print("Numero non valido.")
                             except ValueError:
                                 print("Input non valido.")

                # Crea o aggiorna il profilo
                new_profile_name, final_save_path = create_profile(profiles, profile_name, confirmed_path, skip_save=True)
                # Ora salva tutti i profili
                save_profiles(profiles)

                # Vai direttamente al menu azioni per questo profilo
                print(f"\nProfilo '{new_profile_name}' pronto.")
                profile_menu(new_profile_name, final_save_path)
                # Dopo essere uscito da profile_menu, torna al menu principale (uscendo dal loop while True)
                return

            else:
                print("Scelta non valida.")
        except ValueError:
            print("Inserisci un numero valido.")
        except Exception as e:
            print(f"Errore durante la gestione del gioco Steam: {e}")
            input("Premi Invio per continuare...")
            return # Torna al menu principale in caso di errore grave

# --- Script Principale Modificato ---
if __name__ == "__main__":
    print("Avvio Gestione Salvataggi...")
    try:
         # Carica subito winreg e vdf per segnalare errori di import
         import winreg
         import vdf
    except ImportError as e:
         print(f"ERRORE DI IMPORTAZIONE: {e}")
         print("Assicurati di aver eseguito 'pip install vdf' e di essere su Windows.")
         input("Premi Invio per uscire.")
         exit(1)

    check_winrar() # Controlla WinRAR
    profiles_data = load_profiles()

    while True:
        print("\n===== Menu Gestione Salvataggi Giochi =====")
        print("1. Crea/Modifica Profilo Manuale")
        print("2. Seleziona Profilo Esistente")
        print("3. Gestisci Giochi Steam (Rilevamento Automatico)")
        print("0. Esci")

        main_choice = input("Scegli un'opzione: ")

        if main_choice == '1':
            # Chiama create_profile senza argomenti predefiniti
            create_profile(profiles_data)
            # Salva già dentro create_profile se non skip_save=True
        elif main_choice == '2':
            selected_name, selected_path = select_profile(profiles_data)
            if selected_name:
                profile_menu(selected_name, selected_path)
        elif main_choice == '3':
            steam_menu(profiles_data)
            # Ora profiles_data potrebbe essere stato aggiornato e salvato da steam_menu
        elif main_choice == '0':
            print("Uscita dal programma.")
            break
        else:
            print("Scelta non valida.")