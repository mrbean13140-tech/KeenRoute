"""Каталог: встроенные шаблоны, локальная база доменов (v2fly), поиск, ужатие, IP по ASN (RIPEstat)."""
from __future__ import annotations

import io as _io
import ipaddress
import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .io import app_dir
from .model import IP_RE, normalize_entry

V2FLY_ZIP = "https://codeload.github.com/v2fly/domain-list-community/zip/refs/heads/master"
RIPE = "https://stat.ripe.net/data"
DB_MAX_AGE = 24 * 3600
ZONE_RE = re.compile(r"^(xn--[a-z0-9-]{2,59}|[a-z]{2,63})$")


@dataclass
class Entry:
    """Найденный сервис: из шаблонов или из базы."""
    id: str
    title: str
    source: str                      # "tpl" | "v2fly" | "ripe"
    category: str = ""
    domains: list[str] = field(default_factory=list)
    ips: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)  # региональные зеркала и пр. — по умолчанию сняты
    skipped: int = 0                 # regexp/keyword, которые Keenetic не умеет
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def size(self) -> int:
        return len(self.domains) + len(self.ips) + len(self.zones)

    @property
    def total(self) -> int:
        return self.size + len(self.optional)


# ---------- ужатие ----------
def compact(domains: list[str], zones: list[str] = ()) -> list[str]:
    """Убирает дубли и поддомены, уже покрытые родителем (или зоной). Не обобщает до 2-го уровня:
    gemini.google.com НЕ превращается в google.com."""
    seen = set(zones)
    out = []
    for d in sorted({x.strip().lower().rstrip(".") for x in domains if x}, key=lambda x: (x.count("."), x)):
        if IP_RE.match(d):
            continue
        parts = d.split(".")
        if any(".".join(parts[i:]) in seen for i in range(1, len(parts))):
            continue
        seen.add(d)
        out.append(d)
    order = {d: i for i, d in enumerate(domains)}
    return sorted(out, key=lambda d: order.get(d, 10 ** 6))


def collapse_ips(ips: list[str], max_prefix: int = 32) -> list[str]:
    nets = []
    for x in ips:
        try:
            n = ipaddress.ip_network(x.strip(), strict=False)
        except ValueError:
            continue
        if n.version == 4 and n.prefixlen <= max_prefix:
            nets.append(n)
    return [str(n) if n.prefixlen < 32 else str(n.network_address) for n in ipaddress.collapse_addresses(nets)]


REGIONAL_RE = re.compile(r"^([a-z0-9-]+)\.(?:(?:co|com|org|net|gov|edu)\.)?([a-z]{2})$")


def split_regional(domains: list[str]) -> tuple[list[str], list[str]]:
    """youtube.de, youtube.co.uk… при наличии youtube.com — региональные зеркала (необязательные)."""
    have = set(domains)
    main, regional = [], []
    for d in domains:
        m = REGIONAL_RE.match(d)
        if m and any(f"{m.group(1)}.{t}" in have for t in ("com", "net", "org")):
            regional.append(d)
        else:
            main.append(d)
    return main, regional


# ---------- шаблоны ----------
def load_templates(path: str | Path | None = None) -> list[Entry]:
    if path is None:
        from ..ui.theme import asset  # путь работает и в exe
        path = asset("templates.json")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for t in data["templates"]:
        out.append(Entry(t["id"], t["title"], "tpl", t.get("category", ""),
                         list(t.get("domains", [])), list(t.get("ips", [])), list(t.get("zones", [])),
                         note=t.get("note", "")))
    return out


# ---------- база v2fly ----------
def parse_v2fly(files: dict[str, str]) -> dict[str, dict]:
    """{имя_файла: текст} → {имя: {"domains": [...], "include": [...], "skipped": n}} (без разворота include)."""
    db = {}
    for name, text in files.items():
        rec = {"domains": [], "include": [], "skipped": 0}
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            val, *attrs = line.split()
            if any(a.startswith("@ads") for a in attrs):
                continue
            kind, _, v = val.partition(":") if ":" in val else ("domain", "", val)
            if kind == "include":
                rec["include"].append(v.strip())
            elif kind in ("domain", "full"):
                d = normalize_entry(v)
                if d:
                    rec["domains"].append(d)
            else:  # keyword, regexp
                rec["skipped"] += 1
        db[name] = rec
    return db


def resolve(db: dict[str, dict], name: str, _seen=None) -> tuple[list[str], int]:
    d, s = resolve_depth(db, name, _seen)
    return [x for x, *_ in d], s


def resolve_depth(db: dict[str, dict], name: str, _seen=None, depth: int = 0, origin: str = "") \
        -> tuple[list[tuple[str, int, str]], int]:
    """Как resolve, но для каждого домена: глубина и из какого списка он пришёл (apple, icloud, beats…)."""
    _seen = _seen if _seen is not None else set()
    if name in _seen or name not in db:
        return [], 0
    _seen.add(name)
    rec = db[name]
    domains, skipped = [(x, depth, name) for x in rec["domains"]], rec["skipped"]
    for inc in rec["include"]:
        d, s = resolve_depth(db, inc, _seen, depth + 1)
        domains += d
        skipped += s
    return domains, skipped


GENERIC_TLD = {"com", "net", "org", "io", "co", "app", "dev", "ai", "me", "tv", "cloud", "gg", "so", "to", "ly", "link"}
INFRA_HINTS = ("cdn", "static", "img", "api", "media", "video", "assets", "content", "edge", "auth", "cloud", "push")
CORE_LIMIT = 60      # списки не больше этого берутся целиком
SUB_LIMIT = 15       # у больших — не больше стольких основных доменов на подсервис


def _sld_tld(d: str) -> tuple[str, str]:
    p = d.split(".")
    if len(p) >= 3 and p[-2] in ("co", "com", "org", "net", "gov", "edu") and len(p[-1]) == 2:
        return p[-3], "cc"
    return (p[-2] if len(p) > 1 else p[0]), p[-1]


def _token(name: str) -> str:
    return re.split(r"[-@!:]", name)[0]


def core_score(d: str, token: str) -> int:
    """< 0 — не основной. Чем больше, тем важнее."""
    sld, tld = _sld_tld(d)
    brand = bool(token) and token in sld
    infra = any(h in sld for h in INFRA_HINTS)
    if not (brand or infra) or "xn--" in d:
        return -1
    s = 6 if sld == token else (3 if brand else 2)
    if tld in ("com", "net"):
        s += 2
    elif tld in GENERIC_TLD:
        s += 1
    elif tld == "cc" or len(tld) == 2:
        s -= 3          # региональные зоны
    else:
        s -= 2          # экзотические gTLD (.hamburg, .wang…) — защитные регистрации
    if len(sld) > 14:
        s -= 2          # длинные промо-домены
    return s


def split_core(items: list[tuple[str, int, str]]) -> tuple[list[str], list[str]]:
    """Делит домены на основные (по умолчанию отмечены) и дополнительные."""
    order = list(dict.fromkeys(d for d, _, _ in items))
    if len(order) <= CORE_LIMIT:
        return order, []
    origin = {}
    for d, _, src in items:
        origin.setdefault(d, src)
    core = []
    for src in dict.fromkeys(src for _, _, src in items):
        tok = _token(src)
        cand = [d for d in order if origin[d] == src and core_score(d, tok) >= 2]
        cand.sort(key=lambda d: (-core_score(d, tok), len(d), d))
        core += cand[:SUB_LIMIT]
    core = list(dict.fromkeys(core))[:CORE_LIMIT]
    return core, [d for d in order if d not in set(core)]


class DomainDB:
    """Локальная база в %APPDATA%\\KeenRoute\\db\\v2fly.json. Обновляется только по кнопке."""

    def __init__(self, path: Path | None = None):
        self.path = path or (app_dir() / "db" / "v2fly.json")
        self.data: dict[str, dict] = {}
        self.updated: float = 0
        self.last_changed = 0
        self.load()

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.data, self.updated = raw["services"], raw["updated"]
        except Exception:  # noqa: BLE001
            self.data, self.updated = {}, 0

    @property
    def stale(self) -> bool:
        return time.time() - self.updated > DB_MAX_AGE

    def update(self, timeout: float = 90) -> int:
        r = requests.get(V2FLY_ZIP, timeout=timeout)
        r.raise_for_status()
        files = {}
        with zipfile.ZipFile(_io.BytesIO(r.content)) as z:
            for n in z.namelist():
                parts = n.split("/")
                if len(parts) == 3 and parts[1] == "data" and parts[2]:
                    files[parts[2]] = z.read(n).decode("utf-8", errors="replace")
        if len(files) < 100:
            raise RuntimeError("База скачалась не полностью")
        new = parse_v2fly(files)
        changed = sum(1 for k, v in new.items() if self.data.get(k) != v) + sum(1 for k in self.data if k not in new)
        self.last_changed = changed
        self.data = new
        self.updated = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"updated": self.updated, "services": self.data}), encoding="utf-8")
        tmp.replace(self.path)
        return len(self.data)

    def entry(self, name: str) -> Entry | None:
        if name not in self.data:
            return None
        items, skipped = resolve_depth(self.data, name)
        kept = set(compact([d for d, _, _ in items]))
        main, regional = split_regional([d for d in dict.fromkeys(d for d, _, _ in items) if d in kept])
        zones = [d for d in main if "." not in d]  # целые зоны (.youtube) — только по желанию
        keep = set(main) - set(zones)
        core, rest = split_core([x for x in items if x[0] in keep])
        return Entry(name, name, "v2fly", "База", core, optional=zones + rest + regional, skipped=skipped)

    def search(self, q: str, limit: int = 40) -> list[Entry]:
        q = q.strip().lower()
        if not q or not self.data:
            return []
        scored = []
        for name, rec in self.data.items():
            n = name.lower()
            if n == q:
                s = 0
            elif n.startswith(q):
                s = 1
            elif q in n:
                s = 2
            elif "!" not in n and not n.startswith("tld-") and len(rec["domains"]) <= 500 \
                    and any(q in d for d in rec["domains"]):
                s = 3
            else:
                continue
            scored.append((s, len(n), name))
        return [e for e in (self.entry(n) for _, _, n in sorted(scored)[:limit]) if e]


def search_templates(templates: list[Entry], q: str) -> list[Entry]:
    q = q.strip().lower()
    if not q:
        return list(templates)
    return [t for t in templates if q in t.title.lower() or q in t.id or q in t.category.lower()
            or any(q in d for d in t.domains)]


# ---------- IP по ASN ----------
def ripe_search(query: str, timeout: float = 20) -> list[tuple[str, str]]:  # noqa: D401
    """Название компании → [(AS32934, 'FACEBOOK'), ...]."""
    r = requests.get(f"{RIPE}/searchcomplete/data.json", params={"resource": query}, timeout=timeout)
    r.raise_for_status()
    out = []
    for cat in r.json().get("data", {}).get("categories", []):
        if cat.get("category") == "ASNs":
            for s in cat.get("suggestions", []):
                out.append((s.get("value", ""), s.get("description", "")))
    return out[:10]


# Общие облака/CDN: их подсети целиком добавлять нельзя — туда уйдёт пол-интернета
SHARED_ASN = {"13335": "Cloudflare", "20940": "Akamai", "16625": "Akamai", "16509": "Amazon", "14618": "Amazon",
              "15169": "Google", "396982": "Google Cloud", "8075": "Microsoft", "54113": "Fastly",
              "14061": "DigitalOcean", "24940": "Hetzner", "16276": "OVH", "63949": "Linode/Akamai",
              "20473": "Vultr", "13238": "Yandex", "47764": "VK", "209242": "Cloudflare"}


@dataclass
class IpFinding:
    asn: str
    holder: str
    shared: bool
    prefixes: list[str]   # для общих облаков — только IP самого сайта (/32)


def _ripe(endpoint: str, resource: str, timeout: float = 20) -> dict:
    r = requests.get(f"{RIPE}/{endpoint}/data.json", params={"resource": resource}, timeout=timeout)
    r.raise_for_status()
    return r.json().get("data", {}) or {}


def resolve_ipv4(domain: str) -> list[str]:
    import socket
    try:
        infos = socket.getaddrinfo(domain, 443, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    return sorted({i[4][0] for i in infos})


def find_ips_for_domain(domain: str) -> list[IpFinding]:
    """Домен → его IP → автономные системы → подсети. Для общих облаков — только IP сайта."""
    ips = resolve_ipv4(domain)
    if not ips:
        raise RuntimeError(f"Домен {domain} не резолвится")
    by_asn: dict[str, list[str]] = {}
    for ip in ips:
        for asn in _ripe("network-info", ip).get("asns", []) or ["?"]:
            by_asn.setdefault(str(asn), []).append(ip)
    out = []
    for asn, site_ips in by_asn.items():
        holder = _ripe("as-overview", f"AS{asn}").get("holder", "") if asn != "?" else "неизвестно"
        shared = asn in SHARED_ASN or asn == "?"
        if shared:
            pfx = collapse_ips(site_ips)
        else:
            pfx = ripe_prefixes(f"AS{asn}")
        out.append(IpFinding(f"AS{asn}", holder or SHARED_ASN.get(asn, ""), shared, pfx))
    return out


def ripe_prefixes(asn: str, timeout: float = 30) -> list[str]:
    r = requests.get(f"{RIPE}/announced-prefixes/data.json", params={"resource": asn}, timeout=timeout)
    r.raise_for_status()
    pfx = [p["prefix"] for p in r.json().get("data", {}).get("prefixes", []) if ":" not in p.get("prefix", ":")]
    return collapse_ips(pfx, max_prefix=24)


# ---------- что откуда добавлено (для автообновления) ----------
class SourceStore:
    """%APPDATA%\\KeenRoute\\sources.json: {роутер: {список: {"sources": [...], "excluded": [...]}}}."""

    def __init__(self, path: Path | None = None):
        self.path = path or (app_dir() / "sources.json")
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.data = {}

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, router: str, group: str, source: str, excluded: list[str]):
        rec = self.data.setdefault(router, {}).setdefault(group, {"sources": [], "excluded": []})
        if source not in rec["sources"]:
            rec["sources"].append(source)
        rec["excluded"] = sorted(set(rec["excluded"]) | set(excluded))
        self.save()

    def for_router(self, router: str) -> dict:
        return self.data.get(router, {})


def fresh_entries(source: str, templates: list[Entry], db: DomainDB) -> list[str]:
    kind, _, ident = source.partition(":")
    if kind == "tpl":
        t = next((x for x in templates if x.id == ident), None)
        return (t.zones + t.domains + t.ips) if t else []
    if kind == "v2fly":
        e = db.entry(ident)
        return e.domains if e else []
    return []


class DisabledStore:
    """Выключенные списки: %APPDATA%\\KeenRoute\\disabled.json — {роутер: {список: {"interface", "reject"}}}.
    Список на роутере остаётся, у него лишь снят маршрут; здесь помним, куда вернуть."""

    def __init__(self, path: Path | None = None):
        self.path = path or (app_dir() / "disabled.json")
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.data = {}

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    def for_router(self, router: str) -> dict:
        return self.data.get(router, {})

    def set(self, router: str, group: str, interface: str, reject: bool):
        self.data.setdefault(router, {})[group] = {"interface": interface, "reject": reject}
        self.save()

    def drop(self, router: str, group: str):
        if self.data.get(router, {}).pop(group, None) is not None:
            self.save()
