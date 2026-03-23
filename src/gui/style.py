"""Global stylesheet for Context Pilot GUI."""

STYLESHEET = """
/* ── Global ─────────────────────────────────────────────── */
QMainWindow {
    background: #1e1e2e;
    color: #cdd6f4;
}
QWidget {
    font-family: "Inter", "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 13px;
    color: #cdd6f4;
}
QLabel {
    color: #cdd6f4;
}

/* ── Tabs ───────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #313244;
    border-radius: 6px;
    background: #1e1e2e;
}
QTabBar::tab {
    background: #313244;
    color: #a6adc8;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #45475a;
    color: #ff8f40;
    font-weight: bold;
}
QTabBar::tab:hover {
    background: #45475a;
}

/* ── Buttons ────────────────────────────────────────────── */
QPushButton {
    background: #45475a;
    color: #cdd6f4;
    border: 1px solid #585b70;
    border-radius: 6px;
    padding: 5px 12px;
}
QPushButton:hover {
    background: #585b70;
    border-color: #ff8f40;
}
QPushButton:pressed {
    background: #ff6b2c;
    color: white;
}
QPushButton#primary {
    background: #ff6b2c;
    color: white;
    border: none;
    font-weight: bold;
}
QPushButton#primary:hover {
    background: #ff8f40;
}
QPushButton#adaptive {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff6b2c, stop:1 #fab387);
    color: white;
    border: none;
    font-weight: bold;
}
QPushButton#adaptive:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff8f40, stop:1 #f9e2af);
}

/* ── Inputs ─────────────────────────────────────────────── */
QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {
    border-color: #ff8f40;
}

/* ── Lists ──────────────────────────────────────────────── */
QListWidget {
    background: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 6px;
    outline: none;
}
QListWidget::item {
    border-bottom: 1px solid #313244;
    padding: 2px;
}
QListWidget::item:selected {
    background: #45475a;
}

/* ── Frames / Cards ─────────────────────────────────────── */
QFrame[frameShape="6"] {  /* StyledPanel */
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
}

/* ── Scroll ─────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #1e1e2e;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #585b70;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #ff8f40;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
}

/* ── Tables ─────────────────────────────────────────────── */
QTableWidget {
    background: #1e1e2e;
    gridline-color: #313244;
    border: 1px solid #313244;
    border-radius: 4px;
}
QHeaderView::section {
    background: #313244;
    color: #a6adc8;
    border: none;
    padding: 4px 8px;
    font-weight: bold;
}

/* ── Menu ───────────────────────────────────────────────── */
QMenuBar {
    background: #181825;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
}
QMenuBar::item:selected {
    background: #45475a;
}
QMenu {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #ff6b2c;
    color: white;
}
QMenu::separator {
    height: 1px;
    background: #45475a;
    margin: 4px 8px;
}

/* ── Statusbar ──────────────────────────────────────────── */
QStatusBar {
    background: #181825;
    color: #a6adc8;
    border-top: 1px solid #313244;
}

/* ── Splitter ───────────────────────────────────────────── */
QSplitter::handle {
    background: #313244;
    width: 3px;
}
QSplitter::handle:hover {
    background: #ff8f40;
}

/* ── Dialogs ────────────────────────────────────────────── */
QDialog {
    background: #1e1e2e;
}
QDialogButtonBox QPushButton {
    min-width: 80px;
}

/* ── Progress ───────────────────────────────────────────── */
QProgressBar {
    background: #313244;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff6b2c, stop:1 #fab387);
    border-radius: 4px;
}

/* ── Checkboxes ─────────────────────────────────────────── */
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 2px solid #585b70;
    background: #313244;
}
QCheckBox::indicator:checked {
    background: #ff6b2c;
    border-color: #ff6b2c;
}

/* ── Tooltips ───────────────────────────────────────────── */
QToolTip {
    background: #45475a;
    color: #cdd6f4;
    border: 1px solid #585b70;
    border-radius: 4px;
    padding: 4px 8px;
}
"""
