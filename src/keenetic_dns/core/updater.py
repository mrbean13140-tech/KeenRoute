"""Автообновление программы из GitHub Releases."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

from .. import __version__

REPO = "mrbean13140-tech/KeenRoute"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "KeenRoute.exe"
ASSET_OLD = "KeeneticDNS.exe"  # старые версии ищут этот файл


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:3]) or (0,)


@dataclass
class Release:
    version: str
    notes: str
    asset_url: str        # API-URL ассета (работает и для приватного репозитория с токеном)
    download_url: str     # прямая ссылка (для публичного)
    size: int

    @property
    def newer(self) -> bool:
        return parse_version(self.version) > parse_version(__version__)


def _headers(token: str | None, binary: bool = False) -> dict:
    h = {"Accept": "application/octet-stream" if binary else "application/vnd.github+json",
         "User-Agent": "KeenRoute-updater"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def check(token: str | None = None, timeout: float = 15) -> Release | None:
    r = requests.get(API, headers=_headers(token), timeout=timeout)
    if r.status_code == 404:
        raise RuntimeError("Релиз не найден. Если репозиторий приватный — укажите токен GitHub в настройках обновлений.")
    if r.status_code in (401, 403):
        raise RuntimeError("GitHub отклонил запрос: проверьте токен в настройках обновлений.")
    r.raise_for_status()
    j = r.json()
    a = next((x for x in j.get("assets", []) if x.get("name") == ASSET), None) or \
        next((x for x in j.get("assets", []) if x.get("name") == ASSET_OLD), None)
    if not a:
        return None
    return Release(j.get("tag_name", ""), j.get("body", "") or "", a["url"], a["browser_download_url"], a.get("size", 0))


def download(rel: Release, token: str | None = None, progress=None) -> Path:
    url = rel.asset_url if token else rel.download_url
    dst = Path(tempfile.gettempdir()) / f"KeenRoute_{rel.version}.exe"
    with requests.get(url, headers=_headers(token, binary=True), stream=True, timeout=60) as r:
        r.raise_for_status()
        done = 0
        with open(dst, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                f.write(chunk)
                done += len(chunk)
                if progress and rel.size:
                    progress(int(done * 100 / rel.size))
    if rel.size and dst.stat().st_size != rel.size:
        raise RuntimeError("Файл обновления скачался не полностью")
    return dst


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def install_and_restart(new_exe: Path) -> None:
    """Подменяет текущий exe новым после выхода программы и запускает его. Вызывающий должен сразу закрыть приложение."""
    cur = Path(sys.executable)
    script = Path(tempfile.gettempdir()) / "keenroute_update.cmd"
    script.write_text(
        "@echo off\r\n"
        f"set PID={os.getpid()}\r\n"
        ":wait\r\n"
        'tasklist /FI "PID eq %PID%" | find "%PID%" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
        f'move /y "{new_exe}" "{cur}" >nul\r\n'
        f'start "" "{cur}"\r\n'
        'del "%~f0"\r\n', encoding="cp866")
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000 | 0x00000008, close_fds=True)
