"""DNS-серверы роутера: обычные (ip name-server), DoT (dns-proxy tls upstream), DoH (dns-proxy https upstream)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .model import ndms_unquote


@dataclass(frozen=True)
class Upstream:
    kind: str              # "plain" | "dot" | "doh"
    addr: str              # IP для plain/dot, URL для doh
    sni: str = ""          # для dot
    port: int = 853        # для dot
    domain: str = ""       # только для этого домена (пусто — для всех)
    iface: str = ""        # plain: «on <интерфейс>»

    @property
    def label(self) -> str:
        k = {"plain": "DNS", "dot": "DoT", "doh": "DoH"}[self.kind]
        main = self.sni or self.addr if self.kind == "dot" else self.addr
        extra = []
        if self.domain:
            extra.append(f"только {self.domain}")
        if self.iface:
            extra.append(f"через {self.iface}")
        return f"{k}  {main}" + (f"  ({', '.join(extra)})" if extra else "")

    def cmd(self, remove: bool = False) -> str:
        no = "no " if remove else ""
        if self.kind == "dot":
            c = f"{no}dns-proxy tls upstream {self.addr} {self.port}"
            if self.sni:
                c += f" sni {self.sni}"
        elif self.kind == "doh":
            c = f"{no}dns-proxy https upstream {self.addr} dnsm"
        else:
            c = f"{no}ip name-server {self.addr}"
            if self.domain or self.iface:
                c += f' "{self.domain}"'
            if self.iface:
                c += f" on {self.iface}"
            return c
        if self.domain:
            c += f" domain {self.domain}"
        return c


def parse_dns(lines: list[str]) -> list[Upstream]:
    out, section = [], None
    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if not line.startswith(" "):
            section = "dns" if s == "dns-proxy" else None
            m = re.match(r'^ip name-server (\S+)(?: ("[^"]*"|\S+))?(?: on (\S+))?', s)
            if m:
                dom = ndms_unquote(m.group(2)) if m.group(2) else ""
                out.append(Upstream("plain", m.group(1), domain=dom, iface=m.group(3) or ""))
            continue
        if section != "dns":
            continue
        m = re.match(r"^tls upstream (\S+)(?: (\d+))?(?: sni (\S+))?.*?(?: domain (\S+))?$", s)
        if m:
            out.append(Upstream("dot", m.group(1), m.group(3) or "", int(m.group(2) or 853), m.group(4) or ""))
            continue
        m = re.match(r"^https upstream (\S+)(?: (dnsm|json))?.*?(?: domain (\S+))?$", s)
        if m:
            out.append(Upstream("doh", m.group(1), domain=m.group(3) or ""))
    return out


def load_providers(path: str | Path | None = None) -> list[dict]:
    if path is None:
        from ..ui.theme import asset
        path = asset("dns.json")
    return json.loads(Path(path).read_text(encoding="utf-8"))["providers"]


def preset_upstreams(p: dict, kind: str, domains: list[str] | None = None) -> list[Upstream]:
    """Шаблон провайдера → записи. domains — только для этих доменов (для каждого своя строка)."""
    doms = domains or [""]
    out = []
    for d in doms:
        if kind == "plain":
            out += [Upstream("plain", ip, domain=d) for ip in p["plain"][:2]]
        elif kind == "dot":
            out.append(Upstream("dot", p["dot"]["ip"], p["dot"]["sni"], 853, d))
        elif kind == "doh":
            out.append(Upstream("doh", p["doh"], domain=d))
    return out


def plan_dns(current: list[Upstream], add: list[Upstream], remove: list[Upstream]) -> list[str]:
    cur = set(current)
    cmds = [u.cmd(remove=True) for u in remove if u in cur]
    cmds += [u.cmd() for u in add if u not in cur]
    return cmds


def verify_dns(after: list[Upstream], add: list[Upstream], remove: list[Upstream]) -> list[str]:
    """Что не применилось."""
    s = set(after)
    return [f"не добавлено: {u.label}" for u in add if u not in s] + \
           [f"не удалено: {u.label}" for u in remove if u in s]
