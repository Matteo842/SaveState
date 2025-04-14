# game_saver_cli.py
# -*- coding: utf-8 -*-
import core_logic # Importa la logica refattorizzata
import config     # Importa la configurazione
import os
import time

# --- Funzioni Interfaccia CLI ---

def select_profile_cli(profiles):
    """CLI per selezionare un profilo."""
    if not profiles:
        print("\nNessun profilo esistente. Creane uno prima.")
        return None, None
    print("\n--- Seleziona Profilo ---")
    profile_list = sorted(profiles.keys())
    for i, name in enumerate(profile_list):
        path_display = profiles[name]
        if len(path_display) > 60: path_display = path_display[:25] + "..." + path_display[-30:]
        print(f"{i + 1}. {name} ({path_display})")
    while True:
        try:
            choice = input(f"Scegli (1-{len(profile_list)}) o 0 per annullare: ")
            num = int(choice)
            if num == 0: return None, None
            if 1 <= num <= len(profile_list):
                name = profile_list[num - 1]
                return name, profiles[name]
            else: print("Scelta non valida.")
        except ValueError: print("Inserisci un numero.")

def profile_menu_cli(profiles, profile_name, save_path):
    """Menu CLI per azioni su profilo."""
    while True:
        print(f"\n--- Profilo CLI: {profile_name} ---")
        print(f"Salvataggi: {save_path}")
        print("1. Esegui Backup")
        print("2. Ripristina da Backup")
        print("0. Torna Indietro")
        choice = input("Azione: ")
        if choice == '1':
            print("\nAvvio backup...")
            success, message = core_logic.perform_backup(profile_name, save_path)
            print(f"\nRisultato Backup:\n{message}")
            input("Premi Invio...")
        elif choice == '2':
            handle_restore_cli(profile_name, save_path)
        elif choice == '0': break
        else: print("Scelta non valida.")

def handle_restore_cli(profile_name, save_path):
     """Gestisce il ripristino da CLI."""
     print("\n--- Ripristino CLI ---")
     backups = core_logic.list_available_backups(profile_name)
     if not backups:
         print("Nessun backup trovato per questo profilo.")
         input("Premi Invio...")
         return

     print("Backup disponibili (dal più recente):")
     for i, (name, path, date_str) in enumerate(backups):
         print(f"{i + 1}. {name} ({date_str})")

     while True:
        try:
            choice = input(f"Scegli backup da ripristinare (1-{len(backups)}) o 0 per annullare: ")
            num = int(choice)
            if num == 0: print("Ripristino annullato."); return
            if 1 <= num <= len(backups):
                selected_name, selected_path, _ = backups[num-1]
                break
            else: print("Scelta non valida.")
        except ValueError: print("Inserisci numero.")

     print("\n!!! ATTENZIONE !!!")
     print(f"Stai per ripristinare '{selected_name}'")
     print(f"SOVRASCRIVENDO i file in '{save_path}'")
     confirm = input("Procedere? (sì/no): ").lower()
     if confirm == 's' or confirm == 'si':
         print("\nAvvio ripristino...")
         success, message = core_logic.perform_restore(profile_name, save_path, selected_path)
         print(f"\nRisultato Ripristino:\n{message}")
     else:
         print("Ripristino annullato.")
     input("Premi Invio...")

def create_profile_cli(profiles):
    """Gestisce creazione profilo da CLI."""
    print("\n--- Crea Profilo Manuale CLI ---")
    while True:
        name = input("Nome profilo: ")
        if not name: print("Nome non vuoto."); continue
        if name in profiles: print("Nome già esistente."); continue
        break
    while True:
        path = input(f"Percorso salvataggi per '{name}': ").strip('"')
        path = os.path.normpath(path)
        if os.path.isdir(path): break
        else: print("Percorso non valido o non è una cartella.")

    profiles[name] = path
    if core_logic.save_profiles(profiles): print(f"Profilo '{name}' salvato.")
    else: print("Errore salvataggio profilo.")
    time.sleep(1)


# --- Main CLI ---
if __name__ == "__main__":
    print("\nGestione Backup Salvataggi (CLI Version)\n")

    # Verifica WinRAR subito
    if not os.path.exists(config.WINRAR_PATH):
         print(f"ERRORE: WinRAR non trovato in '{config.WINRAR_PATH}'. Verifica config.py")
         exit(1)

    profiles_data = core_logic.load_profiles()
    print(f"Caricati {len(profiles_data)} profili.")

    while True:
        print("\n===== MENU CLI =====")
        print("1. Crea Profilo Manuale")
        print("2. Seleziona Profilo (Backup/Ripristino)")
        print("3. Gestisci Giochi Steam (NON IMPLEMENTATO in CLI base)") # Steam CLI richiede più lavoro
        print("0. Esci")
        choice = input("Opzione: ")

        if choice == '1': create_profile_cli(profiles_data)
        elif choice == '2':
            name, path = select_profile_cli(profiles_data)
            if name: profile_menu_cli(profiles_data, name, path)
        elif choice == '3': print("Funzione Steam non implementata in questa versione CLI.") # Da fare
        elif choice == '0': break
        else: print("Scelta non valida.")

    print("\nUscita.")