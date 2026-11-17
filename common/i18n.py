# -*- coding: utf-8 -*-
"""
SaveState translations.

How it works:
  - The code writes every text in English, wrapped in tr():   tr("Settings")
  - Each language has one JSON file in the "lang" folder:      {"Settings": "Impostazioni"}
  - The English text itself is the key. There are no IDs, no line numbers and
    no compiled files.
  - If a translation is missing (or the English text was changed in the code),
    that one text is shown in English. Nothing else is affected.

Until init_language() is called the language is English and tr() returns the
text unchanged.

Run "python tools/i18n_check.py" to see which texts still need a translation.
"""
import json
import logging
import os

from common.utils import resource_path

ENGLISH = "en"
AUTO = "auto"  # Follow the language of the operating system
SETTINGS_KEY = "language"
LANG_FOLDER = "lang"

# Languages offered in the language selector: code -> name written in that language.
# To add a language: add it here and create lang/<code>.json.
LANGUAGES = {
    "en": "English",
    "it": "Italiano",
    "de": "Deutsch",
    "es": "Español",
    "pt": "Português (Brasil)",
    "ru": "Русский",
    "ja": "日本語",
    "zh_CN": "简体中文",
}

# The same languages written in English, used by the search box of the selector.
LANGUAGE_ENGLISH_NAMES = {
    "en": "English",
    "it": "Italian",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese (Brazil)",
    "ru": "Russian",
    "ja": "Japanese",
    "zh_CN": "Chinese (Simplified)",
}

# Texts that belong to Qt itself (standard buttons like Yes / No / Cancel).
# They are translated from the same JSON files, see install_qt_translator().
QT_STANDARD_TEXTS = (
    "OK", "Cancel", "&Yes", "&No", "Yes to &All", "N&o to All",
    "Save", "Save All", "Open", "Close", "Apply", "Reset", "Help",
    "Discard", "Abort", "Retry", "Ignore", "Restore Defaults",
    # Right-click menu of text fields
    "&Undo", "&Redo", "Cu&t", "&Copy", "&Paste", "Delete", "Select All",
)

_current_language = ENGLISH
_translations = {}  # English text -> translated text, for the current language
_qt_translator = None  # Kept here so Qt does not lose it


def tr(text, *args, **kwargs):
    """Return `text` in the current language.

    Values that change at runtime are passed as extra arguments and go where
    the text has {0}, {1}, ... (or {name} for named arguments):

        tr("Profile '{0}' deleted.", profile_name)

    A missing or broken translation falls back to the English text.
    """
    translated = _translations.get(text)
    if not args and not kwargs:
        return translated if translated else text
    if translated:
        try:
            return translated.format(*args, **kwargs)
        except Exception:
            # The translation has a wrong placeholder: use the English text instead.
            logging.debug(f"i18n: broken translation for {text!r} in '{_current_language}'")
    return text.format(*args, **kwargs)


def trn(singular, plural, count, *args):
    """Like tr(), but picks the singular or plural text from `count`.

    `count` is {0}, any extra argument is {1}, {2}, ...:

        trn("Add {0} profile", "Add {0} profiles", number_of_profiles)
    """
    return tr(singular if count == 1 else plural, count, *args)


def tr_for(code, text):
    """Return `text` in the language `code`, whatever language is in use now."""
    if code == _current_language:
        return tr(text)
    return load_translations(code).get(text, text)


def get_language():
    """Code of the language in use right now, for example "en" or "it"."""
    return _current_language


def match_language(locale_name):
    """Map a system locale name ("it-IT", "zh_Hans_CN", ...) to one of LANGUAGES.

    Returns None when SaveState has no translation for it.
    """
    parts = str(locale_name).replace("_", "-").lower().split("-")
    primary = parts[0]
    if primary == "zh":
        # Only Simplified Chinese is available. Traditional Chinese systems
        # keep English unless the user picks a language by hand.
        if "hant" in parts or any(region in parts for region in ("tw", "hk", "mo")):
            return None
        return "zh_CN"
    for code in LANGUAGES:
        if code.split("_")[0].lower() == primary:
            return code
    return None


def detect_system_language():
    """Best language for this computer, English when there is no translation."""
    try:
        from PySide6.QtCore import QLocale
        system_names = list(QLocale.system().uiLanguages())
    except Exception as e:
        logging.debug(f"i18n: could not read the system language: {e}")
        return ENGLISH

    chinese_is_traditional = False
    for name in system_names:  # Ordered from most to least preferred
        if str(name).lower().startswith("zh"):
            if chinese_is_traditional:
                continue
            if match_language(name) is None:
                chinese_is_traditional = True
                continue
        code = match_language(name)
        if code:
            return code
    return ENGLISH


def read_saved_setting():
    """Language chosen by the user in settings.json: a language code or "auto"."""
    try:
        from core import settings_manager
        settings_path = os.path.join(settings_manager.get_active_config_dir(),
                                     settings_manager.SETTINGS_FILENAME)
        if not os.path.isfile(settings_path):
            return AUTO
        with open(settings_path, "r", encoding="utf-8") as f:
            value = json.load(f).get(SETTINGS_KEY, AUTO)
        return value if value in LANGUAGES else AUTO
    except Exception as e:
        logging.debug(f"i18n: could not read the saved language: {e}")
        return AUTO


def resolve_language(setting):
    """Turn a saved setting (a language code or "auto") into a language code."""
    if setting in LANGUAGES:
        return setting
    return detect_system_language()


def load_translations(code):
    """Read lang/<code>.json. Returns an empty dict for English or on any error."""
    if code == ENGLISH:
        return {}
    path = resource_path(os.path.join(LANG_FOLDER, f"{code}.json"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("the file must contain one JSON object")
        # Keep only real translations: text -> non-empty text
        return {key: value for key, value in data.items()
                if isinstance(key, str) and isinstance(value, str) and value}
    except Exception as e:
        logging.warning(f"i18n: could not load translations from '{path}': {e}. Using English.")
        return {}


def set_language(code):
    """Switch tr() to `code`. Windows that are already open keep their texts."""
    global _current_language, _translations
    if code not in LANGUAGES:
        code = ENGLISH
    _translations = load_translations(code)
    _current_language = code
    logging.info(f"Language: {code} ({len(_translations)} translated texts)")


def init_language(setting=None):
    """Choose the language at startup. Call it before any window is built.

    `setting` is a language code or "auto"; when omitted it is read from
    settings.json. Returns the language code now in use.
    """
    if setting is None:
        setting = read_saved_setting()
    set_language(resolve_language(setting))
    return _current_language


# Fonts that draw Chinese text well, tried in this order.
CHINESE_FONTS = ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                 "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei"]

# Fonts that draw Japanese text well, tried in this order. Japanese kanji look
# different from Chinese ones, so Japanese must not borrow the Chinese fonts.
JAPANESE_FONTS = ["Yu Gothic UI", "Meiryo UI", "Meiryo", "Hiragino Sans",
                  "Noto Sans CJK JP", "Source Han Sans JP", "IPAexGothic"]

# Language code -> fonts used for its characters
_CJK_FONTS = {"zh_CN": CHINESE_FONTS, "ja": JAPANESE_FONTS}


def apply_font_fallbacks():
    """Chinese and Japanese only: take their characters from one good font.

    Without this, a Windows in another language picks them from several fonts
    and the text looks uneven (Japanese may even get Chinese-style kanji).
    Call it once, after QApplication is created.
    """
    fonts = _CJK_FONTS.get(_current_language)
    if not fonts:
        return
    try:
        from PySide6.QtGui import QFont
        for family in ("Segoe UI", "Arial"):  # The fonts used by the SaveState themes
            QFont.insertSubstitutions(family, fonts)
    except Exception as e:
        logging.debug(f"i18n: could not set the {_current_language} fonts: {e}")


def install_qt_translator(app):
    """Translate Qt's own texts (Yes / No / Cancel buttons, right-click menus).

    Call it once, after QApplication is created.
    """
    global _qt_translator
    if _current_language == ENGLISH or _qt_translator is not None:
        return
    try:
        from PySide6.QtCore import QTranslator

        class _JsonTranslator(QTranslator):
            """Answers Qt's lookups from the same JSON file used by tr()."""

            def isEmpty(self):
                return False

            def translate(self, context, source_text, disambiguation=None, n=-1):
                # None tells Qt to keep its own English text.
                return _translations.get(source_text)

        _qt_translator = _JsonTranslator(app)
        app.installTranslator(_qt_translator)
    except Exception as e:
        logging.warning(f"i18n: could not install the Qt translator: {e}")
