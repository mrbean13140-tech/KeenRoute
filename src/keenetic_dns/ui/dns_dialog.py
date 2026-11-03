"""Окно DNS: текущие серверы роутера + шаблоны провайдеров (обычный DNS / DoT / DoH)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from ..core import dns as D
from ..core.model import normalize_entry
from .theme import app_icon, dark_titlebar


class DnsDialog(QDialog):
    """После accept(): self.add, self.remove — списки Upstream."""

    def __init__(self, parent, current: list[D.Upstream], providers: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("DNS-серверы роутера")
        self.setWindowIcon(app_icon())
        self.resize(1000, 620)
        self.setMinimumSize(720, 460)
        self.current, self.providers = current, providers
        self.add: list[D.Upstream] = []
        self.remove: list[D.Upstream] = []
        self.boxes: list[tuple[dict, str, QCheckBox]] = []
        self._build()
        dark_titlebar(self)

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        root.addWidget(split)

        left = QWidget(objectName="sidebar")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 16, 14, 12)
        ll.setSpacing(8)
        ll.addWidget(QLabel("Сейчас на роутере", objectName="title"))
        ll.addWidget(QLabel("Снимите галочку, чтобы удалить сервер.", objectName="muted"))
        self.cur = QListWidget()
        for u in self.current:
            it = QListWidgetItem(u.label)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, u)
            it.setToolTip(u.cmd())
            self.cur.addItem(it)
        if not self.current:
            self.cur.addItem(QListWidgetItem("Свои DNS не заданы — используются DNS провайдера"))
        ll.addWidget(self.cur, 1)
        split.addWidget(left)

        right = QWidget(objectName="central")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(20, 16, 20, 14)
        rl.setSpacing(10)
        rl.addWidget(QLabel("Добавить из шаблонов", objectName="title"))
        rl.addWidget(QLabel("DoT и DoH шифруют DNS-запросы — провайдер их не видит и не подменяет. "
                            "Обычный DNS — без шифрования.", objectName="muted", wordWrap=True))
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        il.setSpacing(8)
        for p in self.providers:
            card = QFrame(objectName="card")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            tl = QVBoxLayout()
            tl.setSpacing(0)
            tl.addWidget(QLabel(p["title"], objectName="h2"))
            tl.addWidget(QLabel(p.get("note", ""), objectName="muted"))
            cl.addLayout(tl, 1)
            for kind, text, tip in [("plain", "DNS", ", ".join(p["plain"][:2])),
                                    ("dot", "DoT", f"{p['dot']['ip']} · {p['dot']['sni']}"),
                                    ("doh", "DoH", p["doh"])]:
                cb = QCheckBox(text)
                cb.setToolTip(tip)
                cb.setCursor(Qt.PointingHandCursor)
                cl.addWidget(cb)
                self.boxes.append((p, kind, cb))
            il.addWidget(card)
        il.addStretch(1)
        area.setWidget(inner)
        rl.addWidget(area, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Только для доменов:", objectName="muted"))
        self.domains = QLineEdit(placeholderText="пусто — для всех запросов; или через запятую: ozon.ru, wb.ru")
        row.addWidget(self.domains, 1)
        rl.addLayout(row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Применить", objectName="primary")
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        rl.addLayout(btns)
        split.addWidget(right)
        split.setSizes([360, 640])

    def _accept(self):
        doms = [d for d in (normalize_entry(x) for x in self.domains.text().split(",")) if d]
        self.add = []
        for p, kind, cb in self.boxes:
            if cb.isChecked():
                self.add += D.preset_upstreams(p, kind, doms)
        self.remove = [self.cur.item(i).data(Qt.UserRole) for i in range(self.cur.count())
                       if self.cur.item(i).data(Qt.UserRole) and self.cur.item(i).checkState() != Qt.Checked]
        self.accept()
