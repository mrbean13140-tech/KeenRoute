from keenetic_dns.core import policy as P

from .fake_router import FakeRouter

CFG = [
    'known host "MiTV " 20:72:a9:43:41:f4',
    "known host iPhone 28:02:2e:60:a2:ff",
    "known host LGwebOSTV 60:ab:14:95:96:78",
    "ip policy Policy2",
    "    description PNV",
    "    permit global PPPoE0",
    "    no permit global Wireguard1",
    "!",
    "ip hotspot",
    "    policy Bridge0 permit",
    "    host 20:72:a9:43:41:f4 permit",
    "    host 60:ab:14:95:96:78 policy Policy2",
    "!",
]


def test_parse():
    pols = P.parse_policies(CFG)
    assert pols["Policy2"].description == "PNV" and pols["Policy2"].permits == ["PPPoE0"]
    devs = P.parse_devices(CFG)
    assert devs["20:72:a9:43:41:f4"].name == "MiTV" and devs["60:ab:14:95:96:78"].policy == "Policy2"
    assert P.next_policy_name(pols) == "Policy0"


def test_plan_create_and_assign_all():
    pols, devs = P.parse_policies(CFG), P.parse_devices(CFG)
    new = P.Policy("Policy0", "Через VPN", ["Wireguard3", "PPPoE0"])
    cmds, summary = P.plan(pols, devs, list(devs), "Policy0", new)
    assert cmds[:4] == ["ip policy Policy0", 'ip policy Policy0 description "Через VPN"',
                        "ip policy Policy0 permit global Wireguard3 order 0",
                        "ip policy Policy0 permit global PPPoE0 order 1"]
    assert sum(c.startswith("ip hotspot host") for c in cmds) == 3 and len(summary) == 4
    cmds, _ = P.plan(pols, devs, ["60:ab:14:95:96:78", "28:02:2e:60:a2:ff"], None)
    assert cmds == ["no ip hotspot host 60:ab:14:95:96:78 policy"]  # второй уже по умолчанию


def test_apply_on_fake_router():
    r = FakeRouter(CFG)
    devs = P.parse_devices(r.running_config())
    new = P.Policy("Policy0", "Дети", ["PPPoE0"])
    cmds, _ = P.plan(P.parse_policies(r.running_config()), devs, list(devs), "Policy0", new)
    r.run(cmds)
    after = P.read_devices(r, r.running_config())
    assert not P.verify_assign(after, list(devs), "Policy0")
    assert P.parse_policies(r.running_config())["Policy0"].description == "Дети"


def test_edit_and_delete_on_fake_router():
    r = FakeRouter(CFG)
    pols = P.parse_policies(r.running_config())
    want = P.Policy("Policy2", "ТВ", ["Wireguard3", "PPPoE0"])
    cmds, summary = P.edit_cmds(pols["Policy2"], want)
    assert len(summary) == 2
    r.run(cmds)
    assert not P.verify_policy(P.parse_policies(r.running_config()), "Policy2", want)
    devs = P.parse_devices(r.running_config())
    cmds, summary = P.delete_cmds(P.parse_policies(r.running_config())["Policy2"], devs)
    assert cmds == ["no ip hotspot host 60:ab:14:95:96:78 policy", "no ip policy Policy2"]
    r.run(cmds)
    after = r.running_config()
    assert not P.verify_policy(P.parse_policies(after), "Policy2", None)
    assert P.parse_devices(after)["60:ab:14:95:96:78"].policy == ""


def test_reorder_priority():
    r = FakeRouter(CFG)
    r.run(P.create_cmds("Policy0", "", ["PPPoE0", "Wireguard3", "Wireguard1"]))
    old = P.parse_policies(r.running_config())["Policy0"]
    want = P.Policy("Policy0", "", ["Wireguard1", "PPPoE0"])  # Wireguard1 — основной, Wireguard3 убран
    cmds, _ = P.edit_cmds(old, want)
    assert cmds[0] == "no ip policy Policy0 permit global Wireguard3"
    r.run(cmds)
    assert P.parse_policies(r.running_config())["Policy0"].permits == ["Wireguard1", "PPPoE0"]
