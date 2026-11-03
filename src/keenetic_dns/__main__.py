"""Точка входа. GUI по умолчанию; `--dump IP LOGIN PASSWORD` — отладочный вывод без GUI."""
from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler


def setup_logging():
    from .core.io import app_dir
    d = app_dir() / "logs"
    d.mkdir(exist_ok=True)
    h = RotatingFileHandler(d / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[h],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def dump(host: str, login: str, password: str):
    from .api.rci import RCIClient
    from .core.model import parse_interfaces, parse_running_config
    c = RCIClient(host)
    c.login(login, password)
    v = c.version()
    groups = parse_running_config(c.running_config())
    ifs = parse_interfaces(c.interfaces())
    print(json.dumps({
        "version": {k: v.get(k) for k in ("model", "description", "title", "release", "hw_id")},
        "interfaces": [i.__dict__ for i in ifs],
        "groups": [{"name": g.name, "interface": g.interface, "reject": g.reject, "count": len(g.domains)}
                   for g in groups.values()],
    }, ensure_ascii=False, indent=2))


def offer_install() -> bool:
    """Первый запуск из «Загрузок»: предложить установку в постоянную папку с ярлыками. True — перезапущено оттуда."""
    from PySide6.QtWidgets import QMessageBox

    from .core import install as I
    from .core import settings as S
    if not I.current_exe() or I.is_installed():
        return False
    cfg = S.load()
    if cfg.get("install_declined"):
        return False
    ans = QMessageBox.question(
        None, "Установка KeenRoute",
        f"Установить KeenRoute?\n\nПрограмма будет храниться в\n{I.install_dir()}\n"
        "и появятся ярлыки на рабочем столе и в меню «Пуск».\nОбновления будут ставиться туда же.\n\n"
        "«Нет» — запускать как есть (больше не спрашивать).")
    if ans != QMessageBox.Yes:
        cfg["install_declined"] = True
        S.save(cfg)
        return False
    try:
        exe = I.install()
    except Exception as e:  # noqa: BLE001
        QMessageBox.warning(None, "Установка", f"Не удалось установить: {e}\nПрограмма запустится как есть.")
        return False
    I.launch(exe)
    return True


def main():
    setup_logging()
    if len(sys.argv) >= 2 and sys.argv[1] == "--dump":
        if len(sys.argv) != 5:
            print("Использование: KeenRoute --dump IP LOGIN PASSWORD")
            return 2
        dump(*sys.argv[2:5])
        return 0
    from PySide6.QtWidgets import QApplication, QDialog
    from .ui.login import LoginDialog
    from .ui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("KeenRoute")
    from .ui import theme
    from .core import settings
    theme.apply(app, settings.load().get("theme", "auto"))
    if offer_install():
        return 0
    dlg = LoginDialog()
    if dlg.exec() != QDialog.Accepted:
        return 0
    w = MainWindow(dlg.client, dlg.version, dlg.host_info)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
