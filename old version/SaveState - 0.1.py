import os
import subprocess
import json
from datetime import datetime
import time # Usato per la pausa

# --- CONFIGURAZIONE ---
# Assicurati che questo percorso sia corretto per la tua installazione di WinRAR
WINRAR_PATH = r"C:\Program Files\WinRAR\rar.exe"
# Cartella base dove verranno salvati tutti i backup (una sottocartella per profilo)
BACKUP_BASE_DIR = r"C:\GameSaveBackups"
# File dove verranno memorizzati i profili
PROFILE_FILE = "game_save_profiles.json"
# Numero massimo di backup da mantenere per profilo
MAX_BACKUPS = 3
# --- FINE CONFIGURAZIONE ---

def check_winrar():
    """Verifica se il percorso di WinRAR è valido."""
    if not os.path.exists(WINRAR_PATH):
        print(f"ERRORE: Impossibile trovare WinRAR.exe nel percorso specificato: {WINRAR_PATH}")
        print("Per favore, modifica la variabile 'WINRAR_PATH' nello script con il percorso corretto.")
        input("Premi Invio per uscire.")
        exit(1)
    print(f"WinRAR trovato in: {WINRAR_PATH}")

def load_profiles():
    """Carica i profili dal file JSON."""
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, 'r') as f:
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
        with open(PROFILE_FILE, 'w') as f:
            json.dump(profiles, f, indent=4)
    except Exception as e:
        print(f"Errore durante il salvataggio dei profili: {e}")

def create_profile(profiles):
    """Crea un nuovo profilo."""
    print("\n--- Creazione Nuovo Profilo ---")
    while True:
        profile_name = input("Inserisci un nome per il profilo (es. Cyberpunk2077): ")
        if not profile_name:
            print("Il nome del profilo non può essere vuoto.")
        elif profile_name in profiles:
            print(f"Un profilo con il nome '{profile_name}' esiste già.")
        else:
            break

    while True:
        save_folder_path = input(f"Inserisci il percorso completo della cartella dei salvataggi per '{profile_name}': ")
        if not os.path.isdir(save_folder_path):
            print(f"ERRORE: Il percorso '{save_folder_path}' non è una cartella valida o non esiste.")
        else:
            break

    profiles[profile_name] = save_folder_path
    save_profiles(profiles)
    print(f"Profilo '{profile_name}' creato con successo!")
    time.sleep(2) # Pausa per leggere il messaggio

def select_profile(profiles):
    """Seleziona un profilo esistente."""
    if not profiles:
        print("\nNessun profilo esistente. Creane uno prima.")
        return None, None

    print("\n--- Seleziona Profilo ---")
    profile_list = list(profiles.keys())
    for i, name in enumerate(profile_list):
        print(f"{i + 1}. {name} ({profiles[name]})")

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

    # Costruisci ed esegui il comando rar
    # 'a' = aggiungi all'archivio
    # '-r' = ricorsivo (include sottocartelle)
    # '-ep1' = esclude il percorso base dalla struttura dell'archivio
    # '-o+' = sovrascrivi file esistenti nell'archivio (utile se si dovesse interrompere e riprendere?)
    # '-m5' = massima compressione (opzionale)
    # Aggiungere '*' alla fine del percorso per includere tutto il contenuto della cartella
    source_path_for_rar = os.path.join(save_folder_path, '*')

    command = [
        WINRAR_PATH,
        "a",        # Comando: aggiungi ad archivio
        "-r",       # Ricorsivo
        "-ep1",     # Escludi percorso base
        "-o+",      # Sovrascrivi (utile se si ripete lo stesso nome, anche se improbabile col timestamp)
        archive_path, # Archivio di destinazione
        source_path_for_rar # Sorgente (con * per includere il contenuto)
    ]

    try:
        print("Avvio di WinRAR...")
        # Usiamo check=True per sollevare un'eccezione se WinRAR ritorna un errore
        # capture_output=True per non mostrare l'output di WinRAR (opzionale)
        result = subprocess.run(command, check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW) # CREATE_NO_WINDOW nasconde la finestra di cmd
        print("Backup completato con successo!")
        manage_backups(profile_backup_dir) # Pulisce i backup vecchi dopo un successo
    except subprocess.CalledProcessError as e:
        print(f"ERRORE durante l'esecuzione di WinRAR (Codice: {e.returncode}).")
        print(f"Comando: {' '.join(command)}")
        print(f"Output di errore (se disponibile):\n{e.stderr}")
        # Non eliminare l'archivio potenzialmente parziale qui, WinRAR di solito non lo crea se fallisce
    except FileNotFoundError:
         print(f"ERRORE: Impossibile eseguire il comando. Assicurati che WinRAR sia installato e che '{WINRAR_PATH}' sia corretto.")
    except Exception as e:
        print(f"Si è verificato un errore imprevisto durante il backup: {e}")

    input("Premi Invio per continuare...")


def manage_backups(profile_backup_dir):
    """Elimina i backup più vecchi se superano il limite."""
    try:
        # Trova tutti i file .rar nella cartella di backup del profilo
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith("Backup_") and f.endswith(".rar")]
        
        # Ordina i file per data di modifica (dal più vecchio al più recente)
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)))

        num_backups = len(backup_files)
        print(f"Trovati {num_backups} backup per questo profilo (limite: {MAX_BACKUPS}).")

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
        else:
             print("Nessun backup vecchio da eliminare.")

    except FileNotFoundError:
        print(f"La cartella di backup '{profile_backup_dir}' non è stata trovata per la gestione dei backup.")
    except Exception as e:
        print(f"Errore durante la gestione dei backup: {e}")

def perform_restore(profile_name, save_folder_path):
    """Ripristina i salvataggi da un backup selezionato."""
    print(f"\n--- Ripristino per '{profile_name}' ---")
    profile_backup_dir = os.path.join(BACKUP_BASE_DIR, profile_name)

    if not os.path.isdir(profile_backup_dir):
        print(f"Nessuna cartella di backup trovata per '{profile_name}' in '{profile_backup_dir}'.")
        input("Premi Invio per continuare...")
        return

    try:
        # Trova tutti i file .rar nella cartella di backup del profilo
        backup_files = [f for f in os.listdir(profile_backup_dir) if f.startswith(f"Backup_{profile_name}_") and f.endswith(".rar")]
        
        # Ordina i file per data di modifica (dal più recente al più vecchio)
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(profile_backup_dir, f)), reverse=True)

        if not backup_files:
            print(f"Nessun file di backup (.rar) trovato per '{profile_name}' in '{profile_backup_dir}'.")
            input("Premi Invio per continuare...")
            return

        print("Backup disponibili per il ripristino (dal più recente):")
        for i, fname in enumerate(backup_files):
            print(f"{i + 1}. {fname}")

        while True:
            try:
                choice = input(f"Scegli un numero (1-{len(backup_files)}) per ripristinare, o 0 per annullare: ")
                choice_num = int(choice)
                if choice_num == 0:
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
        print(f"Questo SOVRASCRIVERÀ qualsiasi file esistente nella cartella:")
        print(f"'{save_folder_path}'")
        confirm = input("Sei assolutamente sicuro di voler procedere? (sì/no): ").lower()

        if confirm == 'sì' or confirm == 'si':
            print(f"Ripristino da '{archive_to_restore}' a '{save_folder_path}'...")

            # Costruisci ed esegui il comando rar per estrarre
            # 'x' = estrai con percorsi completi
            # '-o+' = sovrascrivi i file esistenti senza chiedere conferma
            command = [
                WINRAR_PATH,
                "x",               # Comando: estrai con percorsi
                "-o+",             # Sovrascrivi esistenti
                archive_to_restore,# Archivio sorgente
                save_folder_path   # Cartella di destinazione
            ]

            try:
                print("Avvio di WinRAR per l'estrazione...")
                result = subprocess.run(command, check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                print("Ripristino completato con successo!")
            except subprocess.CalledProcessError as e:
                print(f"ERRORE durante l'esecuzione di WinRAR (Codice: {e.returncode}).")
                print(f"Comando: {' '.join(command)}")
                print(f"Output di errore (se disponibile):\n{e.stderr}")
            except FileNotFoundError:
                 print(f"ERRORE: Impossibile eseguire il comando. Assicurati che WinRAR sia installato e che '{WINRAR_PATH}' sia corretto.")
            except Exception as e:
                print(f"Si è verificato un errore imprevisto durante il ripristino: {e}")
        else:
            print("Ripristino annullato.")

    except Exception as e:
        print(f"Errore durante la ricerca dei backup: {e}")

    input("Premi Invio per continuare...")


def profile_menu(profile_name, save_folder_path):
    """Menu delle azioni per un profilo selezionato."""
    while True:
        print(f"\n--- Profilo: {profile_name} ---")
        print(f"Cartella salvataggi: {save_folder_path}")
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

# --- Script Principale ---
if __name__ == "__main__":
    check_winrar() # Controlla subito se WinRAR è accessibile
    profiles_data = load_profiles()

    while True:
        print("\n===== Menu Gestione Salvataggi Giochi =====")
        print("1. Crea Nuovo Profilo")
        print("2. Seleziona Profilo Esistente")
        print("0. Esci")

        main_choice = input("Scegli un'opzione: ")

        if main_choice == '1':
            create_profile(profiles_data)
            # Non è necessario salvare qui, create_profile salva già
        elif main_choice == '2':
            selected_name, selected_path = select_profile(profiles_data)
            if selected_name:
                profile_menu(selected_name, selected_path)
        elif main_choice == '0':
            print("Uscita dal programma.")
            break
        else:
            print("Scelta non valida.")

    # Opzionale: salva i profili all'uscita (anche se vengono salvati dopo la creazione)
    # save_profiles(profiles_data)