"""Установка в %LOCALAPPDATA%\\Programs\\KeenRoute и ярлыки (рабочий стол, меню «Пуск»)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP = "KeenRoute"
NO_WINDOW = 0x08000000


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / APP


def installed_exe() -> Path:
    return install_dir() / f"{APP}.exe"


def current_exe() -> Path | None:
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def is_installed() -> bool:
    cur = current_exe()
    return bool(cur) and cur == installed_exe().resolve()


def _ps(script: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    return r.stdout.strip()


def _q(p) -> str:
    return "'" + str(p).replace("'", "''") + "'"


def create_shortcuts(target: Path) -> list[str]:
    """Ярлыки на рабочем столе и в меню «Пуск». Путь рабочего стола берётся у Windows (OneDrive, русская папка и т.п.)."""
    script = (
        "$w = New-Object -ComObject WScript.Shell;"
        "$out = @();"
        "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {"
        f"  $l = $w.CreateShortcut((Join-Path $d '{APP}.lnk'));"
        f"  $l.TargetPath = {_q(target)}; $l.WorkingDirectory = {_q(target.parent)};"
        f"  $l.IconLocation = {_q(target)} + ',0'; $l.Description = 'Умные DNS-маршруты для Keenetic';"
        "  $l.Save(); $out += $l.FullName };"
        "$out -join \"`n\""
    )
    return [x for x in _ps(script).splitlines() if x]


def install() -> Path:
    """Копирует текущий exe в постоянную папку и создаёт ярлыки. Возвращает путь установленного exe."""
    cur = current_exe()
    if not cur:
        raise RuntimeError("Установка доступна только из exe")
    dst = installed_exe()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if cur != dst.resolve():
        shutil.copy2(cur, dst)
    create_shortcuts(dst)
    return dst


def launch(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=0x00000008, close_fds=True)
