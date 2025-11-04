# -*- mode: python ; coding: utf-8 -*-

# --- OPZIONI PRINCIPALI ---
a = Analysis(
    ['main.py'], # Script principale della tua applicazione
    pathex=[],   # Percorsi aggiuntivi per la ricerca di moduli (solitamente vuoto se la struttura è standard)
    binaries=[], # File binari non Python (es. DLL specifiche) da includere (lascia vuoto se non necessario)
    datas=[
         ('icons', 'icons'),              # Copia la cartella 'icons' nella root dell'output [cite: 11]
         ('splash.png', '.'),
		 ('icon.png', '.'),
		 ('backup_runner.py', '.'),
         ('emulator_utils/citra_titles_map.pkl', 'emulator_utils'), # Include il DB dei titoli 3ds
         ('emulator_utils/switch_game_map.pkl', 'emulator_utils'), # Include il DB dei titoli swich
         ('emulator_utils/ps4_game_map.pkl', 'emulator_utils'), # Include il DB dei titoli ps4
         ('emulator_utils/xenia_title_map.pkl', 'emulator_utils'), # include il DB dei titoli xbox 360
         ('cloud_utils/client_secret.json', 'cloud_utils'), # Google Drive OAuth credentials
    ],
    hiddenimports=[
        'PySide6.QtSvg',             # Necessario per icone SVG se usate (incluso per sicurezza) [cite: 8]
        'PySide6.QtNetwork',         # Usato per QLocalServer/QLocalSocket per single instance [cite: 13]
        'PySide6.QtGui',             # Moduli Qt essenziali
        'PySide6.QtWidgets',         # Moduli Qt essenziali
        'PySide6.QtCore',            # Moduli Qt essenziali
        'shiboken6',                 # Runtime PySide6
        'winreg',                    # Usato in core_logic per Steam [cite: 5]
        'winshell',                  # Usato in shortcut_utils [cite: 10]
        'win32com',                  # Dipendenza di winshell/pywin32 [cite: 10]
        'win32com.client',           # Usato specificamente [cite: 10]
        'pkg_resources',             # Spesso richiesto da altre librerie [cite: 1]
        'importlib.metadata',        # Richiesto da pkg_resources o altri [cite: 4]
        'vdf',                       # Dipendenza opzionale per Steam ID [cite: 5]
        'nbtlib',                    # Dipendenza opzionale per nomi mondi Minecraft [cite: 1]
        'thefuzz',                   # Usato in core_logic per similarità [cite: 5]
        'thefuzz.fuzz',              # Parte di thefuzz [cite: 5]
        'thefuzz.process',           # Parte di thefuzz [cite: 5]
        'psutil',                    # Includi per possibili usi nascosti (es. multiprocessing)
        'xml.etree.ElementTree',     # Usato per leggere XML (Cemu meta/settings)
        'configparser',              # Usato per leggere INI (mGBA config)
        # 'Levenshtein',             # Opzionale: per thefuzz[speedup], se installato
        # Aggiungi qui altri moduli che PyInstaller potrebbe non trovare automaticamente
    ],
    hookspath=[],          # Percorsi per script hook personalizzati
    hooksconfig={},
    runtime_hooks=[],      # Script da eseguire al runtime prima del codice principale
    excludes=[],           # Moduli da escludere esplicitamente
    noarchive=False,
    optimize=0             # Livello di ottimizzazione bytecode (0=nessuna, 1=asserts rimossi, 2=docstrings rimosse)
)
pyz = PYZ(a.pure)

splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    # --- Aggiungi parametri extra dal minimale ---
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=False,
    # --- Fine parametri extra ---
)


exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
	splash,
    splash.binaries,
    # splash.datas,
    [],
    #splash=splash,
    name='SaveState',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico'
)

# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='SaveState'
# )