"""Opening hours (and a phone or a web) for the places whose OpenStreetMap object has none, from
open sources that may stand beside ODbL data (docs/mista.md, „Doplněné otevírací doby“):

- `alltheplaces`: All The Places (CC0), the chains' own store finders scraped once a week – a
  chain's shop, pharmacy, bank or post office gets its official hours. A feature belongs to the
  nearest place within ATP_NEAR m whose name has the chain's brand in it (or, for a spider of a
  kind, the nearest place of that kind).
- `web`: the place's own web page (its `web` from OSM), where the page says its hours as
  schema.org data (JSON-LD `openingHoursSpecification` or `openingHours`); nothing else of the
  page is read.
- `mesto`: a list kept by hand in data/mista/hodiny.json – the town's offices and institutions
  (úřední hodiny of the magistrát and the obvody, libraries, pools), each with the page it is
  from and when it was checked.

OSM always wins: a supplement is used only where the OSM object has no `opening_hours`
(petka.mista.export). Of the supplements `mesto` comes before `alltheplaces` before `web`.
Pure functions except `atp_features` and `web_hours`, which go to the network.
"""

import json
import re
from pathlib import Path

from . import osm
from .other import _fold, _m

SOURCES = ("mesto", "alltheplaces", "web")      # in the order one wins over another

# --- All The Places -------------------------------------------------------------------------

ATP_URL = "https://data.alltheplaces.xyz/runs/latest/output/{}.geojson"
# The spiders with shops or offices in Czechia (a spider of a chain's whole country or of a
# continent: its features outside the town are dropped). A spider ATP stops running answers
# 404 and is skipped.
ATP_SPIDERS = (
    "albert_cz", "billa", "kaufland", "lidl", "penny", "tesco_eu", "globus_de", "hruska_cz", "zabka_cz", "cba_cz",
    "coop_cz", "teta_cz", "rossmann_cz", "dm", "dr_max", "benu_cz", "czech_post_cz", "fio_banka", "fio_banka_atm",
    "unicredit_bank_cz", "o2_cz", "tmobile_cz", "vodafone_cz", "kfc_cz", "mcdonalds_cz", "burger_king_cz",
    "pizza_hut_cz", "costa_coffee_cz", "starbucks_eu", "subway", "decathlon_cz", "douglas_cz", "fielmann_cz",
    "hornbach", "obi_eu", "ikea", "dracik", "deichmann", "ccc", "hm", "kik", "pepco", "tedi", "action",
    "takko_fashion", "bala_cz", "novak_cz", "mujobchod_cz", "reznictvi_rabbit_cz", "shell", "omv", "mol", "orlen",
)
# A spider whose features carry a branch's own name („Pardubice 2“), not the chain's: such a
# feature is the nearest place of this kind.
ATP_KIND = {"czech_post_cz": "posta"}
ATP_NEAR = 100      # m
# The town with a margin: what is outside is no place of the export.
TOWN_BOX = (15.62, 49.96, 15.92, 50.11)     # west, south, east, north


def atp_features(client, spiders=ATP_SPIDERS) -> tuple[list[dict], list[str]]:
    """The features of the spiders inside TOWN_BOX that have hours, a phone or a web, as
    {spider, brand, name, at, hours, phone, web}; and the spiders that failed. One request per
    spider; ATP's „latest“ redirects to the last run that had output for it."""
    out, failed = [], []
    for s in spiders:
        try:
            r = client.get(ATP_URL.format(s), headers={"User-Agent": osm.USER_AGENT}, timeout=120)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            features = r.json().get("features") or []
        except Exception:   # noqa: BLE001 – one spider down is no reason to drop the others
            failed.append(s)
            continue
        for f in features:
            g, p = f.get("geometry") or {}, f.get("properties") or {}
            if g.get("type") != "Point":
                continue
            lon, lat = g["coordinates"][:2]
            if not (TOWN_BOX[0] < lon < TOWN_BOX[2] and TOWN_BOX[1] < lat < TOWN_BOX[3]):
                continue
            c = osm.contact_of(p)
            hours = (p.get("opening_hours") or "").strip() or None
            if hours or c:
                out.append({"spider": s, "brand": p.get("brand") or "", "name": p.get("name") or "",
                            "at": [lon, lat], "hours": hours, **c})
    return out, failed


def match_atp(places: list[dict], features: list[dict]) -> dict[str, dict]:
    """{place id: supplement} for the features that belong to a place: the nearest place within
    ATP_NEAR m whose folded name holds the feature's folded brand (or name), or of ATP_KIND's
    kind for such a spider. A place two features claim keeps the nearer one."""
    out: dict[str, tuple[float, dict]] = {}
    for f in features:
        kind = ATP_KIND.get(f["spider"])
        brand = _fold(f["brand"] or f["name"])
        if not kind and not brand:
            continue
        best = None
        for p in places:
            if not p.get("name") or abs(p["at"][1] - f["at"][1]) > 0.002:
                continue
            fits = p["kind"] == kind if kind else brand in _fold(p["name"])
            if fits and (d := _m(p["at"], f["at"])) <= ATP_NEAR and (best is None or d < best[0]):
                best = (d, p)
        if best and (best[1]["id"] not in out or best[0] < out[best[1]["id"]][0]):
            sup = {k: f[k] for k in ("hours", "phone", "web") if f.get(k)}
            out[best[1]["id"]] = (best[0], {**sup, "url": None})
    return {k: v for k, (_, v) in out.items()}


# --- schema.org on the place's own web ------------------------------------------------------

WEB_TIMEOUT = 15        # s for one page
WEB_MAX_BYTES = 2_000_000
NOT_OWN_WEB = re.compile(r"(?i)^https?://([^/]*\.)?(facebook|instagram|fb|google|goo\.gl|firmy|mapy)\.")
DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
SCHEMA_DAY = {"monday": "Mo", "tuesday": "Tu", "wednesday": "We", "thursday": "Th", "friday": "Fr",
              "saturday": "Sa", "sunday": "Su", "mo": "Mo", "tu": "Tu", "we": "We", "th": "Th", "fr": "Fr",
              "sa": "Sa", "su": "Su"}
LD_JSON = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_D = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
_DAYS = rf"{_D}(?:-{_D})?(?:,{_D}(?:-{_D})?)*"
_SPANS = r"\d{1,2}:\d{2}-\d{1,2}:\d{2}(?:,\d{1,2}:\d{2}-\d{1,2}:\d{2})*"
# One rule of opening_hours in the plain form the app reads: days, then times or `off`.
OSM_RULE = re.compile(rf"^(?:{_DAYS} )?(?:{_SPANS}|off)$")


def _hhmm(t: str) -> str | None:
    m = re.match(r"^(\d{1,2}):(\d{2})", (t or "").strip())
    return f"{int(m[1]):02d}:{m[2]}" if m and int(m[1]) <= 24 else None


def _day(d) -> str | None:
    d = str(d or "").rsplit("/", 1)[-1].strip().lower()
    return SCHEMA_DAY.get(d)


def _week(spans: dict[str, list[str]]) -> str | None:
    """{OSM day: ["08:00-12:00", …]} as opening_hours, days in a row with the same spans as one
    rule („Mo-Fr 08:00-17:00; Sa 09:00-12:00“); None when no day has any."""
    rules, i = [], 0
    while i < 7:
        s = ",".join(spans.get(DAYS[i], []))
        j = i
        while j + 1 < 7 and ",".join(spans.get(DAYS[j + 1], [])) == s:
            j += 1
        if s:
            rules.append(f"{DAYS[i]}{'-' + DAYS[j] if j > i else ''} {s}")
        i = j + 1
    return "; ".join(rules) or None


def _things(data):
    """Every dict in a JSON-LD document, @graph and nested ones too."""
    if isinstance(data, list):
        for x in data:
            yield from _things(x)
    elif isinstance(data, dict):
        yield data
        for v in data.values():
            if isinstance(v, (dict, list)):
                yield from _things(v)


def hours_of_schema(thing: dict) -> str | None:
    """The opening_hours of a schema.org thing: its openingHoursSpecification (dayOfWeek, opens,
    closes; a spec with validFrom/validThrough is a season or a holiday and is left out), else
    its openingHours when every rule of it is already in OSM's syntax („Mo-Fr 08:00-17:00“)."""
    specs = thing.get("openingHoursSpecification")
    if specs:
        spans: dict[str, list[str]] = {}
        for s in specs if isinstance(specs, list) else [specs]:
            if not isinstance(s, dict) or s.get("validFrom") or s.get("validThrough"):
                continue
            opens, closes = _hhmm(s.get("opens")), _hhmm(s.get("closes"))
            days = s.get("dayOfWeek")
            for d in days if isinstance(days, list) else [days]:
                if (day := _day(d)) and opens and closes and opens != closes:
                    spans.setdefault(day, []).append(f"{opens}-{closes}")
        for d in spans:
            spans[d] = sorted(set(spans[d]))
        if spans:
            return _week(spans)
    oh = thing.get("openingHours")
    rules = [r.strip() for r in (oh if isinstance(oh, list) else [oh] if isinstance(oh, str) else [])]
    rules = [re.sub(r"\s+", " ", r) for r in rules if r]
    if rules and all(OSM_RULE.match(r) for r in rules):
        return "; ".join(rules)
    return None


def hours_from_html(html: str) -> str | None:
    """The hours a page states as schema.org JSON-LD, of the first thing that has them; None when
    it states none. Broken JSON in one block does not stop the others."""
    for block in LD_JSON.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for thing in _things(data):
            if hours := hours_of_schema(thing):
                return hours
    return None


def web_hours(client, url: str) -> str | None:
    """The hours on the page at `url` (hours_from_html); None for a social network or another
    site that is not the place's own, a page that does not answer 200 with HTML, or too big."""
    if NOT_OWN_WEB.match(url):
        return None
    r = client.get(url, headers={"User-Agent": osm.USER_AGENT}, timeout=WEB_TIMEOUT, follow_redirects=True)
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "") or len(r.content) > WEB_MAX_BYTES:
        return None
    return hours_from_html(r.text)


# --- the town's list ------------------------------------------------------------------------

LIST = Path(__file__).resolve().parents[3] / "data" / "mista" / "hodiny.json"


def town_list(path: Path = LIST) -> dict[str, dict]:
    """{place id: supplement} of the hand-kept list: each entry {id, name, hours, phone?, web?,
    url, checked}; `name` is there for whoever keeps the list, `url` the page the hours are
    from. An entry whose hours OSM's syntax does not read is an error of the list."""
    out = {}
    for e in json.loads(path.read_text())["places"]:
        if e["hours"] != "24/7" and not all(OSM_RULE.match(r.strip()) for r in e["hours"].split(";")):
            raise ValueError(f"{e['id']} {e['name']}: hours not in OSM syntax: {e['hours']}")
        out[e["id"]] = {"hours": e["hours"], "url": e["url"], **{k: e[k] for k in ("phone", "web") if e.get(k)}}
    return out


# --- the weekly job -------------------------------------------------------------------------

WEB_PAUSE = 0.5         # s between two pages


def _places(conn) -> list[dict]:
    rows = conn.execute("SELECT id, kind, name, lon, lat, hours, web FROM mista_places").fetchall()
    return [{**r, "at": [r["lon"], r["lat"]]} for r in rows]


def _replace(conn, source: str, rows: dict[str, dict]) -> int:
    conn.execute("DELETE FROM mista_doplnky WHERE source = %s", (source,))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO mista_doplnky (id, source, hours, phone, web, url) VALUES (%s, %s, %s, %s, %s, %s)",
                        [(i, source, r.get("hours"), r.get("phone"), r.get("web"), r.get("url")) for i, r in rows.items()])
    return len(rows)


def run_mesto(conn, client) -> dict:
    known = {p["id"] for p in _places(conn)}
    rows = town_list()
    missing = sorted(set(rows) - known)
    return {"places": _replace(conn, "mesto", {k: v for k, v in rows.items() if k in known}), "unknown_ids": missing}


def run_atp(conn, client) -> dict:
    features, failed = atp_features(client)
    if len(failed) > len(ATP_SPIDERS) // 2:
        raise RuntimeError(f"All The Places: {len(failed)} spiders failed, the last rows stay")
    rows = match_atp(_places(conn), features)
    return {"features": len(features), "places": _replace(conn, "alltheplaces", rows), "failed": failed}


def run_web(conn, client, sleep=None) -> dict:
    """Every place without OSM hours that has its own web: the hours its page states. A page that
    fails to answer keeps the hours found the week before."""
    import time
    sleep = sleep or time.sleep
    before = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, hours, url FROM mista_doplnky WHERE source = 'web'").fetchall()}
    rows, tried, failed = {}, 0, 0
    for p in _places(conn):
        if p["hours"] or not p["web"] or NOT_OWN_WEB.match(p["web"]):
            continue
        tried += 1
        try:
            if hours := web_hours(client, p["web"]):
                rows[p["id"]] = {"hours": hours, "url": p["web"]}
        except Exception:   # noqa: BLE001 – a site down this week is no reason to forget it
            failed += 1
            if p["id"] in before:
                rows[p["id"]] = before[p["id"]]
        sleep(WEB_PAUSE)
    return {"pages": tried, "failed": failed, "places": _replace(conn, "web", rows)}


def update(only: tuple[str, ...] = SOURCES) -> dict:
    from .. import jobs as runner
    from ..jobs import Unit
    run = {"mesto": run_mesto, "alltheplaces": run_atp, "web": run_web}
    return runner.run("mista-doplnky", "doplňky míst",
                      lambda conn, client: [Unit((s,), s, run[s]) for s in SOURCES if s in only],
                      client={"follow_redirects": True})
