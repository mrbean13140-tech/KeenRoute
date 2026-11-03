import json
import time

from keenetic_dns.core import catalog as K

FILES = {
    "openai": "# OpenAI\nopenai.com\nchatgpt.com\nfull:cdn.oaistatic.com\nkeyword:openai\nregexp:^ai\\.\ninclude:openai-ads\n",
    "openai-ads": "ads.openai.com @ads\nauthn.openai.com\n",
    "coral": "domain:coralapp.com\ncoral.example.org\napi.coralapp.com\n",
    "loop1": "include:loop2\na.com\n",
    "loop2": "include:loop1\nb.com\n",
}


def test_parse_and_resolve():
    db = K.parse_v2fly(FILES)
    assert db["openai"]["skipped"] == 2 and db["openai"]["include"] == ["openai-ads"]
    assert db["openai-ads"]["domains"] == ["authn.openai.com"]  # @ads выкинут
    d, s = K.resolve(db, "openai")
    assert set(d) == {"openai.com", "chatgpt.com", "cdn.oaistatic.com", "authn.openai.com"} and s == 2
    assert set(K.resolve(db, "loop1")[0]) == {"a.com", "b.com"}  # циклы не зависают


def test_compact():
    assert K.compact(["api.coralapp.com", "coralapp.com", "x.coralapp.com", "gemini.google.com"]) == [
        "coralapp.com", "gemini.google.com"]
    assert K.compact(["vk.ru", "vk.com"], zones=["ru"]) == ["vk.com"]
    assert K.collapse_ips(["10.0.0.0/25", "10.0.0.128/25", "1.1.1.1", "::1"]) == ["1.1.1.1", "10.0.0.0/24"]


def test_db_search(tmp_path):
    db = K.DomainDB(tmp_path / "v2fly.json")
    assert db.stale and db.search("coral") == []
    db.data, db.updated = K.parse_v2fly(FILES), time.time()
    db.path.write_text(json.dumps({"updated": db.updated, "services": db.data}))
    db2 = K.DomainDB(tmp_path / "v2fly.json")
    assert not db2.stale
    res = db2.search("coral")
    assert res[0].id == "coral" and res[0].domains == ["coralapp.com", "coral.example.org"]
    assert [e.id for e in db2.search("chatgpt.com")] == ["openai"]  # поиск по домену
    assert db2.entry("openai").domains == ["openai.com", "chatgpt.com", "cdn.oaistatic.com"]  # authn.openai.com ужат


def test_templates_and_sources(tmp_path):
    t = K.load_templates("assets/templates.json")
    ids = {x.id for x in t}
    assert {"chatgpt", "youtube", "telegram", "russia"} <= ids
    for x in t:  # все записи шаблонов проходят нормализацию и уже ужаты
        from keenetic_dns.core.model import clean_list
        assert clean_list(x.domains + x.ips + x.zones) == x.domains + x.ips + x.zones, x.id
    assert [x.id for x in K.search_templates(t, "googlevideo")] == ["youtube"]
    st = K.SourceStore(tmp_path / "s.json")
    st.add("home", "vpn-ai", "tpl:chatgpt", ["sora.com"])
    st.add("home", "vpn-ai", "tpl:claude", [])
    rec = K.SourceStore(tmp_path / "s.json").for_router("home")["vpn-ai"]
    assert rec == {"sources": ["tpl:chatgpt", "tpl:claude"], "excluded": ["sora.com"]}
    assert "sora.com" in K.fresh_entries("tpl:chatgpt", t, K.DomainDB(tmp_path / "none.json"))


def test_find_ips_shared_cloud(monkeypatch):
    monkeypatch.setattr(K, "resolve_ipv4", lambda d: ["104.16.1.1", "149.154.167.99"])
    data = {("network-info", "104.16.1.1"): {"asns": ["13335"]},
            ("network-info", "149.154.167.99"): {"asns": ["62041"]},
            ("as-overview", "AS13335"): {"holder": "CLOUDFLARENET"},
            ("as-overview", "AS62041"): {"holder": "TELEGRAM"}}
    monkeypatch.setattr(K, "_ripe", lambda ep, res, timeout=20: data[(ep, res)])
    monkeypatch.setattr(K, "ripe_prefixes", lambda asn: ["149.154.160.0/20", "91.108.4.0/22"])
    res = {f.asn: f for f in K.find_ips_for_domain("example.org")}
    assert res["AS13335"].shared and res["AS13335"].prefixes == ["104.16.1.1"]  # только IP сайта
    assert not res["AS62041"].shared and res["AS62041"].prefixes == ["149.154.160.0/20", "91.108.4.0/22"]


def test_geo_endpoint(monkeypatch):
    from keenetic_dns.core import geo
    class C:
        def run(self, cmds):
            return [{"parse": {"wireguard": {"peer": [{"public-key": "x", "remote": "203.0.113.5", "remote-port": 51820}]}}}]
    monkeypatch.setattr(geo, "country_of", lambda ip: "NL" if ip == "203.0.113.5" else "")
    assert geo.tunnel_countries(C(), ["Wireguard2"]) == {"Wireguard2": "NL"}
    class Bad:
        def run(self, cmds):
            raise RuntimeError("нет")
    assert geo.tunnel_countries(Bad(), ["Wireguard0"]) == {"Wireguard0": ""}


def test_big_list_core_split():
    files = {"brand": "brand.com\nbrandcdn.net\n" + "\n".join(f"junk{i}x.com" for i in range(80)) + "\ninclude:brand-sub\n",
             "brand-sub": "brand-sub.com\nzzqx.com\n"}
    db = K.parse_v2fly(files)
    items, _ = K.resolve_depth(db, "brand")
    core, rest = K.split_core(items)
    assert core[:2] == ["brand.com", "brandcdn.net"] and "brand-sub.com" in core
    assert "junk1x.com" in rest and "zzqx.com" in rest and len(core) <= K.CORE_LIMIT
    small = [(f"d{i}.com", 0, "x") for i in range(10)]
    assert K.split_core(small) == ([f"d{i}.com" for i in range(10)], [])
