"""
Dialogo per la gestione multipla dei profili durante il drag and drop di più file.
Permette di visualizzare, selezionare ed eliminare i profili prima di aggiungerli.
"""

import os
import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
                              QPushButton, QListWidget, QListWidgetItem, 
                              QWidget, QMessageBox, QProgressBar, QCheckBox)
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QSize
from PySide6.QtGui import QIcon, QFont, QCursor, QPainter, QPen, QColor

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
        
        self.profile_name = profile_name
        self.file_path = file_path
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
        
        # Nome del profilo (in grassetto)
        self.name_label = QLabel(profile_name)
        font = QFont()
        font.setBold(True)
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
        self.name_label.setToolTip(profile_name)
        
        # Define a font for paths
        path_font = QFont()
        path_font.setPointSize(8)
        
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
        
        # Delete button with Unicode trash can icon
        self.delete_button = QPushButton("🗑️")
        self.delete_button.setToolTip("Remove this profile")
        self.delete_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.delete_button.setStyleSheet("""
            QPushButton {
                border: none;
                padding: 5px;
                background-color: transparent;
                font-size: 16px;
                color: #888;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 0.1);
                border-radius: 3px;
                color: #f00;
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
        
        # Aumentiamo significativamente l'altezza per dare più spazio al testo
        base_height = font_height + save_path_height + 30  # Margini più ampi
        
        # Imposta un'altezza fissa che sia sufficiente per tutti gli stati dell'elemento
        self.setFixedHeight(base_height)
    
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
        
        self.files_to_process = files_to_process
        self.total_files = len(files_to_process)
        self.processed_files = 0
        self.profiles_data = {}  # Dictionary to store profile data (name -> data)
        self.accepted_profiles = {}  # Dictionary to store accepted profiles
        self.analysis_running = False  # Flag to indicate if analysis is in progress
        
        self.setWindowTitle("Manage Profiles")
        self.setMinimumWidth(750)
        self.setMinimumHeight(800)
        
        # Main layout
        layout = QVBoxLayout(self)
        
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
        
        # Checkbox to toggle score display
        self.show_scores_checkbox = QCheckBox("Show scores")
        self.show_scores_checkbox.setToolTip("Show scores next to save paths")
        layout.addWidget(self.show_scores_checkbox)
        self.show_scores_checkbox.toggled.connect(self.toggle_scores_display)
        
        # Progress bar (initially hidden)
        self.progress_bar = SegmentedProgressBar()
        self.progress_bar.setRange(0, 1)  # Will be updated when analysis starts
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
        
        # Set layout
        self.setLayout(layout)
    
    def populate_profile_list(self):
        """Populate the list with files to process."""
        for file_path in self.files_to_process:
            # Extract profile name from file name
            file_name = os.path.basename(file_path)
            profile_name = os.path.splitext(file_name)[0]
            
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
    
    def toggle_scores_display(self, show):
        """Show or hide score in all profile list items."""
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            widget = self.profile_list.itemWidget(item)
            widget.set_show_score(show)
            # Manteniamo l'altezza fissa impostata nel widget
            # Impostiamo solo la larghezza dal sizeHint, mantenendo l'altezza fissa
            current_height = widget.height()
            size = QSize(widget.sizeHint().width(), current_height)
            item.setSizeHint(size)
