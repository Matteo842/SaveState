# themes.py
"""Application QSS themes."""

# Stile QSS per il tema scuro
DARK_THEME_QSS = """
QWidget {
    background-color: #2D2D2D; /* Grigio scuro Pokédex */
    color: #F0F0F0; /* Testo quasi bianco */
    font-family: 'Segoe UI', Arial, sans-serif; /* Font pulito */
    font-size: 10pt;
    outline: 0;
}
QMainWindow {
    background-color: #1E1E1E; /* Sfondo ancora più scuro per finestra principale */
}
QLabel {
    background-color: transparent;
    color: #E0E0E0;
}
QLabel#StatusLabel { /* Etichetta di stato specifica */
    color: #A0A0A0;
}
QLineEdit, QTextEdit, QListWidget, QTableWidget, QComboBox, QSpinBox {
    background-color: #3C3C3C; /* Grigio leggermente più chiaro per input/liste */
    color: #F0F0F0;
    border: 1px solid #555555;
    border-radius: 3px;
    padding: 3px;
}
QListWidget::item {
    padding: 3px;
}
QListWidget::item:selected {
    background-color: #A10808; /* Rosso scuro ufficiale per selezione */
    color: #FFFFFF;
}
QPushButton {
    background-color: #4A4A4A; /* Grigio medio per pulsanti */
    color: #F0F0F0;
    border: 1px solid #666666;
    border-radius: 4px;
    padding: 6px 12px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #5A5A5A;
    border: 1px solid #888888;
}
QPushButton:pressed {
    background-color: #404040;
}
QPushButton:disabled {
    background-color: #3A3A3A;
    color: #777777;
    border-color: #555555;
}
QPushButton#DangerButton { /* Bottone speciale per azioni pericolose (es. Ripristina) */
    background-color: #AA0000; /* Rosso scuro */
    color: white;
    font-weight: bold;
}
QPushButton#DangerButton:hover {
    background-color: #CC0000; /* Rosso acceso */
}
QPushButton#DangerButton:pressed {
    background-color: #880000;
}
QPushButton#SaveButton {
    background-color: #229954;
    color: #FFFFFF;
    border: 1px solid #1E8449;
    font-weight: bold;
}
QPushButton#SaveButton:hover {
    background-color: #27AE60;
    border-color: #229954;
}
QPushButton#SaveButton:pressed {
    background-color: #1E8449;
    border-color: #196F3D;
}
QPushButton#SaveButton:disabled {
    background-color: #1A3D2B;
    color: #6B8F7A;
    border-color: #2A4034;
}
/* --- NUOVE REGOLE SEMPLIFICATE PER QGroupBox --- */
QGroupBox {
    background-color: transparent; /* <-- AGGIUNGI (come tema chiaro) */
    /* Bordi Espliciti */
    border-top: 1px solid #555555;
    border-right: 1px solid #555555;
    border-bottom: 1px solid #555555;
    border-left: 1px solid #555555;
    border-radius: 4px;
    /* Spaziatura (come tema chiaro) */
    margin-top: 10px;
    padding-top: 10px;     /* <-- AGGIUNGI (come tema chiaro) */
    /* Aggiungi altri padding se necessario per coerenza col chiaro */
    padding-left: 5px;
    padding-right: 5px;
    padding-bottom: 5px;

    font-weight: bold;
    color: #E0E0E0;
}

QGroupBox::title {
    subcontrol-origin: margin;      /* Come tema chiaro */
    subcontrol-position: top left;  /* Come tema chiaro */
    padding: 0 5px;             /* Come tema chiaro */
    /* background-color: #2D2D2D; */ /* <-- RIMUOVI/COMMENTA (come tema chiaro) */
    left: 10px;            /* Come tema chiaro */
    color: #A10808;             /* Colore titolo scuro ufficiale */
}
/* --- FINE NUOVE REGOLE --- */
QStatusBar {
    color: #A0A0A0;
}
QStatusBar::item {
    border: none; /* Nessun bordo tra messaggi status bar */
}
QProgressBar {
    border: 1px solid #555;
    border-radius: 3px;
    text-align: center;
    color: #F0F0F0;
}
QProgressBar::chunk {
    background-color: #A10808; /* Barra progresso rossa scura */
    width: 10px; /* Larghezza blocchetti barra */
    margin: 1px;
}
QMessageBox {
    background-color: #3C3C3C;
}

QMessageBox {
    background-color: #3C3C3C; /* Sfondo scuro per il box */
}

/* Modifica questa regola esistente */
QMessageBox QLabel {
     color: #F0F0F0;         /* Testo chiaro */
     /* AUMENTA IL FONT */
     font-size: 11pt;        /* Prova 11pt (o 12pt se preferisci ancora più grande) */
     /* RIMUOVI O Riduci min-width: questo permette al box di adattarsi meglio al testo */
     /* min-width: 300px; */ /* Commenta o elimina questa riga */
     padding-left: 5px;      /* Aggiunge un piccolo spazio a sinistra del testo (opzionale) */
     /* Aggiungi un minimo di altezza se il testo sembra schiacciato verticalmente? */
     /* min-height: 40px; */ /* Opzionale, da testare */
}

/* Opzionale: Riduci un po' i pulsanti dentro i MessageBox se sembrano troppo grandi */
QMessageBox QPushButton {
    min-width: 70px; /* Larghezza minima ridotta */
    padding: 4px 10px; /* Padding ridotto */
}

/* Stile specifico per gli item/celle */
QTableWidget::item {
    padding: 4px;           /* Un po' di spazio interno */
    color: #F0F0F0;         /* Colore testo chiaro (conferma) */
    border-bottom: 1px solid #4A4A4A; /* Separa righe se vuoi (alternativa a gridline) */
    /* border: none; */ /* Assicura nessun bordo extra per item */
}

/* Stile per item selezionati */
QTableWidget::item:selected {
    background-color: transparent; /* Sfondo trasparente per pennello personalizzato (linea rossa laterale) */
    color: #FFFFFF;          /* Testo bianco su selezione */
    border: none;
}

/* Stile per le Intestazioni (Header) */
QHeaderView::section {
    background-color: #1E1E1E; /* Sfondo intestazione molto scuro */
    color: #EAEAEA;          /* Testo intestazione chiaro */
    padding: 4px;
    border-top: 0px;         /* Rimuovi bordi header se vuoi look pulito */
    border-bottom: 1px solid #A10808; /* Bordo rosso scuro sotto header */
    border-right: 1px solid #4A4A4A;
    border-left: 0px;
    font-weight: bold;        /* Grassetto */
}

/* Stile per ultima sezione header (opzionale, per non avere doppio bordo) */
QHeaderView::section:last {
    border-right: 0px;
}

QPushButton#LogToggleButton {
    border: none;                /* Nessun bordo */
    background-color: transparent; /* Sfondo trasparente */
    padding: 2px;               /* Padding piccolo */
    margin: 1px;                /* Margine piccolo per spaziatura */
    min-width: 0px;            /* ANNULLA min-width generale */
    /* La dimensione è gestita in Python */
}
/* Effetti Hover/Pressed (Opzionali, uguali per entrambi) */
QPushButton#LogToggleButton:hover {
    background-color: #5A5A5A; /* Sfondo leggero al passaggio */
}
QPushButton#LogToggleButton:pressed {
    background-color: #404040; /* Sfondo leggero alla pressione */
}

QPushButton#MinecraftButton {
    min-width: 25px;  /* Imposta min-width uguale a fixed size */
    max-width: 25px;  /* Imposta max-width uguale a fixed size */
    min-height: 25px; /* Imposta min-height uguale a fixed size */
    max-height: 25px; /* Imposta max-height uguale a fixed size */
    padding: 3px;     /* Padding piccolo e UGUALE su tutti i lati */
    /* Non impostiamo border o background-color qui,
       così eredita l'aspetto standard dal QPushButton generale */
}
/* Manteniamo gli effetti standard se li vogliamo */
QPushButton#MinecraftButton:hover {
    background-color: #5A5A5A;
    border: 1px solid #888888; /* Potrebbe essere necessario specificare anche il bordo qui */
}
QPushButton#MinecraftButton:pressed {
    background-color: #404040;
}


/* Aggiungere stili per altri widget se necessario (QDialog, QInputDialog etc.) */

QPushButton#ShortcutButton {
    border: none;               /* Nessun bordo */
    background-color: transparent; /* Sfondo trasparente */
    padding: 1px;               /* Padding minimo per icona */
    margin: 1px;                /* Margine piccolo */
    min-width: none;            /* Ignora larghezza minima generale */
    /* La dimensione è gestita da Python */
}
QPushButton#ShortcutButton:hover {
    background-color: #5A5A5A; /* Grigio scuro al passaggio */
}
QPushButton#ShortcutButton:pressed {
    background-color: #404040; /* Leggermente più scuro alla pressione */
}

QPushButton#ExitButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 4px;
}
QPushButton#ExitButton:hover {
    background-color: #5A5A5A;
    border: 1px solid #888888;
}
QPushButton#ExitButton:pressed {
    background-color: #404040;
}

QPushButton#ConfigureButton {
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 2px;
}
QPushButton#ConfigureButton:hover {
    background-color: #5A5A5A;
    border: 1px solid #888888;
}
QPushButton#ConfigureButton:pressed {
    background-color: #404040;
}

/* ===== ACTION BUTTONS (Backup/Restore/Manage) - DARK THEME ===== */
QPushButton#BackupButton,
QPushButton#RestoreButton,
QPushButton#ManageButton {
    background-color: #222222;
    border: 1px solid #6b6b6b;
    border-radius: 5px;
    padding: 8px 12px;
    font-weight: bold;
    font-size: 12pt;
}
QPushButton#BackupButton  { color: #2980B9; }
QPushButton#RestoreButton { color: #27AE60; }
QPushButton#ManageButton  { color: #e0e0e0; font-size: 11pt; }

QPushButton#BackupButton:hover,
QPushButton#RestoreButton:hover,
QPushButton#ManageButton:hover {
    background-color: #3a3a3a;
    border-color: #8b8b8b;
}
QPushButton#BackupButton:pressed,
QPushButton#RestoreButton:pressed,
QPushButton#ManageButton:pressed {
    background-color: #454545;
    border-color: #8b8b8b;
}
QPushButton#BackupButton:disabled,
QPushButton#RestoreButton:disabled,
QPushButton#ManageButton:disabled {
    border-color: #444444;
    color: #555555;
}
/* ===== END ACTION BUTTONS DARK ===== */

/* ===== EMPTY STATE WIDGET STYLING (DARK THEME) ===== */
QWidget#EmptyStateWidget {
    background-color: transparent;
}
QLabel#EmptyStateTitle {
    color: #E0E0E0;
    background: transparent;
    font-size: 18pt;
    font-weight: bold;
    padding: 8px 0px;
}
QLabel#EmptyStateInstructions {
    color: #A0A0A0;
    background: transparent;
    font-size: 10pt;
    padding: 10px 20px;
}
QLabel#EmptyStateHint {
    color: #707070;
    background: transparent;
    font-size: 9pt;
    font-style: italic;
    padding: 5px 0px;
}
/* ===== END EMPTY STATE WIDGET ===== */

/* ===== CUSTOM SCROLLBAR STYLING (DARK THEME) ===== */
QScrollBar:vertical {
    background-color: #2D2D2D;  /* Sfondo track (stesso del widget) */
    width: 14px;                /* Larghezza scrollbar (aumentata per bordo) */
    margin: 0px;                /* Nessun margine */
    border: none;               /* Nessun bordo */
}

QScrollBar::handle:vertical {
    background-color: #4A4A4A;  /* Riempimento interno grigio scuro */
    border: 2px solid #A10808;  /* Bordo accent rosso (colore titoli) */
    min-height: 30px;           /* Altezza minima handle */
    border-radius: 4px;         /* Angoli leggermente arrotondati */
    margin: 2px;                /* Margine per distanziare dal bordo */
}

QScrollBar::handle:vertical:hover {
    background-color: #5A5A5A;  /* Riempimento più chiaro al passaggio */
    border: 2px solid #C10A0A;  /* Bordo rosso leggermente più brillante */
}

QScrollBar::handle:vertical:pressed {
    background-color: #A10808;  /* Riempimento rosso quando premuto */
    border: 2px solid #C10A0A;  /* Bordo rosso più brillante */
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;                /* Nascondi le frecce su/giù */
    background: none;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;           /* Nessuno sfondo per le aree sopra/sotto handle */
}

/* Scrollbar orizzontale (se necessaria) */
QScrollBar:horizontal {
    background-color: #2D2D2D;
    height: 14px;
    margin: 0px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #4A4A4A;
    border: 2px solid #A10808;
    min-width: 30px;
    border-radius: 4px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #5A5A5A;
    border: 2px solid #C10A0A;
}

QScrollBar::handle:horizontal:pressed {
    background-color: #A10808;
    border: 2px solid #C10A0A;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
}
/* ===== END CUSTOM SCROLLBAR ===== */

/* ===== NOTIFICATION TOAST ===== */
QWidget#NotificationPopup {
    background-color: transparent;
}
QFrame#NotificationCard {
    background-color: #252628;
    border: 1px solid #45474C;
    border-radius: 10px;
}
QFrame#NotificationAccentSuccess {
    background-color: #35C878;
    border: none;
    border-top-left-radius: 9px;
    border-bottom-left-radius: 9px;
}
QFrame#NotificationAccentError {
    background-color: #E5484D;
    border: none;
    border-top-left-radius: 9px;
    border-bottom-left-radius: 9px;
}
QLabel#NotificationIcon {
    background-color: #323438;
    border: 1px solid #484B51;
    border-radius: 9px;
}
QLabel#NotificationTitle {
    color: #FFFFFF;
    font-size: 11pt;
    font-weight: 600;
}
QLabel#NotificationMessage {
    color: #C9CBD1;
    font-size: 9.5pt;
}
/* ===== END NOTIFICATION TOAST ===== */

"""

LIGHT_THEME_QSS = """
/* =========================================================
   SAVESTATE - LIGHT THEME (modern Fluent / macOS-inspired)
   Palette:
     bg base       #F4F5F7   bg window   #ECEDF0
     surface       #FFFFFF   surface alt #F8F9FB
     border soft   #E1E3E8   border med  #C9CCD3
     text primary  #1F2024   text 2nd    #5A5D66   text muted #8A8D96
     accent        #4F46E5   accent hov  #4338CA   accent prs #3730A3
     accent tint   #EEF2FF   accent text #3730A3
     danger        #E5484D   warn        #F5A524
   ========================================================= */

QWidget {
    background-color: #F4F5F7;
    color: #1F2024;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 10pt;
    outline: 0;
}
QMainWindow {
    background-color: #ECEDF0;
}
QLabel {
    background-color: transparent;
    color: #1F2024;
}
QLabel#StatusLabel {
    color: #5A5D66;
}

/* ---- Inputs / Lists / Tables ---- */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF;
    color: #1F2024;
    border: 1px solid #C9CCD3;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #4F46E5;
    selection-color: #FFFFFF;
}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover,
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border: 1px solid #A8ADB7;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #4F46E5;
    background-color: #FFFFFF;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    background-color: #F0F1F4;
    color: #9CA0AA;
    border-color: #DDE0E5;
}

QListWidget, QTableWidget, QTreeWidget, QTreeView, QListView, QTableView {
    background-color: #FFFFFF;
    color: #1F2024;
    border: 1px solid #C9CCD3;
    border-radius: 6px;
    padding: 2px;
    alternate-background-color: #F8F9FB;
    gridline-color: #ECEDF0;
}
QListWidget::item, QTableWidget::item, QTreeWidget::item {
    padding: 5px;
    color: #1F2024;
    border-bottom: 1px solid #ECEDF0;
}
/* Hover only on QListWidget/QTreeWidget: QTableWidget uses a custom delegate
   (ProfileSelectionDelegate) and adding ::item:hover here would conflict with
   the delegate's paint, hiding the cell icon/text under the cursor. */
QListWidget::item:hover, QTreeWidget::item:hover {
    background-color: #F0F4F4;
}
QListWidget::item:selected, QTableWidget::item:selected, QTreeWidget::item:selected {
    background-color: #EEF2FF;
    color: #3730A3;
}
QListWidget::item:selected:active, QTableWidget::item:selected:active {
    background-color: #DDE4FF;
    color: #312E81;
}

/* ---- Standard Buttons ---- */
QPushButton {
    background-color: #FFFFFF;
    color: #1F2024;
    border: 1px solid #C9CCD3;
    border-radius: 6px;
    padding: 6px 14px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #F4F5F7;
    border: 1px solid #A8ADB7;
}
QPushButton:pressed {
    background-color: #E5E7EB;
    border: 1px solid #8E939E;
}
QPushButton:focus {
    border: 1px solid #4F46E5;
}
QPushButton:disabled {
    background-color: #F0F1F4;
    color: #B0B4BD;
    border-color: #DDE0E5;
}
QPushButton:default {
    border: 1px solid #4F46E5;
    color: #3730A3;
    font-weight: 600;
}

QPushButton#DangerButton {
    background-color: #E5484D;
    color: #FFFFFF;
    border: 1px solid #C73238;
    font-weight: bold;
}
QPushButton#DangerButton:hover {
    background-color: #EF5A5F;
    border-color: #B7282E;
}
QPushButton#DangerButton:pressed {
    background-color: #C73238;
    border-color: #A0252A;
}
QPushButton#SaveButton {
    background-color: #1B5E20;
    color: #FFFFFF;
    border: 1px solid #145214;
    font-weight: bold;
}
QPushButton#SaveButton:hover {
    background-color: #2E7D32;
    border-color: #1B5E20;
}
QPushButton#SaveButton:pressed {
    background-color: #145214;
    border-color: #0D3B10;
}
QPushButton#SaveButton:disabled {
    background-color: #E8F0E8;
    color: #A0B8A0;
    border-color: #C8D8C8;
}

/* ---- Group boxes ---- */
QGroupBox {
    background-color: transparent;
    border: 1px solid #D6D9DF;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 12px;
    padding-left: 6px;
    padding-right: 6px;
    padding-bottom: 6px;
    font-weight: 600;
    color: #1F2024;
}
/* Title floats over the GroupBox border line. The background MUST match the
   parent widget color (not 'transparent') so it covers the border line under
   the text -- same trick used in the dark theme. We use the generic QWidget
   color (#F4F5F7), which is what most GroupBox parents (content containers,
   dialogs, panels) inherit. */
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    color: #4F46E5;
    background-color: #F4F5F7;
}

/* ---- ComboBox ---- */
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #1F2024;
    border: 1px solid #C9CCD3;
    border-radius: 6px;
    selection-background-color: #EEF2FF;
    selection-color: #3730A3;
    padding: 2px;
}

/* ---- Tabs ---- */
QTabWidget::pane {
    border: 1px solid #D6D9DF;
    border-radius: 6px;
    background-color: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background-color: #ECEDF0;
    color: #5A5D66;
    border: 1px solid #D6D9DF;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 14px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #3730A3;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background-color: #F4F5F7;
    color: #1F2024;
}

/* ---- CheckBox / RadioButton ----
   Only label styling here. Indicator rendering is left to Qt's native style
   (same approach as the dark theme) so the system check mark works correctly. */
QCheckBox, QRadioButton {
    background-color: transparent;
    color: #1F2024;
    spacing: 6px;
}

/* ---- Status bar / Progress ---- */
QStatusBar {
    background-color: #ECEDF0;
    color: #5A5D66;
    border-top: 1px solid #D6D9DF;
}
QStatusBar::item {
    border: none;
}
QProgressBar {
    border: 1px solid #C9CCD3;
    border-radius: 6px;
    text-align: center;
    color: #1F2024;
    background-color: #F4F5F7;
    min-height: 14px;
}
QProgressBar::chunk {
    background-color: #4F46E5;
    border-radius: 5px;
}

/* ---- MessageBox / Dialog ---- */
QMessageBox, QDialog {
    background-color: #F4F5F7;
}
QMessageBox QLabel {
    color: #1F2024;
    font-size: 11pt;
    padding-left: 5px;
    background-color: transparent;
}
QMessageBox QPushButton {
    min-width: 80px;
    padding: 5px 14px;
}

/* ---- Headers (Table headers) ---- */
QHeaderView::section {
    background-color: #ECEDF0;
    color: #1F2024;
    padding: 6px 8px;
    border-top: 0px;
    border-bottom: 2px solid #4F46E5;
    border-right: 1px solid #DDE0E5;
    border-left: 0px;
    font-weight: 600;
}
QHeaderView::section:hover {
    background-color: #E2E4E9;
}
QHeaderView::section:last {
    border-right: 0px;
}

/* ---- ToolTip ---- */
QToolTip {
    background-color: #1F2024;
    color: #FFFFFF;
    border: 1px solid #1F2024;
    border-radius: 4px;
    padding: 4px 8px;
}

/* ---- Menu ---- */
QMenu {
    background-color: #FFFFFF;
    color: #1F2024;
    border: 1px solid #C9CCD3;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 22px 6px 14px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #EEF2FF;
    color: #3730A3;
}
QMenu::separator {
    height: 1px;
    background-color: #E1E3E8;
    margin: 4px 6px;
}
QMenuBar {
    background-color: #ECEDF0;
    color: #1F2024;
    border-bottom: 1px solid #D6D9DF;
}
QMenuBar::item:selected {
    background-color: #EEF2FF;
    color: #3730A3;
}

/* ---- Splitter ---- */
QSplitter::handle {
    background-color: #D6D9DF;
}
QSplitter::handle:hover {
    background-color: #4F46E5;
}

/* ---- Slider ---- */
QSlider::groove:horizontal {
    background-color: #DDE0E5;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #4F46E5;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background-color: #4338CA;
}

/* ---- Small icon-only buttons ---- */
QPushButton#LogToggleButton {
    border: none;
    background-color: transparent;
    padding: 2px;
    margin: 1px;
    min-width: 0px;
}
QPushButton#LogToggleButton:hover {
    background-color: #E1E3E8;
    border-radius: 4px;
}
QPushButton#LogToggleButton:pressed {
    background-color: #C9CCD3;
    border-radius: 4px;
}

QPushButton#MinecraftButton {
    min-width: 25px;
    max-width: 25px;
    min-height: 25px;
    max-height: 25px;
    padding: 3px;
}
QPushButton#MinecraftButton:hover {
    background-color: #F4F5F7;
    border: 1px solid #A8ADB7;
}
QPushButton#MinecraftButton:pressed {
    background-color: #E5E7EB;
}

QPushButton#ShortcutButton {
    border: none;
    background-color: transparent;
    padding: 1px;
    margin: 1px;
    min-width: none;
}
QPushButton#ShortcutButton:hover {
    background-color: #E1E3E8;
    border-radius: 4px;
}
QPushButton#ShortcutButton:pressed {
    background-color: #C9CCD3;
    border-radius: 4px;
}

QPushButton#ExitButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 4px;
}
QPushButton#ExitButton:hover {
    background-color: #F4F5F7;
    border: 1px solid #A8ADB7;
}
QPushButton#ExitButton:pressed {
    background-color: #E5E7EB;
}

QPushButton#ConfigureButton {
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 2px;
}
QPushButton#ConfigureButton:hover {
    background-color: #F4F5F7;
    border: 1px solid #A8ADB7;
}
QPushButton#ConfigureButton:pressed {
    background-color: #E5E7EB;
}

/* ===== ACTION BUTTONS (Backup/Restore/Manage) - LIGHT THEME ===== */
QPushButton#BackupButton,
QPushButton#RestoreButton,
QPushButton#ManageButton {
    background-color: #FFFFFF;
    border: 1px solid #C9CCD3;
    border-radius: 8px;
    padding: 8px 12px;
    font-weight: bold;
    font-size: 12pt;
}
QPushButton#BackupButton  { color: #1565C0; }
QPushButton#RestoreButton { color: #2E7D32; }
QPushButton#ManageButton  { color: #37474F; font-size: 11pt; }

QPushButton#BackupButton:hover {
    background-color: #EAF3FB;
    border-color: #1565C0;
}
QPushButton#RestoreButton:hover {
    background-color: #EAF6EC;
    border-color: #2E7D32;
}
QPushButton#ManageButton:hover {
    background-color: #ECEFF1;
    border-color: #607D8B;
}
QPushButton#BackupButton:pressed,
QPushButton#RestoreButton:pressed,
QPushButton#ManageButton:pressed {
    background-color: #DDE0E5;
    border-color: #8E939E;
}
QPushButton#BackupButton:disabled,
QPushButton#RestoreButton:disabled,
QPushButton#ManageButton:disabled {
    background-color: #F0F1F4;
    border-color: #DDE0E5;
    color: #B0B4BD;
}
/* ===== END ACTION BUTTONS LIGHT ===== */

/* ===== EMPTY STATE WIDGET STYLING (LIGHT THEME) ===== */
QWidget#EmptyStateWidget {
    background-color: transparent;
}
QLabel#EmptyStateTitle {
    color: #1F2024;
    background: transparent;
    font-size: 18pt;
    font-weight: bold;
    padding: 8px 0px;
}
QLabel#EmptyStateInstructions {
    color: #5A5D66;
    background: transparent;
    font-size: 10pt;
    padding: 10px 20px;
}
QLabel#EmptyStateHint {
    color: #8A8D96;
    background: transparent;
    font-size: 9pt;
    font-style: italic;
    padding: 5px 0px;
}
/* ===== END EMPTY STATE WIDGET ===== */

/* ===== CUSTOM SCROLLBAR STYLING (LIGHT THEME) ===== */
QScrollBar:vertical {
    background-color: transparent;
    width: 12px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #C9CCD3;
    min-height: 30px;
    border-radius: 6px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background-color: #4F46E5;
}
QScrollBar::handle:vertical:pressed {
    background-color: #3730A3;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background-color: transparent;
    height: 12px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #C9CCD3;
    min-width: 30px;
    border-radius: 6px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #4F46E5;
}
QScrollBar::handle:horizontal:pressed {
    background-color: #3730A3;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
}
/* ===== END CUSTOM SCROLLBAR ===== */

/* ===== NOTIFICATION TOAST ===== */
QWidget#NotificationPopup {
    background-color: transparent;
}
QFrame#NotificationCard {
    background-color: #FFFFFF;
    border: 1px solid #D9DCE3;
    border-radius: 10px;
}
QFrame#NotificationAccentSuccess {
    background-color: #22A966;
    border: none;
    border-top-left-radius: 9px;
    border-bottom-left-radius: 9px;
}
QFrame#NotificationAccentError {
    background-color: #E5484D;
    border: none;
    border-top-left-radius: 9px;
    border-bottom-left-radius: 9px;
}
QLabel#NotificationIcon {
    background-color: #F4F5F7;
    border: 1px solid #E1E3E8;
    border-radius: 9px;
}
QLabel#NotificationTitle {
    color: #17181C;
    font-size: 11pt;
    font-weight: 600;
}
QLabel#NotificationMessage {
    color: #5A5D66;
    font-size: 9.5pt;
}
/* ===== END NOTIFICATION TOAST ===== */

"""
