"""GUI-тесты на фейковом роутере (запускаются в CI на Windows, offscreen) + скриншоты."""
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from keenetic_dns.ui import main_window as mw  # noqa: E402
from keenetic_dns.ui import theme  # noqa: E402

from .fake_router import FakeRouter  # noqa: E402
from .test_core import CFG  # noqa: E402

SHOTS = Path(__file__).resolve().parent.parent / "screenshots"


IFACES = {"Wireguard0": {"id": "Wireguard0", "type": "Wireguard", "description": "Home", "link": "up"},
          "Wireguard1": {"id": "Wireguard1", "type": "Wireguard", "description": "Europe", "link": "down"}}


def Fake(**kw):
    return FakeRouter(CFG, IFACES, **kw)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("KEENETIC_DNS_NO_UPDATE_CHECK", "1")
    monkeypatch.setenv("KEENETIC_DNS_NO_GEO", "1")
    a = QApplication.instance() or QApplication([])
    theme.apply(a)
    monkeypatch.setattr(mw.PreviewDialog, "exec", lambda self: 1)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    return a


def _wait(app):
    """Ждать, пока завершатся все фоновые задачи, включая запущенные из обработчиков (refresh после apply)."""
    pool = QThreadPool.globalInstance()
    for _ in range(20):
        pool.waitForDone()
        app.processEvents()
        if pool.activeThreadCount() == 0:
            pool.waitForDone()
            app.processEvents()
            if pool.activeThreadCount() == 0:
                break


def _shot(w, name):
    SHOTS.mkdir(exist_ok=True)
    w.grab().save(str(SHOTS / name))


def test_main_window(app):
    fake = Fake()
    w = mw.MainWindow(fake, {"model": "KN-1010", "title": "4.2"}, {"name": "Дом"})
    w.show()
    _wait(app)
    assert w.table.rowCount() == 2 and w.gw.count() == 2
    assert w.iflist.count() == 3  # все + 2 WG со списками (пустые шлюзы не показываются)
    w.iflist.setCurrentRow(1)  # Home (Wireguard0)
    assert [w.table.isRowHidden(r) for r in range(2)] == [True, False]
    w.iflist.setCurrentRow(0)
    assert w.table.item(1, mw.COL_NAME).text() == "YT"  # описание вместо технического имени
    assert w.table.item(1, mw.COL_GW).text() == "Home"

    # галочка на первой строке (chatgpt) → назначить Wireguard0
    w.table.item(0, mw.COL_CHK).setCheckState(Qt.Checked)
    assert [g.name for g in w.checked()] == ["chatgpt"]
    assert w.sel_label.text() == "Выбрано: 1"
    w.table.setCurrentCell(1, mw.COL_NAME)
    _shot(w, "main.png")
    w.gw.setCurrentIndex(0)
    w.assign_selected()
    _wait(app)
    assert fake.ran[-1][:2] == ["no dns-proxy route object-group chatgpt Wireguard1",
                                "dns-proxy route object-group chatgpt Wireguard0 auto reject"]

    # узкое окно — кнопки переносятся
    w.resize(900, 560)
    app.processEvents()
    _shot(w, "main_narrow.png")

    # создать бэкап
    from PySide6.QtWidgets import QFileDialog
    target = SHOTS.parent / "screenshots" / "backup_test.txt"
    SHOTS.mkdir(exist_ok=True)
    orig = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(target), ""))
    try:
        w.make_backup()
        _wait(app)
    finally:
        QFileDialog.getSaveFileName = orig
    assert target.read_text(encoding="utf-8").startswith("system name Test")
    target.unlink()

    # выбрать все + перевести всё на Wireguard1
    w.chk_all.setChecked(True)
    w._check_all()
    assert len(w.checked()) == 2
    w.gw.setCurrentIndex(1)
    w.assign_all()
    _wait(app)
    assert set(fake.ran[-1]) == {"no dns-proxy route object-group youtube Wireguard0",
                                 "dns-proxy route object-group youtube Wireguard1 auto",
                                 "no dns-proxy route object-group chatgpt Wireguard0",
                                 "dns-proxy route object-group chatgpt Wireguard1 auto reject",
                                 "system configuration save"}
    assert w.backup_path and w.backup_path.exists()

    # фейковый роутер реально исполнил команды → все списки на Wireguard1, проверка прошла
    assert all(g.interface == "Wireguard1" for g in fake.groups.values())
    assert w.last_apply["ok"]


def test_rollback_on_error(app):
    fake = Fake(fail_on="include new2.com")
    w = mw.MainWindow(fake, {"model": "KN-1010", "title": "4.2"}, {"name": "Дом"})
    _wait(app)
    before = {n: (g.interface, list(g.domains)) for n, g in fake.groups.items()}
    t = w._target()
    t["youtube"].interface = "Wireguard1"
    t["youtube"].domains += ["new1.com", "new2.com"]
    w.apply(t)          # ошибка на new2.com → вопрос об откате (monkeypatch: «Да»)
    _wait(app)
    _wait(app)
    after = {n: (g.interface, list(g.domains)) for n, g in fake.groups.items()}
    assert not w.last_apply["ok"] and "new2.com" in w.last_apply["error"]
    assert after == before


def test_login_hosts(app):
    from keenetic_dns.ui.login import HostStore, LoginDialog
    st = HostStore()
    st.upsert({"name": "Офис", "host": "office.keenetic.pro", "port": 443, "user": "admin", "model": "Ultra"}, None)
    st.upsert({"name": "Дом", "host": "192.168.1.1", "port": 80, "user": "admin"}, None)
    d = LoginDialog()
    d.show()
    app.processEvents()
    assert d.list.count() == 2
    d.list.setCurrentRow(0)
    assert d.name.text() == "Офис" and d.port.value() == 443
    _shot(d, "login.png")
    d.search.setText("дом")
    assert d.list.count() == 1
    d.search.clear()
    d._new()
    d.name.setText("Дача")
    d.host.setText("https://dacha.keenetic.pro")
    d._save()
    assert [h["name"] for h in HostStore().hosts] == ["Офис", "Дом", "Дача"]
    d._delete()
    assert len(HostStore().hosts) == 2


def test_catalog_dialog_and_db_update(app, tmp_path):
    from keenetic_dns.core import catalog as K
    from keenetic_dns.ui.catalog_dialog import CatalogDialog
    from .test_catalog import FILES
    import time
    db = K.DomainDB(tmp_path / "db.json")
    db.data, db.updated = K.parse_v2fly(FILES), time.time()
    tpl = K.load_templates(str(Path(__file__).resolve().parent.parent / "assets" / "templates.json"))
    fake = Fake()
    w = mw.MainWindow(fake, {"model": "KN-1010", "title": "4.2"}, {"name": "Дом", "id": "home1"})
    _wait(app)
    w.db, w.templates = db, tpl

    d = CatalogDialog(w, w.groups, w.ifaces, db, tpl, "Wireguard0")
    d.show()
    d.q.setText("coral")
    d._search()
    items = [d.results.item(i) for i in range(d.results.count())]
    coral = next(i for i in items if i.data(Qt.UserRole) and i.data(Qt.UserRole).id == "coral")
    coral.setCheckState(Qt.Checked)
    d.q.setText("chatgpt")
    d._search()
    items = [d.results.item(i) for i in range(d.results.count())]
    gpt = next(i for i in items if i.data(Qt.UserRole) and i.data(Qt.UserRole).key == "tpl:chatgpt")
    gpt.setCheckState(Qt.Checked)
    assert set(d.checked) == {"v2fly:coral", "tpl:chatgpt"}
    # снять sora.com у ChatGPT
    for i in range(d.tree.topLevelItemCount()):
        top = d.tree.topLevelItem(i)
        for j in range(top.childCount()):
            if top.child(j).data(0, Qt.UserRole) == "sora.com":
                top.child(j).setCheckState(0, Qt.Unchecked)
    _shot(d, "catalog.png")
    d._accept()
    names = {g.name: g for g, _ in d.result}
    assert names["coral"].domains == ["coralapp.com", "coral.example.org"]
    assert "sora.com" not in names["chatgpt"].domains and names["chatgpt"].interface == "Wireguard0"
    assert names["chatgpt"].description == "ChatGPT / OpenAI"

    # главное окно: применить результат каталога → источники запомнены
    monkey_result = d.result
    orig_exec = CatalogDialog.exec
    CatalogDialog.exec = lambda self: (setattr(self, "result", monkey_result), 1)[1]
    try:
        w.open_catalog()
        _wait(app)
    finally:
        CatalogDialog.exec = orig_exec
    assert w.last_apply["ok"]
    assert "coral" in fake.groups and fake.groups["chatgpt"].interface == "Wireguard0"
    rec = w.sources.for_router("home1")
    assert rec["chatgpt"]["excluded"] == ["sora.com"]

    # в базе у coral появился новый домен → «Обновить списки из базы» добавит только его
    db.data["coral"]["domains"].append("coralcdn.net")
    w.update_from_db()
    _wait(app)
    assert fake.groups["coral"].domains[-1] == "coralcdn.net"
    assert "sora.com" not in fake.groups["chatgpt"].domains


def test_dns_dialog(app):
    from keenetic_dns.core import dns as D
    from .test_dns import CFG as DNS_CFG
    fake = FakeRouter(CFG + DNS_CFG, IFACES)
    w = mw.MainWindow(fake, {"model": "KN-1010", "title": "4.2"}, {"name": "Дом"})
    _wait(app)
    assert len(w.dns) == 5
    d = w.dns_panel
    w.open_dns()
    assert w.tabs.currentWidget() is d and d.cur.topLevelItemCount() >= 4
    for p, kind, cb in d.boxes:
        if p["id"] == "adguard-family" and kind == "dot":
            cb.setChecked(True)
    leaf = next(x for x in d._leaves() if x.data(0, Qt.UserRole).addr == "8.8.8.8")
    d.cur.setCurrentItem(leaf)
    d._remove_selected()  # убрать 8.8.8.8
    assert leaf.font(0).strikeOut()
    assert "из 8" in d.limit.text()
    _shot(w, "dns.png")
    d._accept()  # «Применить» → w.apply_dns
    assert [u.sni for u in d.add] == ["family.adguard-dns.com"] and d.remove[0].addr == "8.8.8.8"
    _wait(app)
    assert w.last_apply["ok"]
    assert D.Upstream("dot", "94.140.14.15", "family.adguard-dns.com") in fake.dns
    assert D.Upstream("plain", "8.8.8.8") not in fake.dns


def test_design_features(app, tmp_path):
    from keenetic_dns.ui import theme
    from keenetic_dns.ui.widgets import Toast
    fake = Fake()
    w = mw.MainWindow(fake, {"model": "KN-1010", "title": "4.2"}, {"name": "Дом"})
    w.show()
    _wait(app)
    # проверка домена: поддомен youtube.com → список YT
    shown = []
    orig = Toast.__init__
    Toast.__init__ = lambda self, parent, text, *a, **k: (shown.append(text), orig(self, parent, text, *a, **k))[1]
    try:
        w.check_domain("m.youtube.com")
        w.check_domain("example.net")
    finally:
        Toast.__init__ = orig
    assert "«YT»" in shown[0] and "Home" in shown[0]
    assert "ни в одном списке" in shown[1]
    # перетаскивание: выбранный список на шлюз Wireguard1
    w.table.setCurrentCell(1, mw.COL_NAME)  # YT
    w._on_drop("Wireguard1")
    _wait(app)
    assert fake.groups["youtube"].interface == "Wireguard1"
    # подсветка ошибок в редакторе
    w.table.setCurrentCell(0, mw.COL_NAME)
    w.editor.setPlainText("a.com\nплохо!!\na.com")
    assert "ошибок: 1" in w.ed_count.text() and "дублей: 1" in w.ed_count.text()
    # светлая тема
    w.toggle_theme(); w.toggle_theme()  # auto → dark → light
    assert not theme.is_dark()
    _shot(w, "main_light.png")
    w.toggle_theme()  # → auto


def test_dns_limit(app):
    from keenetic_dns.core import dns as D
    from keenetic_dns.ui.dns_dialog import DnsPanel
    providers = D.load_providers(str(Path(__file__).resolve().parent.parent / "assets" / "dns.json"))
    applied = []
    d = DnsPanel(None, providers, lambda a, r: applied.append((a, r)))
    d.set_current([])
    for p, kind, cb in d.boxes:
        if kind in ("dot", "doh"):
            cb.setChecked(True)  # 7 провайдеров × 2 = 14 > 8
    assert d._update_limit() == 14 and "14 из 8" in d.limit.text()
    d._accept()
    assert applied == []  # не применено из-за лимита


def test_catalog_db_update_button(app, tmp_path):
    from keenetic_dns.core import catalog as K
    from keenetic_dns.ui.catalog_dialog import CatalogDialog
    import time
    db = K.DomainDB(tmp_path / "db.json")
    db.data, db.updated = {"svc": {"domains": ["svc.com"], "include": [], "skipped": 0}}, time.time()
    db.update = lambda: setattr(db, "last_changed", 1) or 1   # «скачали» базу без интернета
    d = CatalogDialog(None, {}, [], db, [], None, pending_updates=lambda: 2)
    d._update_db()
    _wait(app)
    assert "2" in d.b_apply_upd.text()
    d._apply_updates()
    assert d.apply_db_updates and d.result == []
