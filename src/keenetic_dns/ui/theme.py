"""Темы (тёмная / светлая / как в Windows) в стиле Termius / Windows 11 (Fluent)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

DARK = {
    "bg": "#1b1d23",        # основной фон
    "side": "#15171c",      # сайдбар
    "card": "#23262e",      # карточки
    "card2": "#2a2e37",     # hover
    "border": "#2f333d",
    "text": "#e6e8ee",
    "muted": "#8b92a1",
    "accent": "#4c8dff",
    "accent2": "#3a78ea",
    "ok": "#3fb950",
    "bad": "#f85149",
    "warn": "#d29922",
}
LIGHT = {
    "bg": "#f7f8fa", "side": "#eef0f4", "card": "#ffffff", "card2": "#e8ecf3", "border": "#d8dce4",
    "text": "#1f2329", "muted": "#6b7280", "accent": "#2f6fed", "accent2": "#255fd1",
    "ok": "#1a7f37", "bad": "#cf222e", "warn": "#9a6700",
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


def _qss(C) -> str:
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; color: {C['text']}; }}
QMainWindow, QDialog, QWidget#central {{ background: {C['bg']}; }}
QWidget#sidebar {{ background: {C['side']}; border-right: 1px solid {C['border']}; }}
QLabel#title {{ font-size: 15pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted, QLabel#caption {{ color: {C['muted']}; }}
QLabel#caption {{ font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; }}
QFrame#card {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QFrame#actionbar {{ background: {C['card']}; border: 1px solid {C['accent']}; border-radius: 10px; }}

QPushButton {{
    background: {C['card']}; border: 1px solid {C['border']}; border-radius: 6px;
    padding: 6px 14px; min-height: 20px;
}}
QPushButton:hover {{ background: {C['card2']}; }}
QPushButton:pressed {{ background: {C['border']}; }}
QPushButton:disabled {{ color: {C['muted']}; }}
QPushButton#primary {{ background: {C['accent']}; border: 1px solid {C['accent']}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {C['accent2']}; }}
QPushButton#danger {{ color: {C['bad']}; }}
QPushButton#icon {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 0; font-size: 12pt; }}
QPushButton#icon:hover {{ background: {C['card']}; border: 1px solid {C['border']}; }}
QPushButton#nav {{
    background: transparent; border: none; border-radius: 6px; text-align: left; padding: 8px 12px;
}}
QPushButton#nav:hover {{ background: {C['card']}; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
    background: {C['card']}; border: 1px solid {C['border']}; border-radius: 6px; padding: 6px 8px;
    selection-background-color: {C['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-bottom: 2px solid {C['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {C['card']}; border: 1px solid {C['border']}; selection-background-color: {C['accent']}; outline: 0;
}}

QTableWidget {{
    background: {C['bg']}; border: none; gridline-color: transparent; outline: 0;
    alternate-background-color: {C['bg']};
}}
QTableWidget::item {{ padding: 6px; border-bottom: 1px solid {C['border']}; }}
QTableWidget::item:selected {{ background: {C['card2']}; color: {C['text']}; }}
QTableWidget::item:hover {{ background: {C['card']}; }}
QHeaderView::section {{
    background: {C['bg']}; color: {C['muted']}; border: none; border-bottom: 1px solid {C['border']};
    padding: 8px 6px; font-size: 8.5pt; font-weight: 600;
}}

QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; margin: 1px 0; }}
QListWidget::item:hover {{ background: {C['card']}; }}
QListWidget::item:selected {{ background: {C['card2']}; color: {C['text']}; border-left: 3px solid {C['accent']}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QTableWidget::indicator {{
    width: 16px; height: 16px; border-radius: 4px; border: 1px solid {C['muted']}; background: transparent;
}}
QCheckBox::indicator:checked, QTableWidget::indicator:checked {{
    background: {C['accent']}; border: 1px solid {C['accent']};
}}
QCheckBox::indicator:hover, QTableWidget::indicator:hover {{ border: 1px solid {C['accent']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 0; }}

QSplitter::handle {{ background: {C['border']}; width: 1px; }}
QStatusBar {{ background: {C['side']}; color: {C['muted']}; border-top: 1px solid {C['border']}; }}
QToolTip {{ background: {C['card']}; color: {C['text']}; border: 1px solid {C['border']}; padding: 4px; }}
QMessageBox, QInputDialog {{ background: {C['bg']}; }}
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
