"""Мелкие виджеты: тост, список шлюзов с drop, подсветка доменов."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QListWidget, QPushButton,
                               QWidget)

from ..core.model import normalize_entry
from .theme import C as COL


class Toast(QFrame):
    """Уведомление в правом нижнем углу окна; исчезает само, может иметь кнопку действия («Отменить»)."""

    def __init__(self, parent: QWidget, text: str, action: str | None = None, on_action=None, ms: int = 6000,
                 kind: str = "ok"):
        super().__init__(parent)
        self.setObjectName("card")
        color = {"ok": COL["ok"], "bad": COL["bad"], "info": COL["accent"]}.get(kind, COL["accent"])
        self.setStyleSheet(f"QFrame#card {{ border: 1px solid {color}; border-left: 5px solid {color}; border-radius: 12px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 12, 14)
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setMaximumWidth(520)
        f = lb.font()
        f.setPointSizeF(f.pointSizeF() + 1)
        lb.setFont(f)
        lay.addWidget(lb, 1)
        if action and on_action:
            b = QPushButton(action)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda: (self.close(), on_action()))
            lay.addWidget(b)
        x = QPushButton("✕")
        x.setFixedWidth(32)
        x.clicked.connect(self.close)
        lay.addWidget(x)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        self._anim = QPropertyAnimation(eff, b"opacity", self)
        self._anim.setDuration(220)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()
        QTimer.singleShot(ms, self.close)
        parent.installEventFilter(self)

    def _place(self):
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, max(70, (p.height() - self.height()) // 3))

    def eventFilter(self, obj, ev):
        if ev.type() == ev.Type.Resize:
            self._place()
        return False


class GatewayList(QListWidget):
    """Список шлюзов слева: сюда можно перетащить строки таблицы — списки переедут на этот шлюз."""
    dropped = Signal(str)  # ключ шлюза

    def __init__(self, source):
        super().__init__()
        self._source = source
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def _key_at(self, pos):
        it = self.itemAt(pos)
        return it.data(Qt.UserRole) if it else None

    def dragEnterEvent(self, e):
        if e.source() is self._source:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        key = self._key_at(e.position().toPoint())
        if e.source() is self._source and key and not key.startswith("__all"):
            self.setCurrentItem(self.itemAt(e.position().toPoint()))
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        key = self._key_at(e.position().toPoint())
        if e.source() is self._source and key:
            e.acceptProposedAction()
            self.dropped.emit(key)
        else:
            e.ignore()


class DomainHighlighter(QSyntaxHighlighter):
    """Красным — строки, которые не являются доменом/IP; жёлтым — дубли."""

    def highlightBlock(self, text):
        t = text.strip()
        if not t or t.startswith("#"):
            return
        fmt = QTextCharFormat()
        if not normalize_entry(t):
            fmt.setForeground(QColor(COL["bad"]))
            fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            fmt.setUnderlineColor(QColor(COL["bad"]))
            self.setFormat(0, len(text), fmt)
            return
        doc = self.document()
        n = normalize_entry(t)
        blk = doc.firstBlock()
        while blk.isValid() and blk != self.currentBlock():
            if normalize_entry(blk.text().strip() or "-") == n:
                fmt.setForeground(QColor(COL["warn"]))
                self.setFormat(0, len(text), fmt)
                return
            blk = blk.next()
