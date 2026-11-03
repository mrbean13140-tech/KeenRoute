import json

import pytest

from keenetic_dns.api.rci import AuthError, RCIClient, RCIError, auth_hash
from keenetic_dns.core import commands as C
from keenetic_dns.core import io
from keenetic_dns.core.model import Group, clean_list, parse_interfaces, parse_running_config

CFG = """system name Test
object-group fqdn youtube
    description "YT"
    include youtube.com
    include googlevideo.com
!
object-group fqdn chatgpt
    include openai.com
!
dns-proxy
    filter engine public
    route object-group youtube Wireguard0 auto
    route object-group chatgpt Wireguard1 auto reject
!
interface Wireguard0
    description Home
!""".splitlines()


def test_auth_hash_known():
    import hashlib
    md5 = hashlib.md5(b"admin:R:pass").hexdigest()
    assert auth_hash("admin", "pass", "R", "C") == hashlib.sha256(("C" + md5).encode()).hexdigest()


def test_parse_config():
    g = parse_running_config(CFG)
    assert set(g) == {"youtube", "chatgpt"}
    assert g["youtube"].domains == ["youtube.com", "googlevideo.com"]
    assert g["youtube"].interface == "Wireguard0" and not g["youtube"].reject
    assert g["youtube"].description == "YT"
    assert g["chatgpt"].interface == "Wireguard1" and g["chatgpt"].reject


def test_parse_interfaces():
    data = {
        "Wireguard0": {"id": "Wireguard0", "type": "Wireguard", "description": "Home", "link": "up"},
        "Wireguard1": {"id": "Wireguard1", "type": "Wireguard", "link": "down"},
        "Bridge0": {"id": "Bridge0", "type": "Bridge"},
        "PPPoE0": {"id": "PPPoE0", "type": "PPPoE", "connected": "yes"},
    }
    ifs = parse_interfaces(data)
    assert [i.name for i in ifs] == ["Wireguard0", "Wireguard1", "PPPoE0"]
    assert ifs[0].up and not ifs[1].up and ifs[2].up


def test_clean_list():
    assert clean_list(["https://YouTube.com/x", "*.ggpht.com", "# c", "bad domain", "youtube.com", "1.2.3.0/24"]) == [
        "youtube.com", "ggpht.com", "1.2.3.0/24"]


def test_set_gateway_and_split():
    g = parse_running_config(CFG)
    cmds = C.set_gateway(list(g.values()), "Wireguard1")
    assert cmds == [
        "no dns-proxy route object-group youtube Wireguard0",
        "dns-proxy route object-group youtube Wireguard1 auto",
    ]
    cmds = C.assign_map(g, {"youtube": "Wireguard2", "chatgpt": None})
    assert "dns-proxy route object-group youtube Wireguard2 auto" in cmds
    assert "no dns-proxy route object-group chatgpt Wireguard1" in cmds


def test_sync_new_and_update():
    new = Group("x", ["a.com", "b.com"], "Wireguard0")
    assert C.sync_group(None, new) == [
        "object-group fqdn x", "object-group fqdn x include a.com",
        "object-group fqdn x include b.com", "dns-proxy route object-group x Wireguard0 auto"]
    old = Group("x", ["a.com", "c.com"], "Wireguard0")
    assert C.sync_group(old, new) == ["no object-group fqdn x include c.com", "object-group fqdn x include b.com"]


def test_split_and_restore():
    big = Group("big", [f"d{i}.com" for i in range(650)], "Wireguard0")
    parts = C.split_group(big, 300)
    assert [p.name for p in parts] == ["big_1", "big_2", "big_3"] and len(parts[2].domains) == 50
    cur = parse_running_config(CFG)
    bak = {"youtube": cur["youtube"]}
    cmds = C.restore(cur, bak)
    assert cmds == ["no dns-proxy route object-group chatgpt Wireguard1", "no object-group fqdn chatgpt"]


def test_export_import(tmp_path):
    g = list(parse_running_config(CFG).values())
    p = tmp_path / "a.json"
    io.export_json(g, p)
    back = io.import_file(p)
    assert [(x.name, x.interface, x.domains) for x in back] == [(x.name, x.interface, x.domains) for x in g]
    t = tmp_path / "my list.txt"
    t.write_text("a.com\nb.com\na.com\n")
    [x] = io.import_file(t)
    assert x.name == "my_list" and x.domains == ["a.com", "b.com"] and x.description == "my list"


class R:
    def __init__(self, status=200, headers=None, js=None):
        self.status_code, self.headers, self._js = status, headers or {}, js
    def json(self): return self._js
    def raise_for_status(self): pass


class FakeSession:
    def __init__(self, gets, posts):
        self.gets, self.posts, self.sent = list(gets), list(posts), []
        self.cookies = type("J", (), {"clear": lambda self: None})()
    def get(self, url, **kw): return self.gets.pop(0)
    def post(self, url, json=None, **kw):
        self.sent.append(json); return self.posts.pop(0)


CH = {"X-NDM-Realm": "R", "X-NDM-Challenge": "C"}


def test_client_login_and_errors():
    c = RCIClient("r")
    c.s = FakeSession([R(401, CH)], [R(200), R(js=[{"parse": {"status": [{"status": "error", "message": "bad"}]}}])])
    c.login("admin", "pass")
    assert c.s.sent[0] == {"login": "admin", "password": auth_hash("admin", "pass", "R", "C")}
    with pytest.raises(RCIError, match="bad"):
        c.run(["oops"])


def test_client_bad_password():
    c = RCIClient("r")
    c.s = FakeSession([R(401, CH)], [R(401)])
    with pytest.raises(AuthError):
        c.login("admin", "x")


def test_not_keenetic():
    c = RCIClient("r")
    c.s = FakeSession([R(404)], [])
    with pytest.raises(RCIError, match="Keenetic"):
        c.login("a", "b")


def test_client_base_urls():
    assert RCIClient("192.168.1.1").base == "http://192.168.1.1:80"
    assert RCIClient("https://led.keenetic.pro/").base == "https://led.keenetic.pro"
    assert RCIClient("http://x.netcraze.pro", 8080).base == "http://x.netcraze.pro:8080"


def test_description_roundtrip():
    from keenetic_dns.core.model import ndms_quote, ndms_unquote
    raw = '"\\xd0\\x9f\\xd0\\xbe\\xd0\\xb4\\xd0\\xba\\xd0\\xbb Ethernet"'
    assert ndms_unquote(raw) == "Подкл Ethernet"
    assert ndms_unquote("VPN_Home-Router") == "VPN_Home-Router"
    cfg = ["object-group fqdn x", '    description "\\xd0\\xa2\\xd0\\xb5\\xd1\\x81\\xd1\\x82 1"', "    include a.com", "!"]
    assert parse_running_config(cfg)["x"].description == "Тест 1"
    assert ndms_quote("RU-domain") == "RU-domain"
    assert ndms_quote("WhatsApp Instagram") == '"WhatsApp Instagram"'


def test_import_restores_description():
    new = Group("domain-list17", ["vk.com"], "PPPoE0", True, "RU-domain")
    cmds = C.sync_group(None, new)
    assert "object-group fqdn domain-list17 description RU-domain" in cmds
    assert cmds[-1] == "dns-proxy route object-group domain-list17 PPPoE0 auto reject"
    old = Group("x", ["a.com"], description="Old")
    assert C.sync_group(old, Group("x", ["a.com"])) == ["no object-group fqdn x description"]


def test_plan_applies_exactly_on_fake_router():
    from .fake_router import FakeRouter
    r = FakeRouter(CFG)
    cur = parse_running_config(r.running_config())
    target = {
        "youtube": Group("youtube", ["youtube.com", "ytimg.com"], "Wireguard1", False, "YouTube видео"),
        "new": Group("new", ["a.com"], "Wireguard0", True, "Новый"),
    }
    cmds = C.plan(cur, target)
    r.run(cmds)
    after = parse_running_config(r.running_config())
    assert C.plan(after, target) == []
    assert set(after) == {"youtube", "new"} and after["youtube"].description == "YouTube видео"


def test_describe():
    cur = parse_running_config(CFG)
    t = {"youtube": Group("youtube", ["youtube.com", "x.com"], "Wireguard1", False, "YT")}
    s = C.describe(cur, t)
    assert any(x.startswith("− Удалить «chatgpt»") for x in s)
    assert any(x.startswith("~ «YT»") and "+1 −1 доменов" in x and "Wireguard0 → Wireguard1" in x for x in s)


def test_relogin_on_expired_session():
    c = RCIClient("r")
    c.s = FakeSession([R(401, CH), R(401), R(401, CH), R(js={"message": ["ok"]})], [R(200), R(200)])
    c.login("admin", "pass")
    assert c.running_config() == ["ok"]  # 401 → повторный вход → повтор запроса
