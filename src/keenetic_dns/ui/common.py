"""Общие вещи UI: фоновые задачи и диалоги."""
from __future__ import annotations

import logging
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)


log = logging.getLogger(__name__)


class _Signals(QObject):
    done = Signal(object)
    error = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, *a, **kw):
        super().__init__()
        self.setAutoDelete(False)  # временем жизни управляем сами (см. _start)
        self.fn, self.a, self.kw = fn, a, kw
        self.sig = _Signals()

    def run(self):
        try:
            res = self.fn(*self.a, **self.kw)
        except Exception as e:  # noqa: BLE001
            log.exception("Фоновая задача упала")
            self.sig.error.emit(str(e) or e.__class__.__name__)
            return
        self.sig.done.emit(res)


_keep: set = set()


def _safe(fn, *a):
    """Ошибка в обработчике не должна ронять программу."""
    try:
        fn(*a)
    except RuntimeError as e:
        if "already deleted" in str(e):  # окно закрыли, пока шла фоновая задача — просто игнорируем
            log.info("Окно закрыто до завершения задачи")
            return
        log.exception("Ошибка в обработчике")
        QMessageBox.critical(None, "Ошибка", f"{e.__class__.__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        log.exception("Ошибка в обработчике")
        traceback.print_exc()
        QMessageBox.critical(None, "Ошибка", f"{e.__class__.__name__}: {e}")


def _start(t: _Task, on_done, on_error):
    """Держим задачу живой, пока её сигналы не обработаны; отпускаем на следующем витке цикла событий
    (удаление объекта прямо внутри его же сигнала роняло программу)."""
    _keep.add(t)

    def release():
        QTimer.singleShot(0, lambda: _keep.discard(t))

    t.sig.done.connect(lambda r: (_safe(on_done, r), release()))
    t.sig.error.connect(lambda m: (_safe(on_error, m), release()))
    QThreadPool.globalInstance().start(t)


def run_bg(parent: QWidget, fn, on_done, *a, busy: str = "Подождите…", **kw):
    """Запускает fn в пуле потоков; окно блокируется на время работы."""
    parent.setEnabled(False)
    if hasattr(parent, "statusBar"):
        parent.statusBar().showMessage(busy)

    def finish():
        parent.setEnabled(True)
        if hasattr(parent, "statusBar"):
            parent.statusBar().clearMessage()

    _start(_Task(fn, *a, **kw),
           lambda r: (finish(), on_done(r)),
           lambda m: (finish(), QMessageBox.critical(parent, "Ошибка", m)))


def run_quiet(fn, on_done, on_error=None, *a, **kw):
    """Фоновая задача без блокировки окна (обновление базы, запросы в интернет)."""
    _start(_Task(fn, *a, **kw), on_done, on_error or (lambda m: log.warning("Фон: %s", m)))


class PreviewDialog(QDialog):
    """Предпросмотр: сводка «было → станет» + CLI-команды по кнопке."""

    def __init__(self, cmds: list[str], parent=None, summary: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Предпросмотр изменений")
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        n = len([c for c in cmds if c != "system configuration save"])
        head = QLabel("Предпросмотр изменений")
        head.setObjectName("title")
        lay.addWidget(head)
        sub = QLabel("Перед применением сделаю бэкап, после — проверю конфигурацию роутера; при ошибке предложу откат.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        badges = QHBoxLayout()
        badges.setSpacing(6)
        lines = summary or []
        for sign, obj, word in (("+", "badgeAdd", "добавится"), ("~", "badgeMod", "изменится"), ("−", "badgeDel", "удалится")):
            k = sum(1 for x in lines if x[:1] == sign)
            if k:
                b = QLabel(f"{sign} {k} {word}")
                b.setObjectName(obj)
                badges.addWidget(b)
        cnt = QLabel(f"{n} команд")
        cnt.setObjectName("badge")
        badges.addWidget(cnt)
        badges.addStretch(1)
        lay.addLayout(badges)
        lst = QListWidget()
        from .theme import C as COL
        colors = {"+": COL["ok"], "−": COL["bad"], "~": COL["warn"]}
        for line in summary or []:
            it = QListWidgetItem(line)
            if line[:1] in colors:
                it.setForeground(QColor(colors[line[:1]]))
            lst.addItem(it)
        lay.addWidget(lst, 1)
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
