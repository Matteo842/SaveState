# gui_components/theme_manager.py
# -*- coding: utf-8 -*-
import os
import logging
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize
# Assicurati che resource_path sia effettivamente in gui_utils e funzioni correttamente
try:
    from gui_utils import resource_path
except ImportError:
    logging.error("ThemeManager: Failed to import resource_path from gui_utils. Fallback might be needed.")
    # Fallback semplice (potrebbe non funzionare correttamente con PyInstaller senza --add-data)
    def resource_path(relative_path):
        return os.path.join(os.path.abspath("."), relative_path)

import config # Per accedere a LIGHT_THEME_QSS e DARK_THEME_QSS
import settings_manager # Per salvare le impostazioni del tema

class ThemeManager:
    """Gestisce il tema chiaro/scuro e il pulsante di toggle."""

    def __init__(self, theme_button: QPushButton, main_window):
        """
        Inizializza il gestore del tema.

        Args:
            theme_button: L'istanza del QPushButton da gestire.
            main_window: Riferimento all'istanza di MainWindow.
        """
        self.theme_button = theme_button
        self.main_window = main_window # Per accedere a self.tr, self.current_settings
        self.sun_icon = None
        self.moon_icon = None

        self.load_theme_icons() # Carica icone all'inizializzazione

        # Configura il pulsante del tema (proprietà base)
        self.theme_button.setFlat(True)
        self.theme_button.setFixedSize(QSize(24, 24)) # Adatta dimensione se serve
        self.theme_button.setObjectName("ThemeToggleButton")
        # Connetti il segnale click del pulsante al metodo INTERNO di questo manager
        self.theme_button.clicked.connect(self.handle_theme_toggle)

        # Applica tema e icona iniziale LETTI dalle impostazioni correnti
        self.update_theme()

    def load_theme_icons(self):
        """Carica le icone sole/luna dai file."""
        logging.debug("ThemeManager: Loading theme icons...")
        try:
            sun_icon_path = resource_path("icons/sun.png")
            moon_icon_path = resource_path("icons/moon.png")
            self.sun_icon = QIcon(sun_icon_path) if os.path.exists(sun_icon_path) else None
            self.moon_icon = QIcon(moon_icon_path) if os.path.exists(moon_icon_path) else None
            if not self.sun_icon: logging.warning(f"ThemeManager: Sun icon not found or failed to load from: {sun_icon_path}")
            if not self.moon_icon: logging.warning(f"ThemeManager: Moon icon not found or failed to load from: {moon_icon_path}")
            logging.debug(f"ThemeManager: Sun icon loaded: {self.sun_icon is not None}, Moon icon loaded: {self.moon_icon is not None}")
        except Exception as e:
             # Logga l'errore ma cerca di non bloccare l'app solo per le icone
             logging.error(f"ThemeManager: Error loading theme icons: {e}", exc_info=True)


    def update_theme(self):
        """Applica il tema corrente (letto da main_window.current_settings)
           e aggiorna l'icona/tooltip del pulsante del tema."""
        try:
            theme_name = self.main_window.current_settings.get('theme', 'dark') # Leggi impostazione da MainWindow
            logging.debug(f"ThemeManager: Applying theme '{theme_name}'")
            qss_to_apply = config.LIGHT_THEME_QSS if theme_name == 'light' else config.DARK_THEME_QSS

            # Applica lo stile all'intera applicazione
            app_instance = QApplication.instance()
            if app_instance:
                app_instance.setStyleSheet(qss_to_apply)
                logging.info(f"ThemeManager: Theme '{theme_name}' applied via QSS.")
            else:
                # Questo non dovrebbe succedere se l'app è in esecuzione, ma per sicurezza
                logging.error("ThemeManager: Cannot apply theme - QApplication.instance() is None.")
                return

            # Aggiorna icona e tooltip del pulsante del tema
            icon_size = QSize(16, 16) # Mantieni coerenza con altre icone (o usa QSize(24, 24) se preferisci più grande)
            if theme_name == 'light':
                tooltip_text = self.main_window.tr("Passa al tema scuro")
                if self.moon_icon:
                    self.theme_button.setIcon(self.moon_icon)
                    self.theme_button.setIconSize(icon_size)
                    self.theme_button.setText("") # Assicura che non ci sia testo se l'icona c'è
                else:
                    # Fallback a testo se icona luna manca
                    self.theme_button.setText("D") # D per Dark
                    self.theme_button.setIcon(QIcon()) # Rimuovi icona precedente (sole)
                self.theme_button.setToolTip(tooltip_text)
            else: # 'dark' or default theme
                tooltip_text = self.main_window.tr("Passa al tema chiaro")
                if self.sun_icon:
                    self.theme_button.setIcon(self.sun_icon)
                    self.theme_button.setIconSize(icon_size)
                    self.theme_button.setText("") # Assicura che non ci sia testo se l'icona c'è
                else:
                    # Fallback a testo se icona sole manca
                    self.theme_button.setText("L") # L per Light
                    self.theme_button.setIcon(QIcon()) # Rimuovi icona precedente (luna)
                self.theme_button.setToolTip(tooltip_text)
            logging.debug(f"ThemeManager: Button icon/tooltip updated for '{theme_name}' theme.")

        except Exception as e:
            logging.error(f"ThemeManager: Error applying theme '{theme_name}': {e}", exc_info=True)
            # Mostra un errore all'utente? O solo log? Decidi tu.
            # QMessageBox.warning(self.main_window, "Errore Tema", f"Impossibile applicare il tema:\n{e}")


    def handle_theme_toggle(self):
        """Inverte il tema nelle impostazioni, lo salva e lo applica."""
        current_theme = self.main_window.current_settings.get('theme', 'dark')
        new_theme = 'light' if current_theme == 'dark' else 'dark'
        logging.debug(f"ThemeManager: Theme toggle requested from '{current_theme}' to '{new_theme}'.")

        # 1. Aggiorna il dizionario delle impostazioni NELLA FINESTRA PRINCIPALE
        #    Questo è importante perché altre parti del codice potrebbero leggerlo.
        self.main_window.current_settings['theme'] = new_theme

        # 2. Salva le impostazioni aggiornate su file
        if not settings_manager.save_settings(self.main_window.current_settings):
            # Errore nel salvataggio
            logging.error(f"ThemeManager: Failed to save theme setting '{new_theme}' to file.")
            QMessageBox.warning(self.main_window, # Usa main_window come parent per il dialogo
                                self.main_window.tr("Errore"),
                                self.main_window.tr("Impossibile salvare l'impostazione del tema."))
            # Ripristina il valore precedente nel dizionario della main_window per coerenza
            self.main_window.current_settings['theme'] = current_theme
            # NON chiamare update_theme() qui perché il tema non è cambiato effettivamente
        else:
            # 3. Salvataggio riuscito, applica il nuovo tema chiamando update_theme()
            #    che leggerà il nuovo valore da main_window.current_settings
            logging.info(f"ThemeManager: Theme setting saved successfully. Applying '{new_theme}' theme now.")
            self.update_theme()