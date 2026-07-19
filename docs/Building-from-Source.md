# Building from Source

For development or advanced users. Most people should use a [Release](https://github.com/Matteo842/SaveState/releases/latest) or WinGet instead.

> **Note:** Code pull requests are **not** accepted at this time. See [CONTRIBUTING.md](../CONTRIBUTING.md). Issues and feedback are welcome.

## Prerequisites

- **Windows** 10/11, or **Linux** (tested on Ubuntu 24.x LTS)
- **Python** 3.10+ (3.13 works fine)
- **pip** (usually included with Python)
- **Git**

## Setup

```bash
git clone https://github.com/Matteo842/SaveState.git
cd SaveState
```

Create and activate a virtual environment:

```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
```

Install dependencies and run:

```bash
pip install -r requirements.txt
python main.py
```

## Dependencies

**Required:**

| Package | Role |
|---------|------|
| [PySide6](https://pypi.org/project/PySide6/) | GUI (Qt for Python) |
| [winshell](https://pypi.org/project/winshell/) | `.lnk` shortcuts and special folders (Windows) |
| [pywin32](https://pypi.org/project/pywin32/) | Used with winshell / COM shortcuts (Windows) |

**Optional (enhanced features):**

| Package | Role |
|---------|------|
| [vdf](https://pypi.org/project/vdf/) | More accurate Steam names/libraries |
| [nbtlib](https://pypi.org/project/nbtlib/) | Minecraft world names from `level.dat` |
| [thefuzz](https://pypi.org/project/thefuzz/) | Fuzzy string matching for save detection |

Without the optional packages, core backup/restore still works; Steam/Minecraft naming and fuzzy matching may be less precise.
