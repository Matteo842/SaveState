# gui_components/theme_manager.py
# -*- coding: utf-8 -*-
import os
import logging
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize

try:
    from gui_utils import resource_path
except ImportError:
    logging.error("ThemeManager: Failed to import resource_path from gui_utils. Fallback might be needed.")

    def resource_path(relative_path):
        return os.path.join(os.path.abspath("."), relative_path)

import config # To access LIGHT_THEME_QSS and DARK_THEME_QSS
import settings_manager # To save theme settings

class ThemeManager:
    # Manages the light/dark theme and the toggle button.
    """Manages the light/dark theme and the toggle button."""

    # Initializes the theme manager.
    def __init__(self, theme_button: QPushButton, main_window):
        """
        Initializes the theme manager.
        """
        self.theme_button = theme_button
        self.main_window = main_window # For accessing self.current_settings
        self.sun_icon = None
        self.moon_icon = None

        self.load_theme_icons() # Load icons at initialization

        # Configure the theme button (base properties)
        self.theme_button.setFlat(True)
        self.theme_button.setFixedSize(QSize(24, 24)) # Adjust size if needed
        self.theme_button.setObjectName("ThemeToggleButton")
        # Connect the button click signal to the internal method of this manager
        self.theme_button.clicked.connect(self.handle_theme_toggle)

        # Apply theme and initial icon read from current settings
        self.update_theme()

    # Loads the sun/moon icons from files.
    def load_theme_icons(self):
        """Load the sun/moon icons from files."""
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
             # Log the error but don't block the app only for icons
             logging.error(f"ThemeManager: Error loading theme icons: {e}", exc_info=True)

    # Applies the current theme (read from main_window.current_settings) and updates the button icon/tooltip.
    def update_theme(self):
        """Applies the current theme (read from main_window.current_settings)
           and updates the theme button icon/tooltip."""
        try:
            theme_name = self.main_window.current_settings.get('theme', 'dark') # Read setting from MainWindow
            logging.debug(f"ThemeManager: Applying theme '{theme_name}'")
            qss_to_apply = config.LIGHT_THEME_QSS if theme_name == 'light' else config.DARK_THEME_QSS

            # Apply the style to the entire application
            app_instance = QApplication.instance()
            if app_instance:
                app_instance.setStyleSheet(qss_to_apply)
                logging.info(f"ThemeManager: Theme '{theme_name}' applied via QSS.")
            else:
                # This shouldn't happen if the app is running, but for safety
                logging.error("ThemeManager: Cannot apply theme - QApplication.instance() is None.")
                return

            # Update the theme button icon and tooltip
            icon_size = QSize(16, 16) # Keep consistency with other icons
            if theme_name == 'light':
                tooltip_text = "Switch to dark theme"
                if self.moon_icon:
                    self.theme_button.setIcon(self.moon_icon)
                    self.theme_button.setIconSize(icon_size)
                    self.theme_button.setText("") # Ensure there's no text if the icon is present
                else:
                    # Fallback to text if moon icon is missing
                    self.theme_button.setText("D") # D for Dark
                    self.theme_button.setIcon(QIcon()) # Remove previous icon (sun)
                self.theme_button.setToolTip(tooltip_text)
                self.theme_button.update()
            else: # 'dark' or default theme
                tooltip_text = "Switch to light theme"
                if self.sun_icon:
                    self.theme_button.setIcon(self.sun_icon)
                    self.theme_button.setIconSize(icon_size)
                    self.theme_button.setText("") # Ensure there's no text if the icon is present
                else:
                    # Fallback to text if sun icon is missing
                    self.theme_button.setText("L") # L for Light
                    self.theme_button.setIcon(QIcon()) # Remove previous icon (moon)
                self.theme_button.setToolTip(tooltip_text)
                self.theme_button.update()
            logging.debug(f"ThemeManager: Button icon/tooltip updated for '{theme_name}' theme.")

        except Exception as e:
            logging.error(f"ThemeManager: Error applying theme '{theme_name}': {e}", exc_info=True)

    # Inverts the theme in settings, saves it, and applies the new theme.
    def handle_theme_toggle(self):
        """Inverts the theme in settings, saves it, and applies the new theme."""
        current_theme = self.main_window.current_settings.get('theme', 'dark')
        new_theme = 'light' if current_theme == 'dark' else 'dark'
        logging.debug(f"ThemeManager: Theme toggle requested from '{current_theme}' to '{new_theme}'.")

        # 1. Update the settings dictionary in the main window
        #    This is important because other parts of the code might read it.
        self.main_window.current_settings['theme'] = new_theme

        # 2. Save the updated settings to file
        if not settings_manager.save_settings(self.main_window.current_settings):
            # Error in saving
            logging.error(f"ThemeManager: Failed to save theme setting '{new_theme}' to file.")
            QMessageBox.warning(self.main_window, # Use main_window as parent for the dialog
                                "Error",
                                "Unable to save theme setting.")
            # Restore the previous value in the main_window settings for consistency
            self.main_window.current_settings['theme'] = current_theme
            # Don't call update_theme() here because the theme hasn't actually changed
        else:
            # 3. Saving successful, apply the new theme by calling update_theme()
            #    which will read the new value from main_window.current_settings
            logging.info(f"ThemeManager: Theme setting saved successfully. Applying '{new_theme}' theme now.")
            self.update_theme()