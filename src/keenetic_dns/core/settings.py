"""Настройки программы: %APPDATA%\\KeenRoute\\settings.json (токен GitHub — в диспетчере учётных данных)."""
from __future__ import annotations

import json

from .io import app_dir

DEFAULTS = {"check_updates": True, "theme": "auto"}
SERVICE = "KeeneticDNS-github"


def load() -> dict:
    try:
        return {**DEFAULTS, **json.loads((app_dir() / "settings.json").read_text(encoding="utf-8"))}
    except Exception:  # noqa: BLE001
        return dict(DEFAULTS)


def save(s: dict) -> None:
    (app_dir() / "settings.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def get_token() -> str:
    try:
        import keyring
        return keyring.get_password(SERVICE, "token") or ""
    except Exception:  # noqa: BLE001
        return ""


def set_token(token: str) -> None:
    try:
        import keyring
        if token:
            keyring.set_password(SERVICE, "token", token)
        else:
            keyring.delete_password(SERVICE, "token")
    except Exception:  # noqa: BLE001
        pass
