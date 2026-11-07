"""Вкладка «Политики»: выбрать или создать политику доступа и перевести на неё устройства (можно все сразу)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import policy as P
from .icons import set_icon

DEFAULT = ""  # политика по умолчанию (без привязки)


class NewPolicyDialog(QDialog):
    """Новая политика: название и выходы (интерфейсы) в порядке приоритета."""

    def __init__(self, parent, name: str, ifaces, edit: P.Policy | None = None):
        super().__init__(parent)
        self.setWindowTitle("Изменить политику" if edit else "Новая политика")
        self.resize(420, 380)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.desc = QLineEdit(placeholderText="например: Дети, ТВ, Через VPN")
        form.addRow("Имя на роутере:", self.name)
        form.addRow("Название:", self.desc)
        lay.addLayout(form)
        lay.addWidget(QLabel("Через какие подключения выходить в интернет (сверху — основное):", objectName="muted",
                             wordWrap=True))
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.InternalMove)
        if edit:
            self.name.setReadOnly(True)
            self.name.setToolTip("Имя на роутере не меняется")
            self.desc.setText(edit.description)
            order = {n: k for k, n in enumerate(edit.permits)}
            known = {i.name for i in ifaces}
            ifaces = sorted(ifaces, key=lambda i: order.get(i.name, 999)) + \
                [type("X", (), {"name": n, "description": "", "short": n})() for n in edit.permits if n not in known]
        for i in ifaces:
            it = QListWidgetItem(f"{i.short}  ({i.name})" if i.description else i.name)
            it.setData(Qt.UserRole, i.name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if edit and i.name in edit.permits else Qt.Unchecked)
            self.lst.addItem(it)
        lay.addWidget(self.lst, 1)
        lay.addWidget(QLabel("Порядок меняется перетаскиванием.", objectName="muted"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def permits(self) -> list[str]:
        return [self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())
                if self.lst.item(i).checkState() == Qt.Checked]

    def _ok(self):
        n = self.name.text().strip()
        if not n or not all(c.isascii() and (c.isalnum() or c in "_-") for c in n):
            return QMessageBox.warning(self, "Имя", "Имя на роутере — латиница, цифры, «_» и «-», без пробелов.")
        if not self.permits():
            return QMessageBox.warning(self, "Выход", "Отметьте хотя бы одно подключение.")
        self.accept()

    def policy(self) -> P.Policy:
        return P.Policy(self.name.text().strip(), self.desc.text().strip(), self.permits())


class PolicyPanel(QWidget):
    """on_apply(macs, policy_name|None, new_policy|None)."""

    COLS = ["", "Устройство", "MAC", "IP", "Сейчас"]

    def __init__(self, parent, on_apply, on_change=None):
        super().__init__(parent)
        self.on_apply, self.on_change = on_apply, on_change
        self.policies: dict[str, P.Policy] = {}
        self.devices: dict[str, P.Device] = {}
        self.ifaces = []
        self.new: P.Policy | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)
        root.addWidget(QLabel("Политики доступа", objectName="h2"))
        root.addWidget(QLabel("Политика задаёт, через какое подключение устройство выходит в интернет. "
                              "Выберите или создайте политику, отметьте устройства и нажмите «Применить».",
                              objectName="muted", wordWrap=True))
        top = QHBoxLayout()
        top.addWidget(QLabel("Политика:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        self.combo.currentIndexChanged.connect(self._update)
        top.addWidget(self.combo)
        add = QPushButton("Создать политику…")
        set_icon(add, "plus")
        add.clicked.connect(self.create_policy)
        top.addWidget(add)
        self.b_edit = QPushButton("Изменить…")
        self.b_edit.setToolTip("Название и подключения выбранной политики")
        self.b_edit.clicked.connect(self.edit_policy)
        top.addWidget(self.b_edit)
        self.b_del = QPushButton("Удалить", objectName="danger")
        set_icon(self.b_del, "trash", "danger")
        self.b_del.setToolTip("Удалить выбранную политику; её устройства перейдут на политику по умолчанию")
        self.b_del.clicked.connect(self.delete_policy)
        top.addWidget(self.b_del)
        self.permits = QLabel("", objectName="muted")
        top.addWidget(self.permits, 1)
        root.addLayout(top)

        flt = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Поиск по имени, MAC или IP")
        self.search.textChanged.connect(self._filter)
        flt.addWidget(self.search, 1)
        self.only_online = QCheckBox("Только в сети")
        self.only_online.toggled.connect(self._filter)
        flt.addWidget(self.only_online)
        all_b = QPushButton("Отметить все")
        all_b.clicked.connect(lambda: self.check_all(True))
        none_b = QPushButton("Снять все")
        none_b.clicked.connect(lambda: self.check_all(False))
        flt.addWidget(all_b)
        flt.addWidget(none_b)
        root.addLayout(flt)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._update)
        self.table.cellDoubleClicked.connect(self._toggle_row)
        root.addWidget(self.table, 1)

        bot = QHBoxLayout()
        self.info = QLabel("", objectName="muted")
        bot.addWidget(self.info, 1)
        self.ok = QPushButton("Применить", objectName="primary")
        self.ok.clicked.connect(self.accept)
        bot.addWidget(self.ok)
        root.addLayout(bot)

    # ---------- данные ----------
    def set_data(self, policies: dict[str, P.Policy], devices: dict[str, P.Device], ifaces):
        keep = self.current_policy()
        self.policies, self.devices, self.ifaces = policies, devices, ifaces
        self.new = None
        self._fill_combo(keep)
        checked = set(self.checked())
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for d in sorted(devices.values(), key=lambda x: (not x.online, x.title.lower())):
            r = self.table.rowCount()
            self.table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if d.mac in checked else Qt.Unchecked)
            chk.setData(Qt.UserRole, d.mac)
            pol = policies[d.policy].title if d.policy in policies else (d.policy or "по умолчанию")
            cells = [chk, QTableWidgetItem(("● " if d.online else "○ ") + d.title), QTableWidgetItem(d.mac),
                     QTableWidgetItem(d.ip), QTableWidgetItem(pol)]
            for c, it in enumerate(cells):
                self.table.setItem(r, c, it)
        self.table.blockSignals(False)
        self._filter()

    def _fill_combo(self, keep=None):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("По умолчанию (без политики)", DEFAULT)
        for p in sorted(self.policies.values(), key=lambda x: x.title.lower()):
            self.combo.addItem(p.title + (f"  ({p.name})" if p.description else ""), p.name)
        if self.new:
            self.combo.addItem(f"{self.new.title}  (новая)", self.new.name)
        i = self.combo.findData(keep) if keep is not None else -1
        self.combo.setCurrentIndex(max(i, 0))
        self.combo.blockSignals(False)
        self._update()

    def current_policy(self) -> str | None:
        v = self.combo.currentData() if self.combo.count() else None
        return v or None

    def checked(self) -> list[str]:
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    # ---------- действия ----------
    def create_policy(self):
        dlg = NewPolicyDialog(self, P.next_policy_name({**self.policies, **({self.new.name: self.new} if self.new else {})}),
                              self.ifaces)
        if dlg.exec() != QDialog.Accepted:
            return
        p = dlg.policy()
        if p.name in self.policies:
            return QMessageBox.warning(self, "Политика", f"Политика {p.name} уже есть на роутере — выберите её в списке.")
        self.new = p
        self._fill_combo(p.name)

    def _selected(self) -> P.Policy | None:
        name = self.current_policy()
        if self.new and self.new.name == name:
            return self.new
        return self.policies.get(name or "")

    def edit_policy(self):
        p = self._selected()
        if not p:
            return
        dlg = NewPolicyDialog(self, p.name, self.ifaces, edit=p)
        if dlg.exec() != QDialog.Accepted:
            return
        new = dlg.policy()
        if p is self.new:  # ещё не на роутере — просто поправить черновик
            self.new = new
            return self._fill_combo(new.name)
        cmds, summary = P.edit_cmds(p, new)
        if not cmds:
            return QMessageBox.information(self, "Политики", "Ничего не изменилось.")
        self.on_change(cmds, summary, p.name, new)

    def delete_policy(self):
        p = self._selected()
        if not p:
            return
        if p is self.new:
            self.new = None
            return self._fill_combo(DEFAULT)
        bound = [d for d in self.devices.values() if d.policy == p.name]
        msg = f"Удалить политику «{p.title}»?"
        if bound:
            msg += f"\n\nУстройств на ней: {len(bound)} — они перейдут на политику по умолчанию."
        if QMessageBox.question(self, "Удаление политики", msg) != QMessageBox.Yes:
            return
        cmds, summary = P.delete_cmds(p, self.devices)
        self.on_change(cmds, summary, p.name, None)

    def check_all(self, on: bool):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                self.table.item(r, 0).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update()

    def _toggle_row(self, r, _c):
        it = self.table.item(r, 0)
        it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def _filter(self, *_):
        q = self.search.text().strip().lower()
        for r in range(self.table.rowCount()):
            d = self.devices.get(self.table.item(r, 0).data(Qt.UserRole))
            hide = bool(d) and bool((self.only_online.isChecked() and not d.online) or
                                    (q and q not in f"{d.title} {d.mac} {d.ip}".lower()))
            self.table.setRowHidden(r, hide)

    def _update(self, *_):
        name = self.current_policy()
        p = self.new if self.new and self.new.name == name else self.policies.get(name or "")
        self.permits.setText(f"выход: {' → '.join(p.permits)}" if p and p.permits else
                             "" if p else "основное подключение роутера")
        n = len(self.checked())
        self.info.setText(f"Отмечено устройств: {n}")
        self.ok.setEnabled(bool(n) or bool(self.new))
        existing = (name or "") in self.policies
        self.b_edit.setEnabled(existing or bool(self.new and self.new.name == name))
        self.b_del.setEnabled(existing or bool(self.new and self.new.name == name))

    def accept(self):
        macs = self.checked()
        name = self.current_policy()
        new = self.new if self.new and self.new.name == name else None
        if not macs and not new:
            return QMessageBox.information(self, "Политики", "Отметьте устройства.")
        self.on_apply(macs, name, new)
