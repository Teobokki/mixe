"""MIXE visual style — dark modern mail client. ©2026 EX Inc./HYPERION DIGITAL ©2026"""
import os
import sys

BG = "#0e121c"
PANEL = "#12182a"
CARD = "#161e32"
CARD2 = "#1a243a"
BORDER = "#2a3a55"
TXT = "#e8eef8"
MUT = "#9aacc4"
DIM = "#6a7a94"
ACC = "#00d2ff"
ACC2 = "#00c8a8"
WARN = "#ffb44a"
DANGER = "#ff5a6a"
UNREAD = "#7ad8ff"


def res_path(*parts):
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


QSS = """
QWidget#root { background: %s; color: %s; font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 13px; }
QWidget#topbar { background: %s; }
QLabel#apptitle { color: %s; font-size: 16px; font-weight: 700; letter-spacing: 1px; }
QLabel#muted { color: %s; font-size: 11px; }
QLabel#hint { color: %s; font-size: 12px; }
QWidget#hline { background: %s; }
QWidget#sidebar { background: %s; }
QDialog { background: %s; color: %s; font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 13px; }
QPushButton#nav {
  background: transparent; color: %s; border: none; border-radius: 10px;
  padding: 10px 8px; text-align: left;
}
QPushButton#nav:hover { background: %s; color: %s; }
QPushButton#nav:checked { background: rgba(0,210,255,0.16); color: %s; }
QPushButton#primary {
  background: #008ca8; color: #ffffff; border: none; border-radius: 10px;
  padding: 10px 18px; font-weight: 700; font-size: 13px;
}
QPushButton#primary:hover { background: #00a8c4; }
QPushButton#primary:disabled { background: #2a3548; color: #6a7a94; }
QPushButton#secondary {
  background: %s; color: %s; border: 1px solid %s; border-radius: 10px; padding: 9px 14px;
}
QPushButton#secondary:hover { border-color: %s; color: %s; }
QPushButton#secondary:disabled { color: %s; border-color: %s; }
QPushButton#flat { background: transparent; color: %s; border: none; padding: 6px 10px; }
QPushButton#flat:hover { color: %s; }
QPushButton#danger {
  background: rgba(255,90,106,0.14); color: %s; border: 1px solid %s; border-radius: 10px; padding: 9px 14px;
}
QFrame#card { background: %s; border: 1px solid %s; border-radius: 14px; }
QLabel#h1 { color: %s; font-size: 26px; font-weight: 700; }
QLabel#h2 { color: %s; font-size: 16px; font-weight: 600; }
QLabel#body { color: %s; font-size: 13px; }
QLabel#warn {
  background: rgba(255,180,74,0.12); color: %s; border: 1px solid %s;
  border-radius: 10px; padding: 12px;
}
QLabel#error {
  background: rgba(255,90,106,0.12); color: %s; border: 1px solid %s;
  border-radius: 10px; padding: 12px;
}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
  background: %s; color: %s; border: 1px solid %s; border-radius: 8px; padding: 8px 10px;
  selection-background-color: #008ca8; selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
  border-color: #00a8c4;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
  background: %s; color: %s; border: 1px solid %s; selection-background-color: #008ca8;
}
QCheckBox { color: %s; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid %s; border-radius: 3px; background: %s; }
QCheckBox::indicator:checked { background: #008ca8; border-color: #00a8c4; }
QListWidget, QTreeWidget, QTableWidget, QScrollArea { background: %s; border: 1px solid %s; border-radius: 8px; color: %s; }
QListWidget::item, QTreeWidget::item { padding: 8px 10px; border: none; color: %s; }
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {
  background: rgba(0,210,255,0.16); color: %s;
}
QListWidget::item:hover, QTreeWidget::item:hover { background: %s; }
QHeaderView::section {
  background: %s; color: %s; border: none; border-bottom: 1px solid %s;
  padding: 8px 10px; font-weight: 600;
}
QTableWidget { gridline-color: %s; }
QTableWidget::item { padding: 6px 8px; }
QSplitter::handle { background: %s; width: 1px; height: 1px; }
QMenu { background: %s; color: %s; border: 1px solid %s; }
QMenu::item { padding: 7px 18px; }
QMenu::item:selected { background: rgba(0,210,255,0.16); }
QMenu::separator { height: 1px; background: %s; margin: 4px 8px; }
QStatusBar { background: %s; color: %s; }
QScrollBar:vertical { background: %s; width: 10px; margin: 0; border: none; }
QScrollBar::handle:vertical { background: %s; min-height: 24px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: %s; height: 10px; margin: 0; border: none; }
QScrollBar::handle:horizontal { background: %s; min-width: 24px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QToolTip { background: %s; color: %s; border: 1px solid %s; padding: 4px 8px; }
""" % (
    BG, TXT, PANEL, ACC, MUT, MUT, BORDER, PANEL,
    BG, TXT,
    MUT, CARD2, TXT, ACC,
    CARD, TXT, BORDER, ACC, ACC, DIM, BORDER,
    MUT, ACC, DANGER, DANGER,
    CARD, BORDER, TXT, TXT, MUT,
    WARN, WARN, DANGER, DANGER,
    CARD2, TXT, BORDER,
    CARD, TXT, BORDER,
    TXT, BORDER, CARD2,
    CARD2, BORDER, TXT, TXT, TXT, CARD,
    PANEL, MUT, BORDER,
    BORDER, BORDER,
    CARD, TXT, BORDER, BORDER,
    PANEL, DIM,
    BG, BORDER, BG, BORDER,
    CARD, TXT, BORDER,
)
