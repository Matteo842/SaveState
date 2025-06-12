# SaveState

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Latest Release](https://img.shields.io/github/v/release/Matteo842/SaveState)](https://github.com/Matteo842/SaveState/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Matteo842/SaveState/total.svg)](https://github.com/Matteo842/SaveState/releases)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/V7V61GBYAX)

A user-friendly GUI application for Windows and Linux to easily back up and restore video game save files, especially useful for games without cloud saves or for managing multiple save locations.

![Main GUI](images/gui.png)

## About this Project

**SaveState** aims to prevent the frustration of losing your precious game progress due to corruption, accidental deletion, or system changes.

This tool offers a simple graphical user interface for creating compressed backups of your game save files and folders, managing multiple game profiles, and restoring them whenever needed.

Furthermore, SaveState features automatic detection of Steam games and even lets you generate profiles directly from Minecraft worlds or game shortcuts.

---

⚠️ Current Status (2025-06-06): This is a personal project currently **under active development.** 

---

## Features

* **Backup & Restore:** Perform compressed `.zip` backups for selected profiles with a single click. Restore from any available backup.
* **Automatic Backup Management:**
    * Configurable number of backups to keep per profile (automatically deletes the oldest).
    * Configurable backup compression level (Standard/Recommended, Maximum, or None/Stored).
    * Optional check for minimum free disk space on the backup drive before starting a backup.
    * Optional check for maximum source folder size to prevent accidental backup of huge folders.
* **Steam Integration:**
    * Scans for Steam installation and libraries.
    * Automatically detects installed Steam games.
    * Attempts to identify the correct Steam User ID (resolving profile names if the optional `vdf` library is installed).
    * Suggests save game paths based on Steam UserData conventions.
    * Configure backup profiles for Steam games directly from the detected list.
* **Drag & Drop Profile Creation:** Drag a game's shortcut (`.lnk` file) onto the main window to automatically extract the game name and installation path, then initiates a background search for the save location.
* **Manual Profile Creation:** Easily add any game by specifying a profile name and the path to its save folder.
* **Multi Profile Creation:** 
    * Drag a folder OR multiple shortcuts on the main window. 
    * You can visualize all the profile of the folder and start searching for the save path; 
    * You can add all the profile visulizing the save path and add all the profile to the list.
* **Minecraft Java Edition Support:**
    * Automatically locates the default `.minecraft/saves` folder.
    * Lists all installed worlds, reading the world name from `level.dat` if the optional `nbtlib` library is present (falls back to folder name otherwise).
    * Create backup profiles directly from the detected world list.
* **Desktop Shortcut Creation:** Create `.lnk` shortcuts on your desktop for specific profiles. Clicking the shortcut runs a silent backup for that profile using `backup_runner.py` and shows a desktop notification.
* **Emulator Support (Experimental):**
    * Automatic detection and profile creation for supported emulators' save data.
* **User Interface:**
    * Clean and simple graphical interface built with PySide6.
    * Switchable Dark and Light themes.
    * Profile list showing name and basic backup info (count, last backup date).
    * Settings dialog to configure paths, limits, theme, language, and more.
    * Dockable Log Console displaying detailed operation status and errors.
* **No Administrator Privileges Required**
* **Portable:** Runs directly from the `.exe` file without installation.

## Visuals

**Drag & Drop Shortcut for Profile Creation:**
![Drag and Drop GIF](images/drag_and_drop.gif)


## Supported Emulators

SaveState includes experimental support for automatically detecting save data locations for certain emulators, simplifying the profile creation process.

**Currently Supported in version 1.4.2:**

|               |              |            |
|---------------|--------------|------------|
| Ryujinx       | Yuzu         | Rpcs3      |
| DuckStation   | Dolphin      | PPSSPP     |
| Citra         | Azahar       | mGBA       |
| Snes9x        | DeSmuME      | Cemu       |
| Flycast       | ShadPs4      | SameBoy    |
| PCSX2 \*      | xenia        | Eden (yuzu)| 

---
\* PlayStation 2 memory card functionality in `SaveState` utilizes and adapts code from the [mymcplusplus](https://github.com/Adubbz/mymcplusplus) project, which is based on mymc+ by Florian Märkl and the original mymc by Ross Ridge. The mymcplusplus source code is distributed under the GNU General Public License v3.0. `SaveState`, including these derived components, is also licensed under GPLv3.

---

## How Save Search Works (Heuristics)

The following diagram illustrates the main steps that SaveState follows when attempting to locate a game's save folder:

![FlowChart](images/FlowChart.png)

**Log Console:**
![Log Console](images/log.png)

## Getting Started

Get SaveState up and running on your system.

### Prerequisites

* **Operating System:** Windows (tested on Windows 10/11). Relies on Windows-specific libraries for shortcut handling.
* **Operating System:** Linux (tested on Ubuntu 24.x LTS)
* **Python:** Version 3.10 or higher recommended. (3.13 work fine)
* **Pip:** Python package installer (usually included with Python).

### Installation

**Option 1: Using the Release (Recommended for most users)**

**windows**
1.  Go to the [**Releases Page**](https://github.com/Matteo842/SaveState/releases/latest) on GitHub.
2.  Download the `SaveState.exe` file from the latest release assets.
3.  Place `SaveState.exe` in any folder you like and simply run it. No installation required!

**Linux**
1.  Go to the [**Releases Page**](https://github.com/Matteo842/SaveState/releases/latest) on GitHub.
2.  Download the `SaveState-linux.zip` file from the latest release assets.
3.  Place `SaveState` in any folder you like and simply run it. No installation required!

**Option 2: Running from Source (for development or advanced users)**

1.  Ensure you have Python 3.10+ and Git installed.
2.  Clone the repository:
    ```bash
    git clone [https://github.com/Matteo842/SaveState.git](https://github.com/Matteo842/SaveState.git)
    ```
3.  Navigate into the project directory:
    ```bash
    cd SaveState
    ```
4.  (Recommended) Create and activate a virtual environment:
    ```bash
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On Linux/macOS
    source venv/bin/activate
    ```
5.  Install the required dependencies (see Dependencies section below):
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: You need to create the `requirements.txt` file first!)*
6.  Run the application:
    ```bash
    python main.py
    ```

## Usage

1.  **Launch** `SaveState.exe` or run `python main.py`.
2.  **Configure Settings (Recommended on first launch):** Click the Settings button. Set your desired Base Backup Path where all backups will be stored in subfolders named after your profiles. Adjust other settings like max backups, Maximum source size, etc.
3.  **Add Profiles:**
    * **Manually:** Click New Manual Profile, enter a name, and provide the full path to the game's save folder.
    * **Steam:** Click Manage Steam Games. Select a detected game and click Configure Selected Profile. The app will try to guess the save path; confirm or provide it manually.
    * **Minecraft:** Click the Minecraft button. Select a world from the list and click OK. A profile will be created using the world name and its folder path.
    * **Drag & Drop:** Drag a game's `.lnk` shortcut file from your Desktop or elsewhere onto the main application window. The app will suggest a profile name and start searching for the save path; you'll be prompted to confirm or enter it manually.
    * **Multi Profile:** drop a `folder` containing multiple games on the main window. You can visualize all the profile of the folder and delete the profile you don't need. Then you can add all the profile to the list.
4.  **Manage Profiles:**
    * Select a profile in the list.
    * Click **Run Backup** to back it up.
    * Click **Restore from Backup** to restore from a previous backup.
    * Click **Manage Backup** to view and delete specific backup archives for that profile.
    * Click the **Shortcut Icon button** to create a shortcut on your Desktop for quick backups of that profile.
    * Click **Delete Profile** to remove the profile entry (this does not delete existing backup files).
5.  **Other Actions:**
    * Use **Open Backup Folder** to quickly open the base backup location in Explorer.
    * Double Click on a profile to **open** the **save path** in Explorer.
    * Toggle the **Log Console** visibility using the terminal icon button.
    * Toggle the **Theme** using the sun/moon icon button.

## Dependencies

This project relies on the following Python packages:

* **Required:**
    * [`PySide6`](https://pypi.org/project/PySide6/): For the graphical user interface (Qt for Python).
    * [`winshell`](https://pypi.org/project/winshell/): Used for reading `.lnk` shortcut files and finding special Windows folders like the Desktop.
    * [`pywin32`](https://pypi.org/project/pywin32/): A dependency for `winshell` (and used directly for creating shortcuts via COM). *(Note: Installation might sometimes require specific steps or precompiled binaries depending on your Python setup).*

* **Optional (for enhanced features):**
    * [`vdf`](https://pypi.org/project/vdf/): Used to parse Valve's VDF/ACF files to get more accurate Steam game names and library information. If not installed, Steam detection will still work but might use less precise names.
    * [`nbtlib`](https://pypi.org/project/nbtlib/): Used to read Minecraft's `level.dat` NBT files to get the actual world names. If not installed, the world's folder name will be used as the profile name instead.
    * [`thefuzz`](https://pypi.org/project/thefuzz/): It uses Levenshtein Distance to calculate the differences between sequences.

You can install all dependencies using pip. It is recommended to create a `requirements.txt` file with the following content:

```txt
PySide6
winshell
pywin32
vdf
nbtlib
thefuzz
```

And then run:
```txt
pip install -r requirements.txt
```

## Development


![why not use development builds on linux?](images/Development.png)
*(Screenshot: Development.png)*


---
[No time to fate, save your state!](https://www.youtube.com/@MrSujano)

---

## License

Distributed under the **GNU General Public License v3.0.** See the [`LICENSE`](https://www.gnu.org/licenses/gpl-3.0)file for more information.
