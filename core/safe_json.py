# safe_json.py
# -*- coding: utf-8 -*-
"""Scrittura sicura dei file JSON di SaveState.

Il file vero viene sostituito solo quando il nuovo contenuto è già stato
scritto per intero su disco. Se qualcosa va storto (un valore che non si
può salvare, un crash, la corrente che salta) resta il file vecchio, intatto.
"""
import json
import os
import time
import uuid


def write_json_safely(path, data, indent=4, ensure_ascii=True, attempts=5, pause_seconds=0.1):
    """Scrive `data` come JSON in `path` senza mai lasciare un file a metà.

    Se fallisce solleva l'eccezione (come faceva il vecchio open + json.dump)
    e il file che c'era prima resta com'era.
    """
    # 1. Trasforma i dati in testo PRIMA di toccare il disco:
    #    se un valore non si può salvare in JSON, l'errore arriva qui e il file vero non viene toccato.
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)

    # 2. Scrive il testo in un file temporaneo nella STESSA cartella del file vero
    #    e si assicura che sia davvero finito sul disco (flush + fsync).
    temp_path = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

        # 3. Mette il file temporaneo al posto di quello vero in un solo passo.
        #    Su Windows può fallire per un attimo se un altro programma (antivirus,
        #    OneDrive...) tiene aperto il file: in quel caso riprova qualche volta.
        for attempt in range(attempts):
            try:
                os.replace(temp_path, path)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(pause_seconds)
    except BaseException:
        # Qualcosa è andato storto: elimina il temporaneo, il file vecchio resta intatto.
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
