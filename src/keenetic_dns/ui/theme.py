"""Темы (тёмная / светлая / как в Windows) в стиле Termius / Windows 11 (Fluent)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

DARK = {  # KeenRoute 2.0: графит + сдержанный индиго
    "bg": "#0f1013",        # рабочая область
    "side": "#121318",      # боковая навигация
    "card": "#16181d",      # панели и карточки
    "card2": "#23272f",     # hover / выбранное
    "border": "#2a2e37",
    "text": "#e8e9ed",
    "muted": "#9398a5",
    "accent": "#6558db",
    "accent2": "#5547c9",
    "accentText": "#a99cff",  # акцент для текста и индикаторов на тёмном
    "ok": "#46c35a",
    "bad": "#f0706a",
    "warn": "#d9a23a",
}
LIGHT = {
    "bg": "#f7f8fa", "side": "#f1f2f5", "card": "#ffffff", "card2": "#e9ebf0", "border": "#e3e5eb",
    "text": "#16181d", "muted": "#5d6370", "accent": "#6558db", "accent2": "#5547c9", "accentText": "#5446c9",
    "ok": "#1a7f37", "bad": "#c42330", "warn": "#8a5a00",
}
C = dict(DARK)  # текущая палитра (меняется при смене темы)


def windows_is_light() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
    except OSError:
        return False


def is_dark() -> bool:
    return C["bg"] == DARK["bg"]


CHECK_PNG = ""


def _make_check_png() -> str:
    """Белая птичка для отмеченных галочек (QSS берёт картинку только из файла)."""
    import tempfile

    from .icons import icon
    path = Path(tempfile.gettempdir()) / "keenroute_check.png"
    try:
        icon("check", "#ffffff", 16).pixmap(16, 16).save(str(path))
        return path.as_posix()
    except Exception:  # noqa: BLE001
        return ""


def _qss(C) -> str:
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {C['text']}; }}
QMainWindow, QDialog, QWidget#central, QStackedWidget#pages, QWidget#page {{ background: {C['bg']}; }}
QWidget#topbar {{ background: {C['bg']}; border-bottom: 1px solid {C['border']}; }}
QLabel#crumb {{ color: {C['muted']}; }}
QLabel#crumbNow {{ font-weight: 600; }}
QLabel#pill {{ color: {C['ok']}; background: transparent; border: 1px solid {C['ok']}; border-radius: 9px;
              padding: 1px 8px; font-size: 8pt; font-weight: 600; }}
QLabel#statValue {{ font-size: 20pt; font-weight: 650; }}
QLabel#statNote {{ color: {C['muted']}; font-size: 9pt; }}
QLabel#badgeAdd {{ color: {C['ok']}; border: 1px solid {C['ok']}; border-radius: 6px; padding: 2px 8px; font-weight: 600; font-size: 9pt; }}
QLabel#badgeMod {{ color: {C['warn']}; border: 1px solid {C['warn']}; border-radius: 6px; padding: 2px 8px; font-weight: 600; font-size: 9pt; }}
QLabel#badgeDel {{ color: {C['bad']}; border: 1px solid {C['bad']}; border-radius: 6px; padding: 2px 8px; font-weight: 600; font-size: 9pt; }}
QLabel#badge {{ color: {C['muted']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 2px 8px; font-weight: 600; font-size: 9pt; }}
QFrame#row {{ background: transparent; border: none; border-bottom: 1px solid {C['border']}; }}
QPushButton#navitem {{
    background: transparent; border: none; border-radius: 8px; text-align: left; padding: 8px 10px;
    icon-size: 17px; color: {C['muted']}; font-weight: 500;
}}
QPushButton#navitem:hover {{ background: {C['card']}; color: {C['text']}; }}
QPushButton#navitem:checked {{ background: {C['card2']}; color: {C['text']}; }}
QPushButton#routercard {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 10px;
                         text-align: left; padding: 9px 10px; icon-size: 18px; }}
QPushButton#routercard:hover {{ border: 1px solid {C['accent']}; }}
QListWidget#chips {{ background: transparent; border: none; }}
QListWidget#chips::item {{ border: 1px solid {C['border']}; border-radius: 8px; padding: 6px 12px; margin: 0 8px 6px 0;
                          background: {C['card']}; }}
QListWidget#chips::item:hover {{ border: 1px solid {C['muted']}; }}
QListWidget#chips::item:selected {{ background: {C['card2']}; border: 1px solid {C['accentText']}; color: {C['text']}; }}
QWidget#sidebar {{ background: {C['side']}; border-right: 1px solid {C['border']}; }}
QLabel#title {{ font-size: 16pt; font-weight: 600; }}
QLabel#brand {{ font-size: 13pt; font-weight: 700; }}
QFrame#footer {{ border-top: 1px solid {C['border']}; }}
QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted, QLabel#caption {{ color: {C['muted']}; }}
QLabel#caption {{ font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; }}
QFrame#card {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 12px; }}
QFrame#actionbar {{ background: {C['card2']}; border: 1px solid {C['border']}; border-radius: 12px; }}
QWidget#detail {{ background: {C['card']}; border-left: 1px solid {C['border']}; }}

QPushButton {{
    background: {C['card']}; border: 1px solid {C['border']}; border-radius: 8px;
    padding: 7px 14px; min-height: 20px; icon-size: 16px;
}}
QPushButton:hover {{ background: {C['card2']}; }}
QPushButton:pressed {{ background: {C['border']}; }}
QPushButton:disabled {{ color: {C['muted']}; }}
QPushButton#primary {{ background: {C['accent']}; border: 1px solid {C['accent']}; color: white; font-weight: 600; }}
QPushButton#strong {{ background: {C['text']}; border: 1px solid {C['text']}; color: {C['bg']}; font-weight: 600; }}
QPushButton#link {{ background: transparent; border: none; color: {C['accentText']}; font-weight: 600; padding: 4px 6px; }}
QPushButton#primary:hover {{ background: {C['accent2']}; }}
QPushButton#danger {{ color: {C['bad']}; }}
QPushButton#icon {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 0; font-size: 12pt; }}
QPushButton#icon:hover {{ background: {C['card']}; border: 1px solid {C['border']}; }}
QPushButton#chip {{ background: transparent; border: 1px solid {C['border']}; border-radius: 15px; padding: 0 12px;
                    color: {C['muted']}; font-weight: 600; }}
QPushButton#chip:hover {{ border: 1px solid {C['accent']}; color: {C['text']}; }}
QPushButton#chip:disabled {{ color: {C['border']}; border: 1px dashed {C['border']}; }}
QPushButton#chip:checked {{ background: {C['accent']}; border: 1px solid {C['accent']}; color: white; }}
QPushButton#nav {{
    background: transparent; border: none; border-radius: 8px; text-align: left; padding: 9px 12px; icon-size: 18px;
}}
QPushButton#nav:hover {{ background: {C['card']}; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
    background: {C['card']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 7px 9px;
    selection-background-color: {C['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-bottom: 2px solid {C['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {C['card']}; border: 1px solid {C['border']}; selection-background-color: {C['accent']}; outline: 0;
}}

QTableWidget {{
    background: {C['card']}; border: 1px solid {C['border']}; border-radius: 12px; gridline-color: transparent; outline: 0;
    alternate-background-color: {C['card']};
}}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {C['border']}; }}
QTreeWidget {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 10px; padding: 6px; outline: 0; }}
QTreeWidget::item {{ padding: 5px 4px; border-radius: 6px; }}
QTreeWidget::item:hover {{ background: {C['card2']}; }}
QTreeWidget::item:selected {{ background: {C['card2']}; color: {C['text']}; }}
QStatusBar QLabel {{ color: {C['muted']}; }}
QTableWidget::item:selected {{ background: {C['card2']}; color: {C['text']}; border-bottom: 1px solid {C['border']}; }}
QTableWidget::item:hover {{ background: {C['card']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {C['card']}; color: {C['muted']}; border: none; border-bottom: 1px solid {C['border']};
    padding: 9px 8px; font-size: 9pt; font-weight: 500;
}}

QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; margin: 1px 0; }}
QListWidget::item:hover {{ background: {C['card']}; }}
QListWidget::item:selected {{ background: {C['card2']}; color: {C['text']}; border-left: 3px solid {C['accent']}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QTableWidget::indicator, QListWidget::indicator, QTreeWidget::indicator {{
    width: 16px; height: 16px; border-radius: 4px; border: 1px solid {C['muted']}; background: transparent;
}}
QCheckBox::indicator:checked, QTableWidget::indicator:checked, QListWidget::indicator:checked,
QTreeWidget::indicator:checked {{ image: url({CHECK_PNG});
    background: {C['accent']}; border: 1px solid {C['accent']};
}}
QTreeWidget::indicator:indeterminate {{ background: {C['muted']}; border: 1px solid {C['muted']}; }}
QCheckBox::indicator:hover, QTableWidget::indicator:hover, QListWidget::indicator:hover, QTreeWidget::indicator:hover {{ border: 1px solid {C['accent']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 0; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {C['border']}; }}
QTabWidget#pages::tab-bar {{ left: 18px; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {C['muted']}; padding: 7px 16px; margin: 12px 6px 10px 0;
               border: 1px solid transparent; border-radius: 9px; font-weight: 600; }}
QTabBar::tab:hover {{ color: {C['text']}; background: {C['card']}; }}
QTabBar::tab:selected {{ color: {C['text']}; background: {C['card2']}; border: 1px solid {C['border']};
                        border-bottom: 2px solid {C['accent']}; }}
QSplitter::handle {{ background: {C['border']}; width: 1px; }}
QStatusBar {{ background: {C['side']}; color: {C['muted']}; border-top: 1px solid {C['border']}; }}
QToolTip {{ background: {C['card']}; color: {C['text']}; border: 1px solid {C['border']}; padding: 4px; }}
QMessageBox, QInputDialog {{ background: {C['bg']}; }}
QProgressBar {{ background: {C['card2']}; border: 1px solid {C['border']}; border-radius: 6px; height: 18px;
    text-align: center; color: {C['text']}; font-weight: 600; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 5px; }}
"""


def asset(name: str) -> str:
    """Путь к файлу из assets/ (работает и из исходников, и внутри exe PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return str(base / "assets" / name)


def app_icon() -> QIcon:
    return QIcon(asset("icon.png"))


def apply(app: QApplication, mode: str = "auto") -> None:
    """mode: auto | dark | light"""
    light = windows_is_light() if mode == "auto" else mode == "light"
    C.clear()
    C.update(LIGHT if light else DARK)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in [(QPalette.Window, "bg"), (QPalette.Base, "card"), (QPalette.AlternateBase, "bg"),
                      (QPalette.Button, "card"), (QPalette.Text, "text"), (QPalette.WindowText, "text"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"), (QPalette.ToolTipBase, "card"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "muted")]:
        pal.setColor(role, QColor(C[key]))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    app.setPalette(pal)
    f = QFont("Segoe UI Variable Text")
    f.setPointSize(10)
    app.setFont(f)
    global CHECK_PNG
    if not CHECK_PNG:
        CHECK_PNG = _make_check_png()
    app.setStyleSheet(_qss(C))


def dark_titlebar(widget) -> None:
    """Заголовок окна в цвет темы на Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        val = ctypes.c_int(1 if is_dark() else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
        # Mica-фон на Windows 11 (игнорируется на 10)
        backdrop = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), 4)
    except Exception:  # noqa: BLE001
        pass
