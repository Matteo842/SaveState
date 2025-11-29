"""
Dialogo per la gestione multipla dei profili durante il drag and drop di più file.
Permette di visualizzare, selezionare ed eliminare i profili prima di aggiungerli.
"""

import os
import logging
import re
import platform
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
                              QPushButton, QListWidget, QListWidgetItem,
                              QWidget, QMessageBox, QProgressBar, QCheckBox, QLineEdit, QStyle)
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QSize, QEvent
from PySide6.QtGui import QIcon, QFont, QCursor, QPainter, QPen, QColor

from utils import resource_path

# Helper function to sanitize display names
def _sanitize_display_name(name):
    """Removes .exe (case-insensitive) from the end of a string and strips whitespace."""
    if name:
        # Remove .exe (case-insensitive) from the end
        name = re.sub(r'\.exe$', '', name, flags=re.IGNORECASE)
        # Strip leading/trailing whitespace
        name = name.strip()
    return name


# Custom progress bar with smooth segments equal to number of profiles
class SegmentedProgressBar(QProgressBar):
    """Progress bar with segment boundaries equal to number of profiles and smooth fill."""
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        radius = 4
        # Draw background
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#2D2D2D'))
        painter.drawRoundedRect(rect, radius, radius)
        # Draw segment dividers
        segments = self.maximum() - self.minimum()
        if segments > 1:
            pen = QPen(QColor('#2D2D2D'))
            pen.setWidth(1)
            painter.setPen(pen)
            w = rect.width()
            h = rect.height()
            for i in range(1, segments):
                x = int(w * i / segments)
                painter.drawLine(x, 0, x, h)
        # Draw fill
        value = self.value()
        if self.maximum() > self.minimum():
            ratio = (value - self.minimum()) / (self.maximum() - self.minimum())
        else:
            ratio = 0
        fill_width = int(rect.width() * ratio)
        if fill_width > 0:
            fill_rect = QRect(rect.x(), rect.y(), fill_width, rect.height())
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#FF0000'))
            painter.drawRoundedRect(fill_rect, radius, radius)
        # Draw text
        painter.setPen(QColor('#FFFFFF'))
        painter.drawText(rect, Qt.AlignCenter, self.text())
        painter.end()

class ProfileListItem(QWidget):
    """Widget personalizzato per rappresentare un elemento nella lista dei profili."""
    
    deleteClicked = Signal(str)  # Segnale emesso quando si clicca sul pulsante di eliminazione
    
    def __init__(self, profile_name, file_path, parent=None):
        super().__init__(parent)
        
        self.profile_name = profile_name  # Original name for logic/keys
        self.file_path = file_path
        display_name = _sanitize_display_name(profile_name) # Sanitize for display
        self.save_path = ""  # Sarà impostato dopo la ricerca
        self.score = 0  # Sarà impostato dopo la ricerca
        self.analyzed = False  # Flag per indicare se il profilo è stato analizzato
        self.show_score = False  # Flag to control score display
        
        # Layout principale orizzontale
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        # Impostiamo l'allineamento verticale al centro per tutto il contenuto
        layout.setAlignment(Qt.AlignVCenter)
        
        # Layout per le informazioni del profilo (nome e percorso)
        info_layout = QVBoxLayout()
        # Impostiamo margini ridotti per il layout verticale e allineamento al centro
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        info_layout.setSpacing(2)  # Riduciamo lo spazio tra gli elementi
        
        # Nome del profilo (in grassetto e più grande)
        self.name_label = QLabel(display_name)
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)  # Increased from default (usually 9)
        self.name_label.setFont(font)
        # Disabilitiamo il word wrap per evitare che i nomi vadano a capo
        self.name_label.setWordWrap(False)
        # Impostiamo l'ellissi se il testo è troppo lungo
        self.name_label.setTextFormat(Qt.PlainText)
        # Disable context menu and selection
        self.name_label.setContextMenuPolicy(Qt.NoContextMenu)
        # Allineamento verticale al centro, orizzontale a sinistra
        self.name_label.setAlignment(Qt.AlignLeft)
        # Impostiamo il tooltip per mostrare il nome completo al passaggio del mouse
        self.name_label.setToolTip(display_name)
        
        # Define a font for paths (slightly larger)
        path_font = QFont()
        path_font.setPointSize(9)  # Increased from 8
        
        # Keep the file path in memory but don't display it
        self.file_path = file_path
        
        # Save path (initially hidden)
        self.save_path_label = QLabel("")
        self.save_path_label.setFont(path_font)
        self.save_path_label.setStyleSheet("color: #4CAF50;")
        # Enable wrapping for save path
        self.save_path_label.setWordWrap(True)
        # Disable context menu and selection
        self.save_path_label.setContextMenuPolicy(Qt.NoContextMenu)
        # Allineamento a sinistra come per il nome
        self.save_path_label.setAlignment(Qt.AlignLeft)
        # Restrict save path height to one line to avoid item over-expansion
        self.save_path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        line_height = self.save_path_label.fontMetrics().height()
        self.save_path_label.setMaximumHeight(line_height * 2)
        self.save_path_label.hide()
        
        # Add labels to the info layout
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.save_path_label)
        
        # Add the info layout to the main layout
        layout.addLayout(info_layout, 1)  # Stretch factor 1 to give more space
        
        # Delete button with Unicode trash can icon, larger and easier to click
        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("MinecraftButton")  # Use same style as Minecraft button
        self.delete_button.setToolTip("Remove this profile")
        self.delete_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        # Increase button size while keeping a small border within the item row
        self.delete_button.setFixedSize(46, 46)
        self.delete_button.setIconSize(QSize(36, 36))
        self.delete_button.setStyleSheet("""
            QPushButton#MinecraftButton {
                border: none;
                padding: 0;
                background-color: transparent;
                font-size: 22px;  /* Larger glyph for better visibility */
                color: #888;
                border-radius: 0px;  /* Ensure square shape */
            }
            QPushButton#MinecraftButton:hover {
                background-color: rgba(255, 0, 0, 0.1);
                border-radius: 0px;  /* Ensure square shape */
                color: #f00;
            }
            QPushButton#MinecraftButton:pressed {
                background-color: rgba(255, 0, 0, 0.2);
                border-radius: 0px;  /* Ensure square shape */
            }
        """)
        
        # Connetti il segnale clicked al nostro segnale personalizzato
        self.delete_button.clicked.connect(lambda: self.deleteClicked.emit(self.profile_name))
        
        # Aggiungi il pulsante di eliminazione al layout principale
        layout.addWidget(self.delete_button)
        
        # Ensure delete button is fixed size and centered vertically
        self.delete_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.setAlignment(self.delete_button, Qt.AlignVCenter)
        # Ensure widget height accommodates delete button
        btn_height = self.delete_button.sizeHint().height()
        margins = layout.contentsMargins()
        self.setMinimumHeight(btn_height + margins.top() + margins.bottom())
        
        # Set layout
        self.setLayout(layout)
        
        # Imposta un'altezza fissa che accomodi sia il nome che il percorso di salvataggio
        # Calcoliamo l'altezza in base all'altezza del font e aggiungiamo spazio extra
        font_height = self.name_label.fontMetrics().height()
        save_path_height = self.save_path_label.fontMetrics().height() * 2  # Spazio per due righe
        
        # Aumentiamo l'altezza base, ma garantiamo che contenga anche il pulsante (con un minimo di bordo)
        base_height = font_height + save_path_height + 30  # Margini più ampi
        min_for_button = btn_height + margins.top() + margins.bottom() + 6  # piccolo bordo
        row_height = max(base_height, min_for_button)
        self.setFixedHeight(row_height)
    
    def update_save_path(self, save_path, score):
        """Aggiorna il percorso di salvataggio e lo score dopo l'analisi."""
        self.save_path = save_path
        self.score = score
        self.analyzed = True
        
        # Update label text based on show_score flag
        self.update_label()
        self.save_path_label.show()
    
    def update_label(self):
        """Update save_path_label text based on show_score flag."""
        text = f"Save path: {self.save_path}" + (f" (Score: {self.score})" if self.show_score else "")
        self.save_path_label.setText(text)
        self.save_path_label.setToolTip(self.save_path)
        
        # Set text color based on score
        if self.score < 0:
            self.save_path_label.setStyleSheet("color: #FF5555;")  # Rosso per score negativo
        else:
            self.save_path_label.setStyleSheet("color: #4CAF50;")  # Verde per score positivo o zero
    
    def set_show_score(self, show):
        """Enable or disable score display and refresh label if analyzed."""
        self.show_score = show
        if self.analyzed:
            self.update_label()

class MultiProfileDialog(QDialog):
    """
    Dialogo che mostra una lista di profili rilevati durante il drag and drop multiplo,
    permettendo all'utente di selezionare quali profili aggiungere e quali eliminare.
    """
    
    # Segnale emesso quando viene aggiunto un nuovo profilo
    profileAdded = Signal(dict)
    analysis_completed = Signal()
    
    def __init__(self, files_to_process, parent=None):
        """
        Inizializza il dialogo.
        
        Args:
            files_to_process: Lista di file da processare
            parent: Widget genitore
        """
        super().__init__(parent)

        # --- Adopt app's custom window style (frameless with custom title bar) ---
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self._drag_pos = None
        self._is_linux = platform.system() == "Linux"  # Check if running on Linux
        # Keep dialog non-modal to match app interaction model
        self.setWindowModality(Qt.NonModal)
        
        self.files_to_process = files_to_process
        self.total_files = len(files_to_process)
        self.processed_files = 0
        self.profiles_data = {}  # Dictionary to store profile data (name -> data)
        self.accepted_profiles = {}  # Dictionary to store accepted profiles
        self.analysis_running = False  # Flag to indicate if analysis is in progress
        
        self.setWindowTitle("Manage Profiles")
        self.setMinimumWidth(750)
        self.setMinimumHeight(800)
        try:
            self.setWindowIcon(QIcon(resource_path("icon.png")))
        except Exception:
            pass
        
        # Main layout (title bar + content container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Custom Title Bar ---
        self.title_bar = QWidget()
        self.title_bar.setObjectName("CustomTitleBar")
        self.title_bar.setMinimumHeight(36)
        tb_layout = QHBoxLayout()
        tb_layout.setContentsMargins(12, 4, 12, 4)
        tb_layout.setSpacing(6)
        # Window title
        self.title_label = QLabel("Manage Profiles")
        self.title_label.setObjectName("TitleLabel")
        tb_layout.addWidget(self.title_label)
        tb_layout.addStretch(1)
        # Close button only (dialogs usually don't need minimize/maximize)
        style = self.style() if hasattr(self, 'style') else None
        self.close_button = QPushButton()
        self.close_button.setObjectName("CloseButton")
        try:
            self.close_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        except Exception:
            pass
        self.close_button.setFixedSize(QSize(28, 28))
        self.close_button.setFlat(True)
        self.close_button.setIconSize(QSize(14, 14))
        self.close_button.clicked.connect(self.reject)
        tb_layout.addWidget(self.close_button)
        self.title_bar.setLayout(tb_layout)
        # Make the title bar draggable
        self.title_bar.installEventFilter(self)

        # Title bar styling (mirror main window look)
        self.title_bar.setStyleSheet(
            """
            QWidget#CustomTitleBar { background-color: #0d0d0d; border-bottom: 1px solid #333333; }
            QLabel#TitleLabel { color: #f2f2f2; font-size: 14pt; font-weight: 700; }
            QPushButton#CloseButton {
                border: none; background: transparent; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 0px; border-radius: 4px;
            }
            QPushButton#CloseButton:hover { background-color: #b00020; }
            """
        )
        main_layout.addWidget(self.title_bar)

        # Content container with margins like main window
        content_container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        content_container.setLayout(layout)
        
        # Intestazione
        self.header_label = QLabel(f"<b>{self.total_files} file rilevati</b>")
        self.header_label.setObjectName("header_label")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.header_label)
        
        # Description
        self.description_label = QLabel("Select the Games you want to analyze to create profiles. "
                                  "You can remove Games you don't want before starting the analysis.")
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.description_label)
        
        # Search bar (hidden by default)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search profiles...")
        self.search_bar.hide()
        self.search_bar.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_bar)
        
        # Checkbox to toggle score display
        self.show_scores_checkbox = QCheckBox("Show scores")
        self.show_scores_checkbox.setToolTip("Show scores next to save paths")
        layout.addWidget(self.show_scores_checkbox)
        self.show_scores_checkbox.toggled.connect(self.toggle_scores_display)
        
        # Progress bar (initially hidden)
        self.progress_bar = SegmentedProgressBar()
        self.progress_bar.setRange(0, self.total_files if self.total_files > 0 else 1)  # Set range based on actual total files
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v/%m file processed (%p%)")
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # Material design style for progress bar: solid fill, no segments
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 4px;
                background-color: #2D2D2D;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #FF0000;
                border-radius: 4px;
                margin: 0px;
            }
        """)
        
        # Current status label (initially hidden)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.hide()
        layout.addWidget(self.status_label)
        
        # Lista dei profili
        self.profile_list = QListWidget()
        # Remove alternating row colors that cause readability issues
        self.profile_list.setAlternatingRowColors(False)
        # Disable item selection - we'll handle clicks through custom widgets
        self.profile_list.setSelectionMode(QListWidget.NoSelection)
        # Use uniform item sizes to ensure all profile items have the same height
        self.profile_list.setUniformItemSizes(True)
        # Set a consistent style with the dark theme
        self.profile_list.setStyleSheet("""
            QListWidget {
                background-color: #2D2D2D;
                color: #F0F0F0;
                border: 1px solid #555555;
            }
            QListWidget::item {
                background-color: #2D2D2D;
                color: #F0F0F0;
                border-bottom: 1px solid #3F3F46;
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #505050;
                color: #FFFFFF;
            }
            QListWidget::item:hover {
                background-color: #3F3F46;
            }
        """)
        layout.addWidget(self.profile_list)
        
        # Popola la lista con i file da processare
        self.populate_profile_list()
        
        # Buttons
        buttons_layout = QHBoxLayout()
        
        # Button to start analysis
        self.start_analysis_button = QPushButton("Start Analysis")
        self.start_analysis_button.clicked.connect(self.start_analysis)
        
        # Button to add profiles
        self.add_button = QPushButton("Add Profiles")
        self.add_button.setEnabled(False)  # Disabled until analysis is complete
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.accept)
        
        # Button to cancel
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.start_analysis_button)
        buttons_layout.addWidget(self.add_button)
        
        layout.addLayout(buttons_layout)

        # Add content to main layout (beneath title bar)
        main_layout.addWidget(content_container, stretch=1)
        self.setLayout(main_layout)

    def _update_add_button_label(self):
        """Update 'Add Profiles' button to include the number of profiles ready to add."""
        try:
            # Only meaningful when analysis is finished
            if getattr(self, 'analysis_running', False):
                return
            if not hasattr(self, 'add_button') or self.add_button is None:
                return
            count = len(self.accepted_profiles) if hasattr(self, 'accepted_profiles') else 0
            text = f"Add {count} profile" if count == 1 else f"Add {count} profiles"
            self.add_button.setText(text)
        except Exception:
            pass
    def eventFilter(self, watched, event):
        """Enable window dragging from the custom title bar and ignore double-click maximize."""
        try:
            if hasattr(self, 'title_bar') and watched is self.title_bar:
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                    # On Linux, try to use native window dragging via startSystemMove()
                    if self._is_linux and hasattr(self, 'windowHandle') and self.windowHandle():
                        try:
                            # Get global position from event
                            if hasattr(event, 'globalPosition'):
                                global_pos = event.globalPosition().toPoint()
                            else:
                                global_pos = event.globalPos()
                            # Use Qt's native window move for better Linux compatibility
                            self.windowHandle().startSystemMove()
                            return True
                        except Exception as e:
                            logging.debug(f"startSystemMove failed on Linux, falling back to manual drag: {e}")
                    
                    # Fallback to manual dragging (for Windows or if startSystemMove fails)
                    pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                    self._drag_pos = pos - self.frameGeometry().topLeft()
                    return True
                    
                if event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                    if self._drag_pos is not None:
                        pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
                        new_pos = pos - self._drag_pos
                        self.move(new_pos)
                        return True
                        
                if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                    # Reset drag position on release
                    self._drag_pos = None
                    return True
                    
                if event.type() == QEvent.Type.MouseButtonDblClick:
                    # Do nothing on double click (no maximize toggle)
                    return True
        except Exception as e:
            logging.debug(f"eventFilter exception: {e}")
        return super().eventFilter(watched, event)
    
    def populate_profile_list(self):
        """Populate the list with files to process."""
        for file_path in self.files_to_process:
            # Extract profile name from file name
            file_name = os.path.basename(file_path)
            profile_name = os.path.splitext(file_name)[0]
            # Remove .exe extension if present (for .exe.lnk files)
            if profile_name.lower().endswith('.exe'):
                profile_name = profile_name[:-4]
            
            # Create custom item
            item_widget = ProfileListItem(profile_name, file_path)
            item_widget.deleteClicked.connect(self.remove_profile)
            
            # Create list item
            list_item = QListWidgetItem()
            # Impostiamo la sizeHint dell'elemento in base all'altezza fissa del widget
            size = QSize(item_widget.width(), item_widget.height())
            list_item.setSizeHint(size)
            
            # Add item to list
            self.profile_list.addItem(list_item)
            self.profile_list.setItemWidget(list_item, item_widget)
            
            # Aggiungi il profilo al dizionario dei profili
            self.profiles_data[profile_name] = {
                'file_path': file_path,
                'analyzed': False
            }
    
    def start_analysis(self):
        """Start the analysis of selected profiles."""
        # Check if there are profiles to analyze
        if self.profile_list.count() == 0:
            QMessageBox.warning(self, "No profiles", "No profiles to analyze.")
            return
        
        # Set analysis running flag
        self.analysis_running = True
        
        # Update interface for analysis phase
        self.header_label.setText("<b>Analysis in progress...</b>")
        self.description_label.setText("I'm analyzing the files to find the save paths. "
                                      "Results will be shown as they are found.")
        
        # Show progress bar and status label
        self.progress_bar.setRange(0, self.profile_list.count())
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("Initialization...")
        self.status_label.show()
        
        # Disable the start analysis button
        self.start_analysis_button.setEnabled(False)
        
        # Emetti un segnale per avviare l'analisi
        self.profileAdded.emit({'action': 'start_analysis'})
    
    def update_profile(self, profile_name, save_path, score):
        """Aggiorna un profilo con il percorso di salvataggio trovato."""
        # Aggiorna il dizionario dei profili
        if profile_name in self.profiles_data:
            self.profiles_data[profile_name]['save_path'] = save_path
            self.profiles_data[profile_name]['score'] = score
            self.profiles_data[profile_name]['analyzed'] = True
            
            # Aggiorna l'elemento nella lista
            for i in range(self.profile_list.count()):
                item = self.profile_list.item(i)
                widget = self.profile_list.itemWidget(item)
                if widget.profile_name == profile_name:
                    widget.update_save_path(save_path, score)
                    # Non ridimensioniamo più l'elemento perché ora ha un'altezza fissa
                    break
            
            # Aggiungi il profilo alla lista dei profili accettati
            self.accepted_profiles[profile_name] = {'path': save_path}
            
            # Emetti il segnale
            self.profileAdded.emit({
                'name': profile_name,
                'path': save_path,
                'score': score
            })

        # Refresh button label if analysis already finished
        self._update_add_button_label()
    
    def update_progress(self, current_file, status_text):
        """Update the progress bar and status label."""
        self.processed_files = current_file
        self.progress_bar.setValue(current_file)
        self.status_label.setText(status_text)
        
        # If all files are processed, enable the add button
        if current_file >= self.profile_list.count():
            self.analysis_running = False
            self.add_button.setEnabled(True)
            self.header_label.setText(f"<b>Analysis completed</b>")
            self.description_label.setText("The following profiles will be created with the found save paths. "
                                          "You can still remove profiles you don't want to add.")
            self.status_label.setText("Analysis completed.")
            self._update_add_button_label()
    
    def remove_profile(self, profile_name):
        """Rimuove un profilo dalla lista."""
        # Trova l'elemento nella lista
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            widget = self.profile_list.itemWidget(item)
            
            if widget.profile_name == profile_name:
                # Rimuovi l'elemento dalla lista
                self.profile_list.takeItem(i)
                
                # Rimuovi il profilo dalla lista dei profili accettati
                if profile_name in self.accepted_profiles:
                    del self.accepted_profiles[profile_name]
                
                # Aggiorna l'intestazione
                self.update_header()
                # Update button label after removal if analysis completed
                self._update_add_button_label()
                
                # Esci dal ciclo
                break
    
    def update_header(self):
        """Update the header with the number of profiles."""
        count = self.profile_list.count()
        self.header_label.setText(f"<b>{count} profiles found</b>")
    
    def get_accepted_profiles(self):
        """Return the accepted profiles."""
        # Update accepted profiles with found save paths
        accepted = {}
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            widget = self.profile_list.itemWidget(item)
            if widget.analyzed and widget.save_path:
                accepted[widget.profile_name] = {'path': widget.save_path}
        return accepted
        
    def get_files_to_analyze(self):
        """Return the list of files to analyze."""
        files = []
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            widget = self.profile_list.itemWidget(item)
            files.append((widget.profile_name, widget.file_path))
        return files
    
    def _on_search_text_changed(self, text):
        """Handles search bar text changes for filtering and visibility."""
        # First, apply the filter based on the new text
        self.filter_profiles(text)

        # Then, handle the visibility of the search bar
        if not text.strip():  # If text is empty or only whitespace
            if self.search_bar.isVisible():
                self.search_bar.hide()
        else:
            # If there is text, ensure the search bar is visible.
            if not self.search_bar.isVisible():
                self.search_bar.show()
    
    def event(self, event_obj): # event_obj to avoid conflict with 'event' module
        """Handles events for the dialog, specifically KeyPress to activate search bar."""
        if event_obj.type() == QEvent.KeyPress:
            # Only act if the search bar is currently hidden.
            # If it's visible, key presses should go to it (if it has focus) or other widgets.
            if not self.search_bar.isVisible():
                key_text = event_obj.text()
                # Check if the key produces a printable character and is not just whitespace.
                if key_text.isprintable() and key_text.strip() != '':
                    # Show the search bar, set focus to it, and input the typed character.
                    self.search_bar.show()
                    self.search_bar.setFocus()
                    self.search_bar.setText(key_text) # This also triggers _on_search_text_changed
                    return True # Event handled, stop further processing
        
        # For all other events or if the key press wasn't handled above, 
        # call the base class's event handler.
        return super().event(event_obj)
    
    def filter_profiles(self, text):
        """Filter profiles based on search text."""
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            widget = self.profile_list.itemWidget(item)
            # Always show items when search is empty
            if not text:
                item.setHidden(False)
            else:
                # Case-insensitive search
                search_text = text.lower()
                profile_name = widget.profile_name.lower()
                item.setHidden(search_text not in profile_name)
                
    def toggle_scores_display(self, show):
        """Show or hide score in all profile list items."""
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            widget = self.profile_list.itemWidget(item)
            widget.set_show_score(show)
            widget = self.profile_list.itemWidget(item)
            widget.set_show_score(show)
            # Manteniamo l'altezza fissa impostata nel widget
            # Impostiamo solo la larghezza dal sizeHint, mantenendo l'altezza fissa
            current_height = widget.height()
            size = QSize(widget.sizeHint().width(), current_height)
            item.setSizeHint(size)

    def reject(self):
        """Gestisce la chiusura della dialog e cancella tutti i thread di ricerca."""
        logging.info("MultiProfileDialog.reject() called: User clicked Cancel or closed dialog")
        
        # Emetti il segnale rejected per notificare la cancellazione
        # Questo dovrebbe attivare _cancel_detection_threads in drop_event_logic.py
        logging.info("MultiProfileDialog.reject(): About to call super().reject() which should emit rejected signal")
        super().reject()
        logging.info("MultiProfileDialog.reject(): super().reject() completed")

    def closeEvent(self, event):
        """Gestisce la chiusura della dialog con la X in alto a destra."""
        logging.info("MultiProfileDialog.closeEvent() called: User closed dialog with X button")
        
        # Emetti manualmente il segnale finished per notificare la cancellazione
        logging.info("MultiProfileDialog.closeEvent(): Emitting finished signal manually")
        self.finished.emit(0)  # Emetti il segnale finished con codice 0 (rejected)
        
        # Chiama il closeEvent della classe base
        logging.info("MultiProfileDialog.closeEvent(): About to call super().closeEvent()")
        super().closeEvent(event)
        logging.info("MultiProfileDialog.closeEvent(): super().closeEvent() completed")
