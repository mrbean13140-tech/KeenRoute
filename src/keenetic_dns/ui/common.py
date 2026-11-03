"""Общие вещи UI: фоновые задачи и диалоги."""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)


class _Signals(QObject):
    done = Signal(object)
    error = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, *a, **kw):
        super().__init__()
        self.fn, self.a, self.kw = fn, a, kw
        self.sig = _Signals()

    def run(self):
        try:
            self.sig.done.emit(self.fn(*self.a, **self.kw))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.sig.error.emit(str(e))


def run_bg(parent: QWidget, fn, on_done, *a, busy: str = "Подождите…", **kw):
    """Запускает fn в пуле потоков; UI блокируется курсором и статусом."""
    parent.setEnabled(False)
    if hasattr(parent, "statusBar"):
        parent.statusBar().showMessage(busy)
    t = _Task(fn, *a, **kw)

    def finish():
        parent.setEnabled(True)
        if hasattr(parent, "statusBar"):
            parent.statusBar().clearMessage()

    t.sig.done.connect(lambda r: (finish(), on_done(r)))
    t.sig.error.connect(lambda m: (finish(), QMessageBox.critical(parent, "Ошибка", m)))
    QThreadPool.globalInstance().start(t)
    parent._last_task = t  # держим ссылку


def run_quiet(fn, on_done, on_error=None, *a, **kw):
    """Фоновая задача без блокировки окна (обновление базы, запросы в интернет)."""
    t = _Task(fn, *a, **kw)
    t.sig.done.connect(on_done)
    t.sig.error.connect(on_error or (lambda m: None))
    QThreadPool.globalInstance().start(t)
    _keep.append(t)
    t.sig.done.connect(lambda *_: _keep.remove(t) if t in _keep else None)
    t.sig.error.connect(lambda *_: _keep.remove(t) if t in _keep else None)


_keep: list = []


class PreviewDialog(QDialog):
    """Предпросмотр: сводка «было → станет» + CLI-команды по кнопке."""

    def __init__(self, cmds: list[str], parent=None, summary: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Предпросмотр изменений")
        self.resize(680, 460)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        n = len([c for c in cmds if c != "system configuration save"])
        head = QLabel("Что изменится на роутере")
        head.setObjectName("h2")
        lay.addWidget(head)
        lst = QListWidget()
        colors = {"+": "#3fb950", "−": "#f85149", "~": "#d29922"}
        for line in summary or []:
            it = QListWidgetItem(line)
            if line[:1] in colors:
                it.setForeground(QColor(colors[line[:1]]))
            lst.addItem(it)
        lay.addWidget(lst, 1)
        info = QLabel(f"Команд: {n}. Перед применением будет сделан бэкап, после — проверка; "
                      "при ошибке программа предложит откат.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.txt = QPlainTextEdit("\n".join(cmds))
        self.txt.setReadOnly(True)
        self.txt.setVisible(not summary)
        lay.addWidget(self.txt, 1)
        row = QHBoxLayout()
        tog = QPushButton("Показать команды")
        tog.clicked.connect(lambda: (self.txt.setVisible(not self.txt.isVisible()),
                                     tog.setText("Скрыть команды" if self.txt.isVisible() else "Показать команды")))
        row.addWidget(tog)
        row.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Применить")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
