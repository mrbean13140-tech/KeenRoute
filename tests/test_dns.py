from keenetic_dns.core import dns as D

CFG = """ip name-server 1.1.1.1 "" on Wireguard2
ip name-server 8.8.8.8
dns-proxy
    rebind-protect auto
    route object-group vpn-ai Wireguard2 auto reject
    tls upstream 77.88.8.8 853 sni common.dot.dns.yandex.net domain wbbasket.ru
    https upstream https://cloudflare-dns.com/dns-query dnsm
    https upstream https://common.dot.dns.yandex.net/dns-query dnsm domain ozon.ru
!""".splitlines()


def test_parse_real_config():
    u = D.parse_dns(CFG)
    assert D.Upstream("plain", "1.1.1.1", iface="Wireguard2") in u
    assert D.Upstream("plain", "8.8.8.8") in u
    assert D.Upstream("dot", "77.88.8.8", "common.dot.dns.yandex.net", 853, "wbbasket.ru") in u
    assert D.Upstream("doh", "https://cloudflare-dns.com/dns-query") in u
    assert D.Upstream("doh", "https://common.dot.dns.yandex.net/dns-query", domain="ozon.ru") in u
    assert len(u) == 5


def test_commands_roundtrip():
    p = {x["id"]: x for x in D.load_providers("assets/dns.json")}
    add = D.preset_upstreams(p["yandex"], "dot", ["wb.ru", "ozon.ru"]) + D.preset_upstreams(p["cloudflare"], "doh")
    cmds = D.plan_dns(D.parse_dns(CFG), add, [D.Upstream("plain", "8.8.8.8")])
    assert cmds == [
        "no ip name-server 8.8.8.8",
        "dns-proxy tls upstream 77.88.8.8 853 sni common.dot.dns.yandex.net domain wb.ru",
        "dns-proxy tls upstream 77.88.8.8 853 sni common.dot.dns.yandex.net domain ozon.ru",
    ]  # Cloudflare DoH уже есть — не дублируется
    # команда → строка конфига → тот же объект
    for u in add:
        line = u.cmd().replace("dns-proxy ", "    ", 1)
        assert D.parse_dns(["dns-proxy", line, "!"]) == [u]
    assert D.Upstream("plain", "1.1.1.1", iface="Wireguard2").cmd() == 'ip name-server 1.1.1.1 "" on Wireguard2'


def test_limit_counts_servers_not_domains():
    u = D.parse_dns(CFG)
    # Яндекс DoT (для wbbasket) + Cloudflare DoH + Яндекс DoH (для ozon) = 3 сервера
    assert len(D.encrypted_servers(u)) == 3
    p = D.load_providers("assets/dns.json")
    assert D.provider_name(D.Upstream("doh", "https://cloudflare-dns.com/dns-query"), p) == "Cloudflare"
    assert D.provider_name(D.Upstream("dot", "77.88.8.8", "common.dot.dns.yandex.net"), p) == "Яндекс"
