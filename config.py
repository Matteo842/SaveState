# config.py
import os
import logging
import platform # Aggiunto per system detection


# --- Nome Applicazione (per cartella AppData) ---
APP_NAME = "SaveState"
APP_VERSION = "2.5.0" # Restored APP_VERSION

# --- SINGLE INSTANCE CONSTANTS (defined here for early access before heavy imports) ---
import re  # Needed for sanitize_server_name

def sanitize_server_name(name):
    """
    Sanitizes server name to be compatible with Linux/Unix systems.
    Removes or replaces problematic characters that can cause issues with local sockets.
    """
    # Replace spaces with underscores
    name = name.replace(' ', '_')
    # Remove or replace other problematic characters, keeping only alphanumeric, underscores, hyphens, and dots
    name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', name)
    # Remove multiple consecutive underscores
    name = re.sub(r'_+', '_', name)
    # Remove leading/trailing underscores
    name = name.strip('_')
    return name

APP_GUID = "SaveState_App_Unique_GUID_6f459a83-4f6a-4e3e-8c1e-7a4d5e3d2b1a"
SHARED_MEM_KEY = sanitize_server_name(f"{APP_GUID}_SharedMem")
LOCAL_SERVER_NAME = sanitize_server_name(f"{APP_GUID}_LocalServer")
# --- END SINGLE INSTANCE CONSTANTS ---

# --- Funzione per Trovare/Creare Cartella Dati App ---
def get_app_data_folder():
    """Returns the path of the app's data folder (%LOCALAPPDATA% on Windows)
       and creates it if it doesn't exist. Handles basic fallbacks."""
    system = platform.system()
    base_path = None
    app_folder = None # Initialize to None

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
             logging.error("Unable to determine standard user data folder. Using current folder as fallback.")
             # Fallback to current folder if we can't find a standard path
             app_folder = os.path.abspath(APP_NAME) # Create APP_NAME subfolder here too
        else:
             app_folder = os.path.join(base_path, APP_NAME)

        # Crea la cartella se non esiste
        if not os.path.exists(app_folder):
             try:
                 os.makedirs(app_folder, exist_ok=True)
                 logging.info(f"Application data folder created: {app_folder}")
             except OSError as e:
                 # If we can't create the folder, log the error but still return
                 # the attempted path. The load/save functions will handle the error.
                 logging.error(f"Unable to create data folder {app_folder}: {e}.")

    except Exception as e:
         logging.error(f"Unexpected error in get_app_data_folder: {e}. Attempting CWD fallback.", exc_info=True)
         # Extreme fallback to current directory
         app_folder = os.path.abspath(APP_NAME)
         # Try to create here too for safety
         try:
             os.makedirs(app_folder, exist_ok=True)
         except OSError:
             pass # Ignore if this fails too

    return app_folder # Return the calculated path (or fallback)

# --- General Settings ---
# Function to determine the best default backup directory based on platform
def get_default_backup_dir():
    system = platform.system()
    if system == "Windows":
        # Check for available drives and suggest the most appropriate one
        available_drives = []
        for letter in "CDEFGHIJ":  # Common drive letters in priority order
            drive_path = f"{letter}:\\"
            if os.path.exists(drive_path):
                available_drives.append(letter)
        
        # If D: exists, use it as default, otherwise use the first available non-C drive or C if nothing else
        if "D" in available_drives:
            return r"D:\GameSaveBackups"
        elif len(available_drives) > 1:  # If there's any drive other than C
            for drive in available_drives:
                if drive != "C":  # Prefer any drive other than C
                    return fr"{drive}:\GameSaveBackups"  # Using fr-string to handle backslash correctly
        return r"C:\GameSaveBackups"  # Fallback to C drive if no better option
    
    elif system == "Linux":
        # Use standard Linux user directories
        home_dir = os.path.expanduser("~")
        return os.path.join(home_dir, "GameSaveBackups")
    
    else:  # macOS or other systems
        home_dir = os.path.expanduser("~")
        return os.path.join(home_dir, "GameSaveBackups")

# Default backup directory is now determined dynamically
BACKUP_BASE_DIR = get_default_backup_dir()
MAX_BACKUPS = 3
MIN_FREE_SPACE_GB = 2
MAX_SOURCE_SIZE_MB = 200  # Default max source size in MB for backups
COMPRESSION_MODE = "standard"  # Default compression mode: standard, fast, best, none

# List of common subdirectories SPECIFICALLY used to contain save files
# within the main game or publisher folder.
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
    'userdata', # Variante lowercase (es. Hytale)
    'PlayerProfiles',
    'remote', # Specifico per Steam Userdata, ma a volte replicato altrove
    'GameData', # Simile a SaveData

    # Linux / Wine / Proton specific additions
    'pfx', # Subdir in Steam compatdata for Proton prefix
    'drive_c', # Common in Wine/Proton prefixes
    'steamuser', # Common user name in Wine/Proton prefixes drive_c/users/
    'LocalLow', # Subfolder of AppData, often used by Unity games

    # Aggiungi qui altri nomi specifici che potresti incontrare
]

# <<< NUOVE LISTE PER LINUX >>>
LINUX_COMMON_SAVE_SUBDIRS = [
    # Comuni sotto .local/share/<GameName>/ o .config/<GameName>/ o direttamente in ~/.<gamename>
    'saves', 'Saves', 'save', 'Save', # Case variations
    'savegame', 'SaveGame', 'savegames', 'SaveGames',
    'data', 'Data', # Generico ma comune
    'gamedata', 'GameData',
    'userdata', 'UserData', 'user_data',
    'playerdata', 'PlayerData', 'player_data',
    'profile', 'Profile', 'profiles', 'Profiles',
    'slot', 'Slot', 'slots', 'Slots',
    'config', 'Config', # A volte i salvataggi sono qui
    'Saved', 'saved',
    # Specifici per alcuni engine/giochi su Linux
    'Godot', # Godot engine user data often in ~/.local/share/godot/app_userdata/[ProjectName]
    'unity3d', # Unity games often use ~/.config/[CompanyName]/[ProductName]
    'UnrealEngine',
    # Per Wine/Proton, molte delle voci di COMMON_SAVE_SUBDIRS sono valide, verranno unite dinamicamente
]

_COMMON_USER_FOLDERS_LINUX = [
    # Percorsi relativi alla home dell'utente o radici comuni
    ".local/share",      # XDG_DATA_HOME standard
    ".config",           # XDG_CONFIG_HOME standard
    ".var/app",          # Flatpak user data base (all'interno ci saranno ID app)
    ".steam/steam/steamapps/compatdata", # Steam Play (Proton) prefixes base
    ".steam/root/steamapps/compatdata",  # Variante comune per la base di Steam Play
    ".local/share/Steam/steamapps/compatdata", # Altra possibile locazione per Steam Play
    ".wine",             # Default Wine prefix (se non gestito da Proton/Lutris)
    "Games",             # Cartella comune per installazioni Lutris, Heroic etc.
    "snap",              # Base per Snap packages (all'interno ID app/common, etc)
    # Alcuni giochi più vecchi o indie potrebbero creare cartelle direttamente in home:
    # ".Ketchapp", ".StardewValley", etc. La home dir stessa ("~") viene aggiunta dinamicamente.
]

LINUX_KNOWN_SAVE_LOCATIONS = [
    # Percorsi XDG (più comuni, espansi da ~/.local/share o ~/.config)
    # Questi sono spesso le *basi* e il nome del gioco/publisher viene aggiunto dopo.
    "~/.local/share",
    "~/.config",
    # Steam / Proton (molto comune, la cartella appid sarà cercata all'interno)
    "~/.steam/steam/steamapps/compatdata",
    "~/.steam/root/steamapps/compatdata",
    "~/.local/share/Steam/steamapps/compatdata",
    # Lutris (comune per giochi non-Steam o GOG via Wine)
    "~/Games", # La struttura interna varia in base a come Lutris è configurato
    # Wine generico (se non gestito da Proton/Lutris)
    "~/.wine/drive_c/users/steamuser/Documents/My Games",
    "~/.wine/drive_c/users/steamuser/Saved Games",
    "~/.wine/drive_c/users/steamuser/AppData/Roaming",
    "~/.wine/drive_c/users/steamuser/AppData/Local",
    "~/.wine/drive_c/users/steamuser/Documents", # Documenti generici in Wine
    # Flatpak (la struttura interna è app_id/config o app_id/data)
    "~/.var/app",
    # Snap (la struttura interna varia, spesso ~/snap/game-name/common/ o current/)
    "~/snap",
    # Alcuni giochi potrebbero usare direttamente la home o sottocartelle dirette
    "~", # Home directory stessa, per giochi che creano cartelle come ~/.gamename
    # Esempi specifici noti (possono essere molti)
    "~/.godot/app_userdata", # Base per giochi Godot non Flatpak
    "~/.renpy", # Base per giochi Ren'Py
]
# <<< FINE NUOVE LISTE PER LINUX >>>

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
    'Bloober Team', # Layer of Fear

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
    'klei',
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
    'RedCandleGames', # Nine Souls
    'Studio MDHR', # Cuphead
    'Dogubomb', # BluePrince
    'Pineapple', # Spongebob
    'Stunlock Studios', # V rinsing
    'Noble Muffins', # thief simulator
    'Ocellus', # MARSUPILAMI
    'Steel Crate Games', # keep talking and nobody explode
    'AVGame', # vampyr
    'Flying Wild Hog', # Shadow Warrior series, Evil West
    'TSCGame', # The Sinking City
    'IronGate', # Valheim
    'Microids', # Syberia series
    'Phobia', # Carrion
    'Playdead', # Limbo, Inside
    'Atlas', # Little Nightmares
    'TheGameKitchen', # Blasphemous
    'DevolverDigital.WeirdWest', # Weird West
    'Acid Wizard Studios', # Darkwood
    'SunBorn', # Reverse Collapse
    'Hinterland', # The Long Dark
    'ProjectSnowfall', # Ghostwire Tokyo
    'Acid Nerve', # Death's Door
    'Coffee Stain Publishing', # Huntdown
    'DeadToast Entertainment', # My Friend Pedro
    'Doublefine', # Full Throttle Remastered
    'Kani', # Kill It with Fire
    'MonkeyGame', # Enslaved: Odyssey to the West
    'UnrealEngine3',
    'RedHook', # Darkest Dungeon
    'tinyBuild Games',
    'ZAUM Studio', # Disco Elysium
    'Nerial',
    'Two and Thirty Software',
    'nomada studio', # GRIS
    'NBGI', # DarkSouls Remastered
    'aspyr-media', # civilization 6
    'Ludeon Studios', # RimWorld
    'Dodge Roll', # enter the gungeon
    'Interplay', # fallout 1-2
    
    # Aggiungi qui altri nomi che ti vengono in mente o che noti mancare!
]

# Lista di estensioni file comuni (minuscolo, con punto iniziale)
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

    # Estensioni Emulazione
    '.srm',        # Save RAM (SNES, GBA, etc.)
    '.state',      # Save State (comune in molti emulatori)
    '.eep',        # EEPROM save (N64, GBA)
    '.fla',        # Flash RAM save (GBA)
    '.mc', '.mcr', # Memory Card (PS1/PS2)
    '.gci',        # GameCube Memory Card Image
    '.sl2',        # DarkSouls 3

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

# <<< INIZIO COSTANTI LINUX SCORING & DEPTH >>>
# Punteggi per la logica di Linux
SCORE_LINUX_GAME_NAME_MATCH = 500       # Corrispondenza (fuzzy) del nome del gioco nel percorso
SCORE_LINUX_COMPANY_NAME_MATCH = 200    # Corrispondenza nome azienda/publisher
SCORE_LINUX_SAVE_DIR_MATCH = 150        # Trovata una sottocartella comune per i salvataggi (es. 'saves')
SCORE_LINUX_HAS_SAVE_FILES = 300        # Rilevati file con estensioni/nomi di salvataggio comuni
SCORE_LINUX_PERFECT_MATCH_BONUS = 250   # Bonus addizionale se nome gioco + save dir + (opz.) azienda combaciano
SCORE_LINUX_STEAM_USERDATA_BONUS = 50   # Bonus specifico per percorsi in Steam userdata
SCORE_LINUX_PROTON_PATH_BONUS = 75      # Bonus specifico per percorsi Proton (compatdata)
SCORE_LINUX_WINE_GENERIC_BONUS = 25     # Bonus leggero per percorsi che sembrano WINE generici

PENALTY_LINUX_GENERIC_ENGINE_DIR = -100 # Penalità per cartelle generiche di engine (es. unity3d) se vuote o senza match nome gioco
PENALTY_LINUX_UNRELATED_GAME_IN_PATH = -300 # Penalità se il percorso sembra di un altro gioco specifico
PENALTY_LINUX_DEPTH_BASE = -5           # Penalità base per ogni livello di profondità (moltiplicata per la profondità)
PENALTY_LINUX_BANNED_PATH_SEGMENT = -1000 # Penalità forte se un segmento del percorso è in BANNED_FOLDER_NAMES_LOWER

# Profondità massime di ricerca per Linux
MAX_DEPTH_STEAM_USERDATA_LINUX = 3      # Dentro Steam/userdata/<id3>/<appid>/remote/ (non troppo a fondo)
MAX_DEPTH_PROTON_COMPATDATA_LINUX = 5   # Dentro compatdata/<appid>/pfx/drive_c/ (può essere più profondo)
MAX_DEPTH_COMMON_LINUX_LOCATIONS = 3    # Dentro ~/.local/share, ~/.config, ~/.wine etc.
MAX_DEPTH_GAME_INSTALL_DIR_LINUX = 4    # Dentro la cartella di installazione del gioco (se fornita)

# Maximum number of files to scan within a directory when initially checking 
# if it's a potential save directory (for hints of save files).
# A lower number improves performance during broad searches.
MAX_FILES_TO_SCAN_IN_DIR_LINUX_HINT = 25

# Minimum number of files matching common save patterns (extensions/filenames)
# found within a directory to grant it the SCORE_LINUX_HAS_SAVE_FILES bonus.
MIN_SAVE_FILES_FOR_BONUS_LINUX = 1

# Maximum number of sub-items (files/directories) to scan within any given 
# directory during recursive search. Helps prevent excessive processing in very large directories.
MAX_SUB_ITEMS_TO_SCAN_LINUX = 50

# Maximum depth for 'shallow exploration' in recursive search. This allows the search 
# to go a few levels deeper into non-matching directory structures, potentially finding 
# saves in paths like ~/.local/share/SomeContainerFolder/GameName.
MAX_SHALLOW_EXPLORE_DEPTH_LINUX = 1

# <<< FINE COSTANTI LINUX SCORING & DEPTH >>>

# --- Performance toggles for Linux save-path scanning (safe defaults) ---
# These allow dialing search breadth/depth depending on environment (e.g., VM with synthetic folders).
LINUX_ENABLE_STEAM_USERDATA_REMOTE_SCAN = True
LINUX_ENABLE_PROTON_DEEP_SCAN_STEAM = True
LINUX_ENABLE_PROTON_SCAN_NONSTEAM = True
LINUX_MAX_COMPATDATA_APPIDS_NONSTEAM = 100  # Limit how many compatdata prefixes to scan for non-Steam
LINUX_SKIP_HOME_FALLBACK = False          # Set True to skip scanning the entire home directory
LINUX_SKIP_KNOWN_LOCATIONS_COMPAT_RECURSE_IF_PROTON_ENABLED = True  # Avoid double-recursing compatdata if Proton scan is on
LINUX_ENABLE_SNAP_SEARCH = True
LINUX_ENABLE_FUZZY_FILTER_OTHER_GAMES = True
LINUX_MAX_DIRECTORIES_TO_EXPLORE = 200    # Global cap across a single search run

# Default directories to skip during Linux recursive search (basenames, lowercased match)
LINUX_SKIP_DIRECTORIES = {
    # Desktop/user clutter
    'downloads', 'pictures', 'videos', 'music', 'templates', 'public', 'trash', 'screenshots',
    # Generic caches and system dirs
    '.cache', 'cache', 'caches', 'logs', 'log', 'gpucache', 'shadercache', 'blob_storage',
    'code cache', 'local storage', 'session storage', 'videoDecodestats'.lower(), 'gpuCache'.lower(),
    # GNOME/system bits
    'gnome-shell', 'gnome-session', 'dconf', 'ibus', 'ibus-table', 'keyrings', 'tracker3', 'pulse', 'thumbnails',
    # Snap/Flatpak helpers
    'snap-store', 'snapd-desktop-integration', 'flatpak',
    # Editors/browsers heavy trees
    'code', 'vscode', 'extensions', 'workspaceStorage'.lower(), 'globalStorage'.lower(), 'resources', 'dist', 'out', 'node_modules',
    'firefox', 'chromium',
}

# Strict save evidence patterns to avoid false positives in generic app folders
LINUX_STRICT_EVIDENCE_MODE = True
LINUX_STRICT_SAVE_EXTENSIONS = {
    'sav', 'save', 'sl2', 'state', 'gci', 'srm', 'mcr', 'mc', 'ess', 'fos', 'lsf', 'lsb', 'eep', 'fla'
}
LINUX_STRICT_SAVE_FILENAME_KEYWORDS = {
    'save', 'saves', 'slot', 'slots', 'profile', 'profiles', 'player', 'players',
    'world', 'character', 'quicksave', 'autosave', 'persistent'
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
    'savegame',    # savegame.dat (più specifico)

    # Aggiungi altre parti comuni che noti
}

# Thresholds and settings for similarity checks
SIMILARITY_THRESHOLD = 88  # General fuzzy match threshold
SIMILARITY_THRESHOLD_ABBREVIATION = 80 # Lower threshold for abbreviations
SIMILARITY_MIN_MATCH_WORDS = 2 # Min common words for are_names_similar
SIMILARITY_PATH_THRESHOLD = 80 # For checking if path contains game name
SIMILARITY_IGNORE_WORDS = {'a', 'an', 'the', 'of', 'and', 'remake', 'intergrade',
                         'edition', 'goty', 'demo', 'trial', 'play', 'launch',
                         'definitive', 'enhanced', 'complete', 'collection', 'original',
                         'hd', 'ultra', 'deluxe', 'game', 'year', 'cut', 'final'}

# --- Windows Specific Scoring & Behavior ---
PENALTY_UNRELATED_GAME_WINDOWS = -550 # Penalty for paths matching other installed games (Windows)
MAX_EXPLORATORY_SUBDIRS_WINDOWS = 300 # Max subdirs to check in exploratory search (Windows)
MAX_FILES_TO_SCAN_IN_DIR_WINDOWS = 200 # Max files to check for save extensions in a dir (Windows)
EXPLORATORY_SCAN_MAX_DEPTH_WINDOWS = 3 # Max depth for recursive exploratory scan (Windows)

# --- Linux Specific Scoring & Behavior ---
# Questi sono i valori di default, verranno sovrascritti se presenti in un file di config utente# Punteggi per la logica di Linux
SCORE_LINUX_GAME_NAME_MATCH = 500       # Corrispondenza (fuzzy) del nome del gioco nel percorso
SCORE_LINUX_COMPANY_NAME_MATCH = 200    # Corrispondenza nome azienda/publisher
SCORE_LINUX_SAVE_DIR_MATCH = 150        # Trovata una sottocartella comune per i salvataggi (es. 'saves')
SCORE_LINUX_HAS_SAVE_FILES = 300        # Rilevati file con estensioni/nomi di salvataggio comuni
SCORE_LINUX_PERFECT_MATCH_BONUS = 250   # Bonus addizionale se nome gioco + save dir + (opz.) azienda combaciano
SCORE_LINUX_STEAM_USERDATA_BONUS = 50   # Bonus specifico per percorsi in Steam userdata
SCORE_LINUX_PROTON_PATH_BONUS = 75      # Bonus specifico per percorsi Proton (compatdata)
SCORE_LINUX_WINE_GENERIC_BONUS = 25     # Bonus leggero per percorsi che sembrano WINE generici

PENALTY_LINUX_GENERIC_ENGINE_DIR = -100 # Penalità per cartelle generiche di engine (es. unity3d) se vuote o senza match nome gioco
PENALTY_LINUX_UNRELATED_GAME_IN_PATH = -300 # Penalità se il percorso sembra di un altro gioco specifico
PENALTY_LINUX_DEPTH_BASE = -5           # Penalità base per ogni livello di profondità (moltiplicata per la profondità)
PENALTY_LINUX_BANNED_PATH_SEGMENT = -1000 # Penalità forte se un segmento del percorso è in BANNED_FOLDER_NAMES_LOWER

# Profondità massime di ricerca per Linux
MAX_DEPTH_STEAM_USERDATA_LINUX = 3      # Dentro Steam/userdata/<id3>/<appid>/remote/ (non troppo a fondo)
MAX_DEPTH_PROTON_COMPATDATA_LINUX = 5   # Dentro compatdata/<appid>/pfx/drive_c/ (può essere più profondo)
MAX_DEPTH_COMMON_LINUX_LOCATIONS = 3    # Dentro ~/.local/share, ~/.config, ~/.wine etc.
MAX_DEPTH_GAME_INSTALL_DIR_LINUX = 4    # Dentro la cartella di installazione del gioco (se fornita)

# Maximum number of files to scan within a directory when initially checking 
# if it's a potential save directory (for hints of save files).
# A lower number improves performance during broad searches.
MAX_FILES_TO_SCAN_IN_DIR_LINUX_HINT = 25

# Minimum number of files matching common save patterns (extensions/filenames)
# found within a directory to grant it the SCORE_LINUX_HAS_SAVE_FILES bonus.
MIN_SAVE_FILES_FOR_BONUS_LINUX = 1

# Maximum number of sub-items (files/directories) to scan within any given 
# directory during recursive search. Helps prevent excessive processing in very large directories.
MAX_SUB_ITEMS_TO_SCAN_LINUX = 50

# Maximum depth for 'shallow exploration' in recursive search. This allows the search 
# to go a few levels deeper into non-matching directory structures, potentially finding 
# saves in paths like ~/.local/share/SomeContainerFolder/GameName.
MAX_SHALLOW_EXPLORE_DEPTH_LINUX = 1

# Penalità specifiche per Linux Path Scoring (da aggiungere se non presenti o da aggiornare)
# Assicurati che queste costanti siano definite PRIMA del loro utilizzo in save_path_finder_linux.py
# Idealmente, raggruppale con altre costanti di scoring.
PENALTY_UNRELATED_GAME_IN_PATH = -800 # (Verifica se già definita, altrimenti aggiungi)
PENALTY_KNOWN_IRRELEVANT_COMPANY = -250
PENALTY_NO_GAME_NAME_IN_PATH = -600

# Lista di tutti i nomi dei giochi conosciuti (da popolare per una migliore penalizzazione di giochi non correlati)
# Esempio: ALL_KNOWN_GAME_NAMES_RAW = ["Factorio", "Celeste", "Cyberpunk 2077", "The Witcher 3"]
ALL_KNOWN_GAME_NAMES_RAW = []

# Verifica percorsi base all'import
if not os.path.exists(os.path.dirname(BACKUP_BASE_DIR)) and BACKUP_BASE_DIR.count(os.sep) > 1:
    logging.warning(f"La cartella parente di BACKUP_BASE_DIR ('{os.path.dirname(BACKUP_BASE_DIR)}') non sembra esistere.")

# Segmenti di percorso specifici per Linux da bannare
LINUX_BANNED_PATH_FRAGMENTS = [
    # Simili a BANNED_FOLDER_NAMES_LOWER ma specifici o più comuni su Linux
    "/usr/share/games", # Giochi di sistema, non salvataggi utente
    "/var/games",       # Vecchia locazione per giochi di sistema
    "/opt/",            # Spesso usato per software di terze parti, ma raramente per salvataggi dinamici
    "steamapps/common", # Da aggiungere alla lista principale se manca.
    "steamapps/shadercache",
    "steamapps/temp",
    "steamapps/downloading",
    "/.steam/root/config/htmlcache",
    "/.steam/root/config/overlay日誌", # Esempio con caratteri non ASCII, se necessario
    "/.steam/steam/logs",
    "/.local/share/Steam/logs",
    "/.local/share/vulkan",
    "/.cache/mesa_shader_cache",
    "/.cache/nvidia",
    "/.config/pulse",
    "/.config/dconf",
    "/.config/ibus",
    "/.config/fontconfig",
    "/.config/enchant",
    "/.config/goa-1.0",
    "/.config/gtk-2.0",
    "/.config/gtk-3.0",
    "/.config/gtk-4.0",
    "/.config/KDE",
    "/.config/kdedefaults",
    "/.config/kdeconnect",
    "/.config/kde.org",
    "/.config/KDE/UserFeedback.org",
    "/.config/kscreen",
    "/.config/kwinrc",
    "/.config/krunnercs",
    "/.config/plasma",
    "/.config/plasmashellrc",
    "/.config/powermanagementprofilesrc",
    "/.config/QtProject.conf",
    "/.config/Trolltech.conf",
    "/.config/xsettingsd",
    "/.config/procps",
    "/.config/user-dirs.dirs",
    "/.config/user-dirs.locale",
    "/.dbus",
    "/.gvfs",
    "/.local/share/applications",
    "/.local/share/Trash",
    "/.local/share/RecentDocuments",
    "/.local/share/fonts",
    "/.local/share/icons",
    "/.local/share/zeitgeist",
    "/.local/share/flatpak/repo", # Repository Flatpak, non contiene salvataggi
    "/.wine/drive_c/windows",
    "/.wine/drive_c/Program Files",
    "/.wine/drive_c/Program Files (x86)",
    "/.wine/drive_c/users/steamuser/Documents/My Games",
    "/.wine/drive_c/users/steamuser/Saved Games",
    "/.wine/drive_c/users/steamuser/AppData/Roaming",
    "/.wine/drive_c/users/steamuser/AppData/Local",
    "/.wine/drive_c/users/steamuser/Documents", # Documenti generici in Wine
    # Flatpak (la struttura interna è app_id/config o app_id/data)
    "~/.var/app",
    # Snap (la struttura interna varia, spesso ~/snap/game-name/common/ o current/)
    "~/snap",
    # Alcuni giochi potrebbero usare direttamente la home o sottocartelle dirette
    "~", # Home directory stessa, per giochi che creano cartelle come ~/.gamename
    # Esempi specifici noti (possono essere molti)
    "~/.godot/app_userdata", # Base per giochi Godot non Flatpak
    "~/.renpy", # Base per giochi Ren'Py
]

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
    background-color: #A10808; /* Rosso scuro ufficiale per selezione */
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
    color: #A10808;             /* Colore titolo scuro ufficiale */
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
    background-color: #A10808; /* Barra progresso rossa scura */
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
    background-color: transparent; /* Sfondo trasparente per pennello personalizzato (linea rossa laterale) */
    color: #FFFFFF;          /* Testo bianco su selezione */
    border: none;
}

/* Stile per le Intestazioni (Header) */
QHeaderView::section {
    background-color: #1E1E1E; /* Sfondo intestazione molto scuro */
    color: #EAEAEA;          /* Testo intestazione chiaro */
    padding: 4px;
    border-top: 0px;         /* Rimuovi bordi header se vuoi look pulito */
    border-bottom: 1px solid #A10808; /* Bordo rosso scuro sotto header */
    border-right: 1px solid #4A4A4A;
    border-left: 0px;
    font-weight: bold;        /* Grassetto */
}

/* Stile per ultima sezione header (opzionale, per non avere doppio bordo) */
QHeaderView::section:last {
    border-right: 0px;
}

QPushButton#LogToggleButton {
    border: none;                /* Nessun bordo */
    background-color: transparent; /* Sfondo trasparente */
    padding: 2px;               /* Padding piccolo */
    margin: 1px;                /* Margine piccolo per spaziatura */
    min-width: 0px;            /* ANNULLA min-width generale */
    /* La dimensione è gestita in Python */
}
/* Effetti Hover/Pressed (Opzionali, uguali per entrambi) */
QPushButton#LogToggleButton:hover {
    background-color: #5A5A5A; /* Sfondo leggero al passaggio */
}
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
    /* La dimensione è gestita da Python */
}
QPushButton#ShortcutButton:hover {
    background-color: #5A5A5A; /* Grigio scuro al passaggio */
}
QPushButton#ShortcutButton:pressed {
    background-color: #404040; /* Leggermente più scuro alla pressione */
}

QPushButton#ExitButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 4px;
}
QPushButton#ExitButton:hover {
    background-color: #5A5A5A;
    border: 1px solid #888888;
}
QPushButton#ExitButton:pressed {
    background-color: #404040;
}

QPushButton#ConfigureButton {
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 2px;
}
QPushButton#ConfigureButton:hover {
    background-color: #5A5A5A;
    border: 1px solid #888888;
}
QPushButton#ConfigureButton:pressed {
    background-color: #404040;
}

/* ===== EMPTY STATE WIDGET STYLING (DARK THEME) ===== */
QWidget#EmptyStateWidget {
    background-color: transparent;
}
QLabel#EmptyStateTitle {
    color: #E0E0E0;
    background: transparent;
    font-size: 18pt;
    font-weight: bold;
    padding: 8px 0px;
}
QLabel#EmptyStateInstructions {
    color: #A0A0A0;
    background: transparent;
    font-size: 10pt;
    padding: 10px 20px;
}
QLabel#EmptyStateHint {
    color: #707070;
    background: transparent;
    font-size: 9pt;
    font-style: italic;
    padding: 5px 0px;
}
/* ===== END EMPTY STATE WIDGET ===== */

/* ===== CUSTOM SCROLLBAR STYLING (DARK THEME) ===== */
QScrollBar:vertical {
    background-color: #2D2D2D;  /* Sfondo track (stesso del widget) */
    width: 14px;                /* Larghezza scrollbar (aumentata per bordo) */
    margin: 0px;                /* Nessun margine */
    border: none;               /* Nessun bordo */
}

QScrollBar::handle:vertical {
    background-color: #4A4A4A;  /* Riempimento interno grigio scuro */
    border: 2px solid #A10808;  /* Bordo accent rosso (colore titoli) */
    min-height: 30px;           /* Altezza minima handle */
    border-radius: 4px;         /* Angoli leggermente arrotondati */
    margin: 2px;                /* Margine per distanziare dal bordo */
}

QScrollBar::handle:vertical:hover {
    background-color: #5A5A5A;  /* Riempimento più chiaro al passaggio */
    border: 2px solid #C10A0A;  /* Bordo rosso leggermente più brillante */
}

QScrollBar::handle:vertical:pressed {
    background-color: #A10808;  /* Riempimento rosso quando premuto */
    border: 2px solid #C10A0A;  /* Bordo rosso più brillante */
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;                /* Nascondi le frecce su/giù */
    background: none;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;           /* Nessuno sfondo per le aree sopra/sotto handle */
}

/* Scrollbar orizzontale (se necessaria) */
QScrollBar:horizontal {
    background-color: #2D2D2D;
    height: 14px;
    margin: 0px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #4A4A4A;
    border: 2px solid #A10808;
    min-width: 30px;
    border-radius: 4px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #5A5A5A;
    border: 2px solid #C10A0A;
}

QScrollBar::handle:horizontal:pressed {
    background-color: #A10808;
    border: 2px solid #C10A0A;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
}
/* ===== END CUSTOM SCROLLBAR ===== */

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

QPushButton#LogToggleButton {
    border: none;
    background-color: transparent;
    padding: 2px;
    margin: 1px;
    min-width: 0px; /* ANNULLA min-width generale */
    /* La dimensione è gestita in Python */
}
/* Effetti Hover/Pressed (Opzionali, uguali per entrambi) */
QPushButton#LogToggleButton:hover {
    background-color: #DCDCDC; /* Sfondo leggero chiaro al passaggio */
}
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

QPushButton#ExitButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 4px;
}
QPushButton#ExitButton:hover {
    background-color: #DCDCDC;
    border: 1px solid #888888;
}
QPushButton#ExitButton:pressed {
    background-color: #C8C8C8;
}

QPushButton#ConfigureButton {
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 2px;
}
QPushButton#ConfigureButton:hover {
    background-color: #DCDCDC;
    border: 1px solid #888888;
}
QPushButton#ConfigureButton:pressed {
    background-color: #C8C8C8;
}

/* ===== EMPTY STATE WIDGET STYLING (LIGHT THEME) ===== */
QWidget#EmptyStateWidget {
    background-color: transparent;
}
QLabel#EmptyStateTitle {
    color: #1E1E1E;
    background: transparent;
    font-size: 18pt;
    font-weight: bold;
    padding: 8px 0px;
}
QLabel#EmptyStateInstructions {
    color: #555555;
    background: transparent;
    font-size: 10pt;
    padding: 10px 20px;
}
QLabel#EmptyStateHint {
    color: #888888;
    background: transparent;
    font-size: 9pt;
    font-style: italic;
    padding: 5px 0px;
}
/* ===== END EMPTY STATE WIDGET ===== */

/* ===== CUSTOM SCROLLBAR STYLING (LIGHT THEME) ===== */
QScrollBar:vertical {
    background-color: #F0F0F0;  /* Sfondo track (stesso del widget) */
    width: 14px;                /* Larghezza scrollbar (aumentata per bordo) */
    margin: 0px;                /* Nessun margine */
    border: none;               /* Nessun bordo */
}

QScrollBar::handle:vertical {
    background-color: #DEDEDE;  /* Riempimento interno grigio chiaro */
    border: 2px solid #20B2AA;  /* Bordo accent ciano */
    min-height: 30px;           /* Altezza minima handle */
    border-radius: 4px;         /* Angoli leggermente arrotondati */
    margin: 2px;                /* Margine per distanziare dal bordo */
}

QScrollBar::handle:vertical:hover {
    background-color: #D0D0D0;  /* Riempimento più scuro al passaggio */
    border: 2px solid #1AA89A;  /* Bordo ciano più scuro */
}

QScrollBar::handle:vertical:pressed {
    background-color: #20B2AA;  /* Riempimento ciano quando premuto */
    border: 2px solid #00A89A;  /* Bordo ciano più scuro */
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;                /* Nascondi le frecce su/giù */
    background: none;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;           /* Nessuno sfondo per le aree sopra/sotto handle */
}

/* Scrollbar orizzontale (se necessaria) */
QScrollBar:horizontal {
    background-color: #F0F0F0;
    height: 14px;
    margin: 0px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #DEDEDE;
    border: 2px solid #20B2AA;
    min-width: 30px;
    border-radius: 4px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #D0D0D0;
    border: 2px solid #1AA89A;
}

QScrollBar::handle:horizontal:pressed {
    background-color: #20B2AA;
    border: 2px solid #00A89A;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
}
/* ===== END CUSTOM SCROLLBAR ===== */

"""
# --- FINE NUOVE REGOLE ---
# --- FINE CONFIGURAZIONE ---