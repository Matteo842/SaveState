# ppsspp_manager.py
import os
import logging
from .sfo_utils import parse_param_sfo

# Costanti
EMULATOR_NAME = "PPSSPP"
CORRECT_STANDARD_SUBPATH = os.path.join("PPSSPP", "PSP", "SAVEDATA") # Path from user screenshot

def find_ppsspp_profiles(executable_path=None): 
    """
    Trova i profili di salvataggio di PPSSPP basati sulle cartelle degli ID dei giochi.

    Cerca nella posizione standard: %UserProfile%\Documents\PPSSPP\PSP\SAVEDATA
    Ogni sottocartella in SAVEDATA è considerata un profilo di gioco separato.

    Args:
        executable_path (str, optional): Path to the emulator executable. Defaults to None.

    Returns:
        list: Una lista di dizionari, ognuno rappresentante un profilo trovato.
              Ogni dizionario ha le chiavi: 'emulator', 'id', 'name', 'path'.
              'id' e 'name' sono l'ID della cartella del gioco (es. 'ULUS10041').
              'path' è il percorso completo alla cartella specifica del gioco.
    """
    profiles = []
    log = logging.getLogger(__name__) 
    log.info("Scanning for PPSSPP save profiles...")

    save_data_base_path = None 

    try:
        # ONLY Check Standard Location (using path from screenshot)
        documents_path = os.path.join(os.path.expanduser('~'), 'Documents')
        standard_path = os.path.join(documents_path, CORRECT_STANDARD_SUBPATH) # Use corrected path
        log.info(f"Checking specific standard PPSSPP SAVEDATA location: {standard_path}")
        if os.path.isdir(standard_path):
            log.info("Found PPSSPP SAVEDATA in specific standard location.")
            save_data_base_path = standard_path
        else:
            log.warning(f"Specific standard PPSSPP SAVEDATA directory NOT FOUND at: {standard_path}")
            return [] # Exit if not found here

        # --- Proceed with listing profiles using the found save_data_base_path ---
        log.info(f"Scanning directory for game IDs: {save_data_base_path}")
        # Elenca le sottocartelle (ID dei giochi) dentro SAVEDATA
        for item_name in os.listdir(save_data_base_path):
            item_path = os.path.join(save_data_base_path, item_name)

            if os.path.isdir(item_path):
                game_id = item_name 
                game_name = game_id # Default name is the ID

                # Attempt to read the real game name from PARAM.SFO
                sfo_path = os.path.join(item_path, "PARAM.SFO")
                if os.path.isfile(sfo_path):
                    try:
                        extracted_title = parse_param_sfo(sfo_path)
                        if extracted_title:
                            game_name = extracted_title # Use extracted title if successful
                            log.debug(f"  Successfully parsed PARAM.SFO for {game_id}: '{game_name}'")
                        else:
                            log.warning(f"  parse_param_sfo returned None or empty for {sfo_path}")
                    except Exception as sfo_error:
                        log.error(f"  Error parsing {sfo_path}: {sfo_error}", exc_info=False) # Don't need full traceback usually
                else:
                    log.debug(f"  PARAM.SFO not found in {item_path}")

                log.debug(f"Found potential PPSSPP game save folder: {game_id} at {item_path} (Display Name: '{game_name}')")
                profile = {
                    'emulator': EMULATOR_NAME,
                    'id': game_id,
                    'name': game_name, # Use extracted name or fallback ID
                    'path': item_path 
                }
                profiles.append(profile)

    except FileNotFoundError:
        log.info(f"Standard PPSSPP save path component not found.")
    except Exception as e:
        log.error(f"Error scanning for PPSSPP profiles: {e}", exc_info=True)

    log.info(f"Found {len(profiles)} PPSSPP game save profile(s).")
    return profiles

# Esempio di utilizzo (per test)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    logger = logging.getLogger(__name__)
    logger.info("--- Running PPSSPP Test --- ")
    found_profiles = find_ppsspp_profiles()
    if found_profiles:
        print("\nFound PPSSPP Profiles:")
        for p in found_profiles:
            print(f"  ID: {p['id']}, Name: {p['name']}, Path: {p['path']}")
    else:
        print("\nNo PPSSPP profiles found in standard location.")
