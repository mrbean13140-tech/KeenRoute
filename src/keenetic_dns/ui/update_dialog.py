"""Окно «Обновления программы»."""
from __future__ import annotations

from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
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
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.auto = QCheckBox("Проверять обновления при запуске")
        self.auto.setChecked(self.cfg.get("check_updates", True))
        lay.addWidget(self.auto)
        lay.addWidget(QLabel("Токен GitHub (не нужен — репозиторий публичный; укажите, только если GitHub ограничивает запросы):",
                             objectName="muted", wordWrap=True))
        self.token = QLineEdit(S.get_token())
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("github_pat_…")
        lay.addWidget(self.token)
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
        S.set_token(self.token.text().strip())

    def check(self):
        self._save()
        self.state.setText("Проверяю…")
        self.b_check.setEnabled(False)
        run_quiet(U.check, self._show, self._fail, self.token.text().strip() or None)

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
        run_quiet(U.download, self._downloaded, self._fail, self.rel, self.token.text().strip() or None)

    def _downloaded(self, path):
        self.bar.setValue(100)
        self.state.setText("Устанавливаю и перезапускаю…")
        U.install_and_restart(path)
        QApplication.quit()
