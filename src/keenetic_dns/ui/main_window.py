"""Главное окно (тёмный стиль Termius / Windows 11)."""
from __future__ import annotations

import copy
import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTabWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..api.rci import RCIClient
from ..core import catalog as K
from ..core import commands as C
from ..core import dns as D
from ..core import io
from ..core import policy as P
from ..core.model import (NAME_RE, Group, Iface, clean_list, normalize_entry, parse_interfaces,
                          parse_running_config)
from .common import PreviewDialog, run_bg
from .theme import C as COL
from .flow import FlowLayout
from .icons import icon, lead_icon, refresh_icons, set_icon
from .widgets import DomainHighlighter, GatewayList, Toast
from .theme import app_icon, dark_titlebar

log = logging.getLogger(__name__)
NONE = "— без шлюза —"
ALL, NOGW = "__all__", "__none__"
COL_CHK, COL_NAME, COL_CNT, COL_GW, COL_ST = range(5)


def _btn(text, fn, obj=None, tip=None, ic=None):
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if ic:
        set_icon(b, ic, obj if obj in ("primary", "danger") else None)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(fn)
    return b


def _label(text, obj=None):
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    return lb


class MainWindow(QMainWindow):
    def __init__(self, client: RCIClient, version: dict, host: dict | None = None):
        super().__init__()
        self._set_router(client, version, host)
        self.groups: dict[str, Group] = {}
        self.ifaces: list[Iface] = []
        self.config_lines: list[str] = []
        self.backup_path = None
        self._filter = ALL
        self._filling = False
        self._pending_sources = []
        self.db = K.DomainDB()
        self.sources = K.SourceStore()
        self.disabled = K.DisabledStore()
        self._on_success = None  # что сделать после успешного применения (запомнить выключенные и т.п.)
        try:
            self.templates = K.load_templates()
        except Exception:  # noqa: BLE001
            log.exception("Шаблоны не загрузились")
            self.templates = []
        self.resize(1280, 760)
        self.setMinimumSize(900, 560)
        self._build()
        dark_titlebar(self)
        self.refresh()
        self._check_updates_quiet()


    # ---------- построение UI ----------
    def _build(self):
        self.setWindowIcon(app_icon())
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        split.addWidget(self._sidebar())
        # вкладки: маршрутизация DNS (списки) и DoT / DoH
        routing = QSplitter(Qt.Horizontal)
        routing.setChildrenCollapsible(False)
        routing.setHandleWidth(1)
        routing.addWidget(self._main())
        routing.addWidget(self._editor_panel())
        routing.setStretchFactor(0, 1)
        routing.setStretchFactor(1, 0)
        routing.setSizes([760, 300])
        from .dns_dialog import DnsPanel
        try:
            providers = D.load_providers()
        except Exception:  # noqa: BLE001
            log.exception("Шаблоны DNS не загрузились")
            providers = []
        self.dns_panel = DnsPanel(self, providers, self.apply_dns)
        from .policy_panel import PolicyPanel
        self.policy_panel = PolicyPanel(self, self.apply_policy, self.change_policy)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setObjectName("pages")
        self.tabs.addTab(routing, icon("route"), "Маршрутизация DNS")
        self.tabs.addTab(self.dns_panel, icon("lock"), "DoT / DoH")
        self.tabs.addTab(self.policy_panel, icon("monitor"), "Политики")
        self.tabs.currentChanged.connect(self._on_tab)
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 1060])
        self.setCentralWidget(split)
        self.statusBar().showMessage("Готово")

    def _sidebar(self) -> QWidget:
        w = QWidget(objectName="sidebar")
        w.setMinimumWidth(200)
        w.setMaximumWidth(380)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 16, 14, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(app_icon().pixmap(28, 28))
        head.addWidget(ic)
        head.addWidget(_label("KeenRoute", "brand"), 1)
        from ..core import settings as S
        self.theme_btn = _btn("", self.toggle_theme, "icon", ic="theme")
        self._theme_tip(S.load().get("theme", "auto"))
        self.upd_small = _btn("", self.open_updates, "icon", "Обновления программы", ic="update")
        self.lnk_btn = _btn("", self.make_shortcut, "icon", "Ярлык на рабочий стол и в меню «Пуск»", ic="monitor")
        for b in (self.lnk_btn, self.theme_btn, self.upd_small):
            b.setFixedSize(34, 34)
        lay.addLayout(head)

        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(2)
        self.router_name = _label("", "h2")
        self.router_info = _label("", "muted")
        self.router_info.setWordWrap(True)
        cl.addWidget(self.router_name)
        cl.addWidget(self.router_info)
        cl.addSpacing(6)
        cl.addWidget(_btn("Сменить роутер", self.switch_router, ic="swap"))
        self._show_router()
        lay.addWidget(card)

        self.upd_btn = _btn("", self.open_updates, "primary")
        self.upd_btn.setVisible(False)
        lay.addWidget(self.upd_btn)
        lay.addSpacing(4)
        self.route_cap = _label("ШЛЮЗЫ", "caption")
        lay.addWidget(self.route_cap)
        self.iflist = GatewayList(None)  # источник drag — таблица, задаётся после её создания
        self.iflist.dropped.connect(self._on_drop)
        self.iflist.setToolTip("Перетащите сюда строки таблицы — списки переедут на этот шлюз")
        self.iflist.setCursor(Qt.PointingHandCursor)
        self.iflist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.iflist.setTextElideMode(Qt.ElideRight)
        self.iflist.currentItemChanged.connect(self._on_filter)
        lay.addWidget(self.iflist, 1)
        self.route_spacer = QWidget()  # занимает место списка шлюзов на вкладке DoT / DoH
        lay.addWidget(self.route_spacer, 1)
        self.route_spacer.hide()

        lay.addWidget(_label("ДЕЙСТВИЯ", "caption"))
        for ic, text, fn, tip in [
            ("catalog", "Каталог сервисов", self.open_catalog, "Шаблоны и поиск по базе доменов"),
            ("import", "Импорт из файла", self.import_dialog, "Загрузить списки из .json или .txt"),
            ("export", "Экспорт в файл", self.export_dialog, "Сохранить отмеченные (или все) списки в файл"),
            ("save", "Создать бэкап", self.make_backup, "Сохранить конфигурацию роутера в файл"),
            ("restore", "Восстановить из бэкапа", self.restore_backup, "Вернуть списки и маршруты из файла бэкапа"),
        ]:
            lay.addWidget(_btn(text, fn, "nav", tip, ic=ic))
        # служебное — внизу панели, как в Termius / VS Code
        foot = QFrame(objectName="footer")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(0, 8, 0, 0)
        fh.setSpacing(4)
        for b in (self.lnk_btn, self.theme_btn, self.upd_small):
            fh.addWidget(b)
        fh.addStretch(1)
        from .. import __version__
        ver = _label(f"v{__version__}", "muted")
        ver.setToolTip("Версия программы")
        fh.addWidget(ver)
        lay.addWidget(foot)
        return w

    def _main(self) -> QWidget:
        w = QWidget(objectName="central")
        w.setMinimumWidth(460)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 12)
        lay.setSpacing(10)

        tl = QVBoxLayout()
        tl.setSpacing(0)
        self.title = _label("Все списки", "title")
        self.subtitle = _label("", "muted")
        tl.addWidget(self.title)
        tl.addWidget(self.subtitle)
        lay.addLayout(tl)

        self.search = QLineEdit(placeholderText="Поиск по спискам и доменам")
        lead_icon(self.search, "search")
        self.search.setMinimumWidth(160)
        self.search.textChanged.connect(self._apply_filter)
        self.chk_all = QCheckBox("Выбрать все")
        self.chk_all.setCursor(Qt.PointingHandCursor)
        self.chk_all.clicked.connect(self._check_all)
        self.check = QLineEdit(placeholderText="Куда пойдёт сайт? Например: m.youtube.com + Enter")
        lead_icon(self.check, "compass")
        self.check.setMinimumWidth(160)
        self.check.setToolTip("Введите адрес сайта (m.youtube.com, chatgpt.com) и нажмите Enter — покажу, в каком он "
                              "списке и через какой шлюз пойдёт. Можно ввести и слово (youtube) — найду списки с ним.")
        self.check.returnPressed.connect(lambda: self.check_domain(self.check.text()))
        # строка 1 — действия со списками, строка 2 — поиск и проверка
        tools = QWidget()
        fl = FlowLayout(tools)
        for wd in (_btn("Каталог", self.open_catalog, "primary", "Добавить сервисы из шаблонов и базы доменов",
                        ic="catalog"),
                   _btn("Новый список", self.new_group, ic="plus"),
                   _btn("Разбить большие", self.split_big, tip="Разделить списки, превышающие лимит доменов",
                        ic="split"),
                   _btn("Обновить", self.refresh, tip="Перечитать роутер", ic="refresh")):
            fl.addWidget(wd)
        lay.addWidget(tools)
        finder = QHBoxLayout()
        finder.setSpacing(8)
        finder.addWidget(self.search, 3)
        finder.addWidget(self.check, 2)
        lay.addLayout(finder)
        sel = QHBoxLayout()
        sel.setContentsMargins(4, 4, 0, 0)
        sel.addWidget(self.chk_all)
        sel.addStretch(1)
        lay.addLayout(sel)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "СПИСОК", "ДОМЕНОВ", "ШЛЮЗ", "СТАТУС"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_GW, QHeaderView.Interactive)
        hh.setMinimumSectionSize(36)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(COL_GW, 190)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.itemChanged.connect(self._on_check)
        self.table.cellDoubleClicked.connect(self._toggle_row)
        self.table.setDragEnabled(True)
        self.table.setDragDropMode(QAbstractItemView.DragOnly)
        self.iflist._source = self.table
        lay.addWidget(self.table, 1)

        # панель действий над отмеченными (кнопки переносятся при узком окне)
        bar = QFrame(objectName="actionbar")
        bv = QVBoxLayout(bar)
        bv.setContentsMargins(14, 10, 14, 10)
        bv.setSpacing(8)
        row = QHBoxLayout()
        self.sel_label = _label("Отметьте списки галочками", "h2")
        row.addWidget(self.sel_label)
        row.addStretch(1)
        row.addWidget(_label("Шлюз:", "muted"))
        self.gw = QComboBox()
        self.gw.setMinimumWidth(170)
        self.gw.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.gw.setMinimumContentsLength(16)
        row.addWidget(self.gw)
        bv.addLayout(row)
        btns = QWidget()
        bf = FlowLayout(btns)
        self.sel_buttons = [
            _btn("Назначить шлюз", self.assign_selected, "primary", "Назначить выбранный шлюз отмеченным спискам"),
            _btn("Снять шлюз", self.unassign_selected),
            _btn("Выключить", self.disable_selected, tip="Временно отключить: домены пойдут напрямую, "
                 "список и домены остаются, шлюз запоминается", ic="pause"),
            _btn("Включить", self.enable_selected, tip="Вернуть выключенные списки на их шлюз", ic="play"),
            _btn("Разделение…", self.split_dialog, tip="Распределить отмеченные списки по разным шлюзам"),
            _btn("Экспорт", self.export_dialog, ic="export"),
            _btn("Удалить", self.delete_groups, "danger", ic="trash"),
        ]
        for b in self.sel_buttons:
            bf.addWidget(b)
        bf.addWidget(_btn("Перевести ВСЕ на шлюз", self.assign_all, tip="Все списки на выбранный шлюз"))
        bv.addWidget(btns)
        lay.addWidget(bar)
        return w

    def _editor_panel(self) -> QWidget:
        w = QWidget(objectName="sidebar")
        w.setMinimumWidth(220)
        w.setMaximumWidth(520)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 16, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(_label("ДОМЕНЫ", "caption"))
        self.ed_title = _label("Выберите список", "h2")
        self.ed_info = _label("Кликните по строке в таблице", "muted")
        self.ed_info.setWordWrap(True)
        lay.addWidget(self.ed_title)
        lay.addWidget(self.ed_info)
        self.editor = QPlainTextEdit(placeholderText="example.com\nsub.example.org\n203.0.113.0/24")
        self.editor.setEnabled(False)
        self._hl = DomainHighlighter(self.editor.document())
        self.ed_count = _label("", "muted")
        self.editor.textChanged.connect(self._editor_stats)
        lay.addWidget(self.editor, 1)
        lay.addWidget(self.ed_count)
        self.ed_save = _btn("Сохранить домены", self.save_domains, "primary")
        self.ed_save.setEnabled(False)
        lay.addWidget(self.ed_save)
        return w

    # ---------- роутер ----------
    def _set_router(self, client, version, host):
        self.c = client
        self.host = host or {}
        self.model = version.get("model") or version.get("description") or version.get("hw_id") or "Keenetic"
        self.ndms = version.get("title") or version.get("release") or "?"
        self.backup_path = None  # бэкап делается заново для каждого роутера
        self.setWindowTitle(f"KeenRoute — {self.host.get('name') or self.model}")

    def _show_router(self):
        name = self.host.get("name")
        self.router_name.setText(name or self.model)
        addr = self.c.base.replace("http://", "").replace(":80", "")
        self.router_info.setText((f"{self.model}\n" if name else "") + f"NDMS {self.ndms}\n{addr}")

    def switch_router(self):
        from .login import LoginDialog
        dlg = LoginDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._set_router(dlg.client, dlg.version, dlg.host_info)
            self._filter = ALL
            self.search.clear()
            self._show_router()
            self.refresh()

    # ---------- данные ----------
    def refresh(self):
        def load():
            cfg = self.c.running_config()
            return cfg, parse_running_config(cfg), parse_interfaces(self.c.interfaces()), P.read_devices(self.c, cfg)
        run_bg(self, load, self._loaded, busy="Читаю конфигурацию…")

    def _iface(self, name):
        return next((i for i in self.ifaces if i.name == name), None)

    def _loaded(self, res):
        checked = {g.name for g in self.checked()}
        self.config_lines, self.groups, self.ifaces = res[:3]
        if len(res) > 3:
            self.devices = res[3]
        self.dns = D.parse_dns(self.config_lines)
        self.policies = P.parse_policies(self.config_lines)
        self.policy_panel.set_data(self.policies, getattr(self, "devices", None) or P.parse_devices(self.config_lines),
                                   self.ifaces)
        for n in list(self.disabled.for_router(self._router_key())):
            g = self.groups.get(n)
            if not g or g.interface:
                self.disabled.drop(self._router_key(), n)
        self.dns_panel.set_current(self.dns)
        self._filling = True
        self.table.setRowCount(0)
        for g in sorted(self.groups.values(), key=lambda x: x.title.lower()):
            r = self.table.rowCount()
            self.table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if g.name in checked else Qt.Unchecked)
            chk.setData(Qt.UserRole, g.name)
            self.table.setItem(r, COL_CHK, chk)
            name = QTableWidgetItem(g.title)
            f = name.font(); f.setBold(True); name.setFont(f)
            name.setToolTip(f"{g.title}\nobject-group: {g.name}")
            self.table.setItem(r, COL_NAME, name)
            self.table.setItem(r, COL_CNT, QTableWidgetItem(str(len(g.domains))))
            i = self._iface(g.interface) if g.interface else None
            off = None if g.interface else self.disabled.for_router(self._router_key()).get(g.name)
            if off:
                oi = self._iface(off["interface"])
                gw = QTableWidgetItem(oi.short if oi else off["interface"])
                gw.setToolTip("Список выключен. «Включить» вернёт его на этот шлюз")
            else:
                gw = QTableWidgetItem(i.short if i else (g.interface or "—"))
                gw.setToolTip(f"{i.name} · {i.type}" if i else (g.interface or "без шлюза"))
            if not g.interface:
                gw.setForeground(QColor(COL["muted"]))
            self.table.setItem(r, COL_GW, gw)
            if off:
                st, color = "⏸ выключен", COL["warn"]
            elif not g.interface:
                st, color = "", COL["muted"]
            elif not i:
                st, color = "● нет интерфейса", COL["warn"]
            else:
                st, color = ("● в сети", COL["ok"]) if i.up else ("● не в сети", COL["bad"])
            sti = QTableWidgetItem(st)
            sti.setForeground(QColor(color))
            self.table.setItem(r, COL_ST, sti)
        self._filling = False

        self.gw.clear()
        for i in self.ifaces:
            self.gw.addItem(f"{'●' if i.up else '○'}  {i.short}", i.name)
            self.gw.setItemData(self.gw.count() - 1, f"{i.name} · {i.type}", Qt.ToolTipRole)

        # слева — только шлюзы, к которым реально привязаны списки
        cur = self._filter
        self.iflist.blockSignals(True)
        self.iflist.clear()
        self._add_nav("Все списки", ALL, len(self.groups))
        for i in self.ifaces:
            n = sum(1 for g in self.groups.values() if g.interface == i.name)
            if not n:
                continue
            cc = getattr(self, "_country", {}).get(i.name, "")
            it = self._add_nav(f"{'●' if i.up else '○'}  {i.short}" + (f"   [{cc}]" if cc else ""), i.name, n)
            it.setForeground(QColor(COL["ok"] if i.up else COL["muted"]))
            it.setToolTip(f"{i.name} · {i.type} · {'в сети' if i.up else 'не в сети'}")
        missing = sorted({g.interface for g in self.groups.values() if g.interface and not self._iface(g.interface)})
        for name in missing:
            it = self._add_nav(f"⚠  {name}", name, sum(1 for g in self.groups.values() if g.interface == name))
            it.setForeground(QColor(COL["warn"]))
        n_none = sum(1 for g in self.groups.values() if not g.interface)
        if n_none:
            self._add_nav("○  Без шлюза", NOGW, n_none)
        self.iflist.setCurrentRow(0)
        for r in range(self.iflist.count()):
            if self.iflist.item(r).data(Qt.UserRole) == cur:
                self.iflist.setCurrentRow(r)
        self._filter = self.iflist.currentItem().data(Qt.UserRole)
        self._lookup_countries()
        self.iflist.blockSignals(False)
        self._apply_filter()
        self._clear_editor()
        self.statusBar().showMessage(f"Списков: {len(self.groups)} · шлюзов: {len(self.ifaces)}", 5000)

    def _add_nav(self, text, key, n) -> QListWidgetItem:
        it = QListWidgetItem(f"{text}  ·  {n}")
        it.setData(Qt.UserRole, key)
        self.iflist.addItem(it)
        return it

    # ---------- фильтр и выбор ----------
    def _on_filter(self, cur, _prev=None):
        if cur:
            self._filter = cur.data(Qt.UserRole)
        self._apply_filter()

    def _apply_filter(self):
        q = self.search.text().strip().lower()
        shown = 0
        for r in range(self.table.rowCount()):
            g = self.groups[self.table.item(r, COL_CHK).data(Qt.UserRole)]
            ok = (self._filter == ALL or (self._filter == NOGW and not g.interface) or g.interface == self._filter)
            if ok and q:
                ok = q in g.name.lower() or q in g.title.lower() or any(q in d for d in g.domains)
            self.table.setRowHidden(r, not ok)
            shown += ok
        titles = {ALL: "Все списки", NOGW: "Без шлюза"}
        i = self._iface(self._filter)
        self.title.setText(titles.get(self._filter) or (i.short if i else self._filter))
        total = sum(len(g.domains) for g in self.groups.values())
        self.subtitle.setText(f"Показано {shown} из {len(self.groups)} · всего доменов: {total}")
        self._on_check()

    def checked(self) -> list[Group]:
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHK)
            if it and it.checkState() == Qt.Checked and not self.table.isRowHidden(r):
                out.append(self.groups[it.data(Qt.UserRole)])
        return out

    def selected(self) -> list[Group]:
        """Отмеченные галочками; если ничего не отмечено — текущая строка."""
        ch = self.checked()
        if ch:
            return ch
        r = self.table.currentRow()
        if r >= 0 and not self.table.isRowHidden(r):
            return [self.groups[self.table.item(r, COL_CHK).data(Qt.UserRole)]]
        return []

    def _on_check(self, *_):
        if self._filling:
            return
        n = len(self.checked())
        visible = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        self.chk_all.blockSignals(True)
        self.chk_all.setCheckState(Qt.Checked if visible and n == len(visible) else
                                   Qt.PartiallyChecked if n else Qt.Unchecked)
        self.chk_all.blockSignals(False)
        self.sel_label.setText(f"Выбрано: {n}" if n else "Отметьте списки галочками")
        for b in self.sel_buttons:
            b.setEnabled(bool(n) or self.table.currentRow() >= 0)

    def _check_all(self):
        state = Qt.Checked if self.chk_all.checkState() != Qt.Unchecked else Qt.Unchecked
        self._filling = True
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                self.table.item(r, COL_CHK).setCheckState(state)
        self._filling = False
        self._on_check()

    def _toggle_row(self, r, _c):
        it = self.table.item(r, COL_CHK)
        it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def _clear_editor(self):
        self.ed_title.setText("Выберите список")
        self.ed_info.setText("Кликните по строке в таблице")
        self.editor.clear()
        self.editor.setEnabled(False)
        self.ed_save.setEnabled(False)

    def _on_select(self):
        r = self.table.currentRow()
        if r < 0:
            return self._clear_editor()
        g = self.groups[self.table.item(r, COL_CHK).data(Qt.UserRole)]
        i = self._iface(g.interface) if g.interface else None
        self.ed_title.setText(g.title)
        self.ed_info.setText(f"Доменов: {len(g.domains)} · шлюз: {i.short if i else (g.interface or 'нет')}"
                             + (f"\nobject-group: {g.name}" if g.description else ""))
        self.editor.setPlainText("\n".join(g.domains))
        self.editor.setEnabled(True)
        self.ed_save.setEnabled(True)
        self._on_check()

    def _editor_group(self) -> Group | None:
        r = self.table.currentRow()
        return self.groups[self.table.item(r, COL_CHK).data(Qt.UserRole)] if r >= 0 else None

    # ---------- применение ----------
    def _target(self) -> dict[str, Group]:
        """Копия текущего состояния — от неё строится желаемое."""
        return copy.deepcopy(self.groups)

    def _ifname(self, name):
        i = self._iface(name)
        return i.short if i else name

    def apply(self, target: dict[str, Group]):
        """Перевести роутер в target: предпросмотр → бэкап → команды → проверка → откат при ошибке."""
        current = copy.deepcopy(self.groups)
        cmds = C.plan(current, target)
        if not cmds:
            for group, src, excluded in self._pending_sources:  # всё уже на роутере — просто запомнить источник
                self.sources.add(self._router_key(), group, src, excluded)
            self._pending_sources = []
            QMessageBox.information(self, "Нет изменений", "Всё уже в нужном состоянии.")
            return
        cmds = C.with_save(cmds)
        summary = C.describe(current, target, self._ifname)
        if PreviewDialog(cmds, self, summary).exec() != QDialog.Accepted:
            self._pending_sources = []
            return
        label = self.host.get("name") or self.model

        def work():
            lines = self.c.running_config()
            backup = io.save_backup(lines, label)
            before = parse_running_config(lines)
            try:
                self.c.run(cmds)
                error = None
            except Exception as e:  # noqa: BLE001
                error = str(e)
            after = parse_running_config(self.c.running_config())
            return {"backup": backup, "before": before, "after": after, "error": error,
                    "left": C.plan(after, target)}
        run_bg(self, work, lambda r: self._applied(r, target), busy="Применяю на роутере…")

    def _applied(self, r, target):
        self.backup_path = r["backup"]
        self.last_apply = {"ok": not (r["error"] or r["left"]), "error": r["error"], "left": r["left"]}
        if r["error"] or r["left"]:
            msg = "Изменения применились не полностью."
            if r["error"]:
                msg += "\n\nОшибка роутера:\n" + r["error"]
            if r["left"]:
                msg += f"\n\nНе применено команд: {len(r['left'])}"
            msg += "\n\nОткатить к состоянию до изменений? (бэкап: " + r["backup"].name + ")"
            if QMessageBox.question(self, "Проверка не пройдена", msg) == QMessageBox.Yes:
                self._rollback(r["before"])
                return
            self.statusBar().showMessage("Применено с ошибками — проверьте списки", 10000)
        else:
            self.statusBar().showMessage(f"✓ Применено и проверено · бэкап {r['backup'].name}", 8000)
            before = r["before"]
            Toast(self, "✓ Применено и проверено на роутере", "Отменить", lambda: self._rollback(before))
            for group, src, excluded in self._pending_sources:
                self.sources.add(self._router_key(), group, src, excluded)
            if self._on_success:
                self._on_success()
        self._pending_sources = []
        self._on_success = None
        self.refresh()

    # ---------- каталог ----------
    def _router_key(self) -> str:
        return self.host.get("id") or self.c.base

    def check_db_updates(self):
        """По кнопке: скачать базу → сравнить → предложить новые домены для списков из каталога."""
        def done(_):
            changed = self.db.last_changed
            t = self._db_target()
            if t is not None and C.plan(self.groups, t):
                self.apply(t)  # предпросмотр покажет, что добавится
            else:
                QMessageBox.information(self, "Обновления базы",
                                        f"База обновлена ({len(self.db.data)} сервисов, изменено: {changed}).\n"
                                        "Списки из каталога актуальны — менять на роутере нечего.")
        run_bg(self, self.db.update, done, busy="Проверяю обновления базы доменов…")

    def open_catalog(self):
        from .catalog_dialog import CatalogDialog
        dlg = CatalogDialog(self, self.groups, self.ifaces, self.db, self.templates, self.gw.currentData(),
                            pending_updates=self._pending_db_count)
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.apply_db_updates:
            return self.update_from_db()
        if not dlg.result:
            return
        t = self._target()
        pending = []
        for g, srcs in dlg.result:
            old = t.get(g.name)
            if old:
                old.domains = list(dict.fromkeys(old.domains + g.domains))
                if not getattr(g, "keep_gateway", False):
                    old.interface = g.interface
                old.description = old.description or g.description
                parts = C.split_group(old)
            else:
                parts = C.split_group(g)
            if len(parts) > 1:
                t.pop(g.name, None)
            for p in parts:
                t[p.name] = p
                pending += [(p.name, key, off) for key, off in srcs]
        self._pending_sources = pending
        self.apply(t)

    def _db_target(self):
        tracked = self.sources.for_router(self._router_key())
        if not tracked:
            return None
        t = self._target()
        for name, rec in tracked.items():
            g = t.get(name)
            if not g:
                continue
            fresh = []
            for src in rec["sources"]:
                fresh += K.fresh_entries(src, self.templates, self.db)
            excluded = set(rec["excluded"])
            new = [x for x in clean_list(fresh) if x not in excluded and x not in g.domains]
            zones = [d for d in g.domains if "." not in d]
            g.domains = g.domains + [d for d in K.compact(new, zones + g.domains) if d not in g.domains] \
                + [x for x in new if K.IP_RE.match(x)]
            g.domains = list(dict.fromkeys(g.domains))
        return t

    def _pending_db_count(self) -> int:
        """Сколько списков из каталога получат новые домены из текущей базы."""
        t = self._db_target()
        if t is None:
            return 0
        return sum(1 for n, g in t.items() if n in self.groups and g.domains != self.groups[n].domains)

    def update_from_db(self):
        """Применить текущую локальную базу к спискам из каталога (без скачивания)."""
        t = self._db_target()
        if t is None:
            return QMessageBox.information(self, "Обновление из базы",
                                           "На этом роутере пока нет списков, добавленных из каталога.")
        if not C.plan(self.groups, t):
            return QMessageBox.information(self, "Обновление из базы", "Все списки из каталога актуальны.")
        self.apply(t)

    # ---------- удобства ----------
    def _on_drop(self, key):
        names = [g.name for g in self.selected()]
        if not names or key == ALL:
            return
        self._set_iface(names, None if key == NOGW else key)

    def _editor_stats(self):
        lines = [x.strip() for x in self.editor.toPlainText().splitlines() if x.strip() and not x.strip().startswith("#")]
        norm = [normalize_entry(x) for x in lines]
        bad = sum(1 for x in norm if not x)
        good = [x for x in norm if x]
        dup = len(good) - len(set(good))
        parts = [f"записей: {len(set(good))}"]
        if bad:
            parts.append(f"ошибок: {bad} (красным)")
        if dup:
            parts.append(f"дублей: {dup} (жёлтым)")
        self.ed_count.setText(" · ".join(parts) if lines else "")

    def check_domain(self, text):
        word = text.strip().lower()
        if word and "." not in word and "/" not in word:  # слово, а не домен: ищем списки и домены с ним
            found = []
            for g in self.groups.values():
                doms = [e for e in g.domains if word in e]
                if word in g.title.lower() or doms:
                    i = self._iface(g.interface) if g.interface else None
                    gw = i.short if i else (g.interface or "без шлюза")
                    found.append(f"«{g.title}» → {gw}" + (f"  ({', '.join(doms[:3])}{'…' if len(doms) > 3 else ''})"
                                                         if doms else ""))
            if found:
                return Toast(self, f"«{word}» встречается в списках:\n" + "\n".join(found), kind="ok", ms=10000)
            return Toast(self, f"«{word}» нет ни в одном списке. Введите адрес сайта целиком, например {word}.com",
                         kind="info", ms=8000)
        d = normalize_entry(text)
        if not d:
            return Toast(self, "Это не похоже на домен или IP", kind="bad")
        import ipaddress
        hits = []
        for g in self.groups.values():
            for e in g.domains:
                if e == d or d.endswith("." + e):
                    hits.append((g, e))
                    break
                if "/" in e or e.replace(".", "").isdigit():
                    try:
                        if ipaddress.ip_address(d) in ipaddress.ip_network(e, strict=False):
                            hits.append((g, e))
                            break
                    except ValueError:
                        pass
        if not hits:
            return Toast(self, f"{d} — нет ни в одном списке, значит пойдёт напрямую через провайдера, без VPN",
                         kind="info", ms=8000)
        lines = []
        for g, e in hits:
            i = self._iface(g.interface) if g.interface else None
            cc = getattr(self, "_country", {}).get(g.interface or "", "")
            gw = (i.short if i else (g.interface or "без шлюза")) + (f" [{cc}]" if cc else "")
            lines.append(f"«{g.title}» (по записи {e}) → {gw}")
        Toast(self, f"{d}:\n" + "\n".join(lines), kind="ok", ms=10000)

    def _lookup_countries(self):
        """Страна выхода WG-туннелей: endpoint пира → геолокация. В фоне, ошибки игнорируются."""
        if getattr(self, "_country_busy", False) or os.environ.get("KEENETIC_DNS_NO_GEO"):
            return
        todo = [i.name for i in self.ifaces if i.is_wg and i.name not in getattr(self, "_country", {})]
        if not todo:
            return
        self._country_busy = True
        client = self.c

        def work():
            from ..core.geo import tunnel_countries
            return tunnel_countries(client, todo)

        def done(res):
            self._country_busy = False
            self._country = {**getattr(self, "_country", {}), **res}
            if any(res.values()):
                self._loaded((self.config_lines, self.groups, self.ifaces))
        from .common import run_quiet
        run_quiet(work, done, lambda m: setattr(self, "_country_busy", False))

    def toggle_theme(self):
        from PySide6.QtWidgets import QApplication

        from ..core import settings as S
        from . import theme
        cfg = S.load()
        order = ["auto", "dark", "light"]
        cfg["theme"] = order[(order.index(cfg.get("theme", "auto")) + 1) % 3]
        S.save(cfg)
        theme.apply(QApplication.instance(), cfg["theme"])
        theme.dark_titlebar(self)
        refresh_icons(self)
        self.tabs.setTabIcon(0, icon("route"))
        self.tabs.setTabIcon(1, icon("lock"))
        self._theme_tip(cfg["theme"])
        self._loaded((self.config_lines, self.groups, self.ifaces))

    def _theme_tip(self, mode):
        self.theme_btn.setToolTip({"auto": "Тема: как в Windows", "dark": "Тема: тёмная",
                                   "light": "Тема: светлая"}[mode] + " — нажмите, чтобы сменить")

    # ---------- обновления программы ----------
    def _check_updates_quiet(self):
        import os

        from ..core import settings as S
        from ..core import updater as U
        if os.environ.get("KEENETIC_DNS_NO_UPDATE_CHECK") or not S.load().get("check_updates", True):
            return

        def done(rel):
            if rel and rel.newer:
                self._new_release = rel
                self.upd_btn.setText(f"⬆  Доступна версия {rel.version}")
                self.upd_btn.setVisible(True)
        from .common import run_quiet
        run_quiet(U.check, done, lambda m: log.info("Проверка обновлений: %s", m), S.get_token() or None)

    def make_shortcut(self):
        from PySide6.QtWidgets import QApplication

        from ..core import install as I
        if not I.current_exe():
            return Toast(self, "Ярлык можно создать только из KeenRoute.exe", kind="info")
        try:
            if I.is_installed():
                I.create_shortcuts(I.installed_exe())
                return Toast(self, "✓ Ярлыки созданы на рабочем столе и в меню «Пуск»")
            exe = I.install()
        except Exception as e:  # noqa: BLE001
            return Toast(self, f"Не удалось создать ярлык: {e}", kind="bad", ms=10000)
        if QMessageBox.question(self, "Ярлык создан",
                                f"KeenRoute установлен в {exe.parent},\nярлыки — на рабочем столе и в меню «Пуск».\n\n"
                                "Перезапустить из новой папки сейчас?") == QMessageBox.Yes:
            I.launch(exe)
            QApplication.quit()

    def open_updates(self):
        from .update_dialog import UpdateDialog
        UpdateDialog(self, getattr(self, "_new_release", None)).exec()

    # ---------- DNS ----------
    def _on_tab(self, idx):
        """Шлюзы слева относятся только к маршрутизации — на вкладке DoT / DoH прячем."""
        routing = idx == 0
        for w in (self.route_cap, self.iflist):
            w.setVisible(routing)
        self.route_spacer.setVisible(not routing)

    def open_dns(self):
        self.tabs.setCurrentWidget(self.dns_panel)

    def _dns_exec(self, add, remove, before) -> dict:
        """Применить DNS на роутере (в фоне): удаление по одной с запасными формами команды,
        добавление пачкой, восстановление случайно задетых записей, сохранение, проверка."""
        errors = []
        for u in remove:
            if u not in before:
                continue
            last = ""
            for cmd in D.remove_candidates(u):
                try:
                    self.c.run([cmd])
                    last = ""
                    break
                except Exception as e:  # noqa: BLE001
                    last = str(e)
                    if "parse" not in last.lower() and "argument" not in last.lower():
                        break
            if last:
                errors.append(last)
        add_cmds = [u.cmd() for u in add if u not in before]
        if add_cmds:
            try:
                self.c.run(add_cmds)
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
        mid = D.parse_dns(self.c.running_config())
        lost = [u for u in before if u not in remove and u not in mid]  # задело короткой формой «no …»
        if lost:
            try:
                self.c.run([u.cmd() for u in lost])
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
        try:
            self.c.run(["system configuration save"])
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
        after = D.parse_dns(self.c.running_config())
        left = D.verify_dns(after, add, remove) + [f"пропало: {u.label}" for u in before
                                                    if u not in remove and u not in after]
        return {"error": "\n".join(errors) or None, "left": left, "after": after}

    def apply_dns(self, add: list[D.Upstream], remove: list[D.Upstream]):
        cmds = D.plan_dns(getattr(self, "dns", []), add, remove)
        if not cmds:
            return QMessageBox.information(self, "DNS", "Нечего менять.")
        result = [u for u in getattr(self, "dns", []) if u not in set(remove)] + [u for u in add]
        over = D.over_limit(result)
        if over:
            return QMessageBox.warning(self, "Лимит DoT/DoH",
                                       "Keenetic хранит не больше 8 записей DoT и 8 записей DoH "
                                       "(каждый домен — отдельная запись).\nПосле изменений было бы: "
                                       + ", ".join(over) + ".\nУдалите лишние записи или укажите меньше доменов.")
        cur = set(getattr(self, "dns", []))
        summary = [f"− Удалить {u.label}" for u in remove if u in cur] + \
                  [f"+ Добавить {u.label}" for u in add if u not in cur]
        cmds = C.with_save(cmds)
        if PreviewDialog(cmds, self, summary).exec() != QDialog.Accepted:
            return
        label = self.host.get("name") or self.model

        def work():
            lines = self.c.running_config()
            return {"backup": io.save_backup(lines, label), **self._dns_exec(add, remove, D.parse_dns(lines))}

        def done(r):
            self.backup_path = r["backup"]
            self.last_apply = {"ok": not (r["error"] or r["left"]), "error": r["error"], "left": r["left"]}
            if r["error"] or r["left"]:
                msg = "DNS применились не полностью.\n\n" + "\n".join(filter(None, [r["error"], *r["left"]]))
                if QMessageBox.question(self, "Проверка не пройдена", msg + "\n\nОткатить?") == QMessageBox.Yes:
                    now = set(r["after"])
                    back_add = [u for u in remove if u not in now and u in cur]
                    back_rm = [u for u in add if u in now and u not in cur]
                    if back_add or back_rm:
                        run_bg(self, lambda: self._dns_exec(back_add, back_rm, list(now)),
                               lambda _: self.refresh(), busy="Откатываю DNS…")
                        return
            else:
                self.statusBar().showMessage(f"✓ DNS применены и проверены · бэкап {r['backup'].name}", 8000)
            self.refresh()
        run_bg(self, work, done, busy="Применяю DNS…")

    # ---------- политики ----------
    def open_policies(self):
        self.tabs.setCurrentWidget(self.policy_panel)

    def apply_policy(self, macs: list[str], policy: str | None, new: P.Policy | None = None):
        devices = getattr(self, "devices", None) or P.parse_devices(self.config_lines)
        cmds, summary = P.plan(getattr(self, "policies", {}), devices, macs, policy, new)
        if not cmds:
            return QMessageBox.information(self, "Политики", "Все отмеченные устройства уже на этой политике.")
        if PreviewDialog(C.with_save(cmds), self, summary).exec() != QDialog.Accepted:
            return
        label = self.host.get("name") or self.model
        before = {m: (devices.get(m) or P.Device(m)).policy for m in macs}

        def work():
            backup = io.save_backup(self.c.running_config(), label)
            error = None
            try:
                self.c.run(C.with_save(cmds))
            except Exception as e:  # noqa: BLE001
                error = str(e)
            lines = self.c.running_config()
            after = P.read_devices(self.c, lines)
            return {"backup": backup, "error": error, "left": P.verify_assign(after, macs, policy)}

        def done(r):
            self.backup_path = r["backup"]
            self.last_apply = {"ok": not (r["error"] or r["left"]), "error": r["error"], "left": r["left"]}
            if r["error"] or r["left"]:
                msg = "Политики применились не полностью.\n\n" + "\n".join(filter(None, [r["error"], *r["left"]]))
                if QMessageBox.question(self, "Проверка не пройдена", msg + "\n\nВернуть устройства как было?") \
                        == QMessageBox.Yes:
                    back = []
                    for m, pol in before.items():
                        back += P.assign_cmds([P.Device(m, policy=policy or "")], pol or None)
                    if back:
                        run_bg(self, lambda: self.c.run(C.with_save(back)), lambda _: self.refresh(),
                               busy="Возвращаю политики…")
                        return
            else:
                self.statusBar().showMessage(f"✓ Политики применены и проверены · бэкап {r['backup'].name}", 8000)
            self.refresh()
        run_bg(self, work, done, busy="Применяю политики…")

    def change_policy(self, cmds: list[str], summary: list[str], name: str, want: P.Policy | None):
        """Изменить (want) или удалить (want=None) политику: предпросмотр, бэкап, применение, проверка."""
        if PreviewDialog(C.with_save(cmds), self, summary).exec() != QDialog.Accepted:
            return
        label = self.host.get("name") or self.model

        def work():
            backup = io.save_backup(self.c.running_config(), label)
            error = None
            try:
                self.c.run(C.with_save(cmds))
            except Exception as e:  # noqa: BLE001
                error = str(e)
            left = P.verify_policy(P.parse_policies(self.c.running_config()), name, want)
            return {"backup": backup, "error": error, "left": left}

        def done(r):
            self.backup_path = r["backup"]
            self.last_apply = {"ok": not (r["error"] or r["left"]), "error": r["error"], "left": r["left"]}
            if r["error"] or r["left"]:
                QMessageBox.warning(self, "Проверка не пройдена",
                                    "Изменения применились не полностью.\n\n"
                                    + "\n".join(filter(None, [r["error"], *r["left"]]))
                                    + f"\n\nБэкап до изменений: {r['backup'].name} (кнопка «Восстановить из бэкапа»).")
            else:
                self.statusBar().showMessage(f"✓ Готово и проверено · бэкап {r['backup'].name}", 8000)
            self.refresh()
        run_bg(self, work, done, busy="Применяю…")

    def _rollback(self, before: dict[str, Group]):
        def work():
            now = parse_running_config(self.c.running_config())
            cmds = C.plan(now, before)
            if cmds:
                self.c.run(C.with_save(cmds))
            return C.plan(parse_running_config(self.c.running_config()), before)
        run_bg(self, work, lambda left: (
            self.statusBar().showMessage("↺ Откат выполнен" if not left else
                                         f"Откат выполнен частично, осталось команд: {len(left)}", 10000),
            self.refresh()), busy="Откатываю…")

    def _gw(self) -> str | None:
        if not self.gw.count():
            QMessageBox.warning(self, "Нет шлюзов", "На роутере не найдено подходящих подключений.")
            return None
        return self.gw.currentData()

    def _set_iface(self, names, iface):
        t = self._target()
        for n in names:
            t[n].interface = iface
        self.apply(t)

    def disable_selected(self):
        sel = [g for g in self.selected() if g.interface]
        if not sel:
            return Toast(self, "Отметьте включённые списки (с шлюзом), которые нужно выключить", kind="info")
        key = self._router_key()
        memo = [(g.name, g.interface, g.reject) for g in sel]
        self._on_success = lambda: [self.disabled.set(key, n, i, r) for n, i, r in memo]
        t = self._target()
        for g in sel:
            t[g.name].interface = None
        self.apply(t)

    def enable_selected(self):
        off = self.disabled.for_router(self._router_key())
        sel = [g for g in self.selected() if not g.interface and g.name in off]
        if not sel:
            return Toast(self, "Отметьте выключенные списки (статус «⏸ выключен»)", kind="info")
        key = self._router_key()
        names = [g.name for g in sel]
        self._on_success = lambda: [self.disabled.drop(key, n) for n in names]
        t = self._target()
        for g in sel:
            t[g.name].interface = off[g.name]["interface"]
            t[g.name].reject = bool(off[g.name].get("reject"))
        self.apply(t)

    def unassign_selected(self):
        sel = self.selected()
        if sel:
            self._set_iface([g.name for g in sel], None)

    def assign_selected(self):
        sel, gw = self.selected(), self._gw()
        if not sel:
            return QMessageBox.information(self, "Выбор", "Отметьте списки галочками.")
        if gw:
            self._set_iface([g.name for g in sel], gw)

    def assign_all(self):
        gw = self._gw()
        if gw and QMessageBox.question(self, "Все списки",
                                       f"Перевести ВСЕ списки на {self._ifname(gw)}?") == QMessageBox.Yes:
            self._set_iface(list(self.groups), gw)

    def split_dialog(self):
        sel = self.selected() or list(self.groups.values())
        d = QDialog(self); d.setWindowTitle("Разделение списков по шлюзам"); d.resize(560, 480)
        lay = QVBoxLayout(d)
        t = QTableWidget(len(sel), 2); t.setHorizontalHeaderLabels(["Список", "Шлюз"])
        t.horizontalHeader().setStretchLastSection(True)
        combos = {}
        for r, g in enumerate(sel):
            t.setItem(r, 0, QTableWidgetItem(f"{g.title} ({len(g.domains)})"))
            cb = QComboBox(); cb.addItem(NONE, None)
            for i in self.ifaces:
                cb.addItem(i.short, i.name)
            idx = cb.findData(g.interface); cb.setCurrentIndex(max(idx, 0))
            t.setCellWidget(r, 1, cb); combos[g.name] = cb
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept); bb.rejected.connect(d.reject); lay.addWidget(bb)
        if d.exec() == QDialog.Accepted:
            tg = self._target()
            for n, cb in combos.items():
                tg[n].interface = cb.currentData()
            self.apply(tg)

    def split_big(self):
        limit, ok = QInputDialog.getInt(self, "Разбить большие", "Максимум доменов в списке:",
                                        C.MAX_DOMAINS_PER_GROUP, 10, 5000)
        if not ok:
            return
        t = self._target()
        for g in list(t.values()):
            parts = C.split_group(g, limit)
            if len(parts) > 1:
                del t[g.name]
                for p in parts:
                    t[p.name] = p
        self.apply(t)

    def save_domains(self):
        old = self._editor_group()
        if not old:
            return
        t = self._target()
        t[old.name].domains = clean_list(self.editor.toPlainText().splitlines())
        self.apply(t)

    def new_group(self):
        name, ok = QInputDialog.getText(self, "Новый список", "Имя (латиница, цифры, _ -, до 32):")
        if not ok:
            return
        if not NAME_RE.match(name) or name in self.groups:
            return QMessageBox.warning(self, "Имя", "Недопустимое или уже существующее имя.")
        domains, ok = QInputDialog.getMultiLineText(self, "Домены", "Домены (по одному в строке):")
        if not ok:
            return
        t = self._target()
        t[name] = Group(name, clean_list(domains.splitlines()), self.gw.currentData())
        self.apply(t)

    def delete_groups(self):
        sel = self.selected()
        if not sel:
            return
        text = "Удалить списки: " + ", ".join(g.title for g in sel) + "?"
        if any(g.interface for g in sel):
            text += ("\n\nВнимание: пока списков нет, эти сайты пойдут напрямую через провайдера. "
                     "Приложения (например, детский YouTube) могут увидеть смену страны и сбросить настройки.\n"
                     "Чтобы обновить списки, лучше импортировать файл в режиме «Заменить» — без удаления.")
        if QMessageBox.question(self, "Удаление", text) == QMessageBox.Yes:
            t = self._target()
            for g in sel:
                del t[g.name]
            self.apply(t)

    # ---------- импорт/экспорт ----------
    def export_dialog(self):
        sel = self.selected() or list(self.groups.values())
        if len(sel) == 1:
            path, flt = QFileDialog.getSaveFileName(self, "Экспорт", f"{sel[0].name}.json",
                                                    "JSON (*.json);;Текст (*.txt)")
        else:
            path, flt = QFileDialog.getSaveFileName(self, "Экспорт", "keenetic_dns.json", "JSON (*.json)")
        if not path:
            return
        if path.lower().endswith(".txt"):
            io.export_txt(sel[0], path)
        else:
            io.export_json(sel, path, {"model": self.model, "ndms": self.ndms})
        self.statusBar().showMessage(f"Экспортировано: {len(sel)} → {path}", 6000)

    def import_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Импорт", "", "Списки (*.json *.txt *.lst);;Все (*)")
        groups = []
        for p in paths:
            try:
                groups += io.import_file(p)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Импорт", f"{p}: {e}")
        if groups:
            self._import(groups)

    def _import(self, groups: list[Group]):
        items = ["Как в файле", NONE] + [i.short for i in self.ifaces]
        choice, ok = QInputDialog.getItem(self, "Шлюз для импорта", "Назначить импортируемым спискам:", items, 0, False)
        if not ok:
            return
        idx = items.index(choice)
        conflict = [g.name for g in groups if g.name in self.groups]
        mode = "replace"
        if conflict:
            m, ok = QInputDialog.getItem(self, "Совпадают имена", "Уже есть: " + ", ".join(conflict),
                                         ["Объединить домены", "Заменить", "Переименовать новые"], 0, False)
            if not ok:
                return
            mode = {"Объединить домены": "merge", "Заменить": "replace", "Переименовать новые": "rename"}[m]
        t = self._target()
        for g in groups:
            if idx == 1:
                g.interface = None
            elif idx >= 2:
                g.interface = self.ifaces[idx - 2].name
            old = self.groups.get(g.name)
            if old and mode == "rename":
                n = 2
                while f"{g.name}_{n}"[:32] in t:
                    n += 1
                g.name, old = f"{g.name}_{n}"[:32], None
            elif old and mode == "merge":
                g.domains = list(dict.fromkeys(old.domains + g.domains))
                g.description = g.description or old.description
            parts = C.split_group(g)
            if len(parts) > 1:
                t.pop(g.name, None)
            for p in parts:
                t[p.name] = p
        self.apply(t)

    def make_backup(self):
        default = io.app_dir() / "backups" / io.backup_name(self.host.get("name") or self.model)
        default.parent.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Создать бэкап", str(default), "Бэкап (*.txt)")
        if not path:
            return

        def work():
            lines = self.c.running_config()
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return path
        run_bg(self, work, lambda p: self.statusBar().showMessage(f"Бэкап сохранён: {p}", 8000),
               busy="Сохраняю бэкап…")

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Бэкап", str(io.app_dir() / "backups"), "Бэкап (*.txt)")
        if not path:
            return
        with open(path, encoding="utf-8") as f:
            backup = parse_running_config(f.read().splitlines())
        self.apply(backup)
