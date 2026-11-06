"""Окно «Обновления программы»."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from .. import __version__
from ..core import settings as S
from ..core import updater as U
from .common import run_quiet
from .theme import app_icon, dark_titlebar


class UpdateDialog(QDialog):
    def __init__(self, parent=None, release: U.Release | None = None):
        super().__init__(parent)
        self.setWindowTitle("Обновления программы")
        self.setWindowIcon(app_icon())
        self.resize(560, 360)
        self.rel = release
        self.cfg = S.load()
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Обновления", objectName="title"))
        self.ver = QLabel(f"Установлена версия {__version__}", objectName="muted")
        lay.addWidget(self.ver)
        self.state = QLabel("", objectName="h2", wordWrap=True)
        lay.addWidget(self.state)
        self.notes = QLabel("", objectName="muted", wordWrap=True)
        lay.addWidget(self.notes)
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setFormat("%p%")
        self.bar.setMinimumHeight(20)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.auto = QCheckBox("Проверять обновления при запуске")
        self.auto.setChecked(self.cfg.get("check_updates", True))
        lay.addWidget(self.auto)
        lay.addStretch(1)
        row = QHBoxLayout()
        self.b_check = QPushButton("Проверить")
        self.b_check.clicked.connect(self.check)
        self.b_install = QPushButton("Скачать и установить", objectName="primary")
        self.b_install.clicked.connect(self.install)
        self.b_install.setEnabled(False)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        row.addWidget(self.b_check)
        row.addStretch(1)
        row.addWidget(close)
        row.addWidget(self.b_install)
        lay.addLayout(row)
        self.finished.connect(self._save)
        dark_titlebar(self)
        if release:
            self._show(release)
        else:
            self.check()

    def _save(self, *_):
        self.cfg["check_updates"] = self.auto.isChecked()
        S.save(self.cfg)

    def check(self):
        self._save()
        self.state.setText("Проверяю…")
        self.b_check.setEnabled(False)
        run_quiet(U.check, self._show, self._fail, None)

    def _fail(self, msg):
        self.b_check.setEnabled(True)
        self.state.setText(f"Не удалось проверить: {msg}")

    def _show(self, rel):
        self.b_check.setEnabled(True)
        self.rel = rel
        if not rel:
            self.state.setText("В последнем релизе нет файла программы.")
        elif rel.newer:
            self.state.setText(f"Доступна новая версия {rel.version}")
            self.notes.setText(rel.notes[:600])
            self.b_install.setEnabled(True)
        else:
            self.state.setText(f"У вас последняя версия ({rel.version}).")

    def install(self):
        if not U.can_self_update():
            return QMessageBox.information(self, "Обновление",
                                           "Программа запущена не из exe — обновите исходники через git pull.")
        self.b_install.setEnabled(False)
        self.bar.setVisible(True)
        self.state.setText(f"Скачиваю {self.rel.version}…")
        self._done = [0]  # байт скачано — пишет фоновый поток, читает таймер
        self._t0, self._speed = None, []
        self.bar.setValue(0)
        if not self.rel.size:
            self.bar.setRange(0, 0)  # размер неизвестен — «бегущая» полоса
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(300)
        run_quiet(U.download, self._downloaded, self._fail_dl, self.rel, None,
                  lambda n: self._done.__setitem__(0, n))

    def _tick(self):
        import time
        n, total = self._done[0], self.rel.size or 0
        now = time.monotonic()
        self._speed = [x for x in self._speed if now - x[0] < 5] + [(now, n)]  # скорость за последние 5 с
        (t1, n1), (t2, n2) = self._speed[0], self._speed[-1]
        bps = (n2 - n1) / (t2 - t1) if t2 > t1 else 0
        if total:
            self.bar.setValue(int(n * 100 / total))
        txt = f"Скачиваю {self.rel.version}… {n / 1048576:.1f}" + (f" из {total / 1048576:.1f} МБ" if total else " МБ")
        if bps > 0:
            txt += f" · {bps / 1024:.0f} КБ/с"
            if total:
                left = int((total - n) / bps)
                txt += f" · осталось ~{left // 60}:{left % 60:02d}"
        self.state.setText(txt)

    def _fail_dl(self, e):
        self._timer.stop()
        self.b_install.setEnabled(True)
        self._fail(e)

    def _downloaded(self, path):
        self._timer.stop()
        self.bar.setValue(100)
        self.state.setText("Устанавливаю и перезапускаю…")
        try:
            U.install_and_restart(path)
        except Exception as e:  # noqa: BLE001
            self.b_install.setEnabled(True)
            self.state.setText("Не удалось установить обновление")
            return QMessageBox.warning(self, "Обновление",
                                       f"Не удалось заменить файл программы:\n{e}\n\n"
                                       "Скачайте KeenRoute.exe со страницы проекта вручную.")
        QApplication.quit()
