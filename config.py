# config.py
import os
import logging
import platform # Aggiunto per system detection


# --- Nome Applicazione (per cartella AppData) ---
APP_NAME = "SaveState"

# --- Funzione per Trovare/Creare Cartella Dati App ---
def get_app_data_folder():
    """Restituisce il percorso della cartella dati dell'app (%LOCALAPPDATA% su Win)
       e la crea se non esiste. Gestisce fallback basici."""
    system = platform.system()
    base_path = None
    app_folder = None # Inizializza a None

    try:
        if system == "Windows":
            base_path = os.getenv('LOCALAPPDATA')
        elif system == "Darwin": # macOS
            base_path = os.path.expanduser('~/Library/Application Support')
        elif system == "Linux":
             # Standard XDG Base Directory Specification
             xdg_data_home = os.getenv('XDG_DATA_HOME', os.path.expanduser('~/.local/share'))
             base_path = xdg_data_home # Mettiamo direttamente qui

        if not base_path:
             logging.error("Impossibile determinare la cartella dati utente standard. Uso la cartella corrente come fallback.")
             # Fallback alla cartella corrente se non troviamo un percorso standard
             app_folder = os.path.abspath(APP_NAME) # Crea sottocartella APP_NAME anche qui
        else:
             app_folder = os.path.join(base_path, APP_NAME)

        # Crea la cartella se non esiste
        if not os.path.exists(app_folder):
             try:
                 os.makedirs(app_folder, exist_ok=True)
                 logging.info(f"Creata cartella dati applicazione: {app_folder}")
             except OSError as e:
                 # Se non possiamo creare la cartella, logga errore ma restituisci comunque
                 # il percorso tentato. Le funzioni load/save gestiranno l'errore.
                 logging.error(f"Impossibile creare cartella dati {app_folder}: {e}.")

    except Exception as e:
         logging.error(f"Errore imprevisto in get_app_data_folder: {e}. Tentativo fallback CWD.", exc_info=True)
         # Fallback estremo alla cartella corrente
         app_folder = os.path.abspath(APP_NAME)
         # Prova a creare anche qui per sicurezza
         try:
             os.makedirs(app_folder, exist_ok=True)
         except OSError:
             pass # Ignora se anche questo fallisce

    return app_folder # Restituisce il percorso calcolato (o fallback)

# --- Impostazioni Generali (quelle che c'erano già) ---
BACKUP_BASE_DIR = r"D:\GameSaveBackups"
MAX_BACKUPS = 3
MIN_FREE_SPACE_GB = 2

# --- Heuristic Search Configuration ---
# Lista di sottocartelle comuni usate per i salvataggi
COMMON_SAVE_SUBDIRS = [
    'Saves', 'Save', 'SaveGame', 'Saved', 'SaveGames',
    'savegame', 'savedata', 'save_data', 'SaveData'
    # Aggiungi altre se necessario
]

# Lista di nomi di publisher comuni usati come cartelle genitore
COMMON_PUBLISHERS = [
    'My Games', # Cartella genitore comune
    # Aggiungi nomi di publisher reali se noti pattern
    # es., 'Ubisoft', 'Rockstar Games', 'WB Games', 'DevolverDigital'
]

# Set di estensioni file comuni per i salvataggi
COMMON_SAVE_EXTENSIONS = {
    '.sav', '.save', '.dat', '.bin', '.slot', '.prof', '.profile', '.usr', '.sgd'
    # Aggiungi altre se necessario
}

# Set di sottostringhe comuni trovate nei nomi dei file di salvataggio
COMMON_SAVE_FILENAMES = {
    'save', 'user', 'profile', 'settings', 'config', 'game', 'player', 'slot', 'progress'
    # Aggiungi altre se necessario
}

# Set di parole da ignorare quando si confrontano nomi di giochi/cartelle per similarità
SIMILARITY_IGNORE_WORDS = {
    'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade', 'edition', 'goty',
    'demo', 'trial', 'play', 'launch', 'definitive', 'enhanced', 'complete',
    'collection', 'hd', 'ultra', 'deluxe', 'game', 'year', 'server', 'client',
    'directx', 'redist', 'sdk', 'runtime'
    # Aggiungi altre se necessario
}

# Set di nomi di cartelle (minuscolo) da ignorare sempre durante la ricerca esplorativa
# (Evita ricerche dentro cartelle di sistema/applicazioni irrilevanti)
BANNED_FOLDER_NAMES_LOWER = {
     "microsoft", "nvidia corporation", "intel", "amd", "google", "mozilla",
     "common files", "internet explorer", "windows", "system32", "syswow64",
     "program files", "program files (x86)", "programdata", "drivers",
     "perflogs", "dell", "hp", "lenovo", "avast software", "avg",
     "kaspersky lab", "mcafee", "adobe", "python", "java", "oracle", "steam",
     "$recycle.bin", "config.msi", "system volume information",
     "default", "all users", "public", "vortex", "soundtrack",
     "artbook", "extras", "dlc", "ost", "digital Content",
     # Aggiungi launcher/manager se causano problemi
     "epic games", "ubisoft game launcher", "battle.net", "origin", "gog galaxy",
     # Cartelle cache comuni
     "cache", "shadercache", "gpucache", "webcache", "log", "logs", "crash", "crashes",
     "temp", "tmp"
}
# ==================================

# Stile QSS per il tema scuro (può essere spostato in un file .qss separato)
DARK_THEME_QSS = """
QWidget {
    background-color: #2D2D2D; /* Grigio scuro Pokédex */
    color: #F0F0F0; /* Testo quasi bianco */
    font-family: 'Segoe UI', Arial, sans-serif; /* Font pulito */
    font-size: 10pt;
    outline: 0;
}
QMainWindow {
    background-color: #1E1E1E; /* Sfondo ancora più scuro per finestra principale */
}
QLabel {
    background-color: transparent;
    color: #E0E0E0;
}
QLabel#StatusLabel { /* Etichetta di stato specifica */
    color: #A0A0A0;
}
QLineEdit, QTextEdit, QListWidget, QTableWidget, QComboBox, QSpinBox {
    background-color: #3C3C3C; /* Grigio leggermente più chiaro per input/liste */
    color: #F0F0F0;
    border: 1px solid #555555;
    border-radius: 3px;
    padding: 3px;
}
QListWidget::item {
    padding: 3px;
}
QListWidget::item:selected {
    background-color: #CC0000; /* Rosso acceso Pokédex per selezione */
    color: #FFFFFF;
}
QPushButton {
    background-color: #4A4A4A; /* Grigio medio per pulsanti */
    color: #F0F0F0;
    border: 1px solid #666666;
    border-radius: 4px;
    padding: 6px 12px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #5A5A5A;
    border: 1px solid #888888;
}
QPushButton:pressed {
    background-color: #404040;
}
QPushButton:disabled {
    background-color: #3A3A3A;
    color: #777777;
    border-color: #555555;
}
QPushButton#DangerButton { /* Bottone speciale per azioni pericolose (es. Ripristina) */
    background-color: #AA0000; /* Rosso scuro */
    color: white;
    font-weight: bold;
}
QPushButton#DangerButton:hover {
    background-color: #CC0000; /* Rosso acceso */
}
QPushButton#DangerButton:pressed {
    background-color: #880000;
}
/* --- NUOVE REGOLE SEMPLIFICATE PER QGroupBox --- */
QGroupBox {
    background-color: transparent; /* <-- AGGIUNGI (come tema chiaro) */
    /* Bordi Espliciti */
    border-top: 1px solid #555555;
    border-right: 1px solid #555555;
    border-bottom: 1px solid #555555;
    border-left: 1px solid #555555;
    border-radius: 4px;
    /* Spaziatura (come tema chiaro) */
    margin-top: 10px;
    padding-top: 10px;     /* <-- AGGIUNGI (come tema chiaro) */
    /* Aggiungi altri padding se necessario per coerenza col chiaro */
    padding-left: 5px;
    padding-right: 5px;
    padding-bottom: 5px;

    font-weight: bold;
    color: #E0E0E0;
}

QGroupBox::title {
    subcontrol-origin: margin;      /* Come tema chiaro */
    subcontrol-position: top left;  /* Come tema chiaro */
    padding: 0 5px;             /* Come tema chiaro */
    /* background-color: #2D2D2D; */ /* <-- RIMUOVI/COMMENTA (come tema chiaro) */
    left: 10px;            /* Come tema chiaro */
    color: #CC0000;             /* Colore titolo scuro */
}
/* --- FINE NUOVE REGOLE --- */
QStatusBar {
    color: #A0A0A0;
}
QStatusBar::item {
    border: none; /* Nessun bordo tra messaggi status bar */
}
QProgressBar {
    border: 1px solid #555;
    border-radius: 3px;
    text-align: center;
    color: #F0F0F0;
}
QProgressBar::chunk {
    background-color: #CC0000; /* Barra progresso rossa */
    width: 10px; /* Larghezza blocchetti barra */
    margin: 1px;
}
QMessageBox {
    background-color: #3C3C3C;
}

QMessageBox {
    background-color: #3C3C3C; /* Sfondo scuro per il box */
}

/* Modifica questa regola esistente */
QMessageBox QLabel {
     color: #F0F0F0;         /* Testo chiaro */
     /* AUMENTA IL FONT */
     font-size: 11pt;        /* Prova 11pt (o 12pt se preferisci ancora più grande) */
     /* RIMUOVI O Riduci min-width: questo permette al box di adattarsi meglio al testo */
     /* min-width: 300px; */ /* Commenta o elimina questa riga */
     padding-left: 5px;      /* Aggiunge un piccolo spazio a sinistra del testo (opzionale) */
     /* Aggiungi un minimo di altezza se il testo sembra schiacciato verticalmente? */
     /* min-height: 40px; */ /* Opzionale, da testare */
}

/* Opzionale: Riduci un po' i pulsanti dentro i MessageBox se sembrano troppo grandi */
QMessageBox QPushButton {
    min-width: 70px; /* Larghezza minima ridotta */
    padding: 4px 10px; /* Padding ridotto */
}

/* Stile specifico per gli item/celle */
QTableWidget::item {
    padding: 4px;           /* Un po' di spazio interno */
    color: #F0F0F0;         /* Colore testo chiaro (conferma) */
    border-bottom: 1px solid #4A4A4A; /* Separa righe se vuoi (alternativa a gridline) */
    /* border: none; */ /* Assicura nessun bordo extra per item */
}

/* Stile per item selezionati */
QTableWidget::item:selected {
    background-color: #CC0000; /* Rosso Pokédex per selezione */
    color: #FFFFFF;          /* Testo bianco su selezione */
}

/* Stile per le Intestazioni (Header) */
QHeaderView::section {
    background-color: #1E1E1E; /* Sfondo intestazione molto scuro */
    color: #EAEAEA;          /* Testo intestazione chiaro */
    padding: 4px;
    border-top: 0px;         /* Rimuovi bordi header se vuoi look pulito */
    border-bottom: 1px solid #CC0000; /* Bordo rosso sotto header */
    border-right: 1px solid #4A4A4A;
    border-left: 0px;
    font-weight: bold;        /* Grassetto */
}

/* Stile per ultima sezione header (opzionale, per non avere doppio bordo) */
QHeaderView::section:last {
    border-right: 0px;
}

QPushButton#ThemeToggleButton,
QPushButton#LogToggleButton {
    border: none;                /* Nessun bordo */
    background-color: transparent; /* Sfondo trasparente */
    padding: 2px;               /* Padding piccolo */
    margin: 1px;                /* Margine piccolo per spaziatura */
    min-width: none;            /* ANNULLA min-width generale */
    /* La dimensione è gestita da setFixedSize(24,24) in Python */
}
/* Effetti Hover/Pressed (Opzionali, uguali per entrambi) */
QPushButton#ThemeToggleButton:hover,
QPushButton#LogToggleButton:hover {
    background-color: #5A5A5A; /* Sfondo leggero al passaggio */
}
QPushButton#ThemeToggleButton:pressed,
QPushButton#LogToggleButton:pressed {
    background-color: #404040; /* Sfondo leggero alla pressione */
}

QPushButton#MinecraftButton {
    min-width: 25px;  /* Imposta min-width uguale a fixed size */
    max-width: 25px;  /* Imposta max-width uguale a fixed size */
    min-height: 25px; /* Imposta min-height uguale a fixed size */
    max-height: 25px; /* Imposta max-height uguale a fixed size */
    padding: 3px;     /* Padding piccolo e UGUALE su tutti i lati */
    /* Non impostiamo border o background-color qui,
       così eredita l'aspetto standard dal QPushButton generale */
}
/* Manteniamo gli effetti standard se li vogliamo */
QPushButton#MinecraftButton:hover {
    background-color: #5A5A5A;
    border: 1px solid #888888; /* Potrebbe essere necessario specificare anche il bordo qui */
}
QPushButton#MinecraftButton:pressed {
    background-color: #404040;
}


/* Aggiungere stili per altri widget se necessario (QDialog, QInputDialog etc.) */

QPushButton#ShortcutButton {
    border: none;               /* Nessun bordo */
    background-color: transparent; /* Sfondo trasparente */
    padding: 1px;               /* Padding minimo per icona */
    margin: 1px;                /* Margine piccolo */
    min-width: none;            /* Ignora larghezza minima generale */
    /* La dimensione 24x24 è impostata da Python */
}
QPushButton#ShortcutButton:hover {
    background-color: #5A5A5A; /* Grigio scuro al passaggio */
}
QPushButton#ShortcutButton:pressed {
    background-color: #404040; /* Leggermente più scuro alla pressione */
}

"""

LIGHT_THEME_QSS = """
QWidget {
    background-color: #F0F0F0; /* Sfondo base: Grigio Molto Chiaro */
    color: #1E1E1E;          /* Testo base: Quasi Nero */
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 10pt;
    outline: 0; /* Rimuove bordo focus */
}
QMainWindow {
    background-color: #EAEAEA; /* Sfondo finestra leggermente diverso */
}
QLabel {
    background-color: transparent; /* Assicura sfondo trasparente per Label semplici */
    color: #1E1E1E;
}
QLabel#StatusLabel {
    color: #555555; /* Grigio medio per status bar */
}
QLineEdit, QTextEdit, QListWidget, QTableWidget, QComboBox, QSpinBox {
    background-color: #dedede; /* Sfondo Bianco per campi input/liste */
    color: #1E1E1E;          /* Testo Nero */
    border: 1px solid #AAAAAA; /* Bordo Grigio Chiaro */
    border-radius: 3px;
    padding: 3px;
}
QTableWidget {
    gridline-color: #D0D0D0; /* Griglia Chiara */
    /* alternate-background-color: #F8F8F8; */ /* Righe alternate molto leggere */
}
QListWidget::item, QTableWidget::item {
    padding: 4px;
    color: #1E1E1E; /* Testo Nero */
    border-bottom: 1px solid #E0E0E0; /* Separatore riga chiaro */
    /* border: none; */
}
QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #20B2AA; /* <<< ACCENTO CIANO (LightSeaGreen) >>> */
    color: #FFFFFF;          /* Testo Bianco su selezione */
}
QPushButton {
    background-color: #E1E1E1; /* Grigio chiaro base per pulsanti */
    color: #1E1E1E;          /* Testo Nero */
    border: 1px solid #AAAAAA;
    border-radius: 4px;
    padding: 6px 12px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #DCDCDC; /* Più chiaro al passaggio */
    border: 1px solid #888888;
}
QPushButton:pressed {
    background-color: #C8C8C8; /* Più scuro quando premuto */
}
QPushButton:disabled {
    background-color: #E8E8E8;
    color: #999999;
    border-color: #BBBBBB;
}
QPushButton#DangerButton { /* Pulsante pericoloso (es. Ripristina, Elimina) */
    background-color: #E57373; /* Rosso chiaro/desaturato */
    color: #FFFFFF;          /* Testo Bianco */
    font-weight: bold;
}
QPushButton#DangerButton:hover {
    background-color: #EF5350; /* Rosso più acceso */
}
QPushButton#DangerButton:pressed {
    background-color: #D32F2F; /* Rosso più scuro */
}
QGroupBox {
    background-color: transparent; /* Rende sfondo gruppo trasparente */
    border: 1px solid #C0C0C0;   /* Bordo grigio chiaro */
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 10px; /* Aggiunge padding sopra per non sovrapporre titolo */
    font-weight: bold;
    color: #1E1E1E; /* Testo titolo scuro */
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    /* Rimuoviamo sfondo esplicito per il titolo, eredita quello del parent */
    /* background-color: #F0F0F0; */
    left: 10px;
    color: #007c8e; /* <<< ACCENTO CIANO/TEAL più scuro per leggibilità su chiaro >>> */
}
QStatusBar {
    color: #555555;
}
QStatusBar::item {
    border: none;
}
QProgressBar {
    border: 1px solid #AAAAAA;
    border-radius: 3px;
    text-align: center;
    color: #1E1E1E; /* Testo scuro */
    background-color: #FFFFFF; /* Sfondo bianco per contrasto */
}
QProgressBar::chunk {
    background-color: #20B2AA; /* <<< ACCENTO CIANO >>> */
    width: 10px;
    margin: 1px;
}
QMessageBox {
    background-color: #FFFFFF; /* Sfondo bianco */
}
QMessageBox QLabel {
     color: #1E1E1E; /* Testo scuro */
     font-size: 11pt;
     /* min-width: 250px; */ /* Rimosso min-width per adattabilità */
     padding-left: 5px;
}
QHeaderView::section { /* Intestazioni chiare */
    background-color: #EAEAEA;
    color: #1E1E1E;
    padding: 4px;
    border-top: 0px;
    border-bottom: 1px solid #007c8e; /* Bordo ciano/teal sotto header */
    border-right: 1px solid #D0D0D0;
    border-left: 0px;
    font-weight: bold;
}
QHeaderView::section:last {
    border-right: 0px;
}

QPushButton#ThemeToggleButton,
QPushButton#LogToggleButton {
    border: none;
    background-color: transparent;
    padding: 2px;
    margin: 1px;
    min-width: none; /* ANNULLA min-width generale */
    /* La dimensione è gestita da setFixedSize(24,24) in Python */
}
/* Effetti Hover/Pressed (Opzionali, uguali per entrambi) */
QPushButton#ThemeToggleButton:hover,
QPushButton#LogToggleButton:hover {
    background-color: #DCDCDC; /* Sfondo leggero chiaro al passaggio */
}
QPushButton#ThemeToggleButton:pressed,
QPushButton#LogToggleButton:pressed {
    background-color: #C8C8C8; /* Sfondo leggero chiaro alla pressione */
}

QPushButton#MinecraftButton {
    min-width: 25px;
    max-width: 25px;
    min-height: 25px;
    max-height: 25px;
    padding: 3px; /* Padding piccolo e UGUALE */
    /* Eredita aspetto standard */
}
QPushButton#MinecraftButton:hover {
    background-color: #DCDCDC;
    border: 1px solid #888888; /* Potrebbe servire anche qui */
}
QPushButton#MinecraftButton:pressed {
    background-color: #C8C8C8;
}

QPushButton#ShortcutButton {
    border: none;               /* Nessun bordo */
    background-color: transparent; /* Sfondo trasparente */
    padding: 1px;               /* Padding minimo per icona */
    margin: 1px;                /* Margine piccolo */
    min-width: none;            /* Ignora larghezza minima generale */
    /* La dimensione 24x24 è impostata da Python */
}
QPushButton#ShortcutButton:hover {
    background-color: #DCDCDC; /* Grigio chiaro al passaggio */
}
QPushButton#ShortcutButton:pressed {
    background-color: #C8C8C8; /* Leggermente più scuro alla pressione */
}

"""
# --- FINE NUOVE REGOLE ---
# --- FINE CONFIGURAZIONE ---

# Verifica percorsi base all'import
if not os.path.exists(os.path.dirname(BACKUP_BASE_DIR)) and BACKUP_BASE_DIR.count(os.sep) > 1:
    logging.warning(f"La cartella parente di BACKUP_BASE_DIR ('{os.path.dirname(BACKUP_BASE_DIR)}') non sembra esistere.")