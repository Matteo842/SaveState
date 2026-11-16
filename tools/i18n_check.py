# -*- coding: utf-8 -*-
"""
Translation check for SaveState.

Run it from the project folder:

    python tools/i18n_check.py            report what is missing or wrong
    python tools/i18n_check.py --export   also write lang/_missing_<code>.json

It reads every tr("...") and trn("...", "...") in the code and compares them
with the files in the "lang" folder. It never changes the code or the
translation files.

What it reports, per language:
  MISSING      text used in the code, no translation yet (shown in English)
  UNUSED       translation whose English text is no longer in the code
  PLACEHOLDER  translation whose {0} {1} ... do not match the English text
"""
import ast
import json
import os
import string
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from common.i18n import ENGLISH, LANG_FOLDER, LANGUAGES, QT_STANDARD_TEXTS  # noqa: E402

SKIP_FOLDERS = {"__pycache__", ".git", "tests", "tester", "tools", "scripts", "build", "dist", "venv", ".venv"}


def find_python_files():
    for folder, subfolders, files in os.walk(PROJECT_DIR):
        subfolders[:] = [name for name in subfolders if name not in SKIP_FOLDERS]
        for name in files:
            if name.endswith(".py") and not name.startswith("test_") and name != "i18n.py":
                yield os.path.join(folder, name)


def collect_texts():
    """Return {english text: "file:line" of its first use} and a list of problems."""
    texts = {}
    problems = []
    for path in sorted(find_python_files()):
        relative = os.path.relpath(path, PROJECT_DIR).replace("\\", "/")
        with open(path, "rb") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "tr":
                text_args = node.args[:1]
            elif node.func.id == "tr_for":
                text_args = node.args[1:2]
            elif node.func.id == "trn":
                text_args = node.args[:2]
            else:
                continue
            for arg in text_args:
                where = f"{relative}:{node.lineno}"
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    texts.setdefault(arg.value, where)
                else:
                    problems.append(f"{where}: the text inside tr() must be written directly, "
                                    f"not built from variables")
    for text in QT_STANDARD_TEXTS:
        texts.setdefault(text, "Qt standard button")
    return texts, problems


def placeholders(text):
    """The {0} {name} ... fields of a text, or None when the braces are broken."""
    try:
        return sorted({str(field) for _, field, _, _ in string.Formatter().parse(text) if field is not None})
    except ValueError:
        return None


def collect_texts_with_arguments():
    """English texts that are filled with values, e.g. tr("Hello {0}", name)."""
    with_args = set()
    for path in find_python_files():
        with open(path, "rb") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "tr" and (len(node.args) > 1 or node.keywords):
                if isinstance(node.args[0], ast.Constant):
                    with_args.add(node.args[0].value)
            elif node.func.id == "trn":
                for arg in node.args[:2]:
                    if isinstance(arg, ast.Constant):
                        with_args.add(arg.value)
    return with_args


def main():
    export = "--export" in sys.argv
    texts, problems = collect_texts()
    with_args = collect_texts_with_arguments()
    print(f"Texts found in the code: {len(texts)}")
    for problem in problems:
        print("  PROBLEM", problem)

    exit_code = 1 if problems else 0
    for code, name in LANGUAGES.items():
        if code == ENGLISH:
            continue
        path = os.path.join(PROJECT_DIR, LANG_FOLDER, f"{code}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                translations = json.load(f)
        except FileNotFoundError:
            translations = {}
        except ValueError as e:
            print(f"\n{name} ({code}): the file is not valid JSON: {e}")
            exit_code = 1
            continue

        missing = [text for text in texts if not translations.get(text)]
        unused = [text for text in translations if text not in texts]
        wrong = []
        for text, translated in translations.items():
            if text in with_args and isinstance(translated, str) and translated:
                if placeholders(translated) != placeholders(text):
                    wrong.append(text)

        print(f"\n{name} ({code}): {len(texts) - len(missing)} of {len(texts)} translated")
        for text in missing:
            print(f"  MISSING      {text!r}   ({texts[text]})")
        for text in unused:
            print(f"  UNUSED       {text!r}")
        for text in wrong:
            print(f"  PLACEHOLDER  {text!r} -> {translations[text]!r}")
        if missing or wrong:
            exit_code = 1

        if export and missing:
            out_path = os.path.join(PROJECT_DIR, LANG_FOLDER, f"_missing_{code}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({text: "" for text in missing}, f, ensure_ascii=False, indent=2)
            print(f"  -> written {out_path}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
