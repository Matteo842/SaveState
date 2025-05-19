# emulator_utils/sameboy_special_handler.py
# -*- coding: utf-8 -*-

import os
import logging
import zipfile
import shutil

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())  # Avoid 'No handler found' warnings

def handle_sameboy_restore(archive_path, destination_path):
    """
    Gestisce il ripristino speciale per i salvataggi di SameBoy.
    SameBoy salva i file nella stessa cartella delle ROM, ma i backup potrebbero
    contenere il percorso completo con la cartella 'GameBoyColor/' o simili.
    
    Args:
        archive_path: Percorso dell'archivio ZIP da ripristinare
        destination_path: Percorso di destinazione dove ripristinare il file
        
    Returns:
        (bool success, str message): Risultato dell'operazione
    """
    log.info(f"Handling special SameBoy restore from '{archive_path}' to '{destination_path}'")
    
    if not os.path.isfile(archive_path) or not zipfile.is_zipfile(archive_path):
        msg = f"ERROR: Invalid archive file: '{archive_path}'"
        log.error(msg)
        return False, msg
    
    try:
        # Estrai il nome del file di destinazione
        dest_filename = os.path.basename(destination_path)
        dest_dir = os.path.dirname(destination_path)
        
        # Assicurati che la directory di destinazione esista
        os.makedirs(dest_dir, exist_ok=True)
        
        # Apri l'archivio ZIP
        with zipfile.ZipFile(archive_path, 'r') as zipf:
            # Ottieni la lista dei file nell'archivio
            file_list = zipf.namelist()
            log.debug(f"Files in archive: {file_list}")
            
            # Cerca il file .sav nell'archivio
            target_file = None
            
            # Prima cerca una corrispondenza esatta
            if dest_filename in file_list:
                target_file = dest_filename
                log.debug(f"Found exact match: {target_file}")
            else:
                # Cerca il file con qualsiasi percorso
                for file_path in file_list:
                    if file_path.endswith(dest_filename):
                        target_file = file_path
                        log.debug(f"Found match with path: {target_file}")
                        break
            
            if target_file:
                # Estrai il file nella destinazione
                log.info(f"Extracting '{target_file}' to '{destination_path}'")
                with zipf.open(target_file) as source, open(destination_path, 'wb') as target:
                    shutil.copyfileobj(source, target)
                return True, f"Successfully restored '{dest_filename}' from archive"
            else:
                msg = f"ERROR: Could not find '{dest_filename}' in the archive"
                log.error(msg)
                return False, msg
    
    except Exception as e:
        msg = f"ERROR during SameBoy special restore: {e}"
        log.error(msg, exc_info=True)
        return False, msg
