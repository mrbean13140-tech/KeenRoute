"""Главное окно KeenRoute 2.0: меню слева, страницы справа."""
from __future__ import annotations

import copy
import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

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
        set_icon(b, ic, obj if obj in ("primary", "danger", "strong") else None)
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
        from ..core.history import HistoryStore
        self.history = HistoryStore()
        self.devices = None
        self._on_success = None  # что сделать после успешного применения (запомнить выключенные и т.п.)
        try:
            self.templates = K.load_templates()
        except Exception:  # noqa: BLE001
            log.exception("Шаблоны не загрузились")
            self.templates = []
        self.resize(1360, 820)
        self.setMinimumSize(1000, 600)
        self._build()
        dark_titlebar(self)
        self.refresh()
        self._check_updates_quiet()


    # ---------- построение UI (KeenRoute 2.0: меню слева, страницы справа) ----------
    PAGES = [("overview", "Обзор", "grid"), ("routing", "Маршрутизация", "route"),
             ("catalog", "Каталог сервисов", "catalog"), ("dns", "DNS · DoT · DoH", "lock"),
             ("policies", "Политики", "monitor"), ("history", "История изменений", "history"),
             ("backups", "Резервные копии", "save")]

    def _build(self):
        self.setWindowIcon(app_icon())
        from .dns_dialog import DnsPanel
        from .policy_panel import PolicyPanel
        try:
            providers = D.load_providers()
        except Exception:  # noqa: BLE001
            log.exception("Шаблоны DNS не загрузились")
            providers = []
        self.dns_panel = DnsPanel(self, providers, self.apply_dns)
        self.policy_panel = PolicyPanel(self, self.apply_policy, self.change_policy)

        root = QWidget(objectName="central")
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._sidebar())
        content = QWidget(objectName="page")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._topbar())
        self.tabs = QStackedWidget(objectName="pages")  # имя оставлено для совместимости
        self.page_index = {}
        for key, widget in [("overview", self._overview_page()), ("routing", self._routing_page()),
                            ("dns", self._wrap(self.dns_panel)), ("policies", self._wrap(self.policy_panel)),
                            ("history", self._history_page()), ("backups", self._backups_page())]:
            self.page_index[key] = self.tabs.addWidget(widget)
        cl.addWidget(self.tabs, 1)
        rl.addWidget(content, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Готово")
        self.go("routing")

    @staticmethod
    def _wrap(panel: QWidget) -> QWidget:
        w = QWidget(objectName="page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 0)
        lay.addWidget(panel)
        return w

    def _sidebar(self) -> QWidget:
        w = QWidget(objectName="sidebar")
        w.setFixedWidth(240)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 14, 12, 10)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 2, 10)
        ic = QLabel()
        ic.setPixmap(app_icon().pixmap(26, 26))
        head.addWidget(ic)
        head.addSpacing(4)
        head.addWidget(_label("KeenRoute", "brand"), 1)
        self.conn_pill = _label("Подключено", "pill")
        head.addWidget(self.conn_pill)
        lay.addLayout(head)

        self.nav_buttons = {}
        groups = [("РАБОТА", self.PAGES[:5]), ("УПРАВЛЕНИЕ", self.PAGES[5:])]
        for caption, items in groups:
            cap = _label(caption, "caption")
            cap.setContentsMargins(10, 12, 0, 4)
            lay.addWidget(cap)
            for key, text, ic_name in items:
                b = QPushButton(text, objectName="navitem")
                set_icon(b, ic_name, "muted")
                b.setCheckable(key != "catalog")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, k=key: self.go(k))
                self.nav_buttons[key] = b
                lay.addWidget(b)
        lay.addStretch(1)

        self.upd_btn = _btn("", self.open_updates, "primary")
        self.upd_btn.setVisible(False)
        lay.addWidget(self.upd_btn)
        lay.addSpacing(6)
        self.router_btn = QPushButton(objectName="routercard")
        set_icon(self.router_btn, "router")
        self.router_btn.setToolTip("Сменить роутер")
        self.router_btn.setCursor(Qt.PointingHandCursor)
        self.router_btn.clicked.connect(self.switch_router)
        self.router_name = _label("", "h2")      # для совместимости: текст кнопки собирается из них
        self.router_info = _label("", "muted")
        lay.addWidget(self.router_btn)
        self._show_router()

        from ..core import settings as S
        self.theme_btn = _btn("", self.toggle_theme, "icon", ic="theme")
        self._theme_tip(S.load().get("theme", "auto"))
        self.upd_small = _btn("", self.open_updates, "icon", "Обновления программы", ic="update")
        self.lnk_btn = _btn("", self.make_shortcut, "icon", "Ярлык на рабочий стол и в меню «Пуск»", ic="monitor")
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 8, 2, 0)
        foot.setSpacing(2)
        for b in (self.theme_btn, self.lnk_btn, self.upd_small):
            b.setFixedSize(34, 34)
            foot.addWidget(b)
        foot.addStretch(1)
        from .. import __version__
        ver = _label(f"v{__version__}", "muted")
        ver.setToolTip("Версия программы")
        foot.addWidget(ver)
        lay.addLayout(foot)
        return w

    def _topbar(self) -> QWidget:
        bar = QWidget(objectName="topbar")
        bar.setFixedHeight(56)
        h = QHBoxLayout(bar)
        h.setContentsMargins(24, 0, 20, 0)
        h.setSpacing(8)
        self.crumb_router = _label("Дом", "crumb")
        h.addWidget(self.crumb_router)
        h.addWidget(_label("›", "crumb"))
        self.crumb_page = _label("", "crumbNow")
        h.addWidget(self.crumb_page)
        h.addStretch(1)
        self.check = QLineEdit(placeholderText="Куда пойдёт сайт? Домен или слово + Enter")
        lead_icon(self.check, "search")
        self.check.setFixedWidth(340)
        self.check.setToolTip("Введите адрес сайта (m.youtube.com) и нажмите Enter — покажу, в каком он списке и через "
                              "какой шлюз пойдёт. Слово (youtube) — найду списки с ним.")
        self.check.returnPressed.connect(lambda: self.check_domain(self.check.text()))
        h.addWidget(self.check)
        h.addWidget(_btn("", self.refresh, "icon", "Перечитать роутер", ic="refresh"))
        return bar

    def go(self, key: str):
        """Перейти на страницу из меню. «Каталог» открывается окном поверх маршрутизации."""
        if key == "catalog":
            self.go("routing")
            return self.open_catalog()
        if key not in self.page_index:
            return
        self.tabs.setCurrentIndex(self.page_index[key])
        self.current_page = key
        titles = {k: t for k, t, _ in self.PAGES}
        self.crumb_page.setText(titles.get(key, ""))
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        if key == "overview":
            self._render_overview()
        elif key == "history":
            self._render_history()
        elif key == "backups":
            self._render_backups()

    # --- общие кусочки страниц ---
    @staticmethod
    def _page_head(title: str, sub: str, *buttons) -> tuple[QHBoxLayout, QLabel, QLabel]:
        row = QHBoxLayout()
        row.setSpacing(8)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        t = _label(title, "title")
        s = _label(sub, "muted")
        s.setWordWrap(True)
        tl.addWidget(t)
        tl.addWidget(s)
        row.addLayout(tl, 1)
        for b in buttons:
            row.addWidget(b, 0, Qt.AlignBottom)
        return row, t, s

    @staticmethod
    def _dot(color: str, size: int = 8) -> QLabel:
        d = QLabel()
        d.setFixedSize(size, size)
        d.setStyleSheet(f"background: {color}; border-radius: {size // 2}px;")
        return d

    def _list_row(self, color, title, sub="", right="", button=None) -> QFrame:
        f = QFrame(objectName="row")
        h = QHBoxLayout(f)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(12)
        h.addWidget(self._dot(color), 0, Qt.AlignVCenter)
        v = QVBoxLayout()
        v.setSpacing(0)
        t = _label(title)
        t.setStyleSheet("font-weight: 600;")
        t.setWordWrap(True)
        v.addWidget(t)
        if sub:
            s = _label(sub, "muted")
            s.setWordWrap(True)
            v.addWidget(s)
        h.addLayout(v, 1)
        if right:
            h.addWidget(_label(right, "muted"))
        if button:
            h.addWidget(button)
        return f

    @staticmethod
    def _card(title: str = "", right: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        if title:
            head = QFrame(objectName="row")
            hh = QHBoxLayout(head)
            hh.setContentsMargins(16, 12, 16, 12)
            lb = _label(title, "h2")
            hh.addWidget(lb, 1)
            if right:
                hh.addWidget(right)
            v.addWidget(head)
        body = QVBoxLayout()
        body.setSpacing(0)
        v.addLayout(body)
        return card, body

    @staticmethod
    def _clear(lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    # --- Обзор ---
    def _overview_page(self) -> QWidget:
        w = QWidget(objectName="page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(16)
        head, _, self.ov_sub = self._page_head("Обзор", "")
        lay.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.ov_stats = []
        for i in range(4):
            card = QFrame(objectName="card")
            v = QVBoxLayout(card)
            v.setContentsMargins(16, 14, 16, 14)
            v.setSpacing(4)
            cap, val, note = _label("", "muted"), _label("", "statValue"), _label("", "statNote")
            for x in (cap, val, note):
                v.addWidget(x)
            grid.addWidget(card, 0, i)
            self.ov_stats.append((cap, val, note))
        lay.addLayout(grid)
        two = QHBoxLayout()
        two.setSpacing(12)
        self.ov_gw_count = _label("", "muted")
        gcard, self.ov_gw = self._card("Туннели и шлюзы", self.ov_gw_count)
        hcard, self.ov_hist = self._card("Последние изменения",
                                         _btn("Вся история", lambda: self.go("history"), "link"))
        two.addWidget(gcard, 1)
        two.addWidget(hcard, 1)
        lay.addLayout(two)
        acard, self.ov_att = self._card("Требует внимания")
        lay.addWidget(acard)
        lay.addStretch(1)
        return w

    def _render_overview(self):
        if not hasattr(self, "ov_stats"):
            return
        addr = self.c.base.replace("http://", "").replace(":80", "")
        self.ov_sub.setText(f"{self.host.get('name') or self.model} · {addr} · {self.model} · NDMS {self.ndms}")
        key = self._router_key()
        off = self.disabled.for_router(key)
        n_off = sum(1 for n in off if n in self.groups and not self.groups[n].interface)
        total_dom = sum(len(g.domains) for g in self.groups.values())
        tun = [i for i in self.ifaces if i.type.lower() in ("wireguard", "openvpn", "ike", "sstp", "l2tp", "pptp")]
        up = sum(1 for i in tun if i.up)
        dns = getattr(self, "dns", [])
        stats = [
            ("DNS-списков", str(len(self.groups)), f"{len(self.groups) - n_off} работают" + (f" · {n_off} выключен" if n_off else ""), COL["muted"]),
            ("Доменов и подсетей", str(total_dom), "поддомены роутер ловит сам", COL["muted"]),
            ("Туннели", f"{up} / {len(tun)}" if tun else "—", "все в сети" if tun and up == len(tun) else
             (f"{len(tun) - up} не в сети" if tun else "VPN-подключений нет"), COL["ok"] if tun and up == len(tun) else COL["warn"]),
            ("DoT · DoH", f"{D.count_kind(dns, 'dot')} · {D.count_kind(dns, 'doh')}", "из 8 записей каждого", COL["muted"]),
        ]
        for (cap, val, note), (c, v, n, col) in zip(self.ov_stats, stats):
            cap.setText(c)
            val.setText(v)
            note.setText(n)
            note.setStyleSheet(f"color: {col};")
        self._clear(self.ov_gw)
        self.ov_gw_count.setText(f"{up} из {len(tun)} в сети" if tun else "")
        for i in sorted(self.ifaces, key=lambda x: (not x.is_wg, x.name)):
            n = sum(1 for g in self.groups.values() if g.interface == i.name)
            if not (i.is_wg or n):
                continue
            cc = getattr(self, "_country", {}).get(i.name, "")
            self.ov_gw.addWidget(self._list_row(COL["ok"] if i.up else COL["bad"], i.short,
                                                f"{i.name} · {i.type}" + (f" · {cc}" if cc else ""),
                                                f"{n} спис." if n else "нет списков"))
        self._clear(self.ov_hist)
        items = self.history.for_router(key)[:4]
        from ..core.history import human_when
        for h in items:
            self.ov_hist.addWidget(self._list_row(COL["accentText"], h["title"], (h["lines"] or [""])[0], human_when(h["at"])))
        if not items:
            self.ov_hist.addWidget(self._list_row(COL["muted"], "Пока ничего не применялось",
                                                  "Изменения, сделанные в KeenRoute, появятся здесь"))
        self._clear(self.ov_att)
        att = []
        for i in tun:
            if not i.up:
                att.append((COL["bad"], f"{i.short} не в сети", "К шлюзам", lambda: self.go("routing")))
        for n in off:
            g = self.groups.get(n)
            if g and not g.interface:
                att.append((COL["warn"], f"«{g.title}» выключен — домены идут напрямую", "Открыть", lambda: self.go("routing")))
        import time
        age = (time.time() - self.db.updated) / 86400 if self.db.updated else None
        if age is None or age > 7:
            att.append((COL["muted"], "База доменов не скачана" if age is None else f"База доменов обновлялась {int(age)} дн. назад",
                        "В каталог", self.open_catalog))
        for color, text, btn_text, fn in att:
            self.ov_att.addWidget(self._list_row(color, text, button=_btn(btn_text, fn)))
        if not att:
            self.ov_att.addWidget(self._list_row(COL["ok"], "Всё в порядке", "Туннели в сети, выключенных списков нет"))

    # --- Маршрутизация ---
    def _routing_page(self) -> QWidget:
        page = QWidget(objectName="page")
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        w = QWidget(objectName="page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(12)
        head, self.title, self.subtitle = self._page_head(
            "Маршрутизация DNS", "",
            _btn("", self.import_dialog, "icon", "Импорт из файла", ic="import"),
            _btn("", self.export_dialog, "icon", "Экспорт в файл", ic="export"),
            _btn("Из каталога", self.open_catalog, None, "Шаблоны и база из 1500+ сервисов", ic="catalog"),
            _btn("Новый список", self.new_group, "strong", ic="plus"))
        lay.addLayout(head)

        self.iflist = GatewayList(None)  # фильтр-чипы по шлюзам; на них можно перетащить строки таблицы
        self.iflist.setObjectName("chips")
        self.iflist.setFlow(QListView.LeftToRight)
        self.iflist.setWrapping(True)
        self.iflist.setResizeMode(QListView.Adjust)
        self.iflist.setFixedHeight(42)
        self.iflist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.iflist.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.iflist.setToolTip("Фильтр по шлюзу. Перетащите сюда строки таблицы — списки переедут на этот шлюз")
        self.iflist.setCursor(Qt.PointingHandCursor)
        self.iflist.dropped.connect(self._on_drop)
        self.iflist.currentItemChanged.connect(self._on_filter)
        lay.addWidget(self.iflist)
        self.route_spacer = QWidget()  # совместимость со старым кодом
        self.route_spacer.hide()

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit(placeholderText="Фильтр по названию или домену")
        lead_icon(self.search, "search")
        self.search.textChanged.connect(self._apply_filter)
        tools.addWidget(self.search, 1)
        self.chk_all = QCheckBox("Выбрать все")
        self.chk_all.setCursor(Qt.PointingHandCursor)
        self.chk_all.clicked.connect(self._check_all)
        tools.addWidget(self.chk_all)
        tools.addWidget(_btn("Разбить большие", self.split_big, tip="Разделить списки, превышающие лимит доменов",
                             ic="split"))
        lay.addLayout(tools)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "Список", "Доменов", "Шлюз", "Статус"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_GW, QHeaderView.Interactive)
        hh.setMinimumSectionSize(40)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(COL_GW, 210)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
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

        # контекстная панель: появляется, когда отмечены списки
        self.actionbar = QFrame(objectName="actionbar")
        ab = QHBoxLayout(self.actionbar)
        ab.setContentsMargins(12, 8, 8, 8)
        ab.setSpacing(6)
        self.sel_label = _label("Отметьте списки галочками", "h2")
        ab.addWidget(self.sel_label)
        ab.addSpacing(6)
        self.gw = QComboBox()
        self.gw.setMinimumWidth(170)
        self.gw.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.gw.setMinimumContentsLength(14)
        self.gw.setToolTip("Шлюз для «Назначить» и «Перевести ВСЕ»")
        ab.addWidget(self.gw)
        self.sel_buttons = [
            _btn("Назначить", self.assign_selected, "primary", "Назначить выбранный шлюз отмеченным спискам"),
            _btn("Снять шлюз", self.unassign_selected),
            _btn("Выключить", self.disable_selected, tip="Временно отключить: домены пойдут напрямую, "
                 "список и домены остаются, шлюз запоминается", ic="pause"),
            _btn("Включить", self.enable_selected, tip="Вернуть выключенные списки на их шлюз", ic="play"),
            _btn("Разделить…", self.split_dialog, tip="Распределить отмеченные списки по разным шлюзам"),
            _btn("", self.export_dialog, "icon", "Экспорт отмеченных", ic="export"),
            _btn("", self.delete_groups, "icon", "Удалить отмеченные", ic="trash"),
        ]
        for b in self.sel_buttons:
            ab.addWidget(b)
        ab.addStretch(1)
        self.btn_all = _btn("Все на шлюз", self.assign_all, tip="Перевести все списки на выбранный шлюз")
        ab.addWidget(self.btn_all)
        ab.addWidget(_btn("", self._clear_checks, "icon", "Снять выбор", ic="close"))
        self.actionbar.hide()
        lay.addWidget(self.actionbar)
        outer.addWidget(w, 1)
        outer.addWidget(self._editor_panel())
        return page

    def _editor_panel(self) -> QWidget:
        self.detail = QWidget(objectName="detail")
        w = self.detail
        w.setFixedWidth(340)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 18, 18, 14)
        lay.setSpacing(10)
        top = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.ed_caption = _label("", "caption")
        self.ed_title = _label("Выберите список", "h2")
        self.ed_title.setWordWrap(True)
        tv.addWidget(self.ed_caption)
        tv.addWidget(self.ed_title)
        top.addLayout(tv, 1)
        top.addWidget(_btn("", self._close_detail, "icon", "Закрыть панель", ic="close"), 0, Qt.AlignTop)
        lay.addLayout(top)
        self.ed_info = _label("Кликните по строке в таблице", "muted")
        self.ed_info.setWordWrap(True)
        lay.addWidget(self.ed_info)
        lay.addWidget(_label("Домены и подсети — по одному в строке; поддомены роутер ловит сам", "muted"))
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
        w.hide()
        return w

    def _close_detail(self):
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.detail.hide()

    def _clear_checks(self):
        self._filling = True
        for r in range(self.table.rowCount()):
            self.table.item(r, COL_CHK).setCheckState(Qt.Unchecked)
        self._filling = False
        self._on_check()

    # --- История и бэкапы ---
    def _history_page(self) -> QWidget:
        w = QWidget(objectName="page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(16)
        head, _, _ = self._page_head("История изменений",
                                     "Всё, что применялось из KeenRoute на этом роутере. Перед каждым шагом — бэкап.")
        lay.addLayout(head)
        card, self.hist_body = self._card()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(card)
        lay.addWidget(scroll, 1)
        return w

    def _render_history(self):
        from ..core.history import human_when
        self._clear(self.hist_body)
        items = self.history.for_router(self._router_key())
        bdir = io.app_dir() / "backups"
        for h in items:
            path = bdir / h["backup"] if h.get("backup") else None
            btn = None
            if h.get("kind") == "lists" and path and path.exists():
                btn = _btn("Откатить", lambda _=False, p=path: self.restore_from(p),
                           tip="Вернуть списки и маршруты к состоянию до этого шага")
            sub = "\n".join(h["lines"][:4]) + (f"\nбэкап {h['backup']}" if h.get("backup") else "")
            self.hist_body.addWidget(self._list_row(COL["accentText"], f"{h['title']}  ·  {human_when(h['at'])}", sub,
                                                    button=btn))
        if not items:
            self.hist_body.addWidget(self._list_row(COL["muted"], "История пуста",
                                                    "Изменения, применённые из KeenRoute, появятся здесь"))
        self.hist_body.addStretch(1)

    def _backups_page(self) -> QWidget:
        w = QWidget(objectName="page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(16)
        head, _, _ = self._page_head(
            "Резервные копии", "Создаются автоматически перед каждым изменением. Хранятся последние 50 на этом компьютере.",
            _btn("Из файла…", self.restore_backup, None, "Восстановить из выбранного файла", ic="restore"),
            _btn("Создать бэкап", self.make_backup, "primary", ic="save"))
        lay.addLayout(head)
        card, self.bk_body = self._card()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(card)
        lay.addWidget(scroll, 1)
        return w

    def _render_backups(self):
        from ..core.history import list_backups
        self._clear(self.bk_body)
        prefix = io.backup_name(self.host.get("name") or self.model).rsplit("_", 2)[0] + "_"
        items = list_backups(prefix)
        for b in items:
            self.bk_body.addWidget(self._list_row(
                COL["muted"], b["name"], f"{b['when']} · {b['size']}",
                button=_btn("Восстановить", lambda _=False, p=b["path"]: self.restore_from(p))))
        if not items:
            self.bk_body.addWidget(self._list_row(COL["muted"], "Бэкапов пока нет",
                                                  "Нажмите «Создать бэкап» или примените любое изменение"))
        self.bk_body.addStretch(1)

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
        if hasattr(self, "router_btn"):
            self.router_btn.setText(f"  {name or self.model}\n  {self.model} · NDMS {self.ndms}" if name
                                    else f"  {self.model}\n  NDMS {self.ndms} · {addr}")
            self.router_btn.setToolTip(f"{addr} — нажмите, чтобы сменить роутер")
        if hasattr(self, "crumb_router"):
            self.crumb_router.setText(name or self.model)

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
        cur_page = getattr(self, "current_page", "routing")
        if cur_page in ("overview", "history", "backups"):
            self.go(cur_page)
        self.statusBar().showMessage(f"Списков: {len(self.groups)} · шлюзов: {len(self.ifaces)}", 5000)

    def _add_nav(self, text, key, n) -> QListWidgetItem:
        it = QListWidgetItem(f"{text}   {n}")
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
        titles = {ALL: "все списки", NOGW: "без шлюза"}
        i = self._iface(self._filter)
        where = titles.get(self._filter) or (i.short if i else self._filter)
        total = sum(len(g.domains) for g in self.groups.values())
        self.subtitle.setText(f"{len(self.groups)} списков · {total} доменов. Показано {shown}: {where}. "
                              "Строки можно перетащить на шлюз выше.")
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
        self.actionbar.setVisible(bool(n))

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
        self.detail.hide()
        self.ed_caption.setText("")
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
        self.detail.show()
        self.ed_caption.setText(f"OBJECT-GROUP {g.name.upper()}")
        self.ed_title.setText(g.title)
        self.ed_info.setText(f"Шлюз: {i.short if i else (g.interface or 'нет — домены идут напрямую')} · "
                             f"записей: {len(g.domains)}")
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
        self._last_summary = summary
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
            self._record("lists", getattr(self, "_last_summary", []), r["backup"])
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
    def open_dns(self):
        self.go("dns")

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
                self._record("dns", summary, r["backup"], "DNS · DoT · DoH")
            self.refresh()
        run_bg(self, work, done, busy="Применяю DNS…")

    # ---------- политики ----------
    def open_policies(self):
        self.go("policies")

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
                self._record("policy", summary, r["backup"], "Политики устройств")
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
                self._record("policy", summary, r["backup"], f"Политика «{name}»")
            self.refresh()
        run_bg(self, work, done, busy="Применяю…")

    def _record(self, kind: str, lines: list[str], backup, title: str | None = None):
        """Запись в «Историю изменений»."""
        if title is None:
            gw = all(x.startswith("~") and "шлюз" in x for x in lines)
            title = ("Смена шлюза" if gw else "Добавлено из каталога" if self._pending_sources
                     else "Изменение списков")
        try:
            self.history.add(self._router_key(), kind, title, lines, getattr(backup, "name", backup))
        except Exception:  # noqa: BLE001
            log.exception("История не записалась")

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
        if path:
            self.restore_from(path)

    def restore_from(self, path):
        """Вернуть списки и DNS-маршруты из файла бэкапа (с предпросмотром разницы)."""
        with open(path, encoding="utf-8") as f:
            backup = parse_running_config(f.read().splitlines())
        self.apply(backup)
