"""Импорт/экспорт списков и бэкапы."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import requests

from .model import NAME_RE, Group, clean_list

FORMAT_VERSION = 1


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "KeenRoute"
    old = Path(base) / "KeeneticDNS"  # прежнее название — переносим роутеры, настройки, бэкапы
    if not p.exists() and old.is_dir():
        import shutil
        try:
            shutil.copytree(old, p)
        except OSError:
            pass
    p.mkdir(parents=True, exist_ok=True)
    return p


def export_json(groups: list[Group], path: str | Path, router: dict | None = None) -> None:
    data = {
        "version": FORMAT_VERSION,
        "exported": dt.datetime.now().isoformat(timespec="seconds"),
        "router": router or {},
        "groups": [
            {"name": g.name, "interface": g.interface, "reject": g.reject,
             "description": g.description, "domains": g.domains}
            for g in groups
        ],
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def export_txt(g: Group, path: str | Path) -> None:
    Path(path).write_text("\n".join(g.domains) + "\n", encoding="utf-8")


def safe_name(name: str) -> str:
    n = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)[:32]
    return n if NAME_RE.match(n) else "list"


def import_file(path: str | Path) -> list[Group]:
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        data = json.loads(text)
        out = []
        for it in data.get("groups", []):
            out.append(Group(safe_name(it["name"]), clean_list(it.get("domains", [])),
                             it.get("interface"), bool(it.get("reject")), it.get("description", "")))
        return out
    return [Group(safe_name(p.stem), clean_list(text.splitlines()), description=p.stem)]


def import_url(url: str, name: str) -> Group:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return Group(safe_name(name), clean_list(r.text.splitlines()), description=name)


def backup_name(label: str) -> str:
    clean = "".join(c if c.isalnum() or c in "_-." else "_" for c in label).strip("_") or "router"
    return f"{clean[:40]}_{dt.datetime.now():%Y%m%d_%H%M%S}.txt"


KEEP_BACKUPS = 50


def save_backup(lines: list[str], model: str) -> Path:
    d = app_dir() / "backups"
    d.mkdir(exist_ok=True)
    p = d / backup_name(model)
    prefix = p.name.rsplit("_", 2)[0] + "_"
    old = sorted(x for x in d.glob(prefix + "*.txt"))
    for x in old[:max(0, len(old) - KEEP_BACKUPS + 1)]:
        try:
            x.unlink()
        except OSError:
            pass
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
