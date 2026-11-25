"""Render tools/banner/banner.html to images/banner.png with headless Chrome/Edge.

Usage:  python tools/banner/render.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
HTML = HERE / "banner.html"
OUT = REPO / "images" / "banner.png"
WIDTH, HEIGHT, SCALE = 1200, 600, 2

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]


def find_browser():
    for c in CANDIDATES:
        if os.path.isfile(c) or shutil.which(c):
            return c
    sys.exit("No Chrome/Edge/Chromium found.")


def main():
    browser = find_browser()
    subprocess.run([
        browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--window-size={WIDTH},{HEIGHT}",
        f"--force-device-scale-factor={SCALE}",
        f"--screenshot={OUT}",
        "--allow-file-access-from-files",
        HTML.as_uri(),
    ], check=True)
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
