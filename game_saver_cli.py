# game_saver_cli.py (Versione con Loading Screen)
# -*- coding: utf-8 -*-

import os
import time
import platform
import sys # Aggiunto sys per exit()

# --- Import Essenziali e Veloci ---
try:
    import colorama
    from colorama import Fore, Back, Style, init
    # Inizializza SUBITO colorama per il messaggio di loading
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    # Definisci colori vuoti come fallback se colorama manca
    class Fore:
        RED = GREEN = YELLOW = CYAN = WHITE = LIGHTBLACK_EX = MAGENTA = BLUE = ""
    class Style:
        BRIGHT = RESET_ALL = ""
    COLORAMA_AVAILABLE = False
    print("Warning: 'colorama' library not found. Output will not be colored.")
    # Non usiamo init() se non c'è colorama

# --- Funzioni Helper per Stampa Colorata (definite prima del loading) ---

def print_title(text):
    """Prints a title in bright red."""
    print(f"{Style.BRIGHT}{Fore.RED}=== {text.upper()} ===")

def print_header(text):
    """Prints a section header in bright magenta."""
    print(f"\n{Style.BRIGHT}{Fore.MAGENTA}--- {text} ---{Style.RESET_ALL}")

def print_option(key, text):
    """Prints a menu option."""
    print(f"  {Style.BRIGHT}{Fore.CYAN}{key}{Style.RESET_ALL}. {text}")

def print_info(text):
    """Prints standard information (white/default)."""
    print(text)

def print_success(text):
    """Prints a success message in green."""
    print(f"{Fore.GREEN}{text}")

def print_warning(text):
    """Prints a warning message in yellow."""
    print(f"{Fore.YELLOW}WARNING: {text}")

def print_error(text):
    """Prints an error message in bright red."""
    print(f"{Style.BRIGHT}{Fore.RED}ERROR: {text}")

def get_input(prompt):
    """Gets user input with a specific prompt style."""
    try:
        return input(f"{Style.BRIGHT}{Fore.WHITE}> {prompt}{Style.RESET_ALL} ")
    except EOFError:
        print_error("\nInput stream closed unexpectedly. Exiting.")
        sys.exit(1) # Usa sys.exit

def pause(message="Press Enter to continue..."):
    """Pauses execution and waits for Enter key."""
    input(f"\n{Fore.LIGHTBLACK_EX}{message}{Style.RESET_ALL}")

def clear_screen():
    """Clears the terminal screen."""
    os.system('cls' if platform.system() == "Windows" else 'clear')


# --- === PUNTO DI INIZIO ESECUZIONE === ---
if __name__ == "__main__":

    # 1. Pulisci lo schermo e mostra messaggio di caricamento IMMEDIATAMENTE
    clear_screen()
    print(f"\n{Style.BRIGHT}{Fore.BLUE}Loading SaveState CLI...{Style.RESET_ALL}\n")
    # Aggiungiamo un piccolo delay artificiale per rendere visibile il "Loading"
    # Puoi rimuoverlo o cambiarlo se vuoi
    # time.sleep(0.5)

    # 2. Ora esegui gli import "pesanti"
    try:
        import core_logic
        import config
        import settings_manager
        import minecraft_utils
        import shortcut_utils
        import logging # Import logging qui se lo usi nelle funzioni sotto
        MODULES_LOADED = True
    except ImportError as e:
        # Errore critico se i moduli principali non si caricano
        clear_screen()
        print_title("Fatal Error")
        print_error(f"Could not import required application modules ({e}).")
        print_error("Ensure the script is run from the correct directory")
        print_error("and all project files are present.")
        MODULES_LOADED = False
        pause("Press Enter to exit.")
        sys.exit(1) # Esce se mancano moduli fondamentali
    except Exception as e_load:
        # Altri errori imprevisti durante l'import
        clear_screen()
        print_title("Fatal Error")
        print_error(f"An unexpected error occurred during module loading: {e_load}")
        MODULES_LOADED = False
        pause("Press Enter to exit.")
        sys.exit(1)

    # --- Se gli import sono andati a buon fine, prosegui ---
    if MODULES_LOADED:

        # --- Funzioni che DIPENDONO dagli import precedenti ---
        # (Le funzioni create_profile_cli, select_profile_cli, etc.
        #  ora devono essere definite QUI, dopo gli import)

        def create_profile_cli(profiles_dict):
            """Handles manual creation of a new profile."""
            clear_screen()
            print_title("Create New Manual Profile")
            new_profile_name = ""
            while True:
                name_input = get_input("Enter a name for the new profile (or leave blank to cancel): ")
                if not name_input:
                    print_info("Profile creation cancelled.")
                    return profiles_dict # Return original dict

                # Sanitize the name
                sanitized_name = shortcut_utils.sanitize_profile_name(name_input)
                if not sanitized_name or sanitized_name == "_invalid_profile_name_":
                     print_error(f"Invalid profile name after sanitization: '{name_input}'. Please use letters, numbers, spaces, dots, or hyphens.")
                     continue

                if sanitized_name in profiles_dict:
                    print_error(f"A profile named '{sanitized_name}' already exists.")
                    continue
                else:
                    new_profile_name = sanitized_name # Store sanitized name
                    break

            new_profile_path = ""
            while True:
                path_input = get_input(f"Enter the FULL path to the saves folder for '{new_profile_name}': ").strip('"')
                if not path_input:
                    print_error("Path cannot be empty.")
                    continue

                # Validate path
                norm_path = os.path.normpath(path_input)
                if not os.path.isdir(norm_path):
                    print_error(f"The specified path is not a valid directory:\n'{norm_path}'")
                    continue

                # Optional: Add root drive check if desired (similar to GUI)
                drive, tail = os.path.splitdrive(norm_path)
                if not tail or tail == os.sep:
                     print_error(f"Cannot use a root drive ('{norm_path}') as the saves folder. Please choose a subfolder.")
                     continue

                new_profile_path = norm_path
                break

            # Add the new profile (as a dictionary)
            profiles_dict[new_profile_name] = {'path': new_profile_path}
            print_info(f"\nProfile '{new_profile_name}' will be saved with path: '{new_profile_path}'")

            # Save the updated profiles dictionary
            if core_logic.save_profiles(profiles_dict):
                print_success(f"Profile '{new_profile_name}' saved successfully.")
            else:
                print_error("Failed to save the profiles file.")
                # Revert addition if save failed?
                if new_profile_name in profiles_dict:
                    del profiles_dict[new_profile_name]
                    print_info("Profile addition reverted due to save error.")

            pause()
            return profiles_dict # Return potentially updated dictionary

        def create_profile_minecraft_cli(profiles_dict):
            """Handles profile creation from Minecraft worlds."""
            clear_screen()
            print_title("Create Profile from Minecraft World")
            print_info("Searching for Minecraft saves folder...")
            saves_folder = minecraft_utils.find_minecraft_saves_folder()

            if not saves_folder:
                print_error("Could not find the standard Minecraft saves folder (.minecraft/saves).")
                print_error("Ensure Minecraft Java Edition is installed.")
                pause()
                return profiles_dict

            print_info(f"Found saves folder: {saves_folder}")
            print_info("Listing available worlds...")
            worlds = minecraft_utils.list_minecraft_worlds(saves_folder)

            if not worlds:
                print_info("No Minecraft worlds found in the saves folder.")
                pause()
                return profiles_dict

            print_info("Available Minecraft Worlds:")
            for i, world_data in enumerate(worlds):
                # Display name (from NBT or folder), and folder name
                display_name = world_data.get('world_name', 'Unknown Name')
                folder_name = world_data.get('folder_name', 'Unknown Folder')
                print_option(i + 1, f"{display_name} (Folder: {folder_name})")

            while True:
                try:
                    choice_str = get_input(f"Select world (1-{len(worlds)}) or 0 to cancel: ")
                    choice = int(choice_str)
                    if choice == 0:
                        print_info("Cancelled.")
                        pause() # Aggiungi pausa qui
                        return profiles_dict
                    if 1 <= choice <= len(worlds):
                        selected_world_data = worlds[choice - 1]
                        break
                    else:
                        print_error("Invalid choice.")
                except ValueError:
                    print_error("Please enter a number.")
                except Exception as e:
                     print_error(f"Unexpected error: {e}")

            # Extract info and sanitize name
            world_path = selected_world_data.get('full_path')
            potential_profile_name = selected_world_data.get('world_name', selected_world_data.get('folder_name'))

            if not world_path or not potential_profile_name:
                 print_error("Could not get valid data for the selected world.")
                 pause()
                 return profiles_dict

            sanitized_name = shortcut_utils.sanitize_profile_name(potential_profile_name)
            if not sanitized_name or sanitized_name == "_invalid_profile_name_":
                 print_error(f"Could not create a valid profile name from '{potential_profile_name}'.")
                 pause()
                 return profiles_dict

            if sanitized_name in profiles_dict:
                print_error(f"A profile named '{sanitized_name}' already exists.")
                pause()
                return profiles_dict

            # Add profile and save
            profiles_dict[sanitized_name] = {'path': world_path}
            print_info(f"\nProfile '{sanitized_name}' will be created for world path: '{world_path}'")

            if core_logic.save_profiles(profiles_dict):
                print_success(f"Profile '{sanitized_name}' created successfully.")
            else:
                print_error("Failed to save the profiles file.")
                if sanitized_name in profiles_dict: del profiles_dict[sanitized_name] # Revert

            pause()
            return profiles_dict

        def select_profile_cli(profiles_dict):
            """Allows the user to select a profile and opens the action menu."""
            # Check if profiles exist BEFORE clearing screen
            if not profiles_dict:
                 clear_screen()
                 print_title("Select Profile")
                 print_info("\nNo existing profiles found. Please create one first.")
                 pause()
                 return

            profile_list = sorted(profiles_dict.keys()) # Sort alphabetically for selection

            while True: # Loop for selection
                clear_screen()
                print_title("Select Profile")
                print_info("Available Profiles:")
                for i, name in enumerate(profile_list):
                    # Only print name
                    print_option(i + 1, f"{name}")

                try:
                    choice_str = get_input(f"Choose (1-{len(profile_list)}) or 0 to cancel: ")
                    choice = int(choice_str)
                    if choice == 0:
                        return # Back to main menu
                    if 1 <= choice <= len(profile_list):
                        selected_name = profile_list[choice - 1]
                        selected_profile_data = profiles_dict[selected_name] # Get the dictionary
                        # Pass the dict to the profile menu
                        profile_menu_cli(profiles_dict, selected_name, selected_profile_data)
                        # After returning from profile menu, break loop to show main menu again
                        break # Exit selection loop, back to main menu prompt
                    else:
                        print_error("Invalid choice.")
                        pause() # Pause on error
                except ValueError:
                    print_error("Please enter a number.")
                    pause() # Pause on error
                except Exception as e:
                     print_error(f"Unexpected error: {e}")
                     pause() # Pause on error


        def profile_menu_cli(profiles_dict, profile_name, profile_data):
            """Action menu for a selected profile."""
            save_path = profile_data.get('path', None)

            # Load settings once for this menu
            settings = {}
            try:
                settings, _ = settings_manager.load_settings()
            except Exception as e_set:
                print_warning(f"Could not load settings, using defaults: {e_set}")

            backup_base = settings.get("backup_base_dir", config.BACKUP_BASE_DIR)
            max_bk = settings.get("max_backups", config.MAX_BACKUPS)
            max_src_size = settings.get("max_source_size_mb", -1)
            compression = settings.get("compression_mode", "standard")
            check_space = settings.get("check_free_space_enabled", True)
            min_gb_req = config.MIN_FREE_SPACE_GB

            while True:
                clear_screen()
                print_title(f"Profile Actions: {profile_name}")
                if save_path:
                    print_info(f"Saves Path: {save_path}")
                else:
                    print_error("Saves path is missing or invalid for this profile!")

                print_option(1, "Perform Backup")
                print_option(2, "Restore from Backup")
                print_option(0, "Back to Main Menu")

                choice = get_input("Action: ")

                if choice == '1':
                    if save_path and os.path.isdir(save_path):
                        print_header("Performing Backup")
                        print_info(f"(Destination Base: {backup_base}, Max: {max_bk}, Comp: {compression})")

                        space_ok = True
                        if check_space:
                            print_info(f"Checking free disk space (Min: {min_gb_req} GB)...")
                            min_bytes_req = min_gb_req * 1024 * 1024 * 1024
                            try:
                                os.makedirs(backup_base, exist_ok=True)
                                import shutil
                                disk_usage = shutil.disk_usage(backup_base)
                                free_bytes = disk_usage.free
                                if free_bytes < min_bytes_req:
                                    free_gb = free_bytes / (1024*1024*1024)
                                    print_error(f"Insufficient disk space! Free: {free_gb:.2f} GB, Required: {min_gb_req} GB.")
                                    space_ok = False
                                else:
                                    print_info("Disk space check passed.")
                            except Exception as e_space:
                                print_warning(f"Disk space check failed: {e_space}")

                        if space_ok:
                            success, message = core_logic.perform_backup(
                                profile_name, save_path, backup_base, max_bk, max_src_size, compression
                            )
                            if success:
                                print_success(f"\nBackup Result:\n{message}")
                            else:
                                print_error(f"\nBackup Result:\n{message}")
                    else:
                        print_error("Cannot perform backup: Saves path is invalid.")
                    pause()

                elif choice == '2':
                    if save_path:
                        handle_restore_cli(profile_name, save_path, backup_base)
                    else:
                         print_error("Cannot restore: Saves path is invalid.")
                         pause()

                elif choice == '0':
                    break

                else:
                    print_error("Invalid choice.")


        def handle_restore_cli(profile_name, save_path_string, backup_base_dir):
            """Handles restoring from backup via CLI."""
            clear_screen()
            print_title(f"Restore Backup for {profile_name}")
            print_info(f"(Searching for backups in: {backup_base_dir})")

            backups = core_logic.list_available_backups(profile_name, backup_base_dir)

            if not backups:
                print_info("No backups found for this profile.")
                pause()
                return

            print_info("Available backups (most recent first):")
            for i, (filename, full_path, date_obj) in enumerate(backups):
                 date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S") if date_obj else "Unknown Date"
                 display_name = core_logic.get_display_name_from_backup_filename(filename)
                 print_option(i + 1, f"{display_name} ({date_str})")

            while True:
                try:
                    choice_str = get_input(f"Choose backup to restore (1-{len(backups)}) or 0 to cancel: ")
                    choice = int(choice_str)
                    if choice == 0:
                         print_info("Restore cancelled.")
                         pause()
                         return
                    if 1 <= choice <= len(backups):
                        selected_filename, selected_filepath, _ = backups[choice - 1]
                        break
                    else:
                         print_error("Invalid choice.")
                except ValueError:
                    print_error("Please enter a number.")
                except Exception as e:
                     print_error(f"Unexpected error: {e}")

            print("")
            print_warning("This will OVERWRITE current files in the saves folder!")
            print_warning(f"Restore '{core_logic.get_display_name_from_backup_filename(selected_filename)}'")
            print_warning(f"to '{save_path_string}'?")
            confirm = get_input("Proceed? (yes/no): ").lower()

            if confirm == 'y' or confirm == 'yes':
                print_info("\nStarting restore...")
                success, message = core_logic.perform_restore(profile_name, save_path_string, selected_filepath)
                if success:
                    print_success(f"\nRestore Result:\n{message}")
                else:
                    print_error(f"\nRestore Result:\n{message}")
            else:
                print_info("Restore cancelled.")
            pause()


        def manage_steam_cli(profiles_dict):
            """Placeholder for Steam Games Management via CLI."""
            clear_screen()
            print_title("Manage Steam Games")
            print_info("This feature is complex for the CLI and will be implemented later.")
            print_info("Please use the main GUI application for Steam integration for now.")
            pause()
            return profiles_dict

        # --- Fine Definizione Funzioni ---

        # 3. Carica i profili (DOPO gli import dei moduli necessari)
        profiles = core_logic.load_profiles()

        # 4. Pulisci lo schermo di nuovo e mostra il menu principale
        clear_screen()
        print_title("SaveState CLI - Ready")
        print_info(f"Loaded {len(profiles)} profiles.")

        # --- Main Menu Loop ---
        while True:
            print("\n" + "="*40)
            print_title("Main Menu")
            print_option(1, "Create New Manual Profile")
            print_option(2, "Create Profile from Minecraft World")
            print_option(3, "Manage Steam Games (Not Implemented Yet)")
            print_option(4, "Select Existing Profile (Backup/Restore)")
            print_option(0, "Exit")
            print("="*40)

            main_choice = get_input("Option: ")

            if main_choice == '1':
                profiles = create_profile_cli(profiles)
            elif main_choice == '2':
                 profiles = create_profile_minecraft_cli(profiles)
            elif main_choice == '3':
                profiles = manage_steam_cli(profiles)
            elif main_choice == '4':
                select_profile_cli(profiles)
            elif main_choice == '0':
                break
            else:
                print_error("Invalid choice.")

        print_success("\nExiting SaveState CLI.")

# --- Fine Blocco if __name__ == "__main__": ---