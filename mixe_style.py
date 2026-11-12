"""MIXE visual style — dark modern shell. ©2026 EX Inc./HYPERION DIGITAL ©2026"""
import os, sys

BG = "#0e121c"
PANEL = "#12182a"
CARD = "#161e32"
CARD2 = "#1a243a"
BORDER = "#2a3a55"
TXT = "#e8eef8"
MUT = "#9aacc4"
DIM = "#6a7a94"
ACC = "#00d2ff"
ACC2 = "#00e6c0"
WARN = "#ffb44a"
DANGER = "#ff5a6a"


def res_path(*parts):
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def engine_root():
    """Bundled engine/ next to the exe (onedir) or beside source."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        meipass = getattr(sys, "_MEIPASS", "")
        cand = [
            os.path.join(exe_dir, "engine"),
            os.path.join(exe_dir, "_internal", "engine"),
            os.path.join(meipass, "engine") if meipass else "",
        ]
    else:
        cand = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine")]
    for c in cand:
        if c and os.path.isdir(c):
            return c
    return [c for c in cand if c][0]


QSS = """
QWidget#root { background: %s; color: %s; font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 13px; }
QWidget#topbar { background: %s; }
QLabel#apptitle { color: %s; font-size: 16px; font-weight: 700; letter-spacing: 1px; }
QLabel#muted { color: %s; font-size: 11px; }
QWidget#hline { background: %s; }
QWidget#sidebar { background: %s; }
QPushButton#nav {
  background: transparent; color: %s; border: none; border-radius: 10px;
  padding: 10px 6px; text-align: center;
}
QPushButton#nav:hover { background: %s; color: %s; }
QPushButton#nav:checked { background: rgba(0,210,255,0.18); color: %s; }
QPushButton#primary {
  background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #0090b8, stop:1 #00c8a0);
  color: white; border: none; border-radius: 12px; padding: 14px 22px; font-weight: 700; font-size: 14px;
}
QPushButton#primary:hover { background: #00d2ff; color: #061018; }
QPushButton#primary:disabled { background: #2a3548; color: #6a7a94; }
QPushButton#secondary {
  background: %s; color: %s; border: 1px solid %s; border-radius: 10px; padding: 10px 16px;
}
QPushButton#secondary:hover { border-color: %s; color: %s; }
QPushButton#flat { background: transparent; color: %s; border: none; padding: 6px 10px; }
QPushButton#flat:hover { color: %s; }
QPushButton#danger {
  background: rgba(255,90,106,0.15); color: %s; border: 1px solid %s; border-radius: 10px; padding: 10px 16px;
}
QFrame#card {
  background: %s; border: 1px solid %s; border-radius: 14px;
}
QLabel#h1 { color: %s; font-size: 26px; font-weight: 700; }
QLabel#h2 { color: %s; font-size: 16px; font-weight: 600; }
QLabel#body { color: %s; font-size: 13px; }
QLabel#warn {
  background: rgba(255,180,74,0.12); color: %s; border: 1px solid %s;
  border-radius: 12px; padding: 14px;
}
QProgressBar {
  background: %s; border: 1px solid %s; border-radius: 8px; height: 16px; text-align: center; color: %s;
}
QProgressBar::chunk { background: %s; border-radius: 7px; }
QLineEdit, QSpinBox, QComboBox {
  background: %s; color: %s; border: 1px solid %s; border-radius: 8px; padding: 8px 10px;
}
QListWidget, QScrollArea { background: transparent; border: none; }
QListWidget::item {
  background: %s; border: 1px solid %s; border-radius: 12px; margin: 6px; padding: 12px; color: %s;
}
QListWidget::item:selected { border-color: %s; background: rgba(0,210,255,0.12); }
QStatusBar { background: %s; color: %s; }
""" % (
    BG, TXT, PANEL, ACC, MUT, BORDER, PANEL, MUT, CARD2, TXT, ACC,
    CARD, TXT, BORDER, ACC, ACC, MUT, ACC, DANGER, DANGER,
    CARD, BORDER, TXT, TXT, MUT, WARN, WARN,
    CARD2, BORDER, TXT, ACC,
    CARD2, TXT, BORDER,
    CARD, BORDER, TXT, ACC,
    PANEL, DIM,
)
