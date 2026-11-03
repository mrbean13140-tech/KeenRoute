"""Модель данных и разбор конфигурации роутера."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Типы интерфейсов, которые можно использовать как шлюз DNS-маршрута
GATEWAY_TYPES = {"Wireguard", "OpenVPN", "PPTP", "L2TP", "SSTP", "IKE", "PPPoE", "GigabitEthernet", "Proxy"}

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z0-9-]{2,63}$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?$")
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")
ZONE_RE = re.compile(r"^(xn--[a-z0-9-]{2,59}|[a-z]{2,24})$")  # целая доменная зона: ru, su, xn--p1ai (рф)


@dataclass
class Group:
    name: str
    domains: list[str] = field(default_factory=list)
    interface: str | None = None  # шлюз из dns-proxy route
    reject: bool = False          # блокировать при недоступности шлюза
    description: str = ""

    @property
    def title(self) -> str:
        """Имя для показа: описание из веб-интерфейса, иначе техническое имя."""
        return self.description or self.name


@dataclass
class Iface:
    name: str
    type: str
    description: str = ""
    up: bool = False

    @property
    def label(self) -> str:
        d = f" ({self.description})" if self.description else ""
        return f"{self.name}{d}"

    @property
    def short(self) -> str:
        """Короткое имя для показа: описание (например, VPN-Europe), иначе имя интерфейса."""
        return self.description or self.name

    @property
    def is_wg(self) -> bool:
        return self.type.lower() == "wireguard"


def normalize_entry(s: str) -> str | None:
    """Приводит строку к домену/IP или возвращает None, если невалидна."""
    s = s.strip().lower()
    if not s or s.startswith("#"):
        return None
    for pfx in ("http://", "https://"):
        if s.startswith(pfx):
            s = s[len(pfx):]
    s = s.split("/", 1)[0] if not IP_RE.match(s) else s
    s = s.lstrip("*.").rstrip(".")
    if s and not s.isascii():  # кириллица: сайт.рф → xn--80aswg.xn--p1ai
        try:
            s = s.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    if DOMAIN_RE.match(s) or IP_RE.match(s) or ZONE_RE.match(s):
        return s
    return None


def clean_list(lines) -> list[str]:
    out, seen = [], set()
    for ln in lines:
        d = normalize_entry(ln)
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def ndms_unquote(s: str) -> str:
    """'"\\xd0\\x9f\\xd1\\x80..."' → 'Пр...' (NDMS экранирует не-ASCII в running-config)."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1]
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "x" and i + 3 < len(s):
                try:
                    out.append(int(s[i + 2:i + 4], 16))
                    i += 4
                    continue
                except ValueError:
                    pass
            out += n.encode()
            i += 2
            continue
        out += c.encode()
        i += 1
    return out.decode("utf-8", errors="replace")


def ndms_quote(s: str) -> str:
    """Строка для CLI: в кавычках, если есть пробелы/спецсимволы."""
    if s and all(c.isascii() and (c.isalnum() or c in "_-.") for c in s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_running_config(lines: list[str]) -> dict[str, Group]:
    groups: dict[str, Group] = {}
    section, cur = None, None
    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if not line.startswith(" "):  # заголовок секции
            cur = None
            m = re.match(r"^object-group fqdn (\S+)", s)
            if m:
                section = "fqdn"
                cur = groups.setdefault(m.group(1), Group(m.group(1)))
            elif s == "dns-proxy":
                section = "dns"
            else:
                section = None
            continue
        if section == "fqdn" and cur:
            if s.startswith("include "):
                cur.domains.append(s.split(None, 1)[1])
            elif s.startswith("description "):
                cur.description = ndms_unquote(s.split(None, 1)[1])
        elif section == "dns":
            m = re.match(r"^route object-group (\S+) (\S+)(.*)$", s)
            if m:
                g = groups.setdefault(m.group(1), Group(m.group(1)))
                g.interface = m.group(2)
                g.reject = "reject" in m.group(3).split()
    return groups


def parse_interfaces(data: dict) -> list[Iface]:
    out = []
    items = data.values() if isinstance(data, dict) else data
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("id") or it.get("interface-name") or it.get("name")
        typ = it.get("type", "")
        if not name or typ not in GATEWAY_TYPES:
            continue
        up = it.get("link") == "up" or it.get("connected") == "yes" or it.get("state") == "up" and it.get("link", "up") == "up"
        out.append(Iface(name, typ, it.get("description", ""), bool(up)))
    out.sort(key=lambda i: (not i.is_wg, i.name))
    return out
