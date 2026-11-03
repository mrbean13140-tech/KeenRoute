"""Генерация CLI-команд NDMS по желаемому состоянию."""
from __future__ import annotations

from .model import Group, ndms_quote

# Подтвердить на реальном роутере и при необходимости поправить (см. docs/compat.md)
MAX_DOMAINS_PER_GROUP = 300


def route_cmd(g: Group, iface: str, remove: bool = False) -> str:
    if remove:
        return f"no dns-proxy route object-group {g.name} {iface}"
    return f"dns-proxy route object-group {g.name} {iface} auto" + (" reject" if g.reject else "")


def set_gateway(groups: list[Group], iface: str) -> list[str]:
    """Перевести группы на другой интерфейс."""
    cmds = []
    for g in groups:
        if g.interface == iface:
            continue
        if g.interface:
            cmds.append(route_cmd(g, g.interface, remove=True))
        cmds.append(route_cmd(g, iface))
    return cmds


def remove_gateway(groups: list[Group]) -> list[str]:
    return [route_cmd(g, g.interface, remove=True) for g in groups if g.interface]


def assign_map(groups: dict[str, Group], mapping: dict[str, str | None]) -> list[str]:
    """Разделение: {имя_группы: интерфейс|None}."""
    cmds = []
    for name, iface in mapping.items():
        g = groups[name]
        if iface == g.interface:
            continue
        if iface is None:
            cmds += remove_gateway([g])
        else:
            cmds += set_gateway([g], iface)
    return cmds


def sync_group(old: Group | None, new: Group) -> list[str]:
    """Создать/обновить группу (домены + маршрут) до состояния new."""
    cmds = []
    old_domains = set(old.domains) if old else set()
    new_domains = list(dict.fromkeys(new.domains))
    if old is None:
        cmds.append(f"object-group fqdn {new.name}")
    for d in old_domains - set(new_domains):
        cmds.append(f"no object-group fqdn {new.name} include {d}")
    for d in new_domains:
        if d not in old_domains:
            cmds.append(f"object-group fqdn {new.name} include {d}")
    old_desc = old.description if old else ""
    if new.description != old_desc:
        if new.description:
            cmds.append(f"object-group fqdn {new.name} description {ndms_quote(new.description)}")
        else:
            cmds.append(f"no object-group fqdn {new.name} description")
    old_if = old.interface if old else None
    if new.interface != old_if or (old and new.reject != old.reject and new.interface):
        if old_if:
            cmds.append(route_cmd(old, old_if, remove=True))
        if new.interface:
            cmds.append(route_cmd(new, new.interface))
    return cmds


def delete_group(g: Group) -> list[str]:
    return remove_gateway([g]) + [f"no object-group fqdn {g.name}"]


def split_group(g: Group, limit: int = MAX_DOMAINS_PER_GROUP) -> list[Group]:
    """Разбить большую группу на части name_1, name_2…"""
    if len(g.domains) <= limit:
        return [g]
    parts = []
    for i in range(0, len(g.domains), limit):
        n = i // limit + 1
        parts.append(Group(f"{g.name}_{n}"[:32], g.domains[i:i + limit], g.interface, g.reject, g.description))
    return parts


def with_save(cmds: list[str]) -> list[str]:
    return cmds + ["system configuration save"] if cmds else []


def restore(current: dict[str, Group], backup: dict[str, Group]) -> list[str]:
    """Вернуть object-group fqdn и dns-proxy route к состоянию из бэкапа."""
    cmds = []
    for name, g in current.items():
        if name not in backup:
            cmds += delete_group(g)
    for name, g in backup.items():
        cmds += sync_group(current.get(name), g)
    return cmds


def plan(current: dict[str, Group], target: dict[str, Group]) -> list[str]:
    """Команды, которые переводят роутер из current в target (только разница)."""
    return restore(current, target)


def describe(current: dict[str, Group], target: dict[str, Group], iface_name=lambda x: x) -> list[str]:
    """Человекочитаемая сводка изменений «было → станет»."""
    out = []
    gw = lambda i: iface_name(i) if i else "без шлюза"  # noqa: E731
    for name, g in current.items():
        if name not in target:
            out.append(f"− Удалить «{g.title}» ({len(g.domains)} доменов, {gw(g.interface)})")
    for name, t in target.items():
        o = current.get(name)
        if o is None:
            out.append(f"+ Создать «{t.title}»: {len(t.domains)} доменов → {gw(t.interface)}")
            continue
        parts = []
        add = len(set(t.domains) - set(o.domains))
        rem = len(set(o.domains) - set(t.domains))
        if add or rem:
            parts.append(" ".join(x for x in (f"+{add}" if add else "", f"−{rem}" if rem else "") if x) + " доменов")
        if o.interface != t.interface:
            parts.append(f"шлюз {gw(o.interface)} → {gw(t.interface)}")
        elif t.interface and o.reject != t.reject:
            parts.append("блокировка при обрыве " + ("вкл" if t.reject else "выкл"))
        if o.description != t.description:
            parts.append(f"название «{o.title}» → «{t.title}»")
        if parts:
            out.append(f"~ «{o.title}»: " + ", ".join(parts))
    return out
