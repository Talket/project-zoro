"""Dark Obsidian & Cyan HUD Stylesheet for PySide6 Desktop Shell."""

HUD_STYLESHEET = """
QMainWindow {
    background-color: #07090E;
}

QWidget {
    color: #E2E8F0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

/* Master Header and Action Bars */
QWidget#headerContainer {
    background-color: #0A0E17;
    border-bottom: 1px solid #162032;
    padding-bottom: 4px;
}

QWidget#actionContainer {
    background-color: #0A0E17;
    border-top: 1px solid #162032;
    padding-top: 6px;
}

/* Scroll Area & Container */
QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QWidget#scrollContent {
    background-color: transparent;
}

/* Card Groups */
QGroupBox {
    border: 1px solid #1A2436;
    border-radius: 8px;
    background-color: #0C101A;
    margin-top: 22px;
    padding: 18px 14px 14px 14px;
    font-weight: bold;
    color: #00D2FF;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 2px 10px;
    background-color: #121A28;
    border: 1px solid #1A2436;
    border-radius: 4px;
    color: #38BDF8;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

QLabel {
    color: #94A3B8;
}

QLabel#titleLabel {
    font-size: 17px;
    font-weight: 800;
    color: #00D2FF;
    letter-spacing: 1.5px;
}

QLabel#statusPill {
    background-color: #04213B;
    color: #00D2FF;
    border: 1px solid #00D2FF;
    border-radius: 12px;
    padding: 4px 12px;
    font-weight: bold;
    font-size: 11px;
    letter-spacing: 0.5px;
}

QLabel#metricValue {
    font-size: 14px;
    font-weight: bold;
    color: #F8FAFC;
}

/* Progress Bars */
QProgressBar {
    border: 1px solid #1A2436;
    border-radius: 4px;
    background-color: #06090F;
    text-align: center;
    color: #E2E8F0;
    font-size: 11px;
    font-weight: 600;
    height: 18px;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284C7, stop:1 #00E5FF);
    border-radius: 3px;
}

/* Inputs & Combos */
QLineEdit {
    background-color: #06090F;
    border: 1px solid #1E293B;
    border-radius: 6px;
    color: #F8FAFC;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: #0284C7;
}

QLineEdit:focus {
    border: 1px solid #00D2FF;
    background-color: #0A0F1A;
}

QComboBox {
    background-color: #121A28;
    border: 1px solid #223046;
    border-radius: 6px;
    color: #F1F5F9;
    padding: 6px 12px;
    font-weight: 500;
    min-height: 20px;
}

QComboBox:hover {
    border-color: #00D2FF;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left-width: 0px;
}

QComboBox QAbstractItemView {
    background-color: #0C101A;
    border: 1px solid #1E293B;
    selection-background-color: #0284C7;
    selection-color: #FFFFFF;
    color: #F1F5F9;
    padding: 4px;
}

/* Checkboxes */
QCheckBox {
    spacing: 8px;
    color: #CBD5E1;
    font-size: 12px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #334155;
    border-radius: 4px;
    background-color: #080B10;
}

QCheckBox::indicator:hover {
    border-color: #00D2FF;
}

QCheckBox::indicator:checked {
    background-color: #008899;
    border-color: #00D2FF;
}

/* Text & Console */
QTextEdit {
    background-color: #05070B;
    border: 1px solid #182233;
    border-radius: 6px;
    color: #CBD5E1;
    font-family: 'Consolas', 'Cascadia Code', 'Courier New', monospace;
    font-size: 12px;
    padding: 8px;
}

QTextEdit:focus {
    border: 1px solid #008899;
}

/* Buttons */
QPushButton {
    background-color: #141C2B;
    border: 1px solid #26354D;
    border-radius: 6px;
    color: #F1F5F9;
    padding: 7px 14px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton:hover {
    background-color: #1F2B3E;
    border-color: #00D2FF;
    color: #FFFFFF;
}

QPushButton:pressed {
    background-color: #0B1018;
}

QPushButton#emergencyButton {
    background-color: #450A0A;
    border: 1px solid #DC2626;
    color: #FCA5A5;
    font-weight: bold;
    letter-spacing: 0.5px;
}

QPushButton#emergencyButton:hover {
    background-color: #7F1D1D;
    border-color: #EF4444;
    color: #FFFFFF;
}

/* Custom Scrollbars */
QScrollBar:vertical {
    background: #080B10;
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #1E293B;
    min-height: 24px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #00D2FF;
}

QScrollBar::handle:vertical:pressed {
    background: #00A3CC;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
    border: none;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: #080B10;
    height: 10px;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #1E293B;
    min-width: 24px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #00D2FF;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
    border: none;
}
"""
