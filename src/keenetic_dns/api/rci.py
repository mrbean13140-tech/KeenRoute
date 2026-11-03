"""Клиент RCI (REST API) роутеров Keenetic/Netcraze."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import requests

log = logging.getLogger(__name__)


class RCIError(Exception):
    pass


class AuthError(RCIError):
    pass


def auth_hash(login: str, password: str, realm: str, challenge: str) -> str:
    md5 = hashlib.md5(f"{login}:{realm}:{password}".encode()).hexdigest()
    return hashlib.sha256((challenge + md5).encode()).hexdigest()


class RCIClient:
    def __init__(self, host: str, port: int = 80, timeout: float = 10.0):
        host = host.strip().rstrip("/")
        if "://" in host:  # удалённый доступ: https://name.keenetic.pro
            scheme, rest = host.split("://", 1)
            if ":" not in rest and port not in (80, 443):
                rest = f"{rest}:{port}"
            self.base = f"{scheme}://{rest}"
        else:
            self.base = f"http://{host}:{port}"
        self.timeout = timeout
        self.s = requests.Session()

    # --- авторизация ---
    def login(self, login: str, password: str) -> None:
        self._cred = (login, password)  # для автоматического повторного входа, когда роутер сбросит сессию
        try:
            r = self.s.get(f"{self.base}/auth", timeout=self.timeout)
        except requests.RequestException as e:
            raise RCIError(f"Роутер недоступен: {e}") from e
        if r.status_code == 200:
            return  # уже авторизованы / без пароля
        realm = r.headers.get("X-NDM-Realm")
        challenge = r.headers.get("X-NDM-Challenge")
        if r.status_code != 401 or not realm or not challenge:
            raise RCIError("Это не похоже на роутер Keenetic (нет X-NDM-заголовков)")
        r = self.s.post(
            f"{self.base}/auth",
            json={"login": login, "password": auth_hash(login, password, realm, challenge)},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise AuthError("Неверный логин или пароль")
        log.info("Авторизация на %s успешна", self.base)

    # --- запросы ---
    def _relogin(self) -> bool:
        cred = getattr(self, "_cred", None)
        if not cred:
            return False
        log.info("Сессия истекла — вхожу заново")
        self.s.cookies.clear()
        self.login(*cred)
        return True

    def get(self, path: str) -> Any:
        r = self.s.get(f"{self.base}/rci/{path.strip('/')}", timeout=self.timeout)
        if r.status_code == 401 and self._relogin():
            r = self.s.get(f"{self.base}/rci/{path.strip('/')}", timeout=self.timeout)
        if r.status_code == 401:
            raise AuthError("Сессия истекла, войдите заново")
        r.raise_for_status()
        return r.json()

    def run(self, commands: list[str]) -> list[Any]:
        """Выполняет пакет CLI-команд. Бросает RCIError при ошибке любой из них."""
        if not commands:
            return []
        def post():
            return self.s.post(f"{self.base}/rci/", json=[{"parse": c} for c in commands],
                               timeout=max(self.timeout, 5 + len(commands) * 0.2))
        r = post()
        if r.status_code == 401 and self._relogin():
            r = post()
        if r.status_code == 401:
            raise AuthError("Сессия истекла, войдите заново")
        r.raise_for_status()
        res = r.json()
        errors = []
        for cmd, item in zip(commands, res):
            for st in _statuses(item):
                if st.get("status") == "error":
                    errors.append(f"{cmd}: {st.get('message', 'ошибка')}")
        if errors:
            raise RCIError("Роутер вернул ошибки:\n" + "\n".join(errors))
        return res

    # --- высокоуровневое чтение ---
    def version(self) -> dict:
        return self.get("show/version")

    def interfaces(self) -> dict:
        return self.get("show/interface")

    def running_config(self) -> list[str]:
        data = self.get("show/running-config")
        if isinstance(data, dict):
            data = data.get("message", [])
        return [str(x) for x in data]


def _statuses(obj: Any):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "status" and isinstance(v, list):
                yield from (x for x in v if isinstance(x, dict))
            else:
                yield from _statuses(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _statuses(v)
