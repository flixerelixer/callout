"""Colours, fonts and the Qt stylesheet.

The palette borrows Counter-Strike's own team colours: CT blue for anything
you can click, T gold for live speech.
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QFont, QFontDatabase

from ..paths import resource_path

log = logging.getLogger(__name__)

BASE = "#181B21"
PANEL = "#20242C"
RAISED = "#272C36"
LINE = "#2C323D"
TEXT = "#E6E8EC"
MUTED = "#8B94A3"
CT_BLUE = "#6E8FD0"
CT_BLUE_HOVER = "#83A1DB"
T_GOLD = "#E3A33B"
DANGER = "#D9604C"
OK = "#5FB37A"

UI_FAMILY = "Barlow"
HUD_FAMILY = "Barlow Semi Condensed"

_FONTS = [
    "Barlow-Regular.ttf",
    "Barlow-Medium.ttf",
    "Barlow-SemiBold.ttf",
    "BarlowSemiCondensed-Medium.ttf",
    "BarlowSemiCondensed-SemiBold.ttf",
    "BarlowSemiCondensed-Bold.ttf",
]


def load_fonts() -> None:
    for name in _FONTS:
        path = resource_path("assets", "fonts", name)
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            log.warning("Could not load font %s", path)


def hud_font(size_px: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    f = QFont(HUD_FAMILY)
    f.setPixelSize(size_px)
    f.setWeight(weight)
    return f


def ui_font(size_px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(UI_FAMILY)
    f.setPixelSize(size_px)
    f.setWeight(weight)
    return f


STYLESHEET = f"""
* {{
    font-family: "{UI_FAMILY}", "Segoe UI", sans-serif;
    font-size: 14px;
    color: {TEXT};
}}
QMainWindow, QWidget#root {{ background: {BASE}; }}
QWidget#page {{ background: {BASE}; }}
QLabel#muted, QLabel.muted {{ color: {MUTED}; }}
QLabel#pageTitle {{
    font-family: "{HUD_FAMILY}";
    font-size: 22px;
    font-weight: 600;
}}
QLabel#sectionTitle {{
    font-family: "{HUD_FAMILY}";
    font-size: 16px;
    font-weight: 600;
    padding-top: 6px;
}}
QLabel#brand {{
    font-family: "{HUD_FAMILY}";
    font-size: 24px;
    font-weight: 700;
}}

/* Navigation */
QListWidget#nav {{
    background: {PANEL};
    border: none;
    border-right: 1px solid {LINE};
    padding: 10px 0;
    outline: none;
}}
QListWidget#nav::item {{
    padding: 9px 18px;
    border-left: 3px solid transparent;
    color: {MUTED};
}}
QListWidget#nav::item:hover {{ color: {TEXT}; }}
QListWidget#nav::item:selected {{
    background: {RAISED};
    color: {TEXT};
    border-left: 3px solid {CT_BLUE};
}}

/* Buttons */
QPushButton {{
    background: {RAISED};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {CT_BLUE}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {LINE}; }}
QPushButton:focus {{ border-color: {CT_BLUE}; }}
QPushButton#primary {{
    background: {CT_BLUE};
    border: 1px solid {CT_BLUE};
    color: #0F1420;
    font-family: "{HUD_FAMILY}";
    font-size: 16px;
    font-weight: 700;
    padding: 8px 22px;
}}
QPushButton#primary:hover {{ background: {CT_BLUE_HOVER}; border-color: {CT_BLUE_HOVER}; }}
QPushButton#primary[running="true"] {{
    background: transparent;
    color: {TEXT};
    border: 1px solid {MUTED};
}}
QPushButton#primary[running="true"]:hover {{ border-color: {DANGER}; color: {DANGER}; }}
QPushButton#link {{
    background: transparent;
    border: none;
    color: {CT_BLUE};
    padding: 2px 0;
    text-align: left;
}}
QPushButton#link:hover {{ color: {CT_BLUE_HOVER}; text-decoration: underline; }}

/* Inputs */
QComboBox, QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {PANEL};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {CT_BLUE};
    selection-color: #0F1420;
}}
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {CT_BLUE};
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url(CHEVRON); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {PANEL};
    border: 1px solid {LINE};
    selection-background-color: {RAISED};
    selection-color: {TEXT};
    outline: none;
}}
QCheckBox {{ spacing: 8px; padding: 3px 0; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {MUTED};
    border-radius: 4px;
    background: {PANEL};
}}
QCheckBox::indicator:hover {{ border-color: {CT_BLUE}; }}
QCheckBox::indicator:checked {{
    background: {CT_BLUE};
    border-color: {CT_BLUE};
    image: url(CHECKMARK);
}}
QCheckBox:focus {{ color: {TEXT}; }}
QSlider::groove:horizontal {{ height: 4px; background: {LINE}; border: none; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {CT_BLUE}; border-radius: 2px; }}
QSlider::add-page:horizontal {{ background: {LINE}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT};
    width: 14px; height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {CT_BLUE_HOVER}; }}
QSlider::handle:horizontal:focus {{ background: {CT_BLUE}; }}
QProgressBar {{
    background: {PANEL};
    border: 1px solid {LINE};
    border-radius: 5px;
    height: 10px;
    text-align: center;
    font-size: 11px;
}}
QProgressBar::chunk {{ background: {CT_BLUE}; border-radius: 4px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{
    background: {RAISED};
    color: {TEXT};
    border: 1px solid {LINE};
    padding: 5px;
}}
QMenu {{ background: {PANEL}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {RAISED}; }}
QMessageBox {{ background: {BASE}; }}
"""


def stylesheet() -> str:
    check = resource_path("assets", "check.svg").as_posix()
    chevron = resource_path("assets", "chevron.svg").as_posix()
    return STYLESHEET.replace("CHECKMARK", check).replace("CHEVRON", chevron)
