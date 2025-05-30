"""
Dialogo per la gestione multipla dei profili durante il drag and drop di più file.
Permette di visualizzare, selezionare ed eliminare i profili prima di aggiungerli.
"""

import os
import logging
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
                              QPushButton, QListWidget, QListWidgetItem, 
                              QWidget, QMessageBox, QProgressBar, QCheckBox)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QIcon, QFont, QCursor

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
        
        # Layout per le informazioni del profilo (nome e percorso)
        info_layout = QVBoxLayout()
        
        # Nome del profilo (in grassetto)
        self.name_label = QLabel(profile_name)
        font = QFont()
        font.setBold(True)
        self.name_label.setFont(font)
        # Enable wrapping and selection for profile name
        self.name_label.setWordWrap(True)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # Definiamo un font per i percorsi
        path_font = QFont()
        path_font.setPointSize(8)
        
        # Manteniamo il percorso del file in memoria ma non lo mostriamo
        self.file_path = file_path
        
        # Percorso di salvataggio (inizialmente nascosto)
        self.save_path_label = QLabel("")
        self.save_path_label.setFont(path_font)
        self.save_path_label.setStyleSheet("color: #4CAF50;")
        # Enable wrapping and selection for save path
        self.save_path_label.setWordWrap(True)
        self.save_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.save_path_label.hide()
        
        # Aggiungi le etichette al layout delle informazioni
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.save_path_label)
        
        # Aggiungi il layout delle informazioni al layout principale
        layout.addLayout(info_layout, 1)  # Stretch factor 1 per dare più spazio
        
        # Pulsante di eliminazione con icona Unicode del cestino
        self.delete_button = QPushButton("🗑️")
        self.delete_button.setToolTip("Rimuovi questo profilo")
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
        
        # Imposta il layout
        self.setLayout(layout)
    
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
        text = f"Percorso salvataggio: {self.save_path}" + (f" (Score: {self.score})" if self.show_score else "")
        self.save_path_label.setText(text)
        self.save_path_label.setToolTip(self.save_path)
    
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
        self.profiles_data = {}  # Dizionario per memorizzare i dati dei profili (nome -> dati)
        self.accepted_profiles = {}  # Dizionario per memorizzare i profili accettati
        self.analysis_running = False  # Flag per indicare se l'analisi è in corso
        
        self.setWindowTitle("Gestione Profili")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        
        # Layout principale
        layout = QVBoxLayout(self)
        
        # Intestazione
        self.header_label = QLabel(f"<b>{self.total_files} file rilevati</b>")
        self.header_label.setObjectName("header_label")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.header_label)
        
        # Descrizione
        self.description_label = QLabel("Seleziona i file che vuoi analizzare per creare profili. "
                                  "Puoi rimuovere i file che non ti interessano prima di avviare l'analisi.")
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.description_label)
        
        # Checkbox to toggle score display
        self.show_scores_checkbox = QCheckBox("Mostra punteggi")
        self.show_scores_checkbox.setToolTip("Mostra i punteggi accanto ai percorsi di salvataggio")
        layout.addWidget(self.show_scores_checkbox)
        self.show_scores_checkbox.toggled.connect(self.toggle_scores_display)
        
        # Barra di avanzamento (inizialmente nascosta)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)  # Sarà aggiornato quando inizia l'analisi
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v/%m file processati (%p%)")
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # Etichetta stato corrente (inizialmente nascosta)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.hide()
        layout.addWidget(self.status_label)
        
        # Lista dei profili
        self.profile_list = QListWidget()
        # Rimuoviamo l'alternanza dei colori che causa problemi di leggibilità
        self.profile_list.setAlternatingRowColors(False)
        # Impostiamo uno stile coerente con il tema scuro
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
        
        # Pulsanti
        buttons_layout = QHBoxLayout()
        
        # Pulsante per avviare l'analisi
        self.start_analysis_button = QPushButton("Avvia Analisi")
        self.start_analysis_button.clicked.connect(self.start_analysis)
        
        # Pulsante per aggiungere i profili
        self.add_button = QPushButton("Aggiungi Profili")
        self.add_button.setEnabled(False)  # Disabilitato finché l'analisi non è completa
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.accept)
        
        # Pulsante per annullare
        self.cancel_button = QPushButton("Annulla")
        self.cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.start_analysis_button)
        buttons_layout.addWidget(self.add_button)
        
        layout.addLayout(buttons_layout)
        
        # Imposta il layout
        self.setLayout(layout)
    
    def populate_profile_list(self):
        """Popola la lista con i file da processare."""
        for file_path in self.files_to_process:
            # Estrai il nome del profilo dal nome del file
            file_name = os.path.basename(file_path)
            profile_name = os.path.splitext(file_name)[0]
            
            # Crea l'elemento personalizzato
            item_widget = ProfileListItem(profile_name, file_path)
            item_widget.deleteClicked.connect(self.remove_profile)
            
            # Crea l'elemento della lista
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            
            # Aggiungi l'elemento alla lista
            self.profile_list.addItem(list_item)
            self.profile_list.setItemWidget(list_item, item_widget)
            
            # Aggiungi il profilo al dizionario dei profili
            self.profiles_data[profile_name] = {
                'file_path': file_path,
                'analyzed': False
            }
    
    def start_analysis(self):
        """Avvia l'analisi dei profili selezionati."""
        # Verifica se ci sono profili da analizzare
        if self.profile_list.count() == 0:
            QMessageBox.warning(self, "Nessun profilo", "Non ci sono profili da analizzare.")
            return
        
        # Imposta il flag di analisi in corso
        self.analysis_running = True
        
        # Aggiorna l'interfaccia per la fase di analisi
        self.header_label.setText("<b>Analisi in corso...</b>")
        self.description_label.setText("Sto analizzando i file per trovare i percorsi di salvataggio. "
                                      "I risultati verranno mostrati man mano che vengono trovati.")
        
        # Mostra la barra di avanzamento e l'etichetta di stato
        self.progress_bar.setRange(0, self.profile_list.count())
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("Inizializzazione...")
        self.status_label.show()
        
        # Disabilita il pulsante di avvio analisi
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
                    # Resize list item to accommodate wrapped text
                    item.setSizeHint(widget.sizeHint())
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
        """Aggiorna la barra di avanzamento e lo stato."""
        self.processed_files = current_file
        self.progress_bar.setValue(current_file)
        self.status_label.setText(status_text)
        
        # Se tutti i file sono stati processati, abilita il pulsante di aggiunta
        if current_file >= self.profile_list.count():
            self.analysis_running = False
            self.add_button.setEnabled(True)
            self.header_label.setText(f"<b>Analisi completata</b>")
            self.description_label.setText("I seguenti profili verranno creati con i percorsi di salvataggio trovati. "
                                          "Puoi ancora rimuovere i profili che non desideri aggiungere.")
            self.status_label.setText("Analisi completata.")
    
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
        """Aggiorna l'intestazione con il numero di profili."""
        count = self.profile_list.count()
        self.header_label.setText(f"<b>{count} profili rilevati</b>")
    
    def get_accepted_profiles(self):
        """Restituisce i profili accettati."""
        # Aggiorna i profili accettati con i percorsi di salvataggio trovati
        accepted = {}
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            widget = self.profile_list.itemWidget(item)
            if widget.analyzed and widget.save_path:
                accepted[widget.profile_name] = {'path': widget.save_path}
        return accepted
        
    def get_files_to_analyze(self):
        """Restituisce la lista dei file da analizzare."""
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
            item.setSizeHint(widget.sizeHint())
