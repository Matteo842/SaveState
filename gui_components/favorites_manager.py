# favorites_manager.py
# -*- coding: utf-8 -*-

import os
import json
import logging
import config # Importa config per ottenere la cartella dati

# --- Nome e Percorso del File dei Preferiti ---
FAVORITES_FILENAME = "favorites_status.json"
APP_DATA_FOLDER = config.get_app_data_folder() # Usa la stessa funzione di config
if APP_DATA_FOLDER:
    FAVORITES_FILE_PATH = os.path.join(APP_DATA_FOLDER, FAVORITES_FILENAME)
else:
    # Fallback se non si trova la cartella dati
    logging.error("Impossibile determinare APP_DATA_FOLDER per i preferiti. Uso percorso relativo.")
    FAVORITES_FILE_PATH = os.path.abspath(FAVORITES_FILENAME)
logging.info(f"Percorso file preferiti in uso: {FAVORITES_FILE_PATH}")
# --- Fine Definizione Percorso ---

_favorites_cache = {} # Cache interna per evitare letture disco continue
_cache_loaded = False # Flag per sapere se la cache è stata caricata

def load_favorites():
    """Carica lo stato dei preferiti da FAVORITES_FILE_PATH.
       Restituisce un dizionario {profile_name: bool}.
    """
    global _favorites_cache, _cache_loaded
    if _cache_loaded:
         #logging.debug("Restituzione cache preferiti.")
         return _favorites_cache.copy() # Restituisce una copia della cache

    favorites_status = {}
    if os.path.exists(FAVORITES_FILE_PATH):
        try:
            with open(FAVORITES_FILE_PATH, 'r', encoding='utf-8') as f:
                favorites_status = json.load(f)
            if not isinstance(favorites_status, dict):
                 logging.warning(f"File preferiti '{FAVORITES_FILE_PATH}' non contiene un dizionario valido. Reset.")
                 favorites_status = {}
            # Verifica che i valori siano booleani (opzionale ma consigliato)
            #for key, value in list(favorites_status.items()):
            #    if not isinstance(value, bool):
            #        logging.warning(f"Valore non booleano per '{key}' nel file preferiti. Rimosso.")
            #        del favorites_status[key]

            logging.info(f"Caricati {len(favorites_status)} stati preferiti da '{FAVORITES_FILE_PATH}'.")
        except json.JSONDecodeError:
            logging.warning(f"File preferiti '{FAVORITES_FILE_PATH}' corrotto o vuoto. Reset.")
            favorites_status = {}
        except Exception as e:
            logging.error(f"Errore durante il caricamento dei preferiti da '{FAVORITES_FILE_PATH}': {e}")
            favorites_status = {}
    else:
        logging.info(f"File preferiti '{FAVORITES_FILE_PATH}' non trovato. Inizio con lista vuota.")

    _favorites_cache = favorites_status.copy() # Aggiorna la cache
    _cache_loaded = True
    return favorites_status # Restituisce il dizionario appena caricato

def save_favorites(favorites_dict):
    """Salva il dizionario dello stato dei preferiti in FAVORITES_FILE_PATH.
       Restituisce True se il salvataggio ha successo, False altrimenti.
    """
    global _favorites_cache
    if not isinstance(favorites_dict, dict):
        logging.error("Tentativo di salvare uno stato preferiti non valido (non un dizionario).")
        return False
    try:
        # Assicura che la directory esista
        os.makedirs(os.path.dirname(FAVORITES_FILE_PATH), exist_ok=True)
        with open(FAVORITES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(favorites_dict, f, indent=4, ensure_ascii=False)
        logging.info(f"Salvati {len(favorites_dict)} stati preferiti in '{FAVORITES_FILE_PATH}'.")
        _favorites_cache = favorites_dict.copy() # Aggiorna la cache DOPO il salvataggio riuscito
        return True
    except Exception as e:
        logging.error(f"Errore durante il salvataggio dei preferiti in '{FAVORITES_FILE_PATH}': {e}")
        return False

def is_favorite(profile_name):
    """Controlla se un profilo è preferito (carica se necessario)."""
    favorites = load_favorites() # Usa la funzione che gestisce la cache
    return favorites.get(profile_name, False) # Default a False se non presente

def set_favorite_status(profile_name, is_fav):
    """Imposta lo stato preferito per un profilo e salva."""
    if not isinstance(is_fav, bool):
         logging.warning(f"Tentativo di impostare stato preferito non booleano ({is_fav}) per '{profile_name}'. Ignorato.")
         return False # Indica fallimento

    favorites = load_favorites() # Carica stato attuale (o cache)
    if favorites.get(profile_name) == is_fav:
         #logging.debug(f"Stato preferito per '{profile_name}' è già {is_fav}. Nessun salvataggio necessario.")
         return True # Nessun cambiamento, ma operazione "riuscita"

    favorites[profile_name] = is_fav
    logging.info(f"Impostato stato preferito per '{profile_name}' a {is_fav}.")
    return save_favorites(favorites) # Salva il dizionario aggiornato

def toggle_favorite(profile_name):
    """Inverte lo stato preferito per un profilo e salva."""
    favorites = load_favorites() # Carica stato attuale (o cache)
    current_status = favorites.get(profile_name, False)
    new_status = not current_status
    return set_favorite_status(profile_name, new_status) # Usa la funzione set per salvare

def remove_profile(profile_name):
    """Rimuove un profilo dal file dei preferiti (quando un profilo viene eliminato)."""
    favorites = load_favorites()
    if profile_name in favorites:
        del favorites[profile_name]
        logging.info(f"Rimosso '{profile_name}' dal file dei preferiti.")
        return save_favorites(favorites)
    #logging.debug(f"Tentativo di rimuovere profilo non preferito '{profile_name}'. Nessuna azione.")
    return True # Considera successo anche se non c'era