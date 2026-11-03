"""Страна выхода VPN-туннелей: endpoint пира WireGuard → геолокация по IP."""
from __future__ import annotations

import re
import socket

import requests

HOST_RE = re.compile(r"^\[?([A-Za-z0-9.\-:]+?)\]?(?::(\d+))?$")


def _find_endpoint(obj) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("remote", "endpoint", "remote-endpoint", "via") and isinstance(v, str) and "." in v:
                return v
        for v in obj.values():
            r = _find_endpoint(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_endpoint(v)
            if r:
                return r
    return None


def endpoint_ip(client, iface: str) -> str | None:
    res = client.run([f"show interface {iface}"])
    ep = _find_endpoint(res)
    if not ep:
        return None
    m = HOST_RE.match(ep.strip())
    host = m.group(1) if m else ep
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        try:
            return socket.gethostbyname(host)
        except OSError:
            return None


def country_of(ip: str) -> str:
    try:
        j = requests.get(f"https://ipwho.is/{ip}", params={"fields": "success,country_code"}, timeout=8).json()
        if j.get("success") and j.get("country_code"):
            return j["country_code"]
    except Exception:  # noqa: BLE001
        pass
    try:
        j = requests.get(f"http://ip-api.com/json/{ip}", params={"fields": "countryCode"}, timeout=8).json()
        return j.get("countryCode", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def tunnel_countries(client, ifaces: list[str]) -> dict[str, str]:
    out = {}
    for name in ifaces:
        try:
            ip = endpoint_ip(client, name)
            out[name] = country_of(ip) if ip else ""
        except Exception:  # noqa: BLE001
            out[name] = ""
    return out
