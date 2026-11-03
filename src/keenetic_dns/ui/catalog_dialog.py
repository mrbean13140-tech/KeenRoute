"""Каталог: шаблоны + поиск по локальной базе доменов, выбор галочками, добавление в списки."""
from __future__ import annotations

import datetime as dt
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
                               QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import catalog as K
from ..core.io import safe_name
from ..core.model import NAME_RE, Group, normalize_entry
from .common import run_quiet
from .theme import C as COL
from .theme import app_icon, dark_titlebar

KEEP = "__keep__"


class CatalogDialog(QDialog):
    """Результат после accept(): self.result = [(Group, [(source_key, excluded)])]"""

    def __init__(self, parent, groups: dict[str, Group], ifaces, db: K.DomainDB, templates: list[K.Entry],
                 default_gw: str | None = None, pending_updates=None):
        super().__init__(parent)
        self.setWindowTitle("Каталог сервисов")
        self.setWindowIcon(app_icon())
        self.resize(1100, 680)
        self.setMinimumSize(760, 480)
        self.groups, self.ifaces, self.db, self.templates = groups, ifaces, db, templates
        self.default_gw = default_gw
        self.pending_updates = pending_updates or (lambda: 0)  # сколько списков из каталога можно дополнить
        self.apply_db_updates = False
        self.checked: dict[str, K.Entry] = {}   # key → Entry
        self.extra: list[K.Entry] = []           # введённые вручную
        self.result = []
        self._build()
        self._search()
        dark_titlebar(self)

    # ---------- UI ----------
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(1)
        root.addWidget(split)

        left = QWidget(objectName="sidebar")
        left.setMinimumWidth(260)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 16, 14, 12)
        ll.setSpacing(8)
        ll.addWidget(QLabel("Каталог", objectName="title"))
        self.q = QLineEdit(placeholderText="🔍  Сервис или домен: youtube, coral, chatgpt.com…")
        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self._search)
        self.q.textChanged.connect(lambda: self._timer.start())
        ll.addWidget(self.q)
        self.results = QListWidget()
        self.results.itemChanged.connect(self._on_result_check)
        self.results.currentItemChanged.connect(self._on_result_pick)
        ll.addWidget(self.results, 1)
        row = QHBoxLayout()
        self.db_label = QLabel("", objectName="muted")
        self.db_label.setWordWrap(True)
        row.addWidget(self.db_label, 1)
        ll.addLayout(row)
        self.b_upd = QPushButton("⟳  Обновить базу")
        self.b_upd.setToolTip("Скачать свежую базу доменов (нужен интернет)")
        self.b_upd.clicked.connect(self._update_db)
        ll.addWidget(self.b_upd)
        self.b_apply_upd = QPushButton("", objectName="primary")
        self.b_apply_upd.setToolTip("Добавить в списки из каталога домены, которые появились в базе")
        self.b_apply_upd.clicked.connect(self._apply_updates)
        self.b_apply_upd.setVisible(False)
        ll.addWidget(self.b_apply_upd)
        self._show_db_status()
        split.addWidget(left)

        right = QWidget(objectName="central")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(20, 16, 20, 14)
        rl.setSpacing(10)
        self.sel_title = QLabel("Отметьте сервисы слева", objectName="title")
        self.sel_note = QLabel("Можно отметить несколько — например ChatGPT, Claude и Gemini.", objectName="muted")
        self.sel_note.setWordWrap(True)
        rl.addWidget(self.sel_title)
        rl.addWidget(self.sel_note)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._count)
        rl.addWidget(self.tree, 1)
        self.counter = QLabel("", objectName="h2")
        rl.addWidget(self.counter)

        box = QFrame(objectName="card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(8)
        mode = QHBoxLayout()
        self.m_sep = QRadioButton("Каждый сервис — отдельным списком")
        self.m_one = QRadioButton("Всё в один список:")
        self.m_sep.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.m_sep)
        grp.addButton(self.m_one)
        mode.addWidget(self.m_sep)
        mode.addWidget(self.m_one)
        self.dest = QComboBox()
        self.dest.addItem("＋ новый список", None)
        for g in sorted(self.groups.values(), key=lambda x: x.title.lower()):
            self.dest.addItem(f"{g.title}  ({len(g.domains)})", g.name)
        self.dest.setMinimumWidth(200)
        mode.addWidget(self.dest, 1)
        bl.addLayout(mode)
        names = QHBoxLayout()
        self.new_title = QLineEdit(placeholderText="Название списка, например «ИИ-сервисы»")
        self.new_name = QLineEdit(placeholderText="имя на роутере: латиница")
        self.new_name.setMaximumWidth(220)
        names.addWidget(self.new_title, 1)
        names.addWidget(self.new_name)
        bl.addLayout(names)
        gwrow = QHBoxLayout()
        gwrow.addWidget(QLabel("Шлюз:", objectName="muted"))
        self.gw = QComboBox()
        self.gw.addItem("— не менять (для существующих) —", KEEP)
        self.gw.addItem("— без шлюза —", None)
        for i in self.ifaces:
            self.gw.addItem(f"{'●' if i.up else '○'}  {i.short}", i.name)
        idx = self.gw.findData(self.default_gw)
        self.gw.setCurrentIndex(idx if idx >= 0 else 0)
        gwrow.addWidget(self.gw, 1)
        bl.addLayout(gwrow)
        rl.addWidget(box)
        for w in (self.m_sep, self.m_one, self.dest):
            (w.toggled if isinstance(w, QRadioButton) else w.currentIndexChanged).connect(self._mode_changed)
        self._mode_changed()

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        self.b_add = QPushButton("Добавить на роутер", objectName="primary")
        self.b_add.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(self.b_add)
        rl.addLayout(btns)
        split.addWidget(right)
        split.setSizes([360, 740])
        self._render()

    def _show_db_status(self):
        if self.db.data:
            when = dt.datetime.fromtimestamp(self.db.updated).strftime("%d.%m %H:%M")
            self.db_label.setText(f"База: {len(self.db.data)} сервисов · обновлена {when}")
        else:
            self.db_label.setText("База не скачана — нажмите «Обновить базу» (нужен интернет, ~1 МБ). "
                                  "Шаблоны работают и без неё.")

    def _update_db(self):
        self.b_upd.setEnabled(False)
        self.db_label.setText("Проверяю обновления…")

        def done(_):
            self.b_upd.setEnabled(True)
            self._show_db_status()
            self.db_label.setText(self.db_label.text() + f" · изменено: {self.db.last_changed}")
            self._search()
            n = self.pending_updates()
            if n:
                self.b_apply_upd.setText(f"＋  Новые домены для списков: {n}")
                self.b_apply_upd.setVisible(True)

        def fail(msg):
            self.b_upd.setEnabled(True)
            self._show_db_status()
            QMessageBox.warning(self, "База", f"Не удалось обновить базу:\n{msg}")
        run_quiet(self.db.update, done, fail)

    def _apply_updates(self):
        self.apply_db_updates = True
        self.result = []
        self.accept()

    # ---------- поиск ----------
    def _add_header(self, text):
        it = QListWidgetItem(text)
        it.setFlags(Qt.NoItemFlags)
        it.setForeground(QColor(COL["muted"]))
        self.results.addItem(it)

    def _add_entry(self, e: K.Entry):
        extra = f"  ·  ещё {len(e.optional)} по желанию" if e.optional else ""
        it = QListWidgetItem(f"{e.title}\n{e.size} основных{extra}" + (f"  ·  {e.category}" if e.category else ""))
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if e.key in self.checked else Qt.Unchecked)
        it.setData(Qt.UserRole, e)
        self.results.addItem(it)

    def _search(self):
        q = self.q.text().strip()
        self.results.blockSignals(True)
        self.results.clear()
        if self.checked:
            self._add_header("ВЫБРАНО")
            for e in self.checked.values():
                self._add_entry(e)
        shown = set(self.checked)
        extra = [e for e in self.extra if e.key not in shown]
        if extra:
            self._add_header("НАЙДЕНО ВРУЧНУЮ")
            for e in extra:
                self._add_entry(e)
                shown.add(e.key)
        tpl = [e for e in K.search_templates(self.templates, q) if e.key not in shown]
        if tpl:
            self._add_header("ШАБЛОНЫ (проверенные списки)")
            for e in tpl:
                self._add_entry(e)
        if q:
            found = [e for e in self.db.search(q) if e.key not in shown]
            if found:
                self._add_header(f"БАЗА ДОМЕНОВ ({len(found)})")
                for e in found:
                    self._add_entry(e)
            d = normalize_entry(q)
            if d and "." in d:
                self._add_header("ДОБАВИТЬ КАК ЕСТЬ")
                self._add_entry(K.Entry(d, d, "manual", "Вручную", [] if re.match(r"^\d", d) else [d],
                                        [d] if re.match(r"^\d", d) else []))
            elif not tpl and not found:
                self._add_header("Ничего не найдено. Введите домен сервиса (например coral.ai) — его можно добавить как есть.")
        self.results.blockSignals(False)

    def _on_result_check(self, it: QListWidgetItem):
        e = it.data(Qt.UserRole)
        if not e:
            return
        if it.checkState() == Qt.Checked:
            self.checked[e.key] = e
            if e.source == "manual" and e not in self.extra:
                self.extra.append(e)
        else:
            self.checked.pop(e.key, None)
        self._render()

    def _on_result_pick(self, it, _prev=None):
        if it and it.data(Qt.UserRole) and it.checkState() != Qt.Checked:
            it.setCheckState(Qt.Checked)

    # ---------- правая панель ----------
    def _render(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for e in self.checked.values():
            top = QTreeWidgetItem([f"{e.title}"])
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            top.setData(0, Qt.UserRole, e)
            f = top.font(0); f.setBold(True); top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            rows = [(d, True, "") for d in e.domains]
            rows += [(z, False, "вся зона — экспериментально") for z in e.zones]
            rows += [(ip, e.source in ("tpl", "manual"), "IP-подсеть") for ip in e.ips]
            for val, on, hint in rows:
                ch = QTreeWidgetItem([val + (f"   — {hint}" if hint else "")])
                ch.setData(0, Qt.UserRole, val)
                ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
                ch.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
                if hint:
                    ch.setForeground(0, QColor(COL["muted"]))
                top.addChild(ch)
            if e.optional:  # всё редкое — одной свёрнутой веткой без галочек
                more = QTreeWidgetItem([f"Дополнительно: {len(e.optional)} — региональные, редкие, защитные домены"])
                more.setFlags(more.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                more.setForeground(0, QColor(COL["muted"]))
                top.addChild(more)
                for d in e.optional:
                    ch = QTreeWidgetItem([d])
                    ch.setData(0, Qt.UserRole, d)
                    ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
                    ch.setCheckState(0, Qt.Unchecked)
                    more.addChild(ch)
                more.setExpanded(False)
            top.setExpanded(len(self.checked) <= 2)
            if e.skipped:
                top.setToolTip(0, f"Пропущено правил-масок (regex/keyword): {e.skipped} — Keenetic их не поддерживает")
        self.tree.blockSignals(False)
        n = len(self.checked)
        self.sel_title.setText("Отметьте сервисы слева" if not n else
                               (next(iter(self.checked.values())).title if n == 1 else f"Выбрано сервисов: {n}"))
        notes = [e.note for e in self.checked.values() if e.note]
        self.sel_note.setText(notes[0] if notes else
                              "Снимите галочки с лишнего. Поддомены роутер захватывает сам — их добавлять не нужно.")
        if n == 1 and not self.new_title.text():
            e = next(iter(self.checked.values()))
            self.new_title.setPlaceholderText(e.title)
        self._count()

    def _selection(self) -> list[tuple[K.Entry, list[str], list[str]]]:
        """[(Entry, выбранные, снятые)]"""
        out = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            on, off = [], []
            stack = [top.child(j) for j in range(top.childCount())]
            while stack:
                ch = stack.pop(0)
                if ch.childCount():
                    stack += [ch.child(k) for k in range(ch.childCount())]
                    continue
                (on if ch.checkState(0) == Qt.Checked else off).append(ch.data(0, Qt.UserRole))
            out.append((top.data(0, Qt.UserRole), on, off))
        return out

    def _count(self, *_):
        sel = self._selection()
        total = len({v for _, on, _ in sel for v in on})
        self.counter.setText(f"На роутер уйдёт записей: {total}" if sel else "")
        self.counter.setStyleSheet(f"color: {COL['warn'] if total > 300 else COL['text']};")
        self.b_add.setEnabled(total > 0)

    def _mode_changed(self, *_):
        one = self.m_one.isChecked()
        self.dest.setEnabled(one)
        new = one and self.dest.currentData() is None
        self.new_title.setVisible(new)
        self.new_name.setVisible(new)

    # ---------- результат ----------
    def _accept(self):
        sel = [(e, on, off) for e, on, off in self._selection() if on]
        if not sel:
            return
        gw = self.gw.currentData()
        self.result = []
        if self.m_sep.isChecked():
            for e, on, off in sel:
                name = safe_name(e.id)
                self.result.append((self._group(name, e.title, on, gw, [z for z in e.zones if z in on]),
                                    [(e.key, off)]))
        else:
            name = self.dest.currentData()
            title = self.new_title.text().strip() or (sel[0][0].title if len(sel) == 1 else "Мой список")
            if name is None:
                name = self.new_name.text().strip() or safe_name(title.lower())
                if not NAME_RE.match(name):
                    return QMessageBox.warning(self, "Имя", "Имя на роутере: латиница, цифры, _ и -, до 32 символов.")
            values = list(dict.fromkeys(v for _, on, _ in sel for v in on))
            zones = [z for e, on, _ in sel for z in e.zones if z in on]
            self.result.append((self._group(name, title, values, gw, zones), [(e.key, off) for e, _, off in sel]))
        self.accept()

    def _group(self, name, title, values, gw, zones) -> Group:
        domains = [v for v in values if not K.IP_RE.match(v)]
        ips = K.collapse_ips([v for v in values if K.IP_RE.match(v)])
        g = Group(name, K.compact(domains, zones) + ips, None if gw == KEEP else gw, description=title)
        g.keep_gateway = gw == KEEP  # для существующих — не трогать шлюз
        return g
