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

# Lista di sottocartelle comuni usate SPECIFICAMENTE per contenere i file di salvataggio
# all'interno della cartella principale del gioco o del publisher.
COMMON_SAVE_SUBDIRS = [
    # I più comuni (con variazioni maiuscolo/minuscolo/spazi)
    'Save',
    'Saves',
    'save',
    'saves',
    'Saved',
    'saved',
    'SaveGame',
    'SaveGames',
    'savegame',
    'savegames',
    'GameSave', # Invertito
    'GameSaves', # Invertito
    'Saved Games', # Meno comune come sottocartella, più come genitore, ma includiamolo
    'saved games',
    'SaveData',
    'Save Data', # Con spazio
    'savedata',
    'save_data', # Con underscore

    # Legati a profili/slot
    'Profiles',
    'Profile',
    'profiles',
    'profile',
    'User', # A volte usato
    'Users',
    'Player', # Meno comune, ma possibile
    'Slots',
    'slots',

    # Usati da alcuni giochi specifici / engine
    'data', # A volte contiene salvataggi, ma può essere ambiguo
    'UserData', # Comune in alcuni contesti Steam/Source engine?
    'PlayerProfiles',
    'remote', # Specifico per Steam Userdata, ma a volte replicato altrove
    'GameData', # Simile a SaveData

    # Aggiungi qui altri nomi specifici che potresti incontrare
]

# Lista di nomi di publisher comuni usati come cartelle genitore
COMMON_PUBLISHERS = [
    # Generici / Standard Windows
    'My Games',
    'Saved Games',
    'MyGames', # Variazione comune

    # Publisher/Sviluppatori Maggiori (con varianti comuni)
    'Ubisoft',
    'EA',
    'Electronic Arts',
    'EA Games',
    'Rockstar Games',
    'Bethesda Softworks',
    'Bethesda',
    'CD Projekt Red',
    'CDProjektRed', # Variazione comune
    'Square Enix',
    'Activision',
    'Valve',
    'Epic Games',
    'FromSoftware',
    'Capcom',
    'Sega',
    'Bandai Namco',
    'BANDAI NAMCO Entertainment', # Spesso usato come nome cartella
    'DevolverDigital',
    'Devolver Digital',
    '2K Games',
    '2K',
    'Paradox Interactive',
    'Team17',
    'Focus Home Interactive',
    'Focus Entertainment', # Rebranding
    'HelloGames',
    'Hello Games',
    'Warner Bros. Interactive Entertainment',
    'Warner Bros. Games',
    'WB Games',
    'Team Cherry', # Esempio specifico (Hollow Knight)
    'Landfall Games',
    'Microsoft Studios', # Anche se meno comune per savegames diretti qui
    'XboxGamesStudios', # Meno probabile ma possibile
    'Mojang Studios', # Minecraft (anche se ha percorsi specifici)
    'Sony Interactive Entertainment', # Meno comune su PC, ma possibile
    'Koei Tecmo',
    'KOEI TECMO GAMES CO., LTD.', # A volte nomi lunghi
    'Konami',
    'Konami Digital Entertainment',
    'THQ Nordic',
    'Embracer Group', # Gruppo che possiede THQ etc.
    'Gearbox Publishing',
    'Gearbox Software',
    'Deep Silver', # Parte di Plaion/Embracer
    'Plaion', # Nuovo nome di Koch Media
    'Koch Media', # Vecchio nome
    'Annapurna Interactive',
    'Atari',
    'Blizzard Entertainment', # Spesso ha cartelle dedicate
    'Bungie',
    'CI Games',
    'Crytek',
    'Daedalic Entertainment',
    'Disney Interactive', # Meno comune ora?
    'Double Fine Productions',
    'Frontier Developments',
    'GOG.com', # A volte salva giochi GOG in una cartella specifica qui
    'Humble Games',
    'IO Interactive',
    'Kalypso Media',
    'Marvelous',
    'Nacon',
    'NCSOFT',
    'Nexon',
    'NIS America',
    'Obsidian Entertainment',
    'Playtonic Games',
    'Private Division', # Etichetta di Take-Two
    'Raw Fury',
    'Rebellion',
    'Remedy Entertainment',
    'Riot Games',
    'Shiro Games',
    'SNK CORPORATION',
    'Spike Chunsoft',
    'Stardock Entertainment',
    'Starbreeze Studios',
    'Take-Two Interactive', # Genitore di Rockstar, 2K
    'TellTale Games', # Ricorda di includere anche possibili nomi per giochi episodici
    'tinyBuild',
    'Tripwire Interactive',
    'Unknown Worlds Entertainment',
    'Versus Evil',
    'WayForward',
    'Wizards of the Coast',
    'Xbox Game Studios', # Alternativa
    'Yacht Club Games',
    'Ys Net',
    'Zen Studios',
    'KojimaProductions', # Death Stranding
    'Respawn', # Starwars
    'BioWare', # Mass Effect
    'id Software', # Doom
    'MachineGames', # wolfenstein
    'Moon Studios', # no rest for the wicked, Ori saga
    'ShooterGame', # ARK saga

    # Altri comuni trovati in AppData/Documents
    '11 bit studios',
    'Coffee Stain Studios', # O 'CoffeeStainStudios'
    ' ConcernedApe', # Stardew Valley
    'Dontnod Entertainment',
    'Egosoft', # Serie X
    'Failbetter Games', # Sunless Sea/Skies
    'Gaslamp Games', # Dungeons of Dredmor
    'Introversion Software', # Prison Architect
    'Klei Entertainment', # Don't Starve, Oxygen Not Included
    'klei'
    'Larian Studios', # Divinity, Baldur's Gate 3
    'Motion Twin', # Dead Cells
    'Ninja Kiwi', # Bloons
    'Pocketwatch Games', # Monaco
    'Red Hook Studios', # Darkest Dungeon
    'Re-Logic', # Terraria
    'Runic Games', # Torchlight
    'Subset Games', # FTL, Into the Breach
    'Supergiant Games', # Bastion, Hades
    'ZAUM', # Disco Elysium
    'sandfall', # Expedition 33
    'RedCandleGames' # Nine Souls
    'Studio MDHR', # Cuphead
    'Dogubomb', # BluePrince
    'Pineapple', # Spongebob
    'Stunlock Studios', # V rinsing
    'Noble Muffins', # thief simulator
    'Ocellus', # MARSUPILAMI
    'Steel Crate Games', # keep talking and nobody explode

    # Aggiungi qui altri nomi che ti vengono in mente o che noti mancare!
]

# Set di estensioni file comuni (minuscolo, con punto iniziale)
# usate per i file di salvataggio dei giochi.
COMMON_SAVE_EXTENSIONS = {
    '.sav',        # La più classica (Save)
    '.save',       # Variante comune
    '.dat',        # Generica, ma usatissima (Data)
    '.bin',        # Generica binaria, a volte usata
    '.slot',       # Per salvataggi basati su slot
    '.prof',       # Profile
    '.profile',    # Profile
    '.usr',        # User data
    '.sgd',        # Steam Game Data? (Specifico a volte)
    '.json',       # Usata da alcuni giochi moderni/indie (es. Minecraft per alcuni dati)
    '.xml',        # Meno comune per salvataggi binari, ma usata per dati strutturati
    '.bak',        # A volte usato come estensione per backup automatici interni
    '.tmp',        # Raramente, ma alcuni giochi salvano temporanei che diventano save
    '.gam',        # Usato da alcuni giochi più vecchi (Game)
    '.ess',        # Skyrim Special Edition Save
    '.fos',        # Fallout Save
    '.lsf',        # Larian Studios Format (Divinity: Original Sin 2)
    '.lsb',        # Larian Studios Format (Baldur's Gate 3?)
    '.db',         # Alcuni giochi usano database SQLite o simili
    '.ark',        # Usato da Ark: Survival Evolved

    # Estensioni Emulazione (se vuoi includerle, altrimenti rimuovile)
    '.srm',        # Save RAM (SNES, GBA, etc.)
    '.state',      # Save State (comune in molti emulatori)
    '.eep',        # EEPROM save (N64, GBA)
    '.fla',        # Flash RAM save (GBA)
    '.mc', '.mcr', # Memory Card (PS1/PS2)
    '.gci',        # GameCube Memory Card Image

    # Aggiungi altre estensioni specifiche che conosci o trovi
}

# Set di sottostringhe comuni (minuscole) trovate nei nomi dei file di salvataggio
# Usato per il check euristico del contenuto di una cartella
COMMON_SAVE_FILENAMES = {
    'save',        # save01.dat, gamesave.sav, quicksave
    'user',        # user.dat, user_profile.bin
    'profile',     # profile.sav, playerprofile
    'settings',    # settings.ini (a volte contiene progressi)
    'config',      # config.sav (raro ma possibile)
    'game',        # gamedata.bin
    'player',      # player.dat
    'slot',        # slot0.sav, save_slot_1
    'data',        # gamedata, savedata
    'progress',    # progress.dat
    'meta',        # save_meta.dat (file metadati)
    'header',      # saveheader.bin
    'info',        # gameinfo.sav
    'stats',       # playerstats.sav
    'world',       # world.sav (giochi sandbox/survival)
    'character',   # character1.sav
    'persistent',  # persistent.sfs (es. KSP)
    'quicksave',   # quicksave.sav
    'autosave',    # autosave.dat

    # Aggiungi altre parti comuni che noti
}

# Lista di sottocartelle comuni usate SPECIFICAMENTE per contenere i file di salvataggio
# all'interno della cartella principale del gioco o del publisher.
COMMON_SAVE_SUBDIRS = [
    # I più comuni (con variazioni maiuscolo/minuscolo/spazi)
    'Save',
    'Saves',
    'save',
    'saves',
    'Saved',
    'saved',
    'SaveGame',
    'SaveGames',
    'savegame',
    'savegames',
    'GameSave', # Invertito
    'GameSaves', # Invertito
    'Saved Games', # Meno comune come sottocartella, più come genitore, ma includiamolo
    'saved games',
    'SaveData',
    'Save Data', # Con spazio
    'savedata',
    'save_data', # Con underscore

    # Legati a profili/slot
    'Profiles',
    'Profile',
    'profiles',
    'profile',
    'User', # A volte usato
    'Users',
    'Player', # Meno comune, ma possibile
    'Slots',
    'slots',

    # Usati da alcuni giochi specifici / engine
    'data', # A volte contiene salvataggi, ma può essere ambiguo
    'UserData', # Comune in alcuni contesti Steam/Source engine?
    'PlayerProfiles',
    'remote', # Specifico per Steam Userdata, ma a volte replicato altrove
    'GameData', # Simile a SaveData

    # Aggiungi qui altri nomi specifici che potresti incontrare
]

# Set di nomi di cartelle (minuscolo) da ignorare sempre durante la ricerca esplorativa
# (Evita ricerche dentro cartelle di sistema/applicazioni/cache irrilevanti)
BANNED_FOLDER_NAMES_LOWER = {
     # Sistema Windows / Utente base
     "windows", "system32", "syswow64", "program files", "program files (x86)",
     "programdata", "intel", "amd", "nvidia", "nvidia corporation",
     "drivers", "$recycle.bin", "config.msi", "system volume information",
     "default", "all users", "public", "perflogs", "users",

     # Applicazioni Comuni / Microsoft
     "microsoft", "microsoft shared", "microsoft office", "office", "edge",
     "onedrive", "onedrivetemp", "skydrive", "internet explorer", "windows defender",
     "windows mail", "windows media player", "windows nt", "windowsapps",
     "microsoft games", # A meno che non si cerchino specificamente giochi MS Store datati

     # Browser / Internet
     "google", "chrome", "google drive", "mozilla", "firefox", "opera", "opera gx",
     "vivaldi", "brave-browser",

     # Sviluppo / Runtime
     "python", "java", "oracle", "jetbrains", "visual studio", "visual studio code",
     "msbuild", "nuget", "packages", ".vscode", ".idea", "node_modules", "common files",

     # Antivirus / Sicurezza
     "avast software", "avg", "kaspersky lab", "mcafee", "symantec", "norton",
     "eset", "malwarebytes", "windows defender advanced threat protection",

     # Hardware / OEM
     "dell", "hp", "lenovo", "asus", "acer", "msi", "realtek", "logitech",
     "corsair", "razer",

     # Launcher / Store Giochi (le cartelle principali, non le librerie giochi)
     "steam", "epic games", "epicgameslauncher", "ubisoft game launcher", "uplay",
     "battle.net", "blizzard entertainment", # A volte usato anche per saves, ma spesso separato
     "origin", "ea desktop", "gog galaxy", "itch", "xboxgames", "gamingservices",

     # Modding / Utility Giochi
     "vortex", "modorganizer", "nexus mod manager", "reshade", "flawless widescreen",
     "steam-tweaks", "steamgriddb", "nexus mods",

     # Cartelle Temporanee / Cache / Log Comuni
     "temp", "tmp", "cache", "shadercache", "gpucache", "webcache", "appcache",
     "log", "logs", "crash", "crashes", "crashdumps", "minidumps", "diagtrack",
     "installer", "installshield installation information", "package cache",

     # Multimedia / Altro
     "adobe", "discord", "spotify", "dropbox", "obs-studio", "zoom", "twitch",
     "nvidia broadcast", "wallpaper_engine", "soundtrack", "artbook", "extras",
     "dlc", "ost", "digital content", "common", # 'common' di Steam è escluso perché cerchiamo *dentro*

     # Aggiunte specifiche da log precedenti
     "pipelinecaches", "thirdparty", "platforms", "plugins", "binaries", "content",
     "programs", "runtime", "slatedebug", "nvidia", "crashreportclient",
     "movies", "paks", "splash", "config", # Se trovate come cartelle *genitore*
     "__pycache__", # Comune in progetti Python
     ".git", # Comune in progetti Git
     ".svn", # Comune in progetti SVN
}

# Set di parole (minuscole) da ignorare durante il confronto di similarità
# tra nomi di giochi e nomi di cartelle (fuzzy matching).
# Aiuta a ignorare termini comuni, edizioni, articoli, ecc.
SIMILARITY_IGNORE_WORDS = {
    # Articoli/Preposizioni/Congiunzioni comuni (inglese/italiano)
    'a', 'an', 'the', 'of', 'and', 'or', 'in', 'on', 'at', 'to', 'for', 'with',
    'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una', 'di', 'a', 'da', 'in',
    'con', 'su', 'per', 'tra', 'fra', 'e', 'o',

    # Titoli/Edizioni Comuni
    'game', 'edition', 'deluxe', 'ultimate', 'complete', 'collection', 'saga',
    'chronicles', 'anthology', 'trilogy', 'remastered', 'remaster', 'remake',
    'definitive', 'enhanced', 'extended', 'gold', 'platinum', 'standard',
    'collectors', "collector's", 'limited', 'special', 'goty', 'game of the year',
    'anniversary', 'legacy', 'hd', 'ultra', '4k', 'vr', 'digital',

    # Demo/Versioni
    'demo', 'trial', 'beta', 'alpha', 'preview', 'test', 'early access', 'full',

    # Azioni/Termini Tecnici
    'play', 'launch', 'launcher', 'start', 'server', 'client', 'update', 'patch',
    'directx', 'redist', 'runtime', 'sdk', 'pack', 'tools', 'bonus', 'content',
    'episode', 'chapter', 'part', 'book',

    # Numeri Romani Comuni (come parole separate)
    'i', 'ii', 'iii', 'iv', 'v', # Utili se "Final Fantasy VII Remake" vs "Final Fantasy 7" (7 non è qui)

    # Altri termini generici
    'official', 'soundtrack', 'artbook', 'dlc', # Anche se bannati come cartelle, meglio ignorarli anche nei nomi

    # Aggiungi altre parole che ritieni opportune
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