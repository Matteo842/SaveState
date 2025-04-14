# -*- coding: utf-8 -*-
import os
import subprocess
import json
from datetime import datetime
import time
try:
    import winreg  # Per leggere il registro di Windows
except ImportError:
    print("ATTENZIONE: Modulo 'winreg' non trovato. Il rilevamento automatico di Steam funzionerà solo su Windows.")
    winreg = None # Imposta a None per controlli successivi
try:
    import vdf     # Per leggere i file VDF/ACF di Steam (installa con: pip install vdf)
except ImportError:
    print("ERRORE CRITICO: Libreria 'vdf' non trovata.")
    print("Esegui 'pip install vdf' nel prompt dei comandi/PowerShell per installarla.")
    vdf = None # Imposta a None per controlli successivi


# --- CONFIGURAZIONE (MODIFICA QUESTI VALORI!) ---

# Percorso COMPLETO dell'eseguibile rar.exe (usa 'r' prima delle virgolette)
WINRAR_PATH = r"C:\Program Files\WinRAR\rar.exe"

# Cartella PRINCIPALE dove verranno creati i backup
# Lo script creerà sottocartelle per ogni profilo qui dentro.
BACKUP_BASE_DIR = r"D:\GameSaveBackups"

# Nome del file JSON dove verranno salvate le informazioni dei profili
# Verrà creato nella stessa cartella dello script.
PROFILE_FILE = "game_save_profiles.json"

# Numero massimo di backup da mantenere per ciascun profilo (i più vecchi verranno eliminati)
MAX_BACKUPS = 3

# --- FINE CONFIGURAZIONE ---


# --- Database Percorsi Salvataggi Conosciuti (Puoi Espanderlo!) ---
# Mappa AppID di Steam a informazioni sul percorso dei salvataggi.
# Utile per giochi che non seguono pattern standard.
# Tipi ('type') possibili:
# 'steam_userdata': Relativo a userdata/<SteamID3>/<AppID>/ (es. path='remote')
# 'relative_to_appdata_roaming': Relativo a %APPDATA% (es. path='Publisher/Gioco')
# 'relative_to_appdata_local': Relativo a %LOCALAPPDATA%
# 'relative_to_appdata_locallow': Relativo a %USERPROFILE%/AppData/LocalLow
# 'relative_to_documents': Relativo alla cartella Documenti
# 'relative_to_my_games': Relativo a Documenti/My Games
# 'relative_to_saved_games': Relativo a %USERPROFILE%/Saved Games
# 'relative_to_install_dir': Relativo alla cartella di installazione del gioco
# 'absolute_path': Un percorso assoluto (usa con cautela)
KNOWN_SAVE_PATTERNS = {
    # AppID: {'type': '...', 'path': '...'}
    '275850': {'type': 'relative_to_appdata_roaming', 'path': 'HelloGames/NMS'}, # No Man's Sky
    '2324650': {'type': 'relative_to_appdata_locallow', 'path': 'Sonic Social/The Murder of Sonic The Hedgehog'}, # The Murder of Sonic The Hedgehog
    '548430': {'type': 'relative_to_install_dir', 'path': 'FSD/Saved'}, # Deep Rock Galactic
    # Esempio: Cyberpunk 2077 (salva in Saved Games)
    '1091500': {'type': 'relative_to_saved_games', 'path': 'CD Projekt Red/Cyberpunk 2077'},
    # Aggiungi qui altri giochi trovando il loro AppID e percorso...
}

# Variabili globali per caching dati Steam (opzionale, per performance)
steam_install_path = None
steam_libraries = None
installed_steam_games = None # Dizionario {appid: {'name': '...', 'installdir': '...'}}
steam_userdata_path = None
steam_id3 = None


# --- FUNZIONI HELPER E CORE ---

def check_winrar():
    """Verifica se il percorso di WinRAR è valido."""
    if not os.path.exists(WINRAR_PATH):
        print("\nERRORE: Impossibile trovare WinRAR.exe nel percorso specificato:")
        print(f"'{WINRAR_PATH}'")
        print("Per favore, modifica la variabile 'WINRAR_PATH' nello script.")
        input("Premi Invio per uscire.")
        exit(1)
    print(f"WinRAR trovato: {WINRAR_PATH}") # Conferma all'avvio

def load_profiles():
    """Carica i profili dal file JSON."""
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"\nATTENZIONE: Il file dei profili '{PROFILE_FILE}' è corrotto o vuoto.")
            print("Verrà trattato come un file nuovo.")
            return {}
        except Exception as e:
            print(f"\nERRORE imprevisto durante il caricamento dei profili: {e}")
            return {}
    return {}

def save_profiles(profiles):
    """Salva i profili nel file JSON."""
    try:
        with open(PROFILE_FILE, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, indent=4, ensure_ascii=False) # ensure_ascii=False per nomi non-inglesi
    except Exception as e:
        print(f"\nERRORE durante il salvataggio dei profili in '{PROFILE_FILE}': {e}")

def create_profile(profiles, profile_name=None, save_folder_path=None, skip_save=False):
    """Crea o aggiorna un profilo, opzionalmente con valori pre-forniti."""
    print("\n--- Creazione/Modifica Profilo ---")
    original_name = profile_name # Salva nome originale se fornito

    if profile_name is None:
        while True:
            profile_name_input = input("Inserisci un nome univoco per il profilo (es. Cyberpunk2077): ")
            if not profile_name_input:
                print("Il nome del profilo non può essere vuoto.")
            elif profile_name_input in profiles:
                overwrite = input(f"Un profilo con il nome '{profile_name_input}' esiste già. Vuoi sovrascriverlo? (s/n): ").lower()
                if overwrite == 's':
                    profile_name = profile_name_input
                    break
                # Altrimenti continua a chiedere un nome nuovo
            else:
                profile_name = profile_name_input
                break
    else:
        print(f"Nome profilo: {profile_name}")
        if profile_name in profiles:
             print("(Profilo esistente, verrà aggiornato)")

    if save_folder_path is None or not os.path.isdir(save_folder_path):
        if save_folder_path and not os.path.isdir(save_folder_path): # Se era fornito ma non valido
             print("\nATTENZIONE: Il percorso suggerito non è valido o non trovato:")
             print(f"'{save_folder_path}'")
        prompt_message = f"Inserisci il percorso COMPLETO della cartella dei salvataggi per '{profile_name}':\n> "
        while True:
            save_folder_path_input = input(prompt_message).strip('"') # Rimuovi eventuali virgolette incollate
            if not save_folder_path_input:
                 print("Il percorso non può essere vuoto.")
                 continue
            # Normalizza il percorso per consistenza
            save_folder_path_input = os.path.normpath(save_folder_path_input)
            if not os.path.isdir(save_folder_path_input):
                print("ERRORE: Il percorso inserito non è una cartella valida o accessibile.")
                print(f"'{save_folder_path_input}'")
            else:
                save_folder_path = save_folder_path_input
                break
    else:
         # Normalizza anche il percorso suggerito e valido
         save_folder_path = os.path.normpath(save_folder_path)
         print(f"Percorso salvataggi: {save_folder_path}")

    # Se il nome è stato cambiato manualmente, rimuovi la vecchia voce (se diversa)
    if original_name and original_name != profile_name and original_name in profiles:
         del profiles[original_name]
         print(f"(Rimosso vecchio profilo '{original_name}' a causa del cambio nome)")

    profiles[profile_name] = save_folder_path
    if not skip_save:
        save_profiles(profiles)
        print(f"Profilo '{profile_name}' salvato.")
    else:
        print(f"Profilo '{profile_name}' configurato (non ancora salvato su file).")

    return profile_name, save_folder_path # Restituisce i dati usati/confermati


def select_profile(profiles):
    """Permette all'utente di selezionare un profilo esistente."""
    if not profiles:
        print("\nNessun profilo esistente. Creane uno prima (opzione 1 o 3).")
        time.sleep(2)
        return None, None

    print("\n--- Seleziona Profilo Esistente ---")
    # Ordina i profili per nome per coerenza
    profile_list = sorted(profiles.keys())
    for i, name in enumerate(profile_list):
        path_display = profiles[name]
        if len(path_display) > 60:
            path_display = path_display[:25] + "..." + path_display[-30:]
        print(f"{i + 1}. {name} ({path_display})")

    while True:
        try:
            choice = input(f"Scegli un profilo (1-{len(profile_list)}) o 0 per annullare: ")
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
    """Elimina i backup più vecchi se superano il limite MAX_BACKUPS."""
    global MAX_BACKUPS
    try:
        if not os.path.isdir(profile_backup_dir):
             # print(f"Cartella backup {profile_backup_dir} non trovata, niente da gestire.")
             return # Non è un errore se non ci sono ancora backup

        print(f"\nControllo backup esistenti in: {profile_backup_dir}")
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".rar")]

        if not backup_files:
            print("Nessun file di backup trovato.")
            return

        # Ordina i file per data di modifica (dal più vecchio al più recente)
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)))

        num_backups = len(backup_files)
        print(f"Trovati {num_backups} backup. Limite massimo: {MAX_BACKUPS}.")

        if num_backups > MAX_BACKUPS:
            num_to_delete = num_backups - MAX_BACKUPS
            print(f"Eliminazione dei {num_to_delete} backup più vecchi...")
            deleted_count = 0
            for i in range(num_to_delete):
                file_to_delete = os.path.join(profile_backup_dir, backup_files[i])
                try:
                    print(f"  Elimino: {backup_files[i]}")
                    os.remove(file_to_delete)
                    deleted_count += 1
                except Exception as e:
                    print(f"  ERRORE durante l'eliminazione di {backup_files[i]}: {e}")
            print(f"Eliminati {deleted_count} backup.")
        else:
             print("Nessun backup vecchio da eliminare.")

    except Exception as e:
        print(f"\nERRORE durante la gestione dei backup obsoleti: {e}")


def perform_backup(profile_name, save_folder_path):
    """Esegue il backup per il profilo specificato usando WinRAR."""
    global WINRAR_PATH, BACKUP_BASE_DIR
    print(f"\n--- Backup per '{profile_name}' ---")

    # Verifica preliminare se la cartella sorgente esiste ed è accessibile
    save_folder_path = os.path.normpath(save_folder_path) # Assicura percorso normalizzato
    if not os.path.isdir(save_folder_path):
        print("ERRORE CRITICO: La cartella dei salvataggi specificata non esiste o non è accessibile:")
        print(f"'{save_folder_path}'")
        print("Impossibile procedere con il backup.")
        input("Premi Invio per continuare...")
        return

    profile_backup_dir = os.path.join(BACKUP_BASE_DIR, profile_name)
    try:
        os.makedirs(profile_backup_dir, exist_ok=True) # Crea cartella backup profilo
    except Exception as e:
         print("ERRORE: Impossibile creare la cartella di destinazione del backup:")
         print(f"'{profile_backup_dir}'")
         print(f"Dettagli: {e}")
         print("Backup annullato.")
         input("Premi Invio per continuare...")
         return


    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Pulisci nome profilo per nome file (rimuovi caratteri problematici)
    safe_profile_name = "".join(c for c in profile_name if c.isalnum() or c in (' ', '_', '-')).strip()
    archive_name = f"Backup_{safe_profile_name}_{timestamp}.rar"
    archive_path = os.path.join(profile_backup_dir, archive_name)

    print(f"Cartella salvataggi da backuppare: {save_folder_path}")
    print(f"Archivio di destinazione: {archive_path}")

    # Passa solo il percorso della cartella sorgente a WinRAR, -r farà il resto.
    source_path_for_rar = save_folder_path

    # Costruisci il comando per WinRAR
    command = [
        WINRAR_PATH,
        "a",        # Comando: aggiungi ad archivio
        "-r",       # Ricorsivo (Include sottocartelle e file)
        "-ep1",     # Escludi il percorso base della cartella sorgente dall'archivio
        "-o+",      # Sovrascrivi file esistenti nell'archivio senza chiedere
        # '-m5',    # Opzionale: usa massima compressione (può essere lento)
        # '-mt2',   # Opzionale: usa 2 thread (modifica se necessario)
        archive_path, # Percorso completo dell'archivio di destinazione
        source_path_for_rar # Percorso completo della cartella sorgente
    ]

    try:
        print("\nEsecuzione comando WinRAR:")
    # Stampa il comando in modo leggibile per debug

    # !!! VECCHIA RIGA PROBLEMATICA !!!
    # print(f"  \"{'\" \"'.join(command)}\"")

    # --- NUOVO CODICE ---
    # 1. Quota ogni parte del comando individualmente
        quoted_command_parts = [f'"{part}"' for part in command]
    # 2. Unisci le parti quotate con uno spazio
        command_str_representation = " ".join(quoted_command_parts)
    # 3. Stampa la rappresentazione costruita (f-string semplice ora)
        print(f"  {command_str_representation}")
    # --- FINE NUOVO CODICE ---

        print("Avvio di WinRAR... (potrebbe richiedere tempo)")

    # Esegui WinRAR... (resto del blocco try invariato)
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=subprocess.CREATE_NO_WINDOW)
# ... resto del blocco try/except ...
# ... resto del blocco try/except ...

        # Mostra l'output di WinRAR (utile per vedere cosa ha fatto)
        print("\n--- Output WinRAR ---")
        print(result.stdout if result.stdout.strip() else "(Nessun output standard significativo)")
        if result.stderr.strip():
             print("--- Output Errori WinRAR ---") # Anche se codice 0, potrebbe esserci warning
             print(result.stderr)
        print("---------------------")
        print("\nBackup completato con successo!")

        # Gestisci i backup vecchi solo DOPO un backup riuscito
        manage_backups(profile_backup_dir)

    except subprocess.CalledProcessError as e:
        # Errore specifico di WinRAR (codice di ritorno non 0)
        print(f"\nERRORE: WinRAR ha terminato con codice di errore {e.returncode}.")
        print(f"Comando fallito: {' '.join(e.cmd)}")
        print("\n--- Output Errori WinRAR (stderr) ---")
        print(e.stderr if e.stderr.strip() else "(Nessuno)")
        print("--- Output Standard WinRAR (stdout) ---")
        print(e.stdout if e.stdout.strip() else "(Nessuno)")
        print("------------------------------------")
        print("Possibili cause:")
        print(" - Codice 1: Warning non fatale (spesso OK)")
        print(" - Codice 2: Errore Fatale")
        print(" - Codice 10 (No files found): La cartella sorgente è vuota o il percorso è errato?")
        print(" - Altri codici: Consultare la documentazione di WinRAR.")

        # Se il backup è fallito, specialmente con "No files", elimina l'archivio vuoto/parziale
        if os.path.exists(archive_path):
             try:
                 file_size = os.path.getsize(archive_path)
                 print(f"Tentativo di rimozione archivio fallito/parziale: {archive_name} (Dim: {file_size} bytes)")
                 os.remove(archive_path)
             except Exception as rem_e:
                 print(f"  ATTENZIONE: Impossibile rimuovere l'archivio: {rem_e}")

    except FileNotFoundError:
         # Errore se WINRAR_PATH non è corretto
         print(f"\nERRORE CRITICO: Impossibile eseguire il comando. '{WINRAR_PATH}' non trovato.")
         print("Controlla la variabile 'WINRAR_PATH' all'inizio dello script.")
    except Exception as e:
         # Altri errori imprevisti (es. permessi, disco pieno)
         print(f"\nSi è verificato un errore imprevisto durante il backup: {e}")

    input("\nPremi Invio per continuare...")


def perform_restore(profile_name, save_folder_path):
    """Ripristina i salvataggi da un backup selezionato usando WinRAR."""
    global WINRAR_PATH, BACKUP_BASE_DIR
    print(f"\n--- Ripristino per '{profile_name}' ---")
    profile_backup_dir = os.path.join(BACKUP_BASE_DIR, profile_name)
    save_folder_path = os.path.normpath(save_folder_path) # Normalizza

    if not os.path.isdir(profile_backup_dir):
        print(f"ERRORE: Nessuna cartella di backup trovata per '{profile_name}'.")
        print(f"Percorso cercato: '{profile_backup_dir}'")
        input("Premi Invio per continuare...")
        return

    try:
        # Trova e ordina i backup disponibili (dal più recente)
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".rar")] # Meno restrittivo sul nome profilo nel file
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)), reverse=True)

        if not backup_files:
            print("Nessun file di backup (.rar) trovato per questo profilo.")
            input("Premi Invio per continuare...")
            return

        print("\nBackup disponibili per il ripristino (dal più recente):")
        for i, fname in enumerate(backup_files):
            file_path = os.path.join(profile_backup_dir, fname)
            date_str = ""
            try:
                mtime = os.path.getmtime(file_path)
                dt_object = datetime.fromtimestamp(mtime)
                date_str = dt_object.strftime("%Y-%m-%d %H:%M:%S")
            except Exception: pass
            print(f"{i + 1}. {fname} ({date_str})")

        # Selezione del backup da ripristinare
        selected_archive_path = None
        while True:
            try:
                choice = input(f"Scegli il numero del backup da ripristinare (1-{len(backup_files)}), o 0 per annullare: ")
                choice_num = int(choice)
                if choice_num == 0:
                    print("Ripristino annullato.")
                    input("Premi Invio per continuare...")
                    return
                if 1 <= choice_num <= len(backup_files):
                    selected_backup_file = backup_files[choice_num - 1]
                    selected_archive_path = os.path.join(profile_backup_dir, selected_backup_file)
                    break
                else:
                    print("Scelta non valida.")
            except ValueError:
                print("Inserisci un numero valido.")

        # Conferma finale prima di sovrascrivere
        print("\n!!! ATTENZIONE !!!")
        print("Stai per ripristinare il backup:")
        print(f"  '{selected_backup_file}'")
        print("Nella cartella:")
        print(f"  '{save_folder_path}'")
        print("\nQuesto processo SOVRASCRIVERÀ qualsiasi file con lo stesso nome")
        print("presente attualmente nella cartella di destinazione.")
        print("\nCONSIGLIO: Se non sei sicuro, fai prima un backup dei file correnti!")

        confirm = input("Sei ASSOLUTAMENTE sicuro di voler procedere? (sì/no): ").lower()

        if confirm == 'sì' or confirm == 'si' or confirm == 's':
            # Assicurati che la cartella di destinazione esista
            try:
                 os.makedirs(save_folder_path, exist_ok=True)
            except Exception as e:
                 print("\nERRORE: Impossibile creare/accedere alla cartella di destinazione:")
                 print(f"'{save_folder_path}'")
                 print(f"Dettagli: {e}")
                 print("Ripristino annullato.")
                 input("Premi Invio per continuare...")
                 return

            print(f"\nRipristino da '{selected_backup_file}' a '{save_folder_path}'...")

            # Comando WinRAR per estrarre ('x' estrae con percorsi completi)
            # '-o+' sovrascrive i file esistenti senza chiedere
            command = [
                WINRAR_PATH,
                "x",               # Comando: estrai con percorsi
                "-o+",             # Sovrascrivi esistenti senza chiedere
                selected_archive_path, # Archivio sorgente da estrarre
                save_folder_path   # Cartella di destinazione (deve esistere)
            ]
            # Aggiungere '*' alla fine della destinazione forza l'estrazione *dentro* la cartella
            # command.append(save_folder_path + os.sep) # Alternativa per chiarezza? Testare.

            try:
                # !!! VECCHIA RIGA PROBLEMATICA !!!
                # print(f"Esecuzione comando: \"{'\" \"'.join(command)}\"")

                # --- NUOVO CODICE ---
                # 1. Quota ogni parte del comando individualmente
                quoted_command_parts = [f'"{part}"' for part in command]
                # 2. Unisci le parti quotate con uno spazio
                command_str_representation = " ".join(quoted_command_parts)
                # 3. Stampa la rappresentazione costruita (f-string semplice ora)
                print(f"Esecuzione comando: {command_str_representation}")
                # --- FINE NUOVO CODICE ---

                print("Avvio di WinRAR per l'estrazione...")
                result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=subprocess.CREATE_NO_WINDOW)
            # ... resto del blocco try/except ...

                print("\n--- Output WinRAR ---")
                print(result.stdout if result.stdout.strip() else "(Nessuno)")
                if result.stderr.strip():
                     print("--- Output Errori WinRAR ---")
                     print(result.stderr)
                print("---------------------")
                print("\nRipristino completato con successo!")

            except subprocess.CalledProcessError as e:
                print(f"\nERRORE: WinRAR ha terminato con codice di errore {e.returncode}.")
                print(f"Comando fallito: {' '.join(e.cmd)}")
                print("\n--- Output Errori WinRAR (stderr) ---")
                print(e.stderr if e.stderr.strip() else "(Nessuno)")
                print("--- Output Standard WinRAR (stdout) ---")
                print(e.stdout if e.stdout.strip() else "(Nessuno)")
                print("------------------------------------")
                print("Ripristino POTREBBE essere incompleto.")
            except FileNotFoundError:
                 print(f"\nERRORE CRITICO: Impossibile eseguire il comando. '{WINRAR_PATH}' non trovato.")
            except Exception as e:
                print(f"\nSi è verificato un errore imprevisto durante il ripristino: {e}")
        else:
            print("\nRipristino annullato dall'utente.")

    except Exception as e:
        print(f"\nERRORE durante la preparazione del ripristino: {e}")

    input("\nPremi Invio per continuare...")


def profile_menu(profile_name, save_folder_path):
    """Menu delle azioni per un profilo selezionato."""
    while True:
        print(f"\n--- Profilo Attivo: {profile_name} ---")
        path_display = save_folder_path
        if len(path_display) > 70:
             path_display = path_display[:30] + "..." + path_display[-35:]
        print(f"Cartella salvataggi: {path_display}")
        print("\nAzioni disponibili:")
        print("  1. Effettua Backup Ora")
        print("  2. Ripristina da un Backup Esistente")
        print("  0. Torna al Menu Principale")

        choice = input("Scegli un'azione: ")

        if choice == '1':
            perform_backup(profile_name, save_folder_path)
        elif choice == '2':
            perform_restore(profile_name, save_folder_path)
        elif choice == '0':
            print(f"Uscita dal menu del profilo '{profile_name}'.")
            break
        else:
            print("Scelta non valida. Riprova.")


# --- FUNZIONI SPECIFICHE PER STEAM ---

def get_steam_install_path():
    """Trova il percorso di installazione di Steam dal registro di Windows."""
    global steam_install_path
    if steam_install_path: # Usa cache se disponibile
        return steam_install_path

    if winreg is None: # Se l'import è fallito
        print("Rilevamento automatico Steam non possibile (modulo 'winreg' non caricato).")
        return None

    try:
        key_path = r"Software\Valve\Steam"
        potential_hives = [(winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")]

        for hive, hive_name in potential_hives:
            try:
                hkey = winreg.OpenKey(hive, key_path)
                path_value, _ = winreg.QueryValueEx(hkey, "SteamPath")
                winreg.CloseKey(hkey)
                if path_value and os.path.isdir(path_value.replace('/', '\\')): # Verifica esistenza
                     steam_install_path = os.path.normpath(path_value.replace('/', '\\'))
                     print(f"Trovata installazione Steam ({hive_name}): {steam_install_path}")
                     return steam_install_path
            except FileNotFoundError:
                continue # Chiave non trovata in questo hive, prova il prossimo
            except OSError as e: # Es. accesso negato a HKLM
                 print(f"Nota: impossibile accedere a {hive_name}\\{key_path} ({e}).")
                 continue
            except Exception as e:
                 print(f"Errore durante lettura registro ({hive_name}): {e}")
                 continue

        print("\nERRORE: Impossibile trovare un'installazione valida di Steam nel registro.")
        print("Steam è installato correttamente?")
        return None

    except Exception as e:
        print(f"\nERRORE imprevisto durante la ricerca di Steam: {e}")
        return None


def parse_vdf(file_path):
    """Legge e decodifica un file VDF usando la libreria vdf."""
    if vdf is None: # Se l'import è fallito
         print("ERRORE: Libreria 'vdf' non caricata, impossibile leggere file Steam.")
         return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Usiamo vdf.loads per gestire potenziali errori meglio di vdf.load
            content = f.read()
            # Aggiungi workaround per potenziali commenti non standard o errori comuni
            content = '\n'.join(line for line in content.splitlines() if not line.strip().startswith('//'))
            return vdf.loads(content, mapper=dict) # Usa dict standard
    except FileNotFoundError:
        return None # Non trovato è normale durante la scansione
    except Exception as e:
        # Non stampare errori per ogni file ACF/VDF mancante, solo per quelli critici
        if 'libraryfolders.vdf' in file_path or 'loginusers.vdf' in file_path:
             print(f"\nERRORE durante la lettura/parsing del file VDF '{os.path.basename(file_path)}':")
             print(f"Dettagli: {e}")
        # else: print(f"Debug: Errore parsing {os.path.basename(file_path)}: {e}") # Verboso
        return None


def find_steam_libraries(steam_path):
    """Trova tutte le cartelle libreria di Steam leggendo libraryfolders.vdf."""
    global steam_libraries
    if steam_libraries is not None: # Cache (può essere lista vuota)
        return steam_libraries

    libs = []
    if not steam_path or not os.path.isdir(steam_path):
        steam_libraries = []
        return libs

    # La cartella principale di Steam è sempre implicitamente una libreria
    main_lib_path = os.path.normpath(steam_path)
    if main_lib_path not in libs:
         libs.append(main_lib_path)

    # Leggi libraryfolders.vdf per trovare librerie aggiuntive
    vdf_path = os.path.join(steam_path, 'steamapps', 'libraryfolders.vdf')
    print(f"\nLettura file librerie Steam: {vdf_path}")
    data = parse_vdf(vdf_path)

    added_libs = 0
    if data:
        # Formato VDF può variare leggermente
        lib_folders_data = data.get('libraryfolders', data) # Prova entrambi i possibili top-level key

        if isinstance(lib_folders_data, dict):
            for key, value in lib_folders_data.items():
                 # Le chiavi sono spesso numeri ("0", "1", ...) o a volte 'contentstatsid'
                 if key.isdigit() or isinstance(value, dict):
                     lib_info = value if isinstance(value, dict) else lib_folders_data.get(key)
                     if isinstance(lib_info, dict) and 'path' in lib_info:
                         lib_path_raw = lib_info['path']
                         # Pulisci e normalizza il percorso
                         lib_path = os.path.normpath(lib_path_raw.replace('\\\\', '\\'))
                         if os.path.isdir(lib_path): # Verifica esistenza
                             if lib_path not in libs:
                                 libs.append(lib_path)
                                 added_libs += 1
                         else:
                              print(f"  Attenzione: Percorso libreria '{lib_path}' non trovato/accessibile.")

    print(f"Trovate {len(libs)} librerie Steam totali ({added_libs} aggiuntive da VDF).")
    steam_libraries = libs
    return libs


def find_installed_steam_games(library_paths):
    """Trova i giochi Steam installati analizzando i file appmanifest_*.acf."""
    global installed_steam_games
    if installed_steam_games is not None: # Cache
        return installed_steam_games

    games = {}
    if not library_paths:
        installed_steam_games = {}
        return games

    print("\nScansione librerie Steam per giochi installati...")
    total_acf_found = 0
    total_installed_games = 0

    for lib_path in library_paths:
        steamapps_path = os.path.join(lib_path, 'steamapps')
        if not os.path.isdir(steamapps_path):
            print(f"  Attenzione: Cartella 'steamapps' non trovata in '{lib_path}'.")
            continue

        # print(f"  Scansione in: {steamapps_path}") # Verboso
        try:
            files_in_steamapps = os.listdir(steamapps_path)
            acf_files = [f for f in files_in_steamapps if f.startswith('appmanifest_') and f.endswith('.acf')]
            total_acf_found += len(acf_files)

            for filename in acf_files:
                acf_path = os.path.join(steamapps_path, filename)
                data = parse_vdf(acf_path)

                if data and 'AppState' in data:
                    app_state = data['AppState']
                    # Verifica campi essenziali
                    if all(k in app_state for k in ['appid', 'name', 'installdir']):
                        appid = app_state['appid']
                        name = app_state.get('name', f"Gioco Sconosciuto {appid}").strip()
                        installdir_relative = app_state['installdir']
                        installdir_absolute = os.path.normpath(os.path.join(steamapps_path, 'common', installdir_relative))

                        # Verifica se è realmente installato
                        # Stato 4 = Installato; Altri stati indicano aggiornamento, preallocazione etc.
                        # Aggiungi controllo esistenza cartella come fallback robusto
                        is_installed = (app_state.get('StateFlags') == '4') or \
                                       (os.path.isdir(installdir_absolute))

                        if is_installed and appid not in games:
                            # Rimuovi simboli TM/R dal nome per pulizia
                            name = name.replace('™', '').replace('®', '').strip()
                            games[appid] = {'name': name, 'installdir': installdir_absolute}
                            total_installed_games += 1
                            # print(f"    + Trovato: {name} (AppID: {appid})") # Verboso

        except FileNotFoundError:
            print(f"  ERRORE: Impossibile accedere a '{steamapps_path}' durante la scansione.")
        except Exception as e:
            print(f"  ERRORE durante la scansione di '{steamapps_path}': {e}")

    print(f"Scansione completata. Trovati {total_installed_games} giochi installati (da {total_acf_found} file manifest).")
    installed_steam_games = games
    return games


def find_steam_userdata_info(steam_path):
    """Trova la cartella userdata e identifica/seleziona lo SteamID3 dell'utente attivo."""
    global steam_userdata_path, steam_id3
    if steam_userdata_path and steam_id3: # Cache
        return steam_userdata_path, steam_id3
    if not steam_path:
        return None, None

    userdata_base = os.path.join(steam_path, 'userdata')
    if not os.path.isdir(userdata_base):
        print("\nCartella 'userdata' di Steam non trovata. Impossibile cercare salvataggi Cloud.")
        steam_userdata_path = None # Assicura sia None se non trovata
        steam_id3 = None
        return None, None

    possible_ids = []
    last_modified_time = 0
    likely_id = None # L'ID più probabile basato sulla modifica

    print(f"\nRicerca ID Utente Steam in: {userdata_base}")
    try:
        for entry in os.listdir(userdata_base):
            user_path = os.path.join(userdata_base, entry)
            if entry.isdigit() and entry != '0' and os.path.isdir(user_path): # ID sono numerici, non '0'
                possible_ids.append(entry)
                current_mtime = 0
                # Cerca la data più recente basandosi su file/cartelle chiave
                check_paths = [
                    os.path.join(user_path, 'config', 'localconfig.vdf'),
                    os.path.join(user_path, 'config', 'shortcuts.vdf'),
                    user_path # Data della cartella ID come fallback
                ]
                for check_path in check_paths:
                     try:
                         if os.path.exists(check_path):
                             current_mtime = max(current_mtime, os.path.getmtime(check_path))
                     except Exception: pass # Ignora errori lettura data

                if current_mtime > last_modified_time:
                     last_modified_time = current_mtime
                     likely_id = entry

    except Exception as e:
        print(f"ERRORE durante la scansione di 'userdata': {e}")
        # Nonostante l'errore, proviamo a procedere con gli ID trovati finora
        # return userdata_base, None # O forse meglio uscire?

    # Selezione dell'ID
    chosen_id = None
    if len(possible_ids) == 0:
        print("Nessun ID utente (SteamID3) valido trovato in 'userdata'.")
        steam_userdata_path = userdata_base
        steam_id3 = None
    elif len(possible_ids) == 1:
        chosen_id = possible_ids[0]
        print(f"Trovato un singolo ID utente Steam (SteamID3): {chosen_id}")
    else: # Multipli ID trovati
        print("\nATTENZIONE: Trovati multipli ID utente Steam (formato SteamID3).")
        print("Questi ID NON corrispondono ai profili web (che usano SteamID64).")
        print("Seleziona l'ID associato all'account con cui giochi di solito:")

        id_options = {}
        for i, uid in enumerate(possible_ids):
            display_text = f"{i+1}. {uid}"
            if uid == likely_id:
                 display_text += " (Probabilmente Recente)"
            # Aggiungi info data modifica
            user_folder_path = os.path.join(userdata_base, uid)
            try:
                 mtime = os.path.getmtime(user_folder_path)
                 display_text += f" (Mod: {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')})"
            except Exception: pass
            print(display_text)
            id_options[str(i+1)] = uid # Mappa scelta a ID

        likely_choice = None
        if likely_id:
             try:
                 # Trova il numero corrispondente all'ID probabile
                 likely_choice = list(id_options.keys())[list(id_options.values()).index(likely_id)]
             except ValueError: likely_choice = None # Non trovato nella lista? Strano.


        while True:
            prompt = f"Quale ID usare? (1-{len(possible_ids)})"
            if likely_choice:
                 prompt += f" [Invio = usa {likely_choice}]: "
            else:
                 prompt += ": "

            choice = input(prompt)
            if not choice and likely_choice: # Utente preme Invio e c'è un suggerimento
                 chosen_id = id_options[likely_choice]
                 print(f"Scelto l'ID probabile: {chosen_id}")
                 break
            elif choice in id_options: # Utente ha inserito un numero valido
                 chosen_id = id_options[choice]
                 print(f"Scelto l'ID: {chosen_id}")
                 break
            else:
                 print("Scelta non valida. Inserisci il numero corrispondente all'ID.")

    steam_userdata_path = userdata_base
    steam_id3 = chosen_id
    if steam_id3:
         print("Nota: Questo SteamID3 è usato per cercare salvataggi nella cartella 'userdata'.")
         print("      Molti giochi, tuttavia, salvano i loro dati altrove.")

    return steam_userdata_path, steam_id3


def get_known_path(appid, game_install_dir, steam_userdata_path, steam_id3):
    """Costruisce il percorso basato sul database KNOWN_SAVE_PATTERNS, se esiste."""
    global KNOWN_SAVE_PATTERNS
    if appid not in KNOWN_SAVE_PATTERNS:
        return None # Non nel nostro DB

    pattern = KNOWN_SAVE_PATTERNS[appid]
    pattern_type = pattern.get('type')
    relative_path = pattern.get('path') # Può essere None se la base stessa è il path
    base_path = None
    full_path = None

    user_profile = os.path.expanduser('~') # Cache?

    # Determina il percorso base a seconda del tipo
    try:
        if pattern_type == 'steam_userdata':
            if steam_userdata_path and steam_id3:
                base_path = os.path.join(steam_userdata_path, steam_id3, appid)
        elif pattern_type == 'relative_to_appdata_roaming':
            base_path = os.getenv('APPDATA')
        elif pattern_type == 'relative_to_appdata_local':
            base_path = os.getenv('LOCALAPPDATA')
        elif pattern_type == 'relative_to_appdata_locallow':
            base_path = os.path.join(user_profile, 'AppData', 'LocalLow')
        elif pattern_type == 'relative_to_documents':
            base_path = os.path.join(user_profile, 'Documents')
        elif pattern_type == 'relative_to_my_games':
            base_path = os.path.join(user_profile, 'Documents', 'My Games')
        elif pattern_type == 'relative_to_saved_games':
            base_path = os.path.join(user_profile, 'Saved Games')
        elif pattern_type == 'relative_to_install_dir':
            base_path = game_install_dir
        elif pattern_type == 'absolute_path':
            full_path = relative_path # 'path' contiene il percorso assoluto
        else:
            print(f"Attenzione DB: tipo pattern non riconosciuto '{pattern_type}' per AppID {appid}")
            return None

        # Costruisci il percorso completo se non è assoluto
        if full_path is None:
            if not base_path or not os.path.isdir(base_path):
                 # print(f"Debug DB: Base path '{base_path}' non trovato per AppID {appid}.")
                 return None # Base non valida
            if relative_path: # Se c'è un path relativo da aggiungere
                 full_path = os.path.join(base_path, relative_path)
            else: # Se il path relativo è None/vuoto, la base è il percorso finale
                 full_path = base_path

        # Verifica finale esistenza e normalizzazione
        if full_path:
            full_path = os.path.normpath(full_path)
            if os.path.isdir(full_path):
                print(f"  -> Trovato percorso valido dal database interno ({pattern_type}):")
                print(f"     '{full_path}'")
                return full_path
            else:
                 # print(f"Debug DB: Percorso costruito '{full_path}' non esiste/non è dir.")
                 return None
        else:
             # print(f"Debug DB: Impossibile costruire full_path per AppID {appid}.")
             return None

    except Exception as e:
        print(f"ERRORE durante l'elaborazione del pattern DB per AppID {appid}: {e}")
        return None


def guess_save_path(appid, game_name, steam_userdata_path, steam_id3, game_install_dir):
    """Tenta di indovinare la cartella dei salvataggi per un gioco Steam."""
    guesses = [] # Lista dei percorsi trovati e validi
    checked_paths = set() # Per evitare controlli duplicati

    def add_guess(path, source_description):
        """Aggiunge un percorso valido alla lista se non già presente."""
        if not path: return
        norm_path = os.path.normpath(path)
        if norm_path not in checked_paths:
            checked_paths.add(norm_path)
            # print(f"  Controllo {source_description}: {norm_path}") # Debug verboso
            if os.path.isdir(norm_path):
                 if norm_path not in guesses:
                    print(f"  -> Trovato percorso potenziale ({source_description}):")
                    print(f"     '{norm_path}'")
                    guesses.append(norm_path)
                    return True # Trovato e aggiunto
            # else: print(f"     (Non trovato/Non è una cartella)") # Debug verboso
        return False # Già controllato o non valido


    print(f"\nRicerca euristica salvataggi per: '{game_name}' (AppID: {appid})")

    # --- 1. Controlla il database interno PRIMA ---
    known_path = get_known_path(appid, game_install_dir, steam_userdata_path, steam_id3)
    if known_path:
        add_guess(known_path, "Database Interno")
        # Non fermarti qui, cerca comunque alternative come fallback

    # --- 2. Steam Userdata (Cloud Saves) ---
    if steam_userdata_path and steam_id3 and appid:
        # Percorsi comuni dentro userdata
        base_userdata_appid = os.path.join(steam_userdata_path, steam_id3, appid)
        potential_paths = [
            os.path.join(base_userdata_appid, 'remote'),
            base_userdata_appid # Alcuni giochi usano direttamente la cartella AppID
        ]
        for path in potential_paths:
             if add_guess(path, "Steam Userdata"):
                 # Se troviamo 'remote', cerchiamo anche sottocartelle comuni
                 if path.endswith('remote'):
                     try:
                         for entry in os.listdir(path):
                             sub_path = os.path.join(path, entry)
                             if os.path.isdir(sub_path) and ('save' in entry.lower() or 'profile' in entry.lower()):
                                 add_guess(sub_path, "Steam Userdata/Subdir")
                     except Exception: pass # Ignora errori listing

    # --- 3. Cartelle Comuni Utente ---
    user_profile = os.path.expanduser('~')
    common_locations = {
         "Documents/My Games": os.path.join(user_profile, 'Documents', 'My Games'),
         "Documents": os.path.join(user_profile, 'Documents'),
         "Saved Games": os.path.join(user_profile, 'Saved Games'),
         "AppData/LocalLow": os.path.join(user_profile, 'AppData', 'LocalLow'),
         "AppData/Local": os.getenv('LOCALAPPDATA'),
         "AppData/Roaming": os.getenv('APPDATA')
    }

    # Prepara varianti nome gioco (pulito, originale, senza spazi)
    game_name_variants = list(dict.fromkeys([
        "".join(c for c in game_name if c.isalnum() or c in (' ', '_', '-')).strip(),
        game_name
    ]))
    if ' ' in game_name_variants[0]: game_name_variants.append(game_name_variants[0].replace(' ', ''))
    game_name_variants = list(dict.fromkeys(game_name_variants))

    common_save_subdirs = ['Saves', 'Save', 'SaveGame', 'SaveGames', 'Saved', 'storage', 'PlayerData']

    for loc_name, base_folder in common_locations.items():
        if base_folder and os.path.isdir(base_folder):
            # A) Cerca cartella con nome gioco direttamente dentro la base
            for name_variant in game_name_variants:
                path = os.path.join(base_folder, name_variant)
                if add_guess(path, f"{loc_name}/NomeGioco"):
                     # Se trovata, cerca anche sottocartelle comuni dentro di essa
                     for subdir in common_save_subdirs:
                          add_guess(os.path.join(path, subdir), f"{loc_name}/NomeGioco/Subdir")

            # B) Cerca cartelle publisher note dentro la base, e poi nome gioco dentro publisher
            common_publishers = ['My Games', 'Saved Games', 'CD Projekt Red', 'Rockstar Games', 'Ubisoft', 'Electronic Arts', 'HelloGames', 'Sonic Social', 'FromSoftware', 'Valve', 'DevolverDigital'] # Lista esempio
            for publisher in common_publishers:
                 pub_path = os.path.join(base_folder, publisher)
                 if os.path.isdir(pub_path): # Non usare add_guess qui, è solo un intermedio
                     for name_variant in game_name_variants:
                         game_in_pub_path = os.path.join(pub_path, name_variant)
                         add_guess(game_in_pub_path, f"{loc_name}/Publisher/NomeGioco")


    # --- 4. Dentro la cartella di installazione ---
    if game_install_dir and os.path.isdir(game_install_dir):
        # Cerca cartelle comuni note a profondità 1
        for subdir in common_save_subdirs + ['UserData', 'Profile', 'Profiles', 'PlayerProfiles', 'Game']:
             path = os.path.join(game_install_dir, subdir)
             add_guess(path, "InstallDir/SubdirComune")

        # Caso specifico: cartella con nome gioco dentro install dir (raro per salvataggi)
        # for name_variant in game_name_variants:
        #      path = os.path.join(game_install_dir, name_variant)
        #      add_guess(path, "InstallDir/NomeGioco")


    # --- Pulizia Finale dei Risultati ---
    # `guesses` contiene già percorsi unici e validi trovati da add_guess

    print(f"\nRicerca terminata. Trovati {len(guesses)} percorsi unici potenziali.")
    if not guesses:
         print("ATTENZIONE: Nessun percorso di salvataggio probabile trovato automaticamente.")
         if game_install_dir:
              print(f"           La cartella di installazione del gioco è: '{game_install_dir}'")
         print("           Sarà necessario inserire il percorso manualmente.")

    return guesses


def steam_menu(profiles):
    """Menu per rilevare e configurare profili per giochi Steam."""
    global installed_steam_games, steam_userdata_path, steam_id3 # Usa cache

    # Verifica dipendenze necessarie per Steam
    if vdf is None or winreg is None:
        print("\nERRORE: Funzionalità Steam non disponibile.")
        print("Mancano le librerie 'vdf' o 'winreg' (necessario Windows).")
        input("Premi Invio per continuare...")
        return

    print("\n--- Gestione Giochi Steam ---")

    # Fasi di rilevamento (usa cache se dati già presenti)
    if steam_install_path is None: get_steam_install_path()
    if steam_install_path is None:
        input("Impossibile procedere senza trovare l'installazione di Steam. Premi Invio...")
        return

    if steam_libraries is None: find_steam_libraries(steam_install_path)
    if not steam_libraries:
         input("Impossibile trovare librerie Steam valide. Premi Invio...")
         return

    if installed_steam_games is None: find_installed_steam_games(steam_libraries)
    if not installed_steam_games:
         input("Nessun gioco Steam installato trovato nelle librerie scansionate. Premi Invio...")
         return

    # Trova userdata solo se serve e non già trovato
    if steam_userdata_path is None or steam_id3 is None:
         find_steam_userdata_info(steam_install_path)


    # Mostra lista giochi installati, ordinati per nome
    game_list = sorted(installed_steam_games.items(), key=lambda item: item[1]['name'])
    print("\n--- Giochi Steam Installati Trovati ---")
    if not game_list:
         print("Nessun gioco trovato dopo l'analisi dei manifest.")
         input("Premi Invio per continuare...")
         return

    for i, (appid, game_data) in enumerate(game_list):
        # Controlla se esiste già un profilo per questo gioco (basato sul nome)
        profile_exists = "[PROFILO ESISTENTE]" if game_data['name'] in profiles else ""
        print(f"{i + 1}. {game_data['name']} (AppID: {appid}) {profile_exists}")

    # Selezione gioco
    selected_game_data = None
    selected_appid = None
    profile_name_to_use = None
    while True:
        try:
            choice = input(f"\nScegli un gioco (1-{len(game_list)}) per configurare/aggiornare il profilo, o 0 per tornare indietro: ")
            choice_num = int(choice)
            if choice_num == 0: return # Torna al menu principale
            if 1 <= choice_num <= len(game_list):
                selected_appid, selected_game_data = game_list[choice_num - 1]
                profile_name_to_use = selected_game_data['name'] # Nome profilo = Nome Gioco
                break
            else:
                print("Scelta non valida.")
        except ValueError:
            print("Inserisci un numero valido.")

    # Ricerca percorso salvataggi per il gioco scelto
    save_path_guesses = guess_save_path(
        selected_appid,
        profile_name_to_use,
        steam_userdata_path,
        steam_id3,
        selected_game_data['installdir']
    )

    # Chiedi all'utente di confermare/scegliere/inserire il percorso
    confirmed_path = None
    existing_profile_path = profiles.get(profile_name_to_use) # Path attuale se profilo esiste

    if not save_path_guesses and not existing_profile_path:
        print("\nImpossibile trovare automaticamente un percorso. Inseriscilo manualmente.")
        # Chiamerà create_profile che forzerà l'input manuale
        confirmed_path = None
    elif not save_path_guesses and existing_profile_path:
         print("\nNessun nuovo percorso trovato automaticamente.")
         use_existing = input(f"Vuoi mantenere il percorso attuale del profilo '{existing_profile_path}'? (s/n): ").lower()
         if use_existing == 's':
              confirmed_path = existing_profile_path
         else:
              confirmed_path = None # Forza input manuale in create_profile
    else: # Almeno un percorso suggerito
        print("\n--- Conferma Percorso Salvataggi ---")
        if existing_profile_path:
             print(f"Percorso attuale nel profilo: '{existing_profile_path}'")

        print("Percorsi suggeriti (il primo è spesso il migliore):")
        for idx, p in enumerate(save_path_guesses):
             is_current = "[ATTUALE]" if p == existing_profile_path else ""
             is_known_db = "[DB]" if p == KNOWN_SAVE_PATTERNS.get(selected_appid, {}).get('_resolved_path') else "" # Helper per marcare DB?
             print(f"  {idx+1}) {p} {is_current} {is_known_db}")

        while True:
             prompt = f"Scegli un numero (1-{len(save_path_guesses)}), 'm' per manuale, "
             if existing_profile_path: prompt += "'k' per mantenere attuale, "
             prompt += "o 0 per annullare: "
             path_choice = input(prompt).lower()

             if path_choice == '0': return # Annulla configurazione profilo
             elif path_choice == 'm':
                 confirmed_path = None # Forza input manuale
                 break
             elif path_choice == 'k' and existing_profile_path:
                 confirmed_path = existing_profile_path
                 print("Mantenuto percorso attuale.")
                 break
             else:
                 try:
                     path_idx = int(path_choice)
                     if 1 <= path_idx <= len(save_path_guesses):
                         confirmed_path = save_path_guesses[path_idx - 1]
                         print(f"Selezionato percorso: '{confirmed_path}'")
                         break
                     else:
                         print("Numero suggerimento non valido.")
                 except ValueError:
                     print("Input non valido.")

    # Crea o aggiorna il profilo (create_profile gestirà l'input se confirmed_path è None)
    # Salva subito dopo la creazione/aggiornamento
    final_profile_name, final_save_path = create_profile(profiles, profile_name_to_use, confirmed_path, skip_save=False)

    # Vai direttamente al menu azioni per questo profilo se creato/aggiornato
    if final_profile_name and final_save_path:
        print(f"\nProfilo '{final_profile_name}' configurato. Ora puoi eseguire azioni.")
        profile_menu(final_profile_name, final_save_path)
    else:
        print("\nConfigurazione profilo annullata o fallita.")
        time.sleep(2)

    # Torna al menu principale dopo aver gestito un gioco Steam


# --- BLOCCO PRINCIPALE DI ESECUZIONE ---

if __name__ == "__main__":
    print("\n" + "="*40)
    print("   Gestione Backup Salvataggi Giochi v2.0")
    print("="*40 + "\n")

    # Controlli iniziali critici
    if vdf is None:
        print("ERRORE: Libreria 'vdf' non trovata. Funzionalità Steam disabilitate.")
        print("Esegui 'pip install vdf' e riavvia lo script.")
        # Potremmo decidere di uscire o continuare con funzionalità limitate
        # Per ora, continuiamo ma il menu Steam non funzionerà correttamente.
    check_winrar() # Controlla subito WinRAR

    # Carica i profili esistenti
    profiles_data = load_profiles()
    print(f"Caricati {len(profiles_data)} profili esistenti da '{PROFILE_FILE}'.")
    time.sleep(1)


    # Loop del menu principale
    while True:
        print("\n===== MENU PRINCIPALE =====")
        print("1. Crea/Modifica Profilo Manualmente")
        print("2. Seleziona Profilo Esistente (Backup/Ripristino)")
        print("3. Gestisci Giochi Steam (Rilevamento Automatico)")
        print("---------------------------")
        print("0. Esci dal Programma")

        main_choice = input("\nScegli un'opzione: ")

        if main_choice == '1':
            # Chiama create_profile senza valori predefiniti, salva subito
            create_profile(profiles_data, skip_save=False)
        elif main_choice == '2':
            selected_name, selected_path = select_profile(profiles_data)
            if selected_name: # Se l'utente non ha annullato
                profile_menu(selected_name, selected_path)
        elif main_choice == '3':
            if vdf is None or winreg is None:
                 print("\nFunzionalità Steam non disponibile (mancano 'vdf' o 'winreg').")
                 time.sleep(2)
            else:
                 steam_menu(profiles_data)
                 # profiles_data potrebbe essere stato aggiornato e salvato da steam_menu
        elif main_choice == '0':
            print("\nSalvataggio profili prima di uscire...")
            save_profiles(profiles_data) # Salva per sicurezza all'uscita
            print("Uscita dal programma. Arrivederci!")
            break
        else:
            print("Scelta non valida. Riprova.")

    # Fine dello script