"""Dark Obsidian & Cyan HUD Stylesheet for PySide6 Desktop Shell."""

HUD_STYLESHEET = """
QMainWindow {
    background-color: #0B0E14;
}

QWidget {
    color: #E2E8F0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #1E293B;
    border-radius: 8px;
    margin-top: 24px;
    padding-top: 16px;
    font-weight: bold;
    color: #00D2FF;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    background-color: #0B0E14;
}

QLabel {
    color: #94A3B8;
}

QLabel#titleLabel {
    font-size: 18px;
    font-weight: 700;
    color: #00D2FF;
    letter-spacing: 1px;
}

QLabel#statusPill {
    background-color: #032541;
    color: #00D2FF;
    border: 1px solid #00D2FF;
    border-radius: 12px;
    padding: 4px 12px;
    font-weight: bold;
    font-size: 11px;
}

QLabel#metricValue {
    font-size: 15px;
    font-weight: bold;
    color: #F8FAFC;
}

QProgressBar {
    border: 1px solid #1E293B;
    border-radius: 4px;
    background-color: #111827;
    text-align: center;
    color: #E2E8F0;
    font-size: 11px;
    height: 18px;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0A84FF, stop:1 #00D2FF);
    border-radius: 3px;
}

QTextEdit {
    background-color: #07090E;
    border: 1px solid #1E293B;
    border-radius: 6px;
    color: #CBD5E1;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    padding: 8px;
}

QPushButton {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #F1F5F9;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #334155;
    border-color: #00D2FF;
}

QPushButton:pressed {
    background-color: #0F172A;
}

QPushButton#emergencyButton {
    background-color: #450A0A;
    border: 1px solid #DC2626;
    color: #FCA5A5;
}

QPushButton#emergencyButton:hover {
    background-color: #7F1D1D;
    color: #FFFFFF;
}

QScrollBar:vertical {
    background: #0B0E14;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #1E293B;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #334155;
}
"""
