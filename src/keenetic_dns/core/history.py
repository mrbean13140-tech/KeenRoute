"""История применённых изменений (по роутеру) и список бэкапов."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .io import app_dir

KEEP = 200


class HistoryStore:
    """%APPDATA%\\KeenRoute\\history.json — {роутер: [{at, kind, title, lines, backup}]} (новые первыми)."""

    def __init__(self, path: Path | None = None):
        self.path = path or (app_dir() / "history.json")
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.data = {}

    def add(self, router: str, kind: str, title: str, lines: list[str], backup: str | None):
        rec = {"at": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind, "title": title,
               "lines": list(lines)[:20], "backup": backup or ""}
        items = self.data.setdefault(router, [])
        items.insert(0, rec)
        del items[KEEP:]
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        return rec

    def for_router(self, router: str) -> list[dict]:
        return list(self.data.get(router, []))


def human_when(iso: str, now: dt.datetime | None = None) -> str:
    try:
        t = dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    now = now or dt.datetime.now()
    hm = t.strftime("%H:%M")
    if t.date() == now.date():
        return f"сегодня, {hm}"
    if (now.date() - t.date()).days == 1:
        return f"вчера, {hm}"
    months = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    return f"{t.day} {months[t.month - 1]}, {hm}"


def list_backups(label_prefix: str | None = None) -> list[dict]:
    """Файлы бэкапов (новые первыми): {path, name, when, size}."""
    d = app_dir() / "backups"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.txt"), key=lambda x: x.stat().st_mtime, reverse=True):
        if label_prefix and not p.name.startswith(label_prefix):
            continue
        st = p.stat()
        out.append({"path": p, "name": p.name,
                    "when": human_when(dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")),
                    "size": f"{max(1, round(st.st_size / 1024))} КБ"})
    return out
