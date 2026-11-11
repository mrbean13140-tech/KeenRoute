import datetime as dt

from keenetic_dns.core import history as H


def test_history_store(tmp_path):
    st = H.HistoryStore(tmp_path / "h.json")
    st.add("r1", "lists", "Назначен шлюз", ["~ «YouTube»: шлюз A → B"], "Дом_1.txt")
    st.add("r1", "dns", "DoT / DoH", ["+ Добавить DoT"], "Дом_2.txt")
    items = H.HistoryStore(tmp_path / "h.json").for_router("r1")
    assert [i["title"] for i in items] == ["DoT / DoH", "Назначен шлюз"]
    assert H.HistoryStore(tmp_path / "h.json").for_router("r2") == []


def test_human_when():
    now = dt.datetime(2026, 11, 12, 15, 0)
    assert H.human_when("2026-11-12T14:32:00", now) == "сегодня, 14:32"
    assert H.human_when("2026-11-11T22:10:00", now) == "вчера, 22:10"
    assert H.human_when("2026-11-03T09:05:00", now) == "3 ноя, 09:05"


def test_list_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from keenetic_dns.core import io
    (io.app_dir() / "backups").mkdir()
    (io.app_dir() / "backups" / "Дом_20261112_1.txt").write_text("x" * 3000)
    (io.app_dir() / "backups" / "Офис_20261112_1.txt").write_text("y")
    assert [b["name"] for b in H.list_backups("Дом")] == ["Дом_20261112_1.txt"]
    assert H.list_backups("Дом")[0]["size"] == "3 КБ"
