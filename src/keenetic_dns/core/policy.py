"""Политики доступа (ip policy) и привязка к ним устройств (ip hotspot host <mac> policy <имя>)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import ndms_quote, ndms_unquote

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


@dataclass
class Policy:
    name: str
    description: str = ""
    permits: list[str] = field(default_factory=list)  # интерфейсы-выходы в порядке приоритета

    @property
    def title(self) -> str:
        return self.description or self.name


@dataclass
class Device:
    mac: str
    name: str = ""
    ip: str = ""
    online: bool = False
    policy: str = ""  # имя политики; пусто — политика по умолчанию

    @property
    def title(self) -> str:
        return self.name or self.mac


def parse_policies(lines: list[str]) -> dict[str, Policy]:
    out: dict[str, Policy] = {}
    cur: Policy | None = None
    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if not line.startswith(" "):
            m = re.match(r"^ip policy (\S+)$", s)
            cur = out.setdefault(m.group(1), Policy(m.group(1))) if m else None
            continue
        if not cur:
            continue
        m = re.match(r"^description (.+)$", s)
        if m:
            cur.description = ndms_unquote(m.group(1))
            continue
        m = re.match(r"^permit global (\S+)", s)
        if m:
            cur.permits.append(m.group(1))
    return out


def parse_devices(lines: list[str]) -> dict[str, Device]:
    """Устройства из running-config: «known host имя mac» и «ip hotspot → host mac policy имя»."""
    out: dict[str, Device] = {}
    section = None
    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if not line.startswith(" "):
            section = "hotspot" if s == "ip hotspot" else None
            m = re.match(r'^known host ("(?:[^"\\]|\\.)*"|\S+) ([0-9a-fA-F:]{17})$', s)
            if m:
                mac = m.group(2).lower()
                out.setdefault(mac, Device(mac)).name = ndms_unquote(m.group(1)).strip()
            continue
        if section == "hotspot":
            m = re.match(r"^host ([0-9a-fA-F:]{17}) policy (\S+)$", s)
            if m:
                mac = m.group(1).lower()
                out.setdefault(mac, Device(mac)).policy = m.group(2)
    return out


def merge_online(devices: dict[str, Device], hotspot: object) -> dict[str, Device]:
    """Добавить данные «show ip hotspot» (кто в сети, IP, имя). Формат ответа у прошивок разный — берём что есть."""
    hosts = hotspot.get("host", []) if isinstance(hotspot, dict) else hotspot if isinstance(hotspot, list) else []
    for h in hosts:
        if not isinstance(h, dict):
            continue
        mac = str(h.get("mac", "")).lower()
        if not MAC_RE.match(mac):
            continue
        d = devices.setdefault(mac, Device(mac))
        d.name = d.name or str(h.get("name") or h.get("hostname") or "").strip()
        d.ip = str(h.get("ip", "") or "")
        d.online = bool(h.get("active") or h.get("link") == "up")
        if not d.policy and h.get("policy"):
            d.policy = str(h["policy"])
    return devices


def next_policy_name(policies: dict[str, Policy]) -> str:
    n = 0
    while f"Policy{n}" in policies:
        n += 1
    return f"Policy{n}"


def create_cmds(name: str, description: str, permits: list[str]) -> list[str]:
    cmds = [f"ip policy {name}"]
    if description:
        cmds.append(f"ip policy {name} description {ndms_quote(description)}")
    cmds += [f"ip policy {name} permit global {i}" for i in permits]
    return cmds


def assign_cmds(devices: list[Device], policy: str | None) -> list[str]:
    """Перевести устройства на политику (None — снять, вернуть политику по умолчанию)."""
    cmds = []
    for d in devices:
        if (policy or "") == d.policy:
            continue
        if policy:
            cmds.append(f"ip hotspot host {d.mac} policy {policy}")
        else:
            cmds.append(f"no ip hotspot host {d.mac} policy")
    return cmds


def verify_assign(after: dict[str, Device], macs: list[str], policy: str | None) -> list[str]:
    want = policy or ""
    return [f"{(after.get(m) or Device(m)).title}: политика не применилась" for m in macs
            if (after.get(m) or Device(m)).policy != want]


def plan(policies: dict[str, Policy], devices: dict[str, Device], macs: list[str], policy: str | None,
         new: Policy | None = None) -> tuple[list[str], list[str]]:
    """Команды и сводка: (при необходимости) создать политику new и перевести на неё устройства macs."""
    cmds, summary = [], []
    if new and new.name not in policies:
        cmds += create_cmds(new.name, new.description, new.permits)
        summary.append(f"+ Создать политику «{new.title}» → выход: {', '.join(new.permits) or 'нет'}")
    title = (new.title if new and new.name == policy else
             policies[policy].title if policy in policies else policy) if policy else "по умолчанию"
    devs = [devices.get(m) or Device(m) for m in macs]
    acmds = assign_cmds(devs, policy)
    cmds += acmds
    for d in devs:
        if (policy or "") != d.policy:
            was = policies[d.policy].title if d.policy in policies else (d.policy or "по умолчанию")
            summary.append(f"~ {d.title}: {was} → {title}")
    return cmds, summary


def read_devices(client, lines: list[str]) -> dict[str, Device]:
    """Устройства: из конфига + кто сейчас в сети (show ip hotspot, если роутер отдаёт)."""
    devs = parse_devices(lines)
    try:
        merge_online(devs, client.get("show/ip/hotspot"))
    except Exception:  # noqa: BLE001 — старые прошивки/эмулятор
        pass
    return devs
