"""Окно подключения: сохранённые роутеры (как хосты в Termius) + форма."""
from __future__ import annotations

import json
import subprocess
import sys
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from ..api.rci import RCIClient
from ..core.io import app_dir
from .theme import C as COL
from .theme import app_icon, dark_titlebar

try:
    import keyring
except Exception:  # noqa: BLE001
    keyring = None

SERVICE = "KeeneticDNS"


def default_gateway() -> str:
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-NetRoute -DestinationPrefix 0.0.0.0/0 | Sort-Object RouteMetric | Select -First 1).NextHop"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000)
            ip = out.stdout.strip()
            if ip and ip != "0.0.0.0":
                return ip
        except Exception:  # noqa: BLE001
            pass
    return "192.168.1.1"


class PortEdit(QLineEdit):
    """Поле порта без стрелок (QSpinBox с тёмной темой прятал текст)."""

    def __init__(self, value: int = 80):
        super().__init__(str(value))
        self.setValidator(QIntValidator(1, 65535, self))

    def value(self) -> int:
        try:
            return int(self.text())
        except ValueError:
            return 80

    def setValue(self, v: int):
        self.setText(str(int(v)))


class HostStore:
    """Сохранённые роутеры: %APPDATA%\\KeenRoute\\hosts.json, пароли — в Windows Credential Manager."""

    def __init__(self):
        self.path = app_dir() / "hosts.json"
        try:
            self.hosts: list[dict] = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.hosts = []

    def save(self):
        self.path.write_text(json.dumps(self.hosts, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_password(self, h: dict) -> str:
        if not keyring:
            return ""
        try:
            return keyring.get_password(SERVICE, h["id"]) or ""
        except Exception:  # noqa: BLE001
            return ""

    def set_password(self, h: dict, pwd: str | None):
        if not keyring:
            return
        try:
            if pwd:
                keyring.set_password(SERVICE, h["id"], pwd)
            else:
                keyring.delete_password(SERVICE, h["id"])
        except Exception:  # noqa: BLE001
            pass

    def upsert(self, h: dict, pwd: str | None):
        h.setdefault("id", uuid.uuid4().hex)
        for i, x in enumerate(self.hosts):
            if x["id"] == h["id"]:
                self.hosts[i] = h
                break
        else:
            self.hosts.append(h)
        self.set_password(h, pwd)
        self.save()
        return h

    def remove(self, h: dict):
        self.hosts = [x for x in self.hosts if x["id"] != h["id"]]
        self.set_password(h, None)
        self.save()


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KeenRoute — подключение")
        self.setWindowIcon(app_icon())
        self.resize(860, 540)
        self.setMinimumSize(640, 460)
        self.client: RCIClient | None = None
        self.version: dict = {}
        self.host_info: dict = {}
        self.store = HostStore()
        self._cur: dict | None = None
        self._build()
        self._fill()
        if self.store.hosts:
            self.list.setCurrentRow(0)
        else:
            self._new()
        dark_titlebar(self)

    # ---------- UI ----------
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QWidget(objectName="sidebar")
        side.setMinimumWidth(220)
        side.setMaximumWidth(320)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 18, 16, 16)
        sl.setSpacing(10)
        th = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(app_icon().pixmap(28, 28))
        th.addWidget(ic)
        th.addWidget(QLabel("KeenRoute", objectName="title"), 1)
        sl.addLayout(th)
        sl.addWidget(QLabel("СОХРАНЁННЫЕ РОУТЕРЫ", objectName="caption"))
        self.search = QLineEdit(placeholderText="🔍  Поиск")
        self.search.textChanged.connect(self._fill)
        sl.addWidget(self.search)
        self.list = QListWidget()
        self.list.setCursor(Qt.PointingHandCursor)
        self.list.currentItemChanged.connect(self._on_pick)
        self.list.itemDoubleClicked.connect(lambda _: self._connect())
        sl.addWidget(self.list, 1)
        self.empty = QLabel("Пока пусто.\nЗаполните форму справа\nи нажмите «Сохранить».", objectName="muted")
        self.empty.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.empty)
        b = QPushButton("＋  Новый роутер")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(self._new)
        sl.addWidget(b)
        root.addWidget(side)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(28, 24, 28, 22)
        ml.setSpacing(14)
        self.form_title = QLabel("Новый роутер", objectName="title")
        ml.addWidget(self.form_title)
        ml.addWidget(QLabel("Локальный IP, KeenDNS-имя (name.keenetic.pro) или https://адрес для удалённого доступа",
                            objectName="muted", wordWrap=True))

        card = QFrame(objectName="card")
        form = QFormLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.name = QLineEdit(placeholderText="Например: Офис, Дача, Склад")
        self.host = QLineEdit()
        self.port = PortEdit()
        self.port.setFixedWidth(110)
        self.port.setToolTip("80 — обычный вход, 443 — https (KeenDNS)")
        self.user = QLineEdit("admin")
        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.Password)
        self.pwd.returnPressed.connect(self._connect)
        self.keep = QCheckBox("Сохранить пароль (диспетчер учётных данных Windows)")
        self.keep.setChecked(True)
        form.addRow("Имя", self.name)
        form.addRow("Адрес", self.host)
        form.addRow("Порт", self.port)
        form.addRow("Логин", self.user)
        form.addRow("Пароль", self.pwd)
        form.addRow("", self.keep)
        ml.addWidget(card)

        self.state = QLabel("", objectName="muted", wordWrap=True)
        ml.addWidget(self.state)
        ml.addStretch(1)

        row = QHBoxLayout()
        self.del_btn = QPushButton("Удалить", objectName="danger")
        self.del_btn.clicked.connect(self._delete)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        save = QPushButton("Сохранить")
        save.clicked.connect(self._save)
        row.addWidget(save)
        go = QPushButton("Подключиться  →", objectName="primary")
        go.setDefault(True)
        go.clicked.connect(self._connect)
        row.addWidget(go)
        for btn in (self.del_btn, save, go):
            btn.setCursor(Qt.PointingHandCursor)
        ml.addLayout(row)
        root.addWidget(main, 1)

    def _fill(self):
        q = self.search.text().strip().lower() if hasattr(self, "search") else ""
        cur_id = self._cur.get("id") if self._cur else None
        self.list.blockSignals(True)
        self.list.clear()
        for h in self.store.hosts:
            if q and q not in h.get("name", "").lower() and q not in h.get("host", "").lower():
                continue
            sub = h.get("model") or ""
            it = QListWidgetItem(f"{h.get('name') or h['host']}\n{h['host']}{'  ·  ' + sub if sub else ''}")
            it.setData(Qt.UserRole, h)
            it.setToolTip("Двойной клик — подключиться")
            self.list.addItem(it)
            if h["id"] == cur_id:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        self.empty.setVisible(not self.store.hosts)

    def _on_pick(self, item, _prev=None):
        if not item:
            return
        h = item.data(Qt.UserRole)
        self._cur = h
        self.form_title.setText(h.get("name") or h["host"])
        self.name.setText(h.get("name", ""))
        self.host.setText(h["host"])
        self.port.setValue(int(h.get("port", 80)))
        self.user.setText(h.get("user", "admin"))
        pwd = self.store.get_password(h)
        self.pwd.setText(pwd)
        self.keep.setChecked(bool(pwd) or not keyring)
        self.del_btn.setEnabled(True)
        self._status("")

    def _new(self):
        self._cur = None
        self.list.clearSelection()
        self.form_title.setText("Новый роутер")
        self.name.clear()
        self.host.setText(default_gateway())
        self.port.setValue(80)
        self.user.setText("admin")
        self.pwd.clear()
        self.del_btn.setEnabled(False)
        self.name.setFocus()
        self._status("")

    def _status(self, text, color=None):
        self.state.setText(text)
        self.state.setStyleSheet(f"color: {color or COL['muted']};")

    # ---------- действия ----------
    def _form_host(self) -> dict:
        h = dict(self._cur or {})
        h.update(name=self.name.text().strip() or self.host.text().strip(),
                 host=self.host.text().strip(), port=self.port.value(), user=self.user.text().strip())
        return h

    def _save(self, quiet=False):
        h = self._form_host()
        if not h["host"]:
            return self._status("Укажите адрес роутера", COL["bad"])
        self._cur = self.store.upsert(h, self.pwd.text() if self.keep.isChecked() else None)
        self._fill()
        self.form_title.setText(self._cur["name"])
        self.del_btn.setEnabled(True)
        if not quiet:
            self._status("Сохранено", COL["ok"])

    def _delete(self):
        if self._cur and QMessageBox.question(
                self, "Удаление", f"Удалить «{self._cur.get('name')}» из списка?") == QMessageBox.Yes:
            self.store.remove(self._cur)
            self._fill()
            self._new()

    def _connect(self):
        h = self._form_host()
        if not h["host"]:
            return self._status("Укажите адрес роутера", COL["bad"])
        self._status(f"Подключаюсь к {h['host']}…")
        self.setEnabled(False)
        self.repaint()
        try:
            c = RCIClient(h["host"], h["port"])
            c.login(h["user"], self.pwd.text())
            self.version = c.version()
        except Exception as e:  # noqa: BLE001
            self.setEnabled(True)
            self._status(f"Не удалось подключиться: {e}", COL["bad"])
            return
        self.setEnabled(True)
        h["model"] = self.version.get("model") or self.version.get("description") or ""
        if self._cur or self.name.text().strip():  # сохраняем известный/именованный роутер
            self._cur = h
            self._save(quiet=True)
        self.client, self.host_info = c, h
        self.accept()
