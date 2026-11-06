"""Мини-эмулятор NDMS: исполняет наши CLI-команды и отдаёт running-config."""
import re

from keenetic_dns.core.model import Group, ndms_unquote, parse_running_config


class FakeRouter:
    base = "http://192.168.1.1:80"

    def __init__(self, cfg_lines, ifaces=None, fail_on=None):
        self.groups = parse_running_config(cfg_lines)
        self.ifaces = ifaces or {}
        self.fail_on = fail_on  # подстрока команды, на которой «роутер» вернёт ошибку
        self.ran = []
        from keenetic_dns.core.dns import parse_dns
        self.dns = parse_dns(cfg_lines)
        from keenetic_dns.core.policy import parse_devices, parse_policies
        self.policies = parse_policies(cfg_lines)
        self.devices = parse_devices(cfg_lines)

    def interfaces(self):
        return self.ifaces

    def running_config(self):
        out = ["system name Test"]
        out += [f'known host "{d.name}" {d.mac}' for d in self.devices.values() if d.name]
        for p in self.policies.values():
            out.append(f"ip policy {p.name}")
            if p.description:
                out.append(f'    description "{p.description}"')
            out += [f"    permit global {i}" for i in p.permits]
            out.append("!")
        out.append("ip hotspot")
        out += [f"    host {d.mac} permit" for d in self.devices.values()]
        out += [f"    host {d.mac} policy {d.policy}" for d in self.devices.values() if d.policy]
        out.append("!")
        for g in self.groups.values():
            out.append(f"object-group fqdn {g.name}")
            if g.description:
                out.append(f'    description "{g.description}"')
            out += [f"    include {d}" for d in g.domains]
            out.append("!")
        out += [u.cmd() for u in self.dns if u.kind == "plain"]
        out.append("dns-proxy")
        out += ["    " + u.cmd().split(" ", 1)[1] for u in self.dns if u.kind != "plain"]
        for g in self.groups.values():
            if g.interface:
                out.append(f"    route object-group {g.name} {g.interface} auto" + (" reject" if g.reject else ""))
        out.append("!")
        return out

    def run(self, cmds):
        from keenetic_dns.api.rci import RCIError
        self.ran.append(cmds)
        for c in cmds:
            if self.fail_on and self.fail_on in c:
                raise RCIError(f"{c}: ошибка")
            self._exec(c)
        return []

    def _exec(self, c):
        m = re.match(r"^(no )?object-group fqdn (\S+)(?: (include|description) ?(.*))?$", c)
        if m:
            neg, name, sub, arg = m.groups()
            if not sub:
                if neg:
                    self.groups.pop(name, None)
                else:
                    self.groups.setdefault(name, Group(name))
                return
            g = self.groups.setdefault(name, Group(name))
            if sub == "include":
                if neg:
                    g.domains = [d for d in g.domains if d != arg]
                elif arg not in g.domains:
                    g.domains.append(arg)
            else:
                g.description = "" if neg else ndms_unquote(arg)
            return
        m = re.match(r"^(no )?dns-proxy route object-group (\S+) (\S+)(.*)$", c)
        if m:
            neg, name, iface, rest = m.groups()
            g = self.groups[name]
            if neg:
                g.interface, g.reject = None, False
            else:
                g.interface, g.reject = iface, "reject" in rest
            return
        from keenetic_dns.core.dns import parse_dns
        if c.startswith("no dns-proxy tls upstream"):  # как NDMS: sni в «no» нельзя, короткая форма удаляет все записи
            from keenetic_dns.api.rci import RCIError
            if " sni " in c:
                raise RCIError(f"{c}: argument parse error.")
            parts = c.split()
            addr = parts[4]
            dom = parts[parts.index("domain") + 1] if "domain" in parts else None
            self.dns = [x for x in self.dns if not (x.kind == "dot" and x.addr == addr
                                                    and (dom is None or x.domain == dom))]
            return
        if c.startswith(("dns-proxy tls", "dns-proxy https", "no dns-proxy tls", "no dns-proxy https",
                         "ip name-server", "no ip name-server")):
            neg = c.startswith("no ")
            body = c[3:] if neg else c
            if body.startswith("dns-proxy "):
                u = parse_dns(["dns-proxy", "    " + body.split(" ", 1)[1], "!"])[0]
            else:
                u = parse_dns([body])[0]
            if neg:
                self.dns = [x for x in self.dns if x != u]
            elif u not in self.dns:
                self.dns.append(u)
            return
        from keenetic_dns.core.policy import Device, Policy
        m = re.match(r"^ip policy (\S+)(?: (description|permit global) (.+))?$", c)
        if m:
            p = self.policies.setdefault(m.group(1), Policy(m.group(1)))
            if m.group(2) == "description":
                p.description = ndms_unquote(m.group(3))
            elif m.group(2):
                p.permits.append(m.group(3))
            return
        m = re.match(r"^(no )?ip hotspot host (\S+) policy ?(\S*)$", c)
        if m:
            neg, mac, pol = m.groups()
            if not neg and pol not in self.policies:
                from keenetic_dns.api.rci import RCIError
                raise RCIError(f"{c}: unable to find policy")
            self.devices.setdefault(mac, Device(mac)).policy = "" if neg else pol
            return
        if c == "system configuration save":
            return
        raise AssertionError(f"неизвестная команда: {c}")
