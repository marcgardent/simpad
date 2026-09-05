"""
SimPulse Qt6 Dark Motorsport Theme & Styling.
"""

DARK_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #121417;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Ubuntu', sans-serif;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #23272e;
    background-color: #181b20;
    border-radius: 6px;
    top: -1px;
}

QTabBar::tab {
    background: #14171c;
    color: #8892b0;
    border: 1px solid #23272e;
    padding: 8px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background: #1e222b;
    color: #00d2ff;
    border-bottom: 2px solid #00d2ff;
}

QTabBar::tab:hover:!selected {
    background: #1a1e26;
    color: #cbd5e1;
}

QGroupBox {
    border: 1px solid #2a2f3b;
    border-radius: 8px;
    margin-top: 18px;
    padding-top: 14px;
    background-color: #15181e;
    font-weight: 600;
    color: #00d2ff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    left: 12px;
}

QPushButton {
    background-color: #1f242d;
    color: #e2e8f0;
    border: 1px solid #333a48;
    border-radius: 5px;
    padding: 6px 14px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #272e3a;
    border-color: #00d2ff;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #0ea5e9;
    color: #ffffff;
}

QPushButton:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
    color: #ffffff;
}

QSlider::groove:horizontal {
    height: 6px;
    background: #23272e;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #00d2ff;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #ffffff;
    border: 1px solid #00d2ff;
    width: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}

QComboBox {
    background-color: #1f242d;
    color: #e2e8f0;
    border: 1px solid #333a48;
    border-radius: 5px;
    padding: 4px 10px;
}

QComboBox QAbstractItemView {
    background-color: #181b20;
    color: #e2e8f0;
    selection-background-color: #0284c7;
    border: 1px solid #333a48;
}

QProgressBar {
    border: 1px solid #2a2f3b;
    border-radius: 4px;
    text-align: center;
    background-color: #14171c;
    color: #ffffff;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: #00d2ff;
    border-radius: 3px;
}

QTableWidget {
    background-color: #14171c;
    border: 1px solid #23272e;
    gridline-color: #23272e;
    color: #e2e8f0;
    border-radius: 6px;
}

QHeaderView::section {
    background-color: #1a1e26;
    color: #94a3b8;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #23272e;
    font-weight: bold;
}

QStatusBar {
    background-color: #0f1115;
    color: #64748b;
    border-top: 1px solid #1f242d;
}
"""
