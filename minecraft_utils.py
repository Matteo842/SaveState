# minecraft_utils.py
# -*- coding: utf-8 -*-

import os
import platform
import logging

# Prova a importare nbtlib, ma preparati al caso non sia installato/funzionante
try:
    import nbtlib
    # Verifica opzionale per una classe/funzione specifica se necessario
    # if not hasattr(nbtlib, 'load'): raise ImportError
    NBT_AVAILABLE = True
    logging.debug("Libreria nbtlib importata con successo.")
except ImportError:
    NBT_AVAILABLE = False
    logging.warning("Libreria 'nbtlib' non trovata o non valida. Impossibile leggere i nomi dei mondi da level.dat. Verranno usati i nomi delle cartelle.")

def find_minecraft_saves_folder():
    """
    Trova il percorso della cartella 'saves' standard di Minecraft Java Edition.

    Restituisce:
        str | None: Il percorso assoluto della cartella 'saves' se trovata, altrimenti None.
    """
    system = platform.system()
    saves_path = None
    minecraft_folder = None

    try:
        if system == "Windows":
            appdata_path = os.getenv('APPDATA')
            if appdata_path:
                minecraft_folder = os.path.join(appdata_path, '.minecraft')
            else:
                logging.warning("Variabile d'ambiente APPDATA non trovata.")
                return None
        elif system == "Darwin": # macOS
            home = os.path.expanduser('~')
            minecraft_folder = os.path.join(home, 'Library', 'Application Support', 'minecraft')
        elif system == "Linux":
            home = os.path.expanduser('~')
            minecraft_folder = os.path.join(home, '.minecraft')
        else:
            logging.warning(f"Sistema operativo '{system}' non supportato per ricerca automatica Minecraft.")
            return None

        if minecraft_folder and os.path.isdir(minecraft_folder):
            potential_saves_path = os.path.join(minecraft_folder, 'saves')
            logging.debug(f"Controllo percorso saves Minecraft: '{potential_saves_path}'")
            if os.path.isdir(potential_saves_path):
                saves_path = potential_saves_path
                logging.info(f"Trovata cartella salvataggi Minecraft: '{saves_path}'")
            else:
                logging.warning(f"Cartella '.minecraft' trovata ('{minecraft_folder}') ma non contiene una sottocartella 'saves' valida.")
        else:
             logging.warning(f"Cartella standard Minecraft ('{minecraft_folder}') non trovata o non è una directory.")

    except Exception as e:
        logging.error(f"Errore durante la ricerca della cartella saves di Minecraft: {e}", exc_info=True)
        saves_path = None

    return saves_path

def list_minecraft_worlds(saves_folder_path):
    """
    Elenca i mondi di Minecraft presenti nella cartella saves specificata.
    Tenta di leggere il nome del mondo da level.dat usando nbtlib se disponibile.

    Args:
        saves_folder_path (str): Percorso della cartella 'saves' di Minecraft.

    Returns:
        list: Una lista di dizionari, ognuno rappresentante un mondo.
              Es: [{'folder_name': 'World1', 'world_name': 'Mondo di Gioco', 'full_path': '.../saves/World1'}, ...]
              Restituisce una lista vuota se la cartella non è valida o non ci sono mondi.
    """
    worlds = []
    if not saves_folder_path or not os.path.isdir(saves_folder_path):
        logging.error(f"Percorso salvataggi Minecraft non valido: {saves_folder_path}")
        return worlds

    logging.info(f"Scansione mondi Minecraft in: {saves_folder_path}")
    try:
        for item_name in os.listdir(saves_folder_path):
            item_path = os.path.join(saves_folder_path, item_name)

            # Considera solo le directory
            if os.path.isdir(item_path):
                folder_name = item_name # Nome della cartella
                world_name = folder_name # Nome di fallback
                level_dat_path = os.path.join(item_path, 'level.dat')

                # Prova a leggere il nome da level.dat solo se nbtlib è disponibile
                if NBT_AVAILABLE and os.path.isfile(level_dat_path):
                    try:
                        logging.debug(f"  Tentativo di leggere: {level_dat_path}")
                        nbt_file = nbtlib.load(level_dat_path)
                        # Il nome di solito è qui, ma usiamo .get per sicurezza
                        data_tag = nbt_file.get('Data', None)
                        if data_tag:
                            name_from_nbt = data_tag.get('LevelName', None)
                            if name_from_nbt:
                                # Assicurati sia una stringa e puliscila
                                world_name = str(name_from_nbt).strip()
                                logging.debug(f"    -> Nome da level.dat: '{world_name}'")
                            else:
                                 logging.debug(f"    -> Tag 'LevelName' non trovato in 'Data'. Uso nome cartella.")
                        else:
                             logging.debug(f"    -> Tag 'Data' non trovato in level.dat. Uso nome cartella.")

                    except nbtlib.MalformedFileError:
                        logging.warning(f"    -> File level.dat corrotto o malformato: {level_dat_path}. Uso nome cartella.")
                    except KeyError as e:
                         logging.warning(f"    -> Struttura NBT inattesa in {level_dat_path} (manca chiave {e}). Uso nome cartella.")
                    except Exception as e_nbt:
                        logging.error(f"    -> Errore imprevisto lettura NBT {level_dat_path}: {e_nbt}", exc_info=True)
                elif not os.path.isfile(level_dat_path):
                     logging.debug(f"  File level.dat non trovato in '{item_path}'. Uso nome cartella.")
                else: # NBT non disponibile
                     logging.debug(f"  Libreria nbtlib non disponibile. Uso nome cartella '{folder_name}'.")


                # Aggiungi le informazioni del mondo alla lista
                worlds.append({
                    'folder_name': folder_name, # Nome cartella originale
                    'world_name': world_name,   # Nome letto da NBT o nome cartella
                    'full_path': item_path      # Percorso completo della cartella mondo
                })

    except OSError as e_list:
        logging.error(f"Errore durante la lettura della cartella saves '{saves_folder_path}': {e_list}")
    except Exception as e_main:
         logging.error(f"Errore imprevisto durante l'elenco dei mondi Minecraft: {e_main}", exc_info=True)


    logging.info(f"Trovati {len(worlds)} mondi Minecraft.")
    # Opzionale: ordina i mondi per nome visualizzato
    worlds.sort(key=lambda w: w['world_name'].lower())
    return worlds
