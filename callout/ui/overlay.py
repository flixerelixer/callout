"""The caption overlay: a transparent, click-through, always-on-top window.

It is a separate window (no injection into the game), so it is safe with
VAC and other anti-cheats. It only shows over the game when CS2 runs in
"Fullscreen Windowed" mode; exclusive fullscreen draws over everything.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..config import Settings
from ..engine import Caption
from . import theme

FADE_S = 0.6
PAD_X = 12
PAD_Y = 7
GAP = 6


@dataclass
class _Shown:
    caption: Caption
    expires: float


class Overlay(QWidget):
    moved = Signal(int, int, int)  # x, y, width

    def __init__(self, settings: Settings):
        super().__init__(None)
        self.settings = settings
        self._items: list[_Shown] = []
        self._edit = False
        self._drag_from: QPoint | None = None
        self.setWindowTitle("Callout overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._apply_flags()

        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._on_tick)
        # Some games push themselves to the top; re-assert every few seconds.
        self._topmost = QTimer(self)
        self._topmost.setInterval(2000)
        self._topmost.timeout.connect(self._raise_topmost)
        self._topmost.start()
        self.apply_settings()

    # ------------------------------------------------------------------ layout
    def _flags(self) -> Qt.WindowType:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        if not self._edit:
            flags |= Qt.WindowType.WindowTransparentForInput
        return flags

    def _apply_flags(self) -> None:
        visible = self.isVisible()
        self.setWindowFlags(self._flags())
        if visible:
            self.show()

    def _line_heights(self) -> tuple[int, int]:
        main = QFontMetrics(theme.hud_font(self.settings.font_size)).lineSpacing()
        sub = QFontMetrics(theme.ui_font(self._sub_size())).lineSpacing()
        return main, sub

    def _sub_size(self) -> int:
        return max(11, round(self.settings.font_size * 0.72))

    def _box_height(self) -> int:
        main, sub = self._line_heights()
        sub_lines = 0
        if self.settings.show_original:
            sub_lines = 2 if self.settings.original_script == "both" else 1
        per = main * 2 + sub * sub_lines + PAD_Y * 2 + GAP
        return per * max(1, self.settings.max_lines) + 8

    def apply_settings(self) -> None:
        s = self.settings
        width = max(280, s.overlay_width)
        height = self._box_height()
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        if s.overlay_x < 0 or s.overlay_y < 0:
            # Default: centred, a bit below the middle, above the bottom HUD.
            x = geo.x() + (geo.width() - width) // 2
            y = geo.y() + int(geo.height() * 0.80) - height
        else:
            x, y = s.overlay_x, s.overlay_y
        self.setGeometry(x, y, width, height)
        self.update()

    def _alignment(self) -> Qt.AlignmentFlag:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return Qt.AlignmentFlag.AlignHCenter
        geo = screen.geometry()
        centre = (self.geometry().center().x() - geo.x()) / max(1, geo.width())
        if centre < 0.36:
            return Qt.AlignmentFlag.AlignLeft
        if centre > 0.64:
            return Qt.AlignmentFlag.AlignRight
        return Qt.AlignmentFlag.AlignHCenter

    # ------------------------------------------------------------------ captions
    def add_caption(self, caption: Caption) -> None:
        if not self.settings.overlay_enabled:
            return
        self._items.append(_Shown(caption, time.monotonic() + self.settings.display_seconds))
        self._items = self._items[-max(1, self.settings.max_lines):]
        if not self.isVisible():
            self.show()
        self._raise_topmost()
        self._tick.start()
        self.update()

    def clear(self) -> None:
        self._items.clear()
        if not self._edit:
            self.hide()

    def _on_tick(self) -> None:
        now = time.monotonic()
        self._items = [i for i in self._items if i.expires > now]
        if not self._items:
            self._tick.stop()
            if not self._edit:
                self.hide()
        self.update()

    # ------------------------------------------------------------------ edit mode
    def set_edit_mode(self, on: bool) -> None:
        self._edit = on
        self._apply_flags()
        if on:
            self.show()
            self.raise_()
        elif not self._items:
            self.hide()
        self.update()

    @property
    def edit_mode(self) -> bool:
        return self._edit

    def mousePressEvent(self, event):  # noqa: N802
        if self._edit and event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._edit and self._drag_from is not None:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._edit and self._drag_from is not None:
            self._drag_from = None
            self.moved.emit(self.x(), self.y(), self.width())

    def wheelEvent(self, event):  # noqa: N802
        if not self._edit:
            return
        step = 40 if event.angleDelta().y() > 0 else -40
        width = min(1600, max(280, self.width() + step))
        centre = self.geometry().center().x()
        self.setGeometry(centre - width // 2, self.y(), width, self.height())
        self.moved.emit(self.x(), self.y(), self.width())
        self.update()

    # ------------------------------------------------------------------ painting
    def _sample_items(self) -> list[_Shown]:
        far = time.monotonic() + 3600
        return [
            _Shown(Caption("ru", "Two on B, one is low. I'm rotating.", "Двое на Б, один лоу. Я ротейчусь.",
                           original_latin="Dvoe na B, odin lou. Ya roteychus."), far),
            _Shown(Caption("pl", "Save your rifle, we buy next round.", "Sejwuj karabin, kupujemy w następnej."), far),
        ]

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = self.rect()

        if self._edit:
            p.fillRect(rect, QColor(24, 27, 33, 110))
            pen = QPen(QColor(theme.CT_BLUE), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), 8, 8)
            p.setFont(theme.ui_font(13))
            p.setPen(QColor(theme.TEXT))
            p.drawText(rect.adjusted(12, 10, -12, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
                       "Drag to move. Scroll to change the width. Press Done in Callout when you're finished.")

        items = self._items if self._items else (self._sample_items() if self._edit else [])
        if not items:
            return

        s = self.settings
        now = time.monotonic()
        align = self._alignment()
        main_font = theme.hud_font(s.font_size)
        sub_font = theme.ui_font(self._sub_size())
        tag_font = theme.hud_font(max(11, round(s.font_size * 0.62)), QFont.Weight.Bold)
        fm_main, fm_sub, fm_tag = QFontMetrics(main_font), QFontMetrics(sub_font), QFontMetrics(tag_font)
        max_text_w = rect.width() - PAD_X * 2 - 8

        y = rect.bottom() - 4
        for item in reversed(items):
            c = item.caption
            alpha = 1.0 if self._edit else max(0.0, min(1.0, (item.expires - now) / FADE_S))
            tag = c.language.upper() if s.show_language_tag else ""
            tag_w = fm_tag.horizontalAdvance(tag) + 10 if tag else 0
            text_w = max_text_w - tag_w
            flags = int(Qt.TextFlag.TextWordWrap)
            main_br = fm_main.boundingRect(QRect(0, 0, text_w, 10000), flags, c.text)
            sub_br = QRect()
            sub_text = "\n".join(c.original_lines(s.original_script)) if s.show_original else ""
            if sub_text:
                sub_br = fm_sub.boundingRect(QRect(0, 0, text_w, 10000), flags, sub_text)
            content_w = max(main_br.width(), sub_br.width()) + tag_w
            content_h = main_br.height() + (sub_br.height() + 2 if sub_br.height() else 0)
            box_w = min(rect.width() - 8, content_w + PAD_X * 2)
            box_h = content_h + PAD_Y * 2
            if align == Qt.AlignmentFlag.AlignLeft:
                bx = rect.left() + 4
            elif align == Qt.AlignmentFlag.AlignRight:
                bx = rect.right() - 4 - box_w
            else:
                bx = rect.left() + (rect.width() - box_w) // 2
            by = y - box_h
            if by < rect.top():
                break
            box = QRectF(bx, by, box_w, box_h)

            bg = QColor(12, 14, 18)
            bg.setAlphaF(max(0.0, min(1.0, s.background_opacity)) * alpha)
            path = QPainterPath()
            path.addRoundedRect(box, 6, 6)
            p.fillPath(path, bg)

            tx = bx + PAD_X
            ty = by + PAD_Y
            if tag:
                gold = QColor(theme.T_GOLD)
                gold.setAlphaF(alpha)
                p.setFont(tag_font)
                p.setPen(gold)
                tag_rect = QRect(int(tx), int(ty), tag_w, fm_main.height())
                p.drawText(tag_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tag)
                tx += tag_w
            self._shadow_text(p, main_font, QRect(int(tx), int(ty), text_w, main_br.height()),
                              c.text, QColor(theme.TEXT), alpha)
            if sub_br.height():
                muted = QColor("#B4BBC7")
                self._shadow_text(p, sub_font, QRect(int(tx), int(ty + main_br.height() + 2), text_w, sub_br.height()),
                                  sub_text, muted, alpha)
            y = by - GAP
        p.end()

    @staticmethod
    def _shadow_text(p: QPainter, font, rect: QRect, text: str, color: QColor, alpha: float) -> None:
        flags = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignTop)
        p.setFont(font)
        shadow = QColor(0, 0, 0)
        shadow.setAlphaF(0.85 * alpha)
        p.setPen(shadow)
        p.drawText(rect.translated(1, 1), flags, text)
        color = QColor(color)
        color.setAlphaF(alpha)
        p.setPen(color)
        p.drawText(rect, flags, text)

    # ------------------------------------------------------------------ Windows
    def _raise_topmost(self) -> None:
        if sys.platform != "win32" or not self.isVisible():
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            # HWND_TOPMOST, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0200)
        except Exception:  # noqa: BLE001
            pass
