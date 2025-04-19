# -*- coding: utf-8 -*-

import sys
import os
#import subprocess
import json
import logging
import platform
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

# --- PySide6 Imports ---
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QDialog, QListWidget, QListWidgetItem,
    QPlainTextEdit, QFileDialog, QDialogButtonBox, QMessageBox,
    QLabel, QLineEdit, QRadioButton
)
from PySide6.QtCore import Slot, QProcess, QSize, QCoreApplication
from PySide6.QtGui import QIcon, QTextCursor

# --- Costanti Globali ---
APP_NAME = "SaveStateTools"
ORG_NAME = "Matteo842"
CONFIG_FILENAME = "SaveStateTools.json"
SCRIPT_DIR = Path(__file__).parent.resolve() # Directory dello script corrente

# --- Costanti per PyInstaller Packaging ---
# Nome del file .spec per la build one-file (relativo allo SCRIPT_DIR)
SPEC_FILE_ONEFILE = "SaveState-OneFile.spec"
# Nome dell'eseguibile/applicazione che verrà creato
PACKAGER_APP_NAME = "SaveState"
# Script Python principale del tuo progetto SaveState
PACKAGER_ENTRY_SCRIPT = "SaveState_gui.py"
# Icona per l'eseguibile (relativa allo SCRIPT_DIR)
PACKAGER_ICON_ICO = "icon.ico" # Per Windows .exe
PACKAGER_ICON_PNG = "icon.png" # Da includere come dato

# Dati da includere (--add-data source;destination)
# Assumiamo che source sia relativo a SCRIPT_DIR e destination relativo alla root dell'app pacchettizzata
PACKAGER_ADD_DATA = [
    ("icons", "icons"),         # Cartella icone -> cartella icone in output
    ("SaveState_en.qm", "."),   # File traduzione -> root output
    ("backup_runner.py", "."),  # Altro script -> root output
    (PACKAGER_ICON_PNG, "."),   # Icona png -> root output
]

# Moduli nascosti necessari per PyInstaller
PACKAGER_HIDDEN_IMPORTS = [
    "PySide6.QtSvg",
    "win32com.client", # Specifico Windows
    "winshell",        # Specifico Windows
    "vdf",
    "nbtlib"
]

DARK_THEME_QSS = """
    QWidget {
        background-color: #2D2D2D; color: #F0F0F0;
        selection-background-color: #5A5A5A; selection-color: #F0F0F0;
    }
    QMainWindow { background-color: #2D2D2D; }
    QDialog { background-color: #353535; }
    QLineEdit, QPlainTextEdit, QListWidget {
        background-color: #3C3C3C; border: 1px solid #555555; padding: 3px;
    }
    QLabel { color: #F0F0F0; }
    QMessageBox { background-color: #3C3C3C; }
    QListWidget::item:selected { background-color: #5A5A5A; }

    /* Stile Generale Pulsanti */
    QPushButton {
        background-color: #555555; border: 1px solid #777777;
        padding: 5px; min-width: 70px; /* Riduci min-width se serve per settings */
        border-radius: 3px; /* Angoli leggermente arrotondati */
    }
    
    QLineEdit, QPlainTextEdit, QListWidget {
        background-color: #3C3C3C;
        border: 1px solid #555555;
        padding: 3px;
        /* Rimuovi font-size da qui se presente, lo mettiamo specifico sotto */
    }

    /* Stile specifico per l'area di Log */
    QPlainTextEdit {
        font-size: 11pt; /* Font size per il log */
    }
    
    QPushButton:hover { background-color: #666666; border: 1px solid #888888;}
    QPushButton:pressed { background-color: #444444; }
    QPushButton:disabled { background-color: #4A4A4A; color: #888888; border: 1px solid #555555;}

    /* ---- Stili Specifici Pulsanti ---- */

    /* Pulsante Impostazioni (Stile aggiornato sotto) */
    QPushButton#settingsButton {
        background-color: transparent;  /* Sfondo trasparente */
        border: none;                 /* Nessun bordo */
        padding: 3px;                 /* Leggero padding attorno all'icona */
        /* Manteniamo le dimensioni forzate per sicurezza, anche se invisibile */
        min-width: 30px;
        max-width: 30px;
        min-height: 30px;
        max-height: 30px;
        /* border-radius: 3px; */ /* Puoi tenerlo se vuoi l'effetto hover arrotondato */
    }
    QPushButton#settingsButton:hover {
        background-color: rgba(255, 255, 255, 30); /* Leggero overlay bianco semi-trasparente */
        border: none; /* Assicura nessun bordo su hover */
        border-radius: 3px; /* Arrotonda leggermente su hover */
    }
    QPushButton#settingsButton:pressed {
        background-color: rgba(255, 255, 255, 50); /* Overlay leggermente più opaco */
        border: none;
        border-radius: 3px;
    }
    QPushButton#settingsButton:hover { background-color: #707070; }
    QPushButton#settingsButton:pressed { background-color: #505050; }

    /* Pulsante Esci (Rosso Scuro) */
    QPushButton#quitButton {
        background-color: #8C2323; /* Rosso più scuro/mattone */
        border-color: #A04040;
        color: #E0E0E0; /* Testo leggermente meno bianco */
    }
    QPushButton#quitButton:hover { background-color: #A03030; }
    QPushButton#quitButton:pressed { background-color: #7A1B1B; }

    /* Pulsante Crea Pacchetto (Blu Scuro/Grigio) */
    QPushButton#packageButton {
        background-color: #4A5A70; /* Blu/Grigio scuro */
        border-color: #6A7A90;
        color: #E0E0E0;
    }
    QPushButton#packageButton:hover { background-color: #5A6A80; }
    QPushButton#packageButton:pressed { background-color: #3A4A60; }

    /* Pulsanti Traduzione (lupdate/lrelease - Verde Scuro) */
    QPushButton#lupdateButton,
    QPushButton#releaseButton {
        background-color: #416A41; /* Verde scuro */
        border-color: #608060;
        color: #E0E0E0;
    }
    QPushButton#lupdateButton:hover,
    QPushButton#releaseButton:hover { background-color: #518A51; }
    QPushButton#lupdateButton:pressed,
    QPushButton#releaseButton:pressed { background-color: #315A31; }

"""

# --- Funzioni di Utilità ---

def get_app_data_dir() -> Path:
    """
    Restituisce il percorso della directory specifica dell'applicazione
    in AppData/Local (Windows) o percorsi equivalenti su altri OS.
    Crea la directory se non esiste.
    """
    system = platform.system()
    base_path: Optional[Path] = None

    try:
        if system == "Windows":
            local_app_data = os.environ.get('LOCALAPPDATA')
            if local_app_data:
                base_path = Path(local_app_data)
        elif system == "Darwin": # macOS
            base_path = Path.home() / "Library" / "Application Support"
        else: # Linux and other Unix-like
            xdg_data_home = os.environ.get('XDG_DATA_HOME')
            if xdg_data_home:
                 base_path = Path(xdg_data_home)
            else:
                 base_path = Path.home() / ".local" / "share"

        if base_path is None:
             raise OSError("Impossibile determinare la directory AppData standard.")

        # Costruisci percorso completo
        app_dir = base_path / "SaveState"

        # Crea la directory
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir

    except OSError as e:
        logging.error(f"Impossibile creare/accedere alla directory AppData: {e}. Uso la cartella dello script come fallback.", exc_info=True)
        fallback_dir = SCRIPT_DIR / f"{APP_NAME}_ConfigData"
        try:
             fallback_dir.mkdir(exist_ok=True)
             return fallback_dir
        except OSError as e_fb:
             logging.critical(f"Impossibile creare anche la directory di fallback {fallback_dir}: {e_fb}. La configurazione potrebbe non essere salvata.", exc_info=True)
             # Caso estremo: restituisce la directory dello script, ma è rischioso
             return SCRIPT_DIR


def resource_path(relative_path: Union[str, Path]) -> Path:
    """
    Ottieni il percorso assoluto della risorsa (es. icone).
    Gestisce il caso in cui lo script sia "congelato" da PyInstaller.
    Le risorse devono essere relative alla directory dello SCRIPT.
    """
    try:
        # PyInstaller crea una cartella temp e mette il path in _MEIPASS
        base_path = Path(sys._MEIPASS) # type: ignore
    except AttributeError:
        # Altrimenti, la base è la directory dove si trova questo script
        base_path = SCRIPT_DIR

    return (base_path / relative_path).resolve()


# --- Classe per Gestire la Configurazione ---

class ConfigManager:
    """
    Gestisce caricamento, salvataggio e accesso alla configurazione
    dell'applicazione, memorizzata in un file JSON nella directory AppData.
    """
    def __init__(self):
        self._config_dir: Path = get_app_data_dir()
        self._config_filepath: Path = self._config_dir / CONFIG_FILENAME
        self.config: Dict[str, Any] = self._load()
        logging.info(f"Configuration file used: {self._config_filepath}")

    def _get_default_config(self) -> Dict[str, Any]:
        """Restituisce la configurazione di default, potenzialmente specifica per OS."""
        defaults = {
            "lupdate_path": "",
            "lupdate_executable": "",
            "translation_file": "SaveState_en.ts", # Default generico
           "source_files": [
            "SaveState_gui.py", # Assumendo che sia nella stessa cartella dello script tool
            r"dialogs/manage_backups_dialog.py", # Usa / per compatibilità
            r"dialogs/minecraft_dialog.py",
            r"dialogs/restore_dialog.py",
            r"dialogs/settings_dialog.py",
            r"dialogs/steam_dialog.py",
            r"gui_components/profile_creation_manager.py", # Usa /
            r"gui_components/profile_list_manager.py",
            r"gui_components/theme_manager.py",
        ]
        }
        system = platform.system()
        try:
            if system == "Windows":
                 # Cerca un'installazione Qt comune in Program Files o C:\Qt
                 qt_base_paths = [Path(p) for p in [os.environ.get("ProgramFiles", "C:/Program Files"), "C:/Qt"] if p]
                 found_lupdate = None
                 for base in qt_base_paths:
                      if not base.exists(): continue
                      # Cerca versioni Qt (es. 6.7.0, 5.15.2)
                      for qt_ver_dir in base.glob("*/"): # Cerca sottocartelle
                            if not qt_ver_dir.is_dir(): continue
                            # Cerca compilatori (mingw_64, msvc2019_64 etc)
                            for compiler_dir in qt_ver_dir.glob("*/"):
                                if not compiler_dir.is_dir(): continue
                                potential_path = compiler_dir / "bin" / "lupdate.exe"
                                if potential_path.is_file():
                                    found_lupdate = potential_path
                                    break # Trovato
                            if found_lupdate: break
                      if found_lupdate: break

                 if found_lupdate:
                     defaults["lupdate_path"] = str(found_lupdate.parent)
                     defaults["lupdate_executable"] = found_lupdate.name
                 else: # Fallback se non trovato automaticamente
                     defaults["lupdate_path"] = r"C:\Qt\6.7.0\mingw_64\bin" # Metti un default comune o lascia vuoto
                     defaults["lupdate_executable"] = "lupdate.exe"

            elif system == "Linux":
                 # Prova a trovare lupdate nel PATH
                 import shutil
                 lupdate_path = shutil.which("lupdate")
                 if lupdate_path:
                     lupdate_p = Path(lupdate_path)
                     defaults["lupdate_path"] = str(lupdate_p.parent)
                     defaults["lupdate_executable"] = lupdate_p.name
                 else:
                     # Default comune se non nel PATH
                     defaults["lupdate_path"] = "/usr/bin"
                     defaults["lupdate_executable"] = "lupdate" # o lupdate-qt6, lupdate-qt5 etc.

            elif system == "Darwin": # macOS
                 # Simile a Linux, cerca nel PATH o in /usr/local/opt/qt/bin
                  import shutil
                  lupdate_path = shutil.which("lupdate")
                  if lupdate_path:
                      lupdate_p = Path(lupdate_path)
                      defaults["lupdate_path"] = str(lupdate_p.parent)
                      defaults["lupdate_executable"] = lupdate_p.name
                  else:
                      qt_opt_path = Path("/usr/local/opt/qt/bin/lupdate")
                      if qt_opt_path.is_file():
                           defaults["lupdate_path"] = str(qt_opt_path.parent)
                           defaults["lupdate_executable"] = qt_opt_path.name
                      else: # Fallback
                           defaults["lupdate_path"] = "/usr/local/bin"
                           defaults["lupdate_executable"] = "lupdate"

        except Exception as e:
            logging.warning(f"Error while auto-detecting lupdate: {e}")
            # Lascia i default generici vuoti se il rilevamento fallisce

        # Se dopo tutto questo, il percorso è ancora vuoto, logga un avviso
        if not defaults["lupdate_path"]:
             logging.warning("Default lupdate path not determined automatically. Please configure it manually in settings.")

        return defaults

    def _load(self) -> Dict[str, Any]:
        """Carica la configurazione dal file JSON, facendo merge con i default."""
        default_config = self._get_default_config()
        if self._config_filepath.exists():
            try:
                with self._config_filepath.open('r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                # Fai il merge: parti dal default, aggiorna con ciò che è caricato
                merged_config = default_config.copy()
                # Itera sui valori caricati e aggiorna solo se la chiave esiste nel default
                # o se è una chiave "conosciuta" (per evitare di mantenere vecchie chiavi obsolete)
                known_keys = default_config.keys() # Add other potential future keys if needed
                for key, value in loaded_config.items():
                    if key in known_keys:
                        # Validazione tipo base
                        if key == "source_files" and not isinstance(value, list):
                             logging.warning(f"Config: 'source_files' it's not a list, using the default one.")
                             merged_config[key] = default_config[key]
                        elif key in ["lupdate_path", "lupdate_executable", "translation_file"] and not isinstance(value, str):
                             logging.warning(f"Config: '{key}' it's not a string, using the default one.")
                             merged_config[key] = default_config[key]
                        else:
                             merged_config[key] = value
                    else:
                        logging.warning(f"Config: Key '{key}' not recognized in the file, will be ignored.")

                logging.info(f"Configuration loaded and merged by {self._config_filepath}")
                return merged_config
            except (json.JSONDecodeError, TypeError) as e:
                logging.error(f"Error loading {self._config_filepath}: {e}. Use default configuration.")
                return default_config.copy()
            except Exception as e:
                logging.error(f"Unexpected error loading {self._config_filepath}: {e}. using the default one.", exc_info=True)
                return default_config.copy()
        else:
            logging.info(f"{self._config_filepath} not found. Use and save default configuration.")
            self.config = default_config.copy() # Imposta self.config per il primo salvataggio
            self.save() # Salva il default
            return self.config # Ritorna il config appena salvato

    def save(self) -> bool:
        """Salva la configurazione corrente (self.config) nel file JSON."""
        try:
            # Assicura che la directory esista (get_app_data_dir dovrebbe averla creata)
            self._config_dir.mkdir(parents=True, exist_ok=True)

            # Prepara il dizionario per il salvataggio (assicura stringhe)
            config_to_save = {}
            for key, value in self.config.items():
                 if isinstance(value, Path):
                     config_to_save[key] = str(value)
                 elif isinstance(value, list):
                     # Assicura che anche gli elementi della lista siano stringhe
                     config_to_save[key] = [str(item) if isinstance(item, Path) else item for item in value]
                 else:
                     config_to_save[key] = value

            with self._config_filepath.open('w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=4, ensure_ascii=False)
            logging.info(f"Configuration saved in {self._config_filepath}")
            return True
        except Exception as e:
            logging.error(f"Error while saving in {self._config_filepath}: {e}", exc_info=True)
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Ottiene un valore dalla configurazione in memoria."""
        return self.config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
         """Ottiene una copia dell'intero dizionario di configurazione."""
         return self.config.copy()

    def update_config(self, new_config_dict: Dict[str, Any]):
        """Aggiorna l'intero dizionario di configurazione in memoria."""
        self.config = new_config_dict.copy() # Sostituisce con la nuova config validata
        logging.debug("Configurazione in memoria aggiornata.")

    # --- Metodi helper per tipi specifici ---
    def get_str(self, key: str, default: str = "") -> str:
        return str(self.get(key, default))

    def get_list_str(self, key: str, default: Optional[List[str]] = None) -> List[str]:
         value = self.get(key, default if default is not None else [])
         if isinstance(value, list):
             return [str(item) for item in value]
         return default if default is not None else []

    def get_path(self, key: str, default_str: str = "") -> Path:
         # Restituisce sempre un Path, anche vuoto se la chiave non c'è
         return Path(self.get_str(key, default_str))

# --- Finestra Dialogo Packaging ---
class PackagingDialog(QDialog):
    """Dialogo per selezionare il tipo di pacchetto PyInstaller."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Create Application Package (PyInstaller)")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the type of package to create:"))

        self.radio_onefile = QRadioButton("One-File (single .exe, slower startup)")
        self.radio_onedir = QRadioButton("One-Folder (folder with .exe, faster startup)")
        self.radio_onedir.setChecked(True) # Pre-seleziona One-Folder (spesso preferito)

        layout.addWidget(self.radio_onefile)
        layout.addWidget(self.radio_onedir)

        # Spazio
        layout.addSpacing(15)

        # Pulsanti OK/Cancel
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Start Creating")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_selected_type(self) -> str:
        """Restituisce 'onefile' o 'onefolder' in base alla selezione."""
        if self.radio_onefile.isChecked():
            return "onefile"
        else:
            return "onefolder"

# --- Finestra Impostazioni ---
class SettingsDialog(QDialog):
    """Finestra di dialogo per modificare le impostazioni dell'applicazione."""

    def __init__(self, current_config: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"{QCoreApplication.applicationName()} - Settings")
        self.setMinimumWidth(650) # Leggermente più largo per percorsi lunghi
        self.config: Dict[str, Any] = current_config.copy() # Lavora su una copia

        layout = QVBoxLayout(self)

        # --- Percorso LUpdate ---
        lupdate_layout = QHBoxLayout()
        lupdate_layout.addWidget(QLabel("LUpdate Folder:"))
        self.lupdate_path_edit = QLineEdit(self.config.get("lupdate_path", ""))
        self.lupdate_path_edit.setPlaceholderText("Es: C:\\Qt\\6.7.0\\mingw_64\\bin")
        lupdate_layout.addWidget(self.lupdate_path_edit)
        browse_lupdate_button = QPushButton("Browse...")
        browse_lupdate_button.clicked.connect(self.browse_lupdate_path)
        lupdate_layout.addWidget(browse_lupdate_button)
        layout.addLayout(lupdate_layout)

        # --- Eseguibile LUpdate ---
        lupdate_exe_layout = QHBoxLayout()
        lupdate_exe_layout.addWidget(QLabel("LUpdate executable:"))
        self.lupdate_exe_edit = QLineEdit(self.config.get("lupdate_executable", ""))
        self.lupdate_exe_edit.setPlaceholderText("Ex: lupdate.exe (Win), lupdate (Linux/Mac)")
        lupdate_exe_layout.addWidget(self.lupdate_exe_edit)
        layout.addLayout(lupdate_exe_layout)

        # --- File Traduzione (.ts) ---
        ts_layout = QHBoxLayout()
        ts_layout.addWidget(QLabel("Translation File (.ts):"))
        self.ts_file_edit = QLineEdit(self.config.get("translation_file", ""))
        self.ts_file_edit.setPlaceholderText("Es: ../resources/myapp_en.ts")
        ts_layout.addWidget(self.ts_file_edit)
        browse_ts_button = QPushButton("Browse...")
        browse_ts_button.clicked.connect(self.browse_ts_file)
        ts_layout.addWidget(browse_ts_button)
        layout.addLayout(ts_layout)

        # --- Lista File Sorgente ---
        layout.addWidget(QLabel("Python Source File (.py) - Script-relative or absolute paths:"))
        self.source_list_widget = QListWidget()
        self.source_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.populate_source_list()
        layout.addWidget(self.source_list_widget)

        # Pulsanti Aggiungi/Rimuovi
        source_button_layout = QHBoxLayout()
        add_button = QPushButton("Add File...")
        remove_button = QPushButton("Remove Selected")
        add_button.clicked.connect(self.add_source_file)
        remove_button.clicked.connect(self.remove_source_file)
        source_button_layout.addStretch()
        source_button_layout.addWidget(add_button)
        source_button_layout.addWidget(remove_button)
        layout.addLayout(source_button_layout)

        # --- Pulsanti OK/Annulla ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def populate_source_list(self):
        """Aggiorna la lista GUI con i file sorgente dalla config."""
        self.source_list_widget.clear()
        source_files = self.config.get("source_files", [])
        if isinstance(source_files, list):
             for file_path_str in sorted(source_files): # Ordina per consistenza
                 item = QListWidgetItem(str(file_path_str))
                 # Tooltip per vedere il percorso assoluto se relativo
                 list_item_path = Path(file_path_str)
                 if not list_item_path.is_absolute():
                      try:
                           abs_tooltip_path = (SCRIPT_DIR / list_item_path).resolve()
                           item.setToolTip(str(abs_tooltip_path))
                      except Exception: # Se il resolve fallisce per qualche motivo
                           item.setToolTip(f"Relating to: {SCRIPT_DIR}")
                 else:
                      item.setToolTip(str(list_item_path))
                 self.source_list_widget.addItem(item)

    @Slot()
    def browse_lupdate_path(self):
        """Dialogo per selezionare la cartella di lupdate."""
        current_path_str = self.lupdate_path_edit.text()
        start_dir = current_path_str if Path(current_path_str).is_dir() else str(SCRIPT_DIR)
        directory = QFileDialog.getExistingDirectory(self, "Select LUpdate Folder", start_dir)
        if directory:
            self.lupdate_path_edit.setText(str(Path(directory))) # Salva come stringa normalizzata

    @Slot()
    def browse_ts_file(self):
        """Dialogo per selezionare/creare il file .ts."""
        current_file_str = self.ts_file_edit.text()
        try:
            start_dir = str(Path(current_file_str).parent) if current_file_str else str(SCRIPT_DIR)
            start_file = str(Path(current_file_str).name) if current_file_str else "translation.ts"
            start_path = Path(start_dir) / start_file
        except Exception: # Gestisce path non validi iniziali
             start_path = SCRIPT_DIR / "translation.ts"

        filename, _ = QFileDialog.getSaveFileName(
            self, "Select or Enter Translation File Name (.ts)",
            str(start_path), # QFileDialog vuole stringa
            "Qt Translation Files (*.ts);;All Files (*)"
        )
        if filename:
            ts_path = Path(filename)
            if not ts_path.name.lower().endswith('.ts'):
                ts_path = ts_path.with_suffix('.ts')
            # Prova a renderlo relativo a SCRIPT_DIR se possibile
            try:
                 rel_path = ts_path.relative_to(SCRIPT_DIR)
                 path_to_set = str(rel_path) if len(str(rel_path)) < len(str(ts_path)) else str(ts_path.resolve())
            except ValueError:
                 path_to_set = str(ts_path.resolve()) # Altrimenti assoluto
            self.ts_file_edit.setText(path_to_set)

    @Slot()
    def add_source_file(self):
        """Aggiunge uno o più file sorgente (.py) alla lista."""
        filenames, _ = QFileDialog.getOpenFileNames(
            self, "Add Python Source File", str(SCRIPT_DIR), "Python Files (*.py);;All Files (*)"
        )
        if filenames:
            current_files_str: List[str] = self.config.get("source_files", [])
            added_count = 0
            for fname_str in filenames:
                abs_path = Path(fname_str).resolve()
                # Prova a renderlo relativo a SCRIPT_DIR
                try:
                    rel_path = abs_path.relative_to(SCRIPT_DIR)
                    # Usa relativo solo se più corto
                    path_to_add_str = str(rel_path) if len(str(rel_path)) < len(str(abs_path)) else str(abs_path)
                except ValueError: # Su drive diversi o non sottocartella
                    path_to_add_str = str(abs_path) # Usa assoluto

                if path_to_add_str not in current_files_str:
                    current_files_str.append(path_to_add_str)
                    added_count += 1

            if added_count > 0:
                self.config["source_files"] = current_files_str # Non ordiniamo qui, lo farà populate
                self.populate_source_list()

    @Slot()
    def remove_source_file(self):
        """Rimuove i file sorgente selezionati dalla lista."""
        selected_items = self.source_list_widget.selectedItems()
        if not selected_items:
            return
        current_files_str: List[str] = self.config.get("source_files", [])
        files_to_remove = {item.text() for item in selected_items}
        new_files_list = [f for f in current_files_str if f not in files_to_remove]

        if len(new_files_list) < len(current_files_str):
             self.config["source_files"] = new_files_list
             self.populate_source_list()

    def _resolve_path(self, path_str: str) -> Optional[Path]:
        """Risolve un percorso stringa (relativo o assoluto) in un Path assoluto."""
        try:
            p = Path(path_str)
            if not p.is_absolute():
                return (SCRIPT_DIR / p).resolve()
            return p.resolve()
        except Exception as e:
            logging.warning(f"Impossibile risolvere il percorso '{path_str}': {e}")
            return None

    @Slot()
    def validate_and_accept(self):
        """Valida i campi; se OK, aggiorna self.config e chiama accept()."""
        lupdate_path_str = self.lupdate_path_edit.text()
        lupdate_exe_name = self.lupdate_exe_edit.text().strip()
        ts_file_str = self.ts_file_edit.text()
        # source_files viene preso da self.config che è aggiornato da add/remove

        # --- Validazione ---
        lupdate_path = Path(lupdate_path_str)
        if not lupdate_path.is_dir():
            QMessageBox.warning(self, "Path Error", f"The specified LUpdate folder does not exist or is not a folder:\n{lupdate_path_str}")
            return

        lupdate_full_path = lupdate_path / lupdate_exe_name
        if not lupdate_exe_name or not lupdate_full_path.is_file():
            QMessageBox.warning(self, "Executable Error", f"The LUpdate executable was not found in the specified path:\n{lupdate_full_path}")
            return

        ts_path = Path(ts_file_str) # Non serve che esista già
        if not ts_path.name or not ts_path.name.lower().endswith(".ts"):
            QMessageBox.warning(self, "Translation File Error", f"Please specify a valid file name with extension .ts.\nReceived: {ts_path.name}")
            return

        source_files_str: List[str] = self.config.get("source_files", [])
        if not source_files_str:
            QMessageBox.warning(self, "Source File Error", "The Python source file list cannot be empty.")
            return

        # Verifica esistenza file sorgente (opzionale ma utile)
        missing_sources = []
        resolved_sources_for_config = [] # Lista dei percorsi da salvare
        for src_str in source_files_str:
            resolved_path = self._resolve_path(src_str)
            if resolved_path is None or not resolved_path.is_file():
                missing_sources.append(src_str)
            # Salviamo comunque il percorso inserito dall'utente (relativo o assoluto)
            resolved_sources_for_config.append(src_str)

        if missing_sources:
             if QMessageBox.question(self, "Missing Source Files?",
                                       f"The following source files were not found (or the paths are invalid):\n- " + \
                                       "\n- ".join(missing_sources) + \
                                       "\n\nThis may cause errors during the update.\nDo you want to save your settings anyway?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No:
                  return # L'utente ha annullato

        # --- Se validazione OK, aggiorna self.config ---
        self.config["lupdate_path"] = lupdate_path_str # Salva stringa originale
        self.config["lupdate_executable"] = lupdate_exe_name
        self.config["translation_file"] = ts_file_str # Salva stringa originale/normalizzata
        self.config["source_files"] = resolved_sources_for_config # Aggiornato da add/remove

        logging.info("Settings validated, ready to be saved.")
        super().accept() # Chiude il dialogo con stato Accettato

    def get_updated_config(self) -> Dict[str, Any]:
        """Restituisce la configurazione validata e aggiornata dal dialogo."""
        # Ritorna la copia interna che è stata modificata e validata
        return self.config


# --- Finestra Principale ---
class TranslatorToolWindow(QMainWindow):
    """Finestra principale dell'applicazione SaveStateTool."""

    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config_manager = config_manager
        self.process: Optional[QProcess] = None
        # Aggiungi stato per sapere quale processo sta girando
        self.current_process_type: Optional[str] = None # Può essere "lupdate" o "pyinstaller"


        # Impostazioni Applicazione Globale
        QCoreApplication.setApplicationName(APP_NAME)
        QCoreApplication.setOrganizationName(ORG_NAME)

        self.setWindowTitle(QCoreApplication.applicationName())
        self.setGeometry(200, 200, 700, 500)

        # --- Widget Principali ---
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        # self.log_output.setStyleSheet("background-color: #2B2B2B; color: #A9B7C6;") # Esempio colori stile IDE

        self.start_button = QPushButton("Start Translation Update")
        self.start_button.setObjectName("lupdateButton")
        self.package_button = QPushButton("Create App Package")
        self.package_button.setObjectName("packageButton")
        self.release_button = QPushButton("Create .QM File (lrelease)")
        self.release_button.setObjectName("releaseButton")
        self.quit_button = QPushButton("Exit")
        self.quit_button.setObjectName("quitButton")
        self.settings_button = QPushButton() # Icona gestita sotto
        self.settings_button.setObjectName("settingsButton")

        # Icona Impostazioni
        try:
            # Cerca l'icona in una sottocartella 'icons' relativa allo script
            settings_icon_path = resource_path("icons/settings.png")
            if settings_icon_path.is_file():
                self.settings_button.setIcon(QIcon(str(settings_icon_path)))
                self.settings_button.setFixedSize(QSize(32, 32))
                self.settings_button.setIconSize(QSize(24, 24))
                self.settings_button.setToolTip("Open Settings (F1)")
                self.settings_button.setShortcut("F1") # Scorciatoia
            else:
                 raise FileNotFoundError(f"Icon file not found at: {settings_icon_path}")
        except Exception as e:
             logging.warning(f"Settings icon not found or error: {e}. Use text 'Set'.")
             self.settings_button.setText("Set")
             self.settings_button.setToolTip("Open Settings (F1)")
             self.settings_button.setFixedSize(QSize(40, 32))
             self.settings_button.setShortcut("F1")

        # --- Layout ---
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.addWidget(QLabel("Process output (LUpdate / PyInstaller):"))
        main_layout.addWidget(self.log_output, stretch=1)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.settings_button)
        button_layout.addStretch()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.package_button)
        button_layout.addWidget(self.release_button)
        button_layout.addWidget(self.quit_button)
        main_layout.addLayout(button_layout)
        self.setCentralWidget(central_widget)

        # --- Connessioni ---
        self.start_button.clicked.connect(self.run_lupdate)
        self.package_button.clicked.connect(self.open_packaging_dialog)
        self.quit_button.clicked.connect(self.close) # Usa self.close per eventuale cleanup futuro
        self.settings_button.clicked.connect(self.open_settings)
        self.release_button.clicked.connect(self.run_lrelease)

        # --- Setup QProcess (una sola volta) ---
        # Creiamo l'oggetto QProcess qui ma lo configuriamo/avviamo nei metodi specifici
        self.process_runner = QProcess(self)
        self.process_runner.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process_runner.readyReadStandardOutput.connect(self.handle_output)
        self.process_runner.finished.connect(self.process_finished)

        
        self.log_message(f"[{APP_NAME}] Ready.")
        self.log_message(f"Configuration loaded by: {self.config_manager._config_filepath}")
        self.log_message("Press 'Start Update' or open Settings (⚙️/Set/F1).")

    def log_message(self, message: str):
        """Aggiunge un messaggio al log della GUI e al logger principale."""
        self.log_output.appendPlainText(message)
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)
        logging.info(f"GUI: {message}") # Logga anche su file/console

    def _resolve_path_for_run(self, path_str: str) -> Optional[Path]:
        """Risolve un path (relativo a SCRIPT_DIR o assoluto) per l'esecuzione."""
        try:
            p = Path(path_str)
            if not p.is_absolute():
                # Risolvi relativo rispetto alla directory dello script
                return (SCRIPT_DIR / p).resolve()
            # Se è già assoluto, risolvilo comunque per pulire (es. rimuovere '..')
            return p.resolve()
        except Exception as e:
             self.log_message(f"ERROR: Unable to resolve path '{path_str}': {e}")
             logging.error(f"Path resolution error for '{path_str}': {e}", exc_info=True)
             return None

    @Slot()
    def open_settings(self):
        """Apre la finestra di dialogo delle impostazioni."""
        dialog = SettingsDialog(self.config_manager.get_all(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.get_updated_config()
            self.config_manager.update_config(new_config) # Aggiorna in memoria
            if self.config_manager.save(): # Tenta il salvataggio su disco
                self.log_message("Settings updated and saved successfully.")
            else:
                self.log_message("ERROR: Unable to save settings to configuration file.")
                QMessageBox.critical(self, "Errore Salvataggio",
                                     f"Unable to save file:\n{self.config_manager._config_filepath}\nCheck logs and permissions.")
        else:
            self.log_message("Change settings canceled.")

    @Slot()
    def run_lupdate(self):
        """Prepara ed esegue il processo lupdate."""
        # 1. Controlla se un altro processo è già attivo (check iniziale corretto)
        if self.process_runner.state() != QProcess.ProcessState.NotRunning:
             QMessageBox.warning(self, "Processo in Corso", "Un altro processo (lupdate o pyinstaller) è già in esecuzione.")
             return

        self.log_output.clear()
        self.log_message(f"Translation update start (lupdate)...")
        self.current_process_type = "lupdate" # Imposta il tipo (corretto)

        # 2. Ottieni configurazione e valida percorsi (questa parte era corretta)
        lupdate_dir = self.config_manager.get_path("lupdate_path")
        lupdate_exe = self.config_manager.get_str("lupdate_executable")
        translation_file_str = self.config_manager.get_str("translation_file")
        source_files_config: List[str] = self.config_manager.get_list_str("source_files")

        lupdate_full_path = lupdate_dir / lupdate_exe
        if not lupdate_full_path.is_file():
            msg = f"ERROR: LUpdate executable not found:\n{lupdate_full_path}\nCheck your settings (F1)."
            self.log_message(msg)
            QMessageBox.critical(self, "Execution Error", msg)
            self.current_process_type = None # Resetta tipo se usciamo per errore
            return

        ts_path_resolved = self._resolve_path_for_run(translation_file_str)
        if ts_path_resolved is None or not ts_path_resolved.name.lower().endswith(".ts"):
             msg = f"ERROR: Translation file path (.ts) is invalid or unresolvable:\n{translation_file_str}"
             self.log_message(msg)
             QMessageBox.critical(self, "Configuration Error", msg)
             self.current_process_type = None # Resetta
             return
        try:
             ts_path_resolved.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
             logging.warning(f"Unable to create directory for {ts_path_resolved}: {e}. LUpdate may fail.")
             self.log_message(f"Warning: Unable to create folder for .ts file ({ts_path_resolved.parent}).")

        abs_source_files_for_run: List[str] = []
        valid = True
        for src_str in source_files_config:
             resolved_src = self._resolve_path_for_run(src_str)
             if resolved_src is None or not resolved_src.is_file():
                 self.log_message(f"ERRORE: File sorgente non trovato o non valido: {src_str} (solved as: {resolved_src})")
                 valid = False
             elif resolved_src:
                 abs_source_files_for_run.append(str(resolved_src))

        if not valid:
             msg = "One or more source files are invalid. Check your settings."
             QMessageBox.critical(self, "Source File Error", msg)
             self.current_process_type = None # Resetta
             return
        if not abs_source_files_for_run:
             msg = "ERROR: No valid source file (.py) specified in settings."
             self.log_message(msg)
             QMessageBox.critical(self, "Configuration Error", msg)
             self.current_process_type = None # Resetta
             return

        # 3. Costruisci comando (questa parte era corretta)
        command_parts = [str(lupdate_full_path)]
        command_parts.extend(abs_source_files_for_run)
        command_parts.extend(["-ts", str(ts_path_resolved)])

        # 4. Log comando (questa parte era corretta)
        self.log_message("-" * 30)
        self.log_message(f"Working directory (CWD): {SCRIPT_DIR}")
        self.log_message(f"LUpdate Command:")
        cmd_log_str = f'"{command_parts[0]}"'
        files_per_line = 2
        for i in range(0, len(abs_source_files_for_run), files_per_line):
            chunk = abs_source_files_for_run[i:i + files_per_line]
            cmd_log_str += " \\\n  " + " ".join(f'"{part}"' for part in chunk)
        cmd_log_str += f' \\\n  {command_parts[-2]}'
        cmd_log_str += f' \\\n  "{command_parts[-1]}"'
        self.log_message(cmd_log_str)
        self.log_message("-" * 30)

        # 5. Disabilita TUTTI i pulsanti usando il metodo helper (MODIFICA)
        self._set_buttons_enabled(False)

        # 6. Configura e avvia il processo USANDO self.process_runner (MODIFICA)
        # NON creare un nuovo QProcess qui! Usa quello condiviso.
        self.process_runner.setWorkingDirectory(str(SCRIPT_DIR))
        try:
            self.log_message("Starting lupdate process in progress...")
            # Estrai eseguibile e argomenti dalla lista command_parts
            lupdate_executable_path = command_parts[0]
            lupdate_arguments = command_parts[1:]

            # Usa self.process_runner per avviare
            self.process_runner.start(lupdate_executable_path, lupdate_arguments)

            if not self.process_runner.waitForStarted(5000): # Timeout 5 sec
                raise RuntimeError(f"lupdate process not started ({self.process_runner.error()}): {self.process_runner.errorString()}")
            self.log_message("lupdate process started successfully.")

        except Exception as e:
            error_msg = f"FATAL ERROR while starting lupdate: {e}"
            self.log_message(error_msg)
            logging.error(error_msg, exc_info=True)
            QMessageBox.critical(self, "Process Start Error", error_msg)
            # Resetta lo stato e riabilita i pulsanti chiamando process_finished
            # Passa un codice di errore e stato di crash per indicare che non è terminato normalmente
            # NON fare self.process = None qui
            self.process_finished( -1, QProcess.ExitStatus.CrashExit) # Simula un crash
            # --- NUOVI Metodi per Packaging ---
    @Slot()
    def open_packaging_dialog(self):
        """Apre il dialogo per scegliere il tipo di pacchetto."""
        if self.process_runner.state() != QProcess.ProcessState.NotRunning:
             QMessageBox.warning(self, "Process Running", "Another process (lupdate or pyinstaller) is already running.")
             return

        dialog = PackagingDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            package_type = dialog.get_selected_type()
            # Chiedi conferma finale prima di avviare
            command_preview = self._build_pyinstaller_command_preview(package_type) # Metodo helper per preview
            reply = QMessageBox.question(self, "Confirm Package Creation",
                                           f"You are about to start PyInstaller to create a package:\n\n"
                                           f"Type: {'One-File' if package_type == 'onefile' else 'One-Folder'}\n"
                                           f"Command (approximate):\n{command_preview}\n\n"
                                           f"Make sure you run this tool from the main project folder '{PACKAGER_APP_NAME}'.\n\n"
                                           "Proceed?",
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                           QMessageBox.StandardButton.Cancel)

            if reply == QMessageBox.StandardButton.Yes:
                self.run_pyinstaller(package_type)
            else:
                self.log_message("Package creation cancelled by user.")

    def _build_pyinstaller_command_preview(self, package_type: str) -> str:
        """Crea una stringa di anteprima del comando pyinstaller."""
        # NOTA: Questa è solo una preview, il comando reale viene costruito dopo
        pyinstaller_exe = "pyinstaller" # Nome base
        if package_type == "onefile":
             return f"{pyinstaller_exe} --clean {SPEC_FILE_ONEFILE}"
        else: # onefolder
             # Mostra solo le parti principali per la preview
             return f"{pyinstaller_exe} --onedir --name {PACKAGER_APP_NAME} --windowed --icon=... --add-data=... {PACKAGER_ENTRY_SCRIPT}"

    @Slot()
    def run_pyinstaller(self, package_type: str):
        """Prepara ed esegue il processo PyInstaller."""
        self.log_output.clear()
        self.log_message(f"Start package creation '{PACKAGER_APP_NAME}' ({package_type})...")
        self.current_process_type = "pyinstaller" # Imposta tipo processo

        # Trova l'eseguibile di pyinstaller
        import shutil
        pyinstaller_path_obj = shutil.which("pyinstaller")
        if not pyinstaller_path_obj:
            msg = "ERROR: Executable 'pyinstaller' not found in system PATH.\nMake sure PyInstaller is installed (pip install pyinstaller) and the path to the Python scripts is in your PATH."
            self.log_message(msg)
            QMessageBox.critical(self, "PyInstaller Error", msg)
            self.current_process_type = None # Resetta
            return
        pyinstaller_path = str(Path(pyinstaller_path_obj))
        self.log_message(f"Found PyInstaller in: {pyinstaller_path}")

        command_parts: List[str] = [pyinstaller_path]
        spec_file_path = SCRIPT_DIR / SPEC_FILE_ONEFILE

        # Costruisci il comando specifico
        try:
            if package_type == "onefile":
                if not spec_file_path.is_file():
                    msg = f"ERRORE: File .spec per One-File non trovato: {spec_file_path}"
                    self.log_message(msg)
                    QMessageBox.critical(self, "File Spec Error", msg)
                    self.current_process_type = None
                    return
                command_parts.extend(["--clean", str(spec_file_path)])
                self.log_message(f"Using the spec file: {spec_file_path}")

            elif package_type == "onefolder":
                command_parts.extend([
                    "--noconfirm",
                    "--clean",
                    "--onedir",
                    "--name", PACKAGER_APP_NAME,
                    "--windowed",
                ])
                # Aggiungi icona (assicurati che esista)
                icon_path = SCRIPT_DIR / PACKAGER_ICON_ICO
                if icon_path.is_file():
                    command_parts.extend(["--icon", str(icon_path)])
                else:
                    self.log_message(f"WARNING: Icon file .ico not found in {icon_path}, the executable will have no icon.")

                # Aggiungi --add-data
                for source, dest in PACKAGER_ADD_DATA:
                    source_path = SCRIPT_DIR / source
                    if not source_path.exists():
                         # Logga un avviso ma continua, PyInstaller darà errore se critico
                         self.log_message(f"WARNING: Source for --add-data not found: {source_path}")
                    # Aggiungi il separatore corretto per PyInstaller (varia per OS, ma ; di solito funziona)
                    command_parts.extend(["--add-data", f"{str(source_path)}{os.pathsep}{dest}"])

                # Aggiungi --hidden-import
                for hidden_import in PACKAGER_HIDDEN_IMPORTS:
                    command_parts.extend(["--hidden-import", hidden_import])

                # Aggiungi lo script di ingresso
                entry_script_path = SCRIPT_DIR / PACKAGER_ENTRY_SCRIPT
                if not entry_script_path.is_file():
                     msg = f"ERROR: Input script '{PACKAGER_ENTRY_SCRIPT}' not found in {SCRIPT_DIR}"
                     self.log_message(msg)
                     QMessageBox.critical(self, "Script Input Error", msg)
                     self.current_process_type = None
                     return
                command_parts.append(str(entry_script_path))
            else:
                 raise ValueError(f"Invalid package type: {package_type}")

        except Exception as e:
            error_msg = f"Error building PyInstaller command: {e}"
            self.log_message(error_msg)
            logging.error(error_msg, exc_info=True)
            QMessageBox.critical(self, "Internal Error", error_msg)
            self.current_process_type = None
            return

        # Log comando finale (può essere molto lungo)
        self.log_message("-" * 30)
        self.log_message(f"Working directory (CWD): {SCRIPT_DIR}")
        self.log_message(f"PyInstaller command to run:")
        # Stampa comando in modo più leggibile nel log
        log_cmd = f'"{command_parts[0]}"'
        current_line = log_cmd
        for part in command_parts[1:]:
            quoted_part = f'"{part}"' if ' ' in part else part
            if len(current_line) + len(quoted_part) + 1 > 100: # Vai a capo se troppo lungo
                self.log_message(current_line + " \\")
                current_line = "  " + quoted_part
            else:
                current_line += " " + quoted_part
        self.log_message(current_line) # Stampa ultima riga
        self.log_message("-" * 30)

        # Disabilita i pulsanti e avvia
        self._set_buttons_enabled(False)

        # Avvia il processo PyInstaller (USANDO self.process_runner)
        self.process_runner.setWorkingDirectory(str(SCRIPT_DIR)) # Esegui dalla cartella dello script (progetto)
        try:
            self.log_message("Starting PyInstaller process... (may take some time)")
            self.process_runner.start(command_parts[0], command_parts[1:])
            if not self.process_runner.waitForStarted(10000): # Timeout più lungo per PyInstaller
                 raise RuntimeError(f"PyInstaller process not started ({self.process_runner.error()}): {self.process_runner.errorString()}")
            self.log_message("PyInstaller process started...")
        except Exception as e:
            error_msg = f"FATAL ERROR while starting PyInstaller: {e}"
            self.log_message(error_msg)
            logging.error(error_msg, exc_info=True)
            QMessageBox.critical(self, "PyInstaller Startup Error", error_msg)
            # Chiama process_finished per riabilitare bottoni etc.
            self.process_finished( -1, QProcess.ExitStatus.CrashExit)
            
    @Slot()
    def run_lrelease(self):
        """Prepara ed esegue il processo lrelease per creare il file .qm."""
        if self.process_runner.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Processo in Corso", "Un altro processo (lupdate o pyinstaller) è già in esecuzione.")
            return

        self.log_output.clear()
        self.log_message(f"Starting .qm file compilation (lrelease)...")
        self.current_process_type = "lrelease" # Imposta il tipo di processo

        # Ottieni configurazione
        lupdate_dir = self.config_manager.get_path("lupdate_path")
        # Assumi che lrelease sia nella stessa cartella di lupdate
        # Determina il nome dell'eseguibile (es. lrelease.exe su Win, lrelease su altri)
        lrelease_exe_name = "lrelease.exe" if platform.system() == "Windows" else "lrelease"
        lrelease_full_path = lupdate_dir / lrelease_exe_name
        translation_file_str = self.config_manager.get_str("translation_file") # Es: SaveState_en.ts

        # Validazione percorsi
        if not lrelease_full_path.is_file():
            msg = f"ERROR: LRelease executable not found (searched for LUpdate):\n{lrelease_full_path}\nVerifica che esista nella stessa cartella di lupdate."
            self.log_message(msg)
            QMessageBox.critical(self, "Error Execution lrelease", msg)
            self.current_process_type = None
            return

        # Risolvi e valida il percorso del file .ts
        ts_path_resolved = self._resolve_path_for_run(translation_file_str)
        if ts_path_resolved is None or not ts_path_resolved.is_file():
            msg = f"ERROR: Translation file (.ts) to compile not found or invalid:\n{translation_file_str} (Solved: {ts_path_resolved})"
            self.log_message(msg)
            QMessageBox.critical(self, ".ts File Error", msg)
            self.current_process_type = None
            return

        # Costruisci comando: lrelease file.ts [-qm file.qm] (l'output di default è file.qm)
        command_parts = [str(lrelease_full_path), str(ts_path_resolved)]
        # Potremmo specificare il file di output -qm opzionalmente, ma di default lo crea accanto al .ts
        output_qm_file = ts_path_resolved.with_suffix(".qm")
        self.log_message(f"Expected output .qm file: {output_qm_file}")

        # Log comando
        self.log_message("-" * 30)
        # Imposta CWD alla cartella del file .ts, lrelease potrebbe cercare file lì
        ts_dir = ts_path_resolved.parent
        self.log_message(f"Working directory (CWD): {ts_dir}")
        self.log_message(f"LRelease command:")
        self.log_message(f'"{command_parts[0]}" "{command_parts[1]}"')
        self.log_message("-" * 30)

        # Disabilita i pulsanti e avvia
        self._set_buttons_enabled(False)
        self.process_runner.setWorkingDirectory(str(ts_dir)) # Esegui dalla cartella del .ts

        try:
            self.log_message("Starting the release process...")
            self.process_runner.start(command_parts[0], command_parts[1:])
            if not self.process_runner.waitForStarted(5000): # Timeout 5 sec
                raise RuntimeError(f"Release process not started ({self.process_runner.error()}): {self.process_runner.errorString()}")
            self.log_message("Release process started successfully.")
        except Exception as e:
            error_msg = f"FATAL ERROR while starting lrelease: {e}"
            self.log_message(error_msg)
            logging.error(error_msg, exc_info=True)
            QMessageBox.critical(self, "Error Starting lrelease", error_msg)
            # Chiama process_finished per riabilitare bottoni etc.
            self.process_finished( -1, QProcess.ExitStatus.CrashExit)
    
    @Slot()
    def handle_output(self):
        """Legge e logga l'output (stdout/stderr uniti) dal processo in corso."""
        if not self.process_runner: return
        try:
            data = self.process_runner.readAllStandardOutput() # QByteArray
            text = ""
            try:
                 import locale
                 preferred_encoding = locale.getpreferredencoding(False) or 'utf-8'
                 text = data.data().decode(preferred_encoding, errors='replace')
            except Exception:
                 try:
                      text = data.data().decode('utf-8', errors='replace')
                 except Exception:
                      text = data.data().decode('latin-1', errors='replace')

            # Keywords per identificare righe di interesse (lupdate e lrelease)
            info_keywords_lupdate = ["updating", "found", "new and", "removed", "obsolete", "finished"]
            info_keywords_lrelease = ["releasing", "writing", "generated"]
            warning_keywords = ["warning:"]

            # Logga righe non vuote
            for line in text.strip().splitlines():
                 line_content = line.strip()
                 if not line_content:
                      continue # Salta righe vuote

                 line_lower = line_content.lower()
                 prefix = "" # Prefisso per il log GUI

                 # Controlla se è una riga di avviso
                 is_warning = any(keyword in line_lower for keyword in warning_keywords)
                 if is_warning:
                      prefix = f"ATTENZIONE [{self.current_process_type or 'Processo'}]: "
                      logging.warning(f"{self.current_process_type or 'Process'}: {line_content}")
                 # Controlla se è una riga informativa specifica del processo
                 elif self.current_process_type == "lupdate":
                      is_info = any(keyword in line_lower for keyword in info_keywords_lupdate)
                      if is_info:
                           prefix = "LUpdate Info: "
                           logging.info(f"LUpdate Stat: {line_content}")
                 elif self.current_process_type == "lrelease":
                       is_info = any(keyword in line_lower for keyword in info_keywords_lrelease)
                       if is_info:
                            prefix = "LRelease Info: "
                            logging.info(f"LRelease Stat: {line_content}")
                 elif self.current_process_type == "pyinstaller":
                      # PyInstaller ha molto output, potremmo filtrare o loggare tutto
                      # Per ora logghiamo tutto senza prefisso specifico, a meno che non sia un warning
                      if not is_warning:
                           prefix = "PyInstaller: " # Aggiungi prefisso generico

                 # Se non è un avviso o un'info specifica, potrebbe essere altro output
                 if not prefix and not is_warning:
                      # Potresti decidere di loggare comunque o ignorare output generico
                      # Per ora logghiamo con un prefisso generico se non identificato
                      prefix = "Output: "

                 self.log_message(prefix + line_content)

        except Exception as e:
             logging.error(f"Error reading process output: {e}", exc_info=True)

    @Slot()
    def process_finished(self, exit_code: int = 0, exit_status: QProcess.ExitStatus = QProcess.ExitStatus.NormalExit):
        """Slot chiamato quando il processo QProcess (lupdate o pyinstaller) termina."""
        # Se non c'è processo, esci
        actual_exit_code = exit_code
        actual_exit_status = exit_status
        if self.process_runner and self.process_runner.state() == QProcess.ProcessState.NotRunning:
                # Se il processo è terminato, controlla il suo stato
                 try:
                     actual_exit_code = self.process_runner.exitCode()
                     actual_exit_status = self.process_runner.exitStatus()
                 except RuntimeError: # Può capitare se il processo non è mai stato valido
                     pass


        process_name = self.current_process_type or "Unknown process"
        log_prefix = f"[{process_name.upper()}] "
        self.log_message("-" * 30)

        if actual_exit_status == QProcess.ExitStatus.NormalExit and actual_exit_code == 0:
            msg = f"{process_name.capitalize()} completed successfully."
            self.log_message(log_prefix + msg)
            
            # Mostra messaggio specifico per processi di successo
            if self.current_process_type == "pyinstaller":
                 dist_folder = SCRIPT_DIR / "dist" # Cartella output di PyInstaller

            elif self.current_process_type == "lrelease":
                 # Cerca di mostrare il percorso del file .qm creato
                 translation_file_str = self.config_manager.get_str("translation_file")
                 ts_path_resolved = self._resolve_path_for_run(translation_file_str) # Usa la stessa logica di run_lrelease
                 if ts_path_resolved and ts_path_resolved.exists(): # Controlla se il .ts esiste ancora
                      output_qm_file = ts_path_resolved.with_suffix(".qm")
                      # Mostra il percorso del file .qm atteso

        elif actual_exit_status == QProcess.ExitStatus.NormalExit:
            msg = f"{process_name.capitalize()} terminated with exit code: {actual_exit_code}."
            self.log_message(log_prefix + msg)
            logging.warning(log_prefix + msg)
            QMessageBox.warning(self, "Process Completed with Code", f"{process_name.capitalize()} finished with code {actual_exit_code}.\nCheck the log for details.")
        else: # CrashExit
            msg = f"ERROR: {process_name.capitalize()} terminated abnormally (crash?). Code: {actual_exit_code}"
            self.log_message(log_prefix + msg)
            logging.error(log_prefix + msg)
            QMessageBox.critical(self, f"Process Error {process_name.capitalize()}", f"The process terminated abnormally.\nCode: {actual_exit_code}")

        # Riabilita i pulsanti e resetta lo stato
        self._set_buttons_enabled(True)
        self.current_process_type = None
        
    # --- Metodo Helper per abilitare/disabilitare bottoni ---
    def _set_buttons_enabled(self, enabled: bool):
        """Abilita o disabilita i pulsanti di azione principali."""
        self.start_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
        self.package_button.setEnabled(enabled)
        self.release_button.setEnabled(enabled)    

    def closeEvent(self, event):
        """Gestisce l'evento di chiusura della finestra."""
        # Qui potresti aggiungere logica per fermare processi in corso, se necessario
        logging.info("Application closing.")
        event.accept()


# --- Blocco Principale di Avvio ---
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Crea il gestore della configurazione (carica o crea config in AppData)
    try:
         config_manager = ConfigManager()
    except Exception as e:
         # Errore critico nel caricamento/creazione config iniziale
         logging.critical(f"Fatal error while initializing ConfigManager: {e}", exc_info=True)
         QMessageBox.critical(None, "Critical Boot Error",
                              f"Unable to load or create initial configuration.\n"
                              f"check the permissions of the AppData folder\n\nDetails: {e}")
         sys.exit(1) # Esce dall'applicazione

    # Applica tema scuro
    try:
        if DARK_THEME_QSS and isinstance(DARK_THEME_QSS, str):
            app.setStyleSheet(DARK_THEME_QSS)
            #logging.info("Tema scuro applicato.")
        else:
            logging.warning("DARK_THEME_QSS invalid or undefined. Using Qt default theme.")
    except Exception as e_theme:
        logging.error(f"Theme Application Error: {e_theme}", exc_info=True)

    # Crea e mostra la finestra principale
    try:
        window = TranslatorToolWindow(config_manager)
        window.show()
    except Exception as e_gui:
         logging.critical(f"Fatal error while creating GUI: {e_gui}", exc_info=True)
         QMessageBox.critical(None, "Critical Boot Error",
                              f"Unable to create main window.\n\nDetails: {e_gui}")
         sys.exit(1)

    # Esegui il loop dell'applicazione
    sys.exit(app.exec())