"""Small custom widgets: status pill, signal meter, caption log."""

from __future__ import annotations

import collections
import time

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..engine import Caption, Skipped
from . import theme


class StatusPill(QWidget):
    """Coloured dot plus a short state, e.g. 'Listening'."""

    COLORS = {
        "idle": theme.MUTED,
        "busy": theme.CT_BLUE,
        "live": theme.OK,
        "speech": theme.T_GOLD,
        "error": theme.DANGER,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._text = "Not listening"
        self.setFont(theme.hud_font(15, QFont.Weight.DemiBold))
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    @property
    def state(self) -> str:
        return self._state

    def set(self, state: str, text: str) -> None:
        self._state, self._text = state, text
        self.setToolTip(text)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        w = self.fontMetrics().horizontalAdvance(self._text)
        return QSize(min(w, 420) + 52, 30)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, QColor(theme.PANEL))
        p.setPen(QColor(theme.LINE))
        p.drawPath(path)
        color = QColor(self.COLORS.get(self._state, theme.MUTED))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(13, r.center().y() - 4, 8, 8))
        p.setPen(QColor(theme.TEXT))
        p.setFont(self.font())
        text_rect = self.rect().adjusted(29, 0, -12, 0)
        text = self.fontMetrics().elidedText(self._text, Qt.TextElideMode.ElideRight, text_rect.width())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class SignalMeter(QWidget):
    """Scrolling bar history of the captured audio. Bars turn gold while the
    voice detector hears speech, like the in-game voice indicator."""

    HISTORY = 160

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars: collections.deque[tuple[float, bool]] = collections.deque(maxlen=self.HISTORY)
        self._source = ""
        self._active = False
        self.setFixedHeight(44)

    def set_source(self, text: str) -> None:
        self._source = text
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active:
            self._bars.clear()
        self.update()

    def push(self, level_db: float, speech: bool) -> None:
        # Map -60..0 dBFS to 0..1.
        v = max(0.0, min(1.0, (level_db + 60.0) / 60.0))
        self._bars.append((v, speech))
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(theme.PANEL))
        p.setPen(QColor(theme.LINE))
        p.drawLine(r.bottomLeft(), r.bottomRight())

        label = self._source if self._active else "No audio yet. Start listening to see the signal."
        p.setFont(theme.ui_font(12))
        fm = p.fontMetrics()
        label_w = min(fm.horizontalAdvance(label) + 24, r.width() // 2)
        bars_rect = r.adjusted(16, 8, -label_w - 8, -8)

        bar_w = 3
        step = 5
        count = max(1, bars_rect.width() // step)
        bars = list(self._bars)[-count:]
        x = bars_rect.right() - len(bars) * step
        mid = bars_rect.center().y()
        muted = QColor(theme.MUTED)
        muted.setAlpha(150)
        gold = QColor(theme.T_GOLD)
        p.setPen(Qt.PenStyle.NoPen)
        for v, speech in bars:
            h = max(2.0, v * bars_rect.height())
            p.setBrush(gold if speech else muted)
            p.drawRoundedRect(QRectF(x, mid - h / 2, bar_w, h), 1.5, 1.5)
            x += step
        if not bars:
            line = QColor(theme.LINE)
            p.setBrush(line)
            p.drawRect(QRectF(bars_rect.left(), mid - 1, bars_rect.width(), 2))

        p.setPen(QColor(theme.MUTED))
        text = fm.elidedText(label, Qt.TextElideMode.ElideLeft, label_w - 16)
        p.drawText(r.adjusted(0, 0, -16, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)


class _Entry(QFrame):
    def __init__(self, caption: Caption, script: str = "native", parent=None):
        super().__init__(parent)
        self.setObjectName("entry")
        self.setStyleSheet(f"QFrame#entry {{ border-bottom: 1px solid {theme.LINE}; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 10, 4, 10)
        row.setSpacing(12)

        meta = QVBoxLayout()
        meta.setSpacing(2)
        when = QLabel(time.strftime("%H:%M:%S", time.localtime(caption.created)))
        when.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        tag = QLabel(caption.language.upper())
        tag.setFont(theme.hud_font(15, QFont.Weight.Bold))
        tag.setStyleSheet(f"color: {theme.T_GOLD};")
        meta.addWidget(tag)
        meta.addWidget(when)
        meta.addStretch(1)
        holder = QWidget()
        holder.setLayout(meta)
        holder.setFixedWidth(64)
        row.addWidget(holder)

        texts = QVBoxLayout()
        texts.setSpacing(3)
        english = QLabel(caption.text)
        english.setWordWrap(True)
        english.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        english.setStyleSheet("font-size: 16px;")
        texts.addWidget(english)
        if caption.original:
            original = QLabel("\n".join(caption.original_lines(script)))
            original.setWordWrap(True)
            original.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            original.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
            texts.addWidget(original)
        row.addLayout(texts, 1)


class _SkippedEntry(QFrame):
    def __init__(self, item: Skipped, parent=None):
        super().__init__(parent)
        self.setObjectName("entry")
        self.setStyleSheet(f"QFrame#entry {{ border-bottom: 1px solid {theme.LINE}; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 6, 4, 6)
        row.setSpacing(12)
        when = QLabel(time.strftime("%H:%M:%S", time.localtime(item.created)))
        when.setFixedWidth(64)
        when.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        row.addWidget(when)
        text = QLabel(f"Skipped: {item.reason}")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        row.addWidget(text, 1)


class CaptionLog(QScrollArea):
    """Newest-first list of everything that was translated this session.
    Kept in memory only."""

    MAX_ENTRIES = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("page")
        self._layout = QVBoxLayout(inner)
        self._layout.setContentsMargins(0, 0, 8, 0)
        self._layout.setSpacing(0)
        self._empty = QLabel(
            "Nothing translated yet.\n\nStart listening and join a match. When a teammate speaks one of "
            "your selected languages, the English translation appears here and on the overlay."
        )
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._empty.setStyleSheet(f"color: {theme.MUTED}; padding: 18px 4px; font-size: 14px;")
        self._layout.addWidget(self._empty)
        self._layout.addStretch(1)
        self.setWidget(inner)

    def add(self, caption: Caption | Skipped, script: str = "native") -> None:
        self._empty.hide()
        entry = _SkippedEntry(caption) if isinstance(caption, Skipped) else _Entry(caption, script)
        self._layout.insertWidget(0, entry)
        # layout = entries + empty label + stretch
        while self._layout.count() - 2 > self.MAX_ENTRIES:
            item = self._layout.takeAt(self._layout.count() - 3)
            if item and item.widget():
                item.widget().deleteLater()
        self.verticalScrollBar().setValue(0)

    def clear(self) -> None:
        # Entries always sit before the empty-state label and the stretch.
        while self._layout.count() > 2:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._empty.show()
