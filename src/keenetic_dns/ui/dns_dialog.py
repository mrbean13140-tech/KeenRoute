"""Вкладка DNS: текущие серверы роутера + шаблоны провайдеров (обычный DNS / DoT / DoH)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import dns as D
from ..core.model import normalize_entry
from .theme import C as COL


class DnsPanel(QWidget):
    """Вкладка «DNS / DoT / DoH». «Применить» вызывает on_apply(add, remove)."""

    def __init__(self, parent, providers: list[dict], on_apply):
        super().__init__(parent)
        self.current: list[D.Upstream] = []
        self.providers, self.on_apply = providers, on_apply
        self.add: list[D.Upstream] = []
        self.remove: list[D.Upstream] = []
        self.boxes: list[tuple[dict, str, QCheckBox]] = []
        self._build()

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
        ll.addWidget(QLabel("Сейчас на роутере", objectName="h2"))
        ll.addWidget(QLabel("Снимите галочку или выделите и нажмите «Удалить». Раскройте сервер, "
                            "чтобы увидеть домены.", objectName="muted", wordWrap=True))
        self.cur = QTreeWidget()
        self.cur.setHeaderHidden(True)
        self.cur.itemChanged.connect(self._mark)
        self.cur.currentItemChanged.connect(self._details)
        ll.addWidget(self.cur, 1)
        self.info = QLabel("", objectName="muted", wordWrap=True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ll.addWidget(self.info)
        row = QHBoxLayout()
        self.limit = QLabel("", objectName="h2")
        row.addWidget(self.limit, 1)
        rm = QPushButton("🗑  Удалить", objectName="danger")
        rm.setToolTip("Отметить выделенный сервер или домен на удаление")
        rm.clicked.connect(self._remove_selected)
        row.addWidget(rm)
        ll.addLayout(row)
        split.addWidget(left)

        right = QWidget(objectName="central")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(20, 16, 20, 14)
        rl.setSpacing(10)
        rl.addWidget(QLabel("Добавить из шаблонов", objectName="h2"))
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
                cb.toggled.connect(self._update_limit)
            il.addWidget(card)
        il.addStretch(1)
        area.setWidget(inner)
        rl.addWidget(area, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Только для доменов:", objectName="muted"))
        self.domains = QLineEdit(placeholderText="пусто — для всех запросов; или через запятую: ozon.ru, wb.ru")
        self.domains.textChanged.connect(self._update_limit)
        row.addWidget(self.domains, 1)
        rl.addLayout(row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Сбросить")
        cancel.clicked.connect(self.reset)
        ok = QPushButton("Применить", objectName="primary")
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        rl.addLayout(btns)
        split.addWidget(right)
        split.setSizes([440, 560])
        self._update_limit()

    def set_current(self, current: list[D.Upstream]):
        """Перерисовать «Сейчас на роутере» (после чтения конфига)."""
        self.current = list(current)
        self.cur.blockSignals(True)
        self.cur.clear()
        groups: dict = {}
        for u in self.current:
            key = D.server_key(u) + ((u.iface,) if u.kind == "plain" else ())
            groups.setdefault(key, []).append(u)
        kinds = {"plain": "DNS", "dot": "DoT", "doh": "DoH"}
        for key, ups in groups.items():
            u0 = ups[0]
            name = D.provider_name(u0, self.providers)
            server = (u0.sni or u0.addr) if u0.kind == "dot" else u0.addr
            via = f"  через {u0.iface}" if u0.iface else ""
            doms = [u.domain for u in ups if u.domain]
            scope = "для всех запросов" if any(not u.domain for u in ups) else f"доменов: {len(doms)}"
            top = QTreeWidgetItem([f"{kinds[u0.kind]} · {name + ' — ' if name else ''}{server}{via}   ({scope})"])
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            top.setCheckState(0, Qt.Checked)
            top.setToolTip(0, server)
            self.cur.addTopLevelItem(top)
            for u in ups:
                ch = QTreeWidgetItem([u.domain or "все запросы"])
                ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
                ch.setCheckState(0, Qt.Checked)
                ch.setData(0, Qt.UserRole, u)
                top.addChild(ch)
        if not self.current:
            self.cur.addTopLevelItem(QTreeWidgetItem(["Свои DNS не заданы — используются DNS провайдера"]))
        self.cur.blockSignals(False)
        self.info.setText("")
        self._update_limit()

    def reset(self):
        for _, _, cb in self.boxes:
            cb.setChecked(False)
        self.domains.clear()
        self.set_current(self.current)

    def _leaves(self):
        for i in range(self.cur.topLevelItemCount()):
            top = self.cur.topLevelItem(i)
            for j in range(top.childCount()):
                yield top.child(j)

    def _mark(self, it, _col=0):
        """Отмеченные на удаление — зачёркнуты красным."""
        self.cur.blockSignals(True)  # смена шрифта сама шлёт itemChanged
        try:
            for x in [it] + [it.child(j) for j in range(it.childCount())] + ([it.parent()] if it.parent() else []):
                off = x.checkState(0) == Qt.Unchecked
                f = x.font(0)
                f.setStrikeOut(off)
                x.setFont(0, f)
                x.setForeground(0, QColor(COL["bad"]) if off else QColor(COL["text"]))
        finally:
            self.cur.blockSignals(False)
        self._update_limit()

    def _details(self, it, _prev=None):
        if not it:
            return
        u = it.data(0, Qt.UserRole)
        if u:
            lines = [f"Команда: {u.cmd()}", f"Тип: {u.label}"]
        else:
            ups = [it.child(j).data(0, Qt.UserRole) for j in range(it.childCount())]
            ups = [x for x in ups if x]
            lines = [f"Записей: {len(ups)}"] + [x.cmd() for x in ups[:6]] + (["…"] if len(ups) > 6 else [])
        self.info.setText("\n".join(lines))

    def _remove_selected(self):
        it = self.cur.currentItem()
        if it and (it.data(0, Qt.UserRole) or it.childCount()):
            it.setCheckState(0, Qt.Unchecked)

    def _planned(self):
        doms = [d for d in (normalize_entry(x) for x in self.domains.text().split(",")) if d]
        add = []
        for p, kind, cb in self.boxes:
            if cb.isChecked():
                add += D.preset_upstreams(p, kind, doms)
        remove = [ch.data(0, Qt.UserRole) for ch in self._leaves()
                  if ch.data(0, Qt.UserRole) and ch.checkState(0) != Qt.Checked]
        return add, remove

    def _update_limit(self, *_):
        add, remove = self._planned()
        after = [u for u in self.current if u not in set(remove)] + add
        n = len(D.encrypted_servers(after))
        self.limit.setText(f"DoT/DoH-серверов: {n} из {D.MAX_ENCRYPTED}")
        self.limit.setStyleSheet(f"color: {COL['bad'] if n > D.MAX_ENCRYPTED else COL['text']};")
        self.limit.setToolTip("Keenetic поддерживает не более 8 серверов DoT/DoH. Один сервер, указанный для "
                              "нескольких доменов, считается одним.")
        return n

    def _accept(self):
        if self._update_limit() > D.MAX_ENCRYPTED:
            return QMessageBox.warning(self, "Лимит DoT/DoH",
                                       f"Keenetic поддерживает не более {D.MAX_ENCRYPTED} серверов DoT/DoH.\n"
                                       "Снимите лишние галочки в шаблонах или удалите старые серверы слева.")
        self.add, self.remove = self._planned()
        if self.add or self.remove:
            self.on_apply(self.add, self.remove)
