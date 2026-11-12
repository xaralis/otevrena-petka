"""Places and parcels of resolutions as geometry, from ČÚZK's RÚIAN map service (free, no key).

    data/usneseni/geo_cache.json   every ČÚZK answer keyed by normalized query (misses too)
    data/usneseni/geo.json         {uid: [{kind, label, source_text, geometry}]}  GeoJSON, WGS84

`places` and `parcels` are LLM output in whatever form the minutes used. Parsing is
deterministic and conservative; what does not parse cleanly is left out:

- parcel: "p. p. č. 2515/14, k. ú. Pardubice", "st. 3815", "č. parc. st. 10089 a 10090" →
  polygon of the parcel as it exists *today*. Without a k. ú. the one the resolution names
  is used (if it names exactly one), else Pardubice. "p. č." without a kind tries pozemková
  first, then stavební.
- address: a Pardubice street + numbers ("Jiránkova 2206-08", "čp. 2731, ul. Sokolovská"),
  a part of the town + čp. ("Dražkovice 121"), or a bare "čp. 2303" (only when exactly one
  building with it lies in MO Pardubice V) → point; several numbers → MultiPoint.
- street: the string is just a Pardubice street name ("ul. A. Krause") → line.
- general (Dukla, sídliště, vnitroblok of several streets, k. ú., other towns) → skipped.

Run `python -m petka.usneseni.geo` to (re)build geo.json; only cache misses go to ČÚZK.
"""

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict

import httpx

from .. import obvody
from .store import DATA, _write
from .text import fold, slug

log = logging.getLogger(__name__)

SERVICE = "https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/Prohlizeci_sluzba_nad_daty_RUIAN/MapServer"
L_ADDRESS, L_STREET, L_PARCEL, L_MOMC, L_PART = 1, 4, 5, 8, 11
OBEC = 555134            # Pardubice
MOMC = obvody.DEFAULT.momc  # Pardubice V
BBOX = (15.70, 49.98, 15.85, 50.07)
KU = {  # katastrální území that the minutes mention -> RÚIAN code
    "pardubice": 717657, "drazkovice": 632252, "nove jesencany": 718084,
    "stare jesencany": 754412, "pardubicky": 717835, "semtin": 747386,
    "nemosice": 703249, "svitkov": 718033,
}
KU_NAME = {"pardubice": "Pardubice", "drazkovice": "Dražkovice", "nove jesencany": "Nové Jesenčany",
           "stare jesencany": "Staré Jesenčany", "pardubicky": "Pardubičky", "semtin": "Semtín",
           "nemosice": "Nemošice", "svitkov": "Svítkov"}
POZEMKOVA, STAVEBNI = 2, 1   # druhcislovanikod
# colloquial or outdated street names -> RÚIAN name
ALIASES = {
    "csa": "Čs. armády", "ceskoslovenske armady": "Čs. armády", "cacka": "Čacké",
    "resslova": "Josefa Ressla", "zborovskeho namesti": "Zborovské náměstí",
    "zborovskeho nam.": "Zborovské náměstí", "spravedlnosti": "Na Spravedlnosti",
    "dukelske namesti": "náměstí Dukelských hrdinů",
}
GENERIC = {"namesti": "nam.", "trida": "tr.", "nabrezi": "nabr."}
DECOR = {"ul", "ulice", "a", "c", "p", "pardubice"}
# allowed around an address (with numbers), never around a bare street name
DESCRIPTORS = {"areal", "budova", "objekt", "bytovy", "dum", "rd", "vnitroblok"}
MAX_RANGE = 12           # "153 – 174" is a stretch of road, not 22 houses: endpoints only
PAUSE, TIMEOUT, RETRIES, BATCH = 0.2, 30, 4, 25

CACHE_PATH = DATA / "geo_cache.json"
OUT_PATH = DATA / "geo.json"


# --- ČÚZK --------------------------------------------------------------------------------

class Cache(dict):
    """JSON file of query -> answer; `offline` turns every miss into an error."""

    def __init__(self, offline: bool = False):
        super().__init__(json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {})
        self.offline, self.dirty = offline, 0

    def put(self, key: str, value) -> None:
        self[key] = value
        self.dirty += 1
        if self.dirty >= 50:
            self.save()

    def save(self) -> None:
        if self.dirty:
            # one entry per line: diffable, and big geometries stay on their own line
            body = ",\n".join(f"{json.dumps(k, ensure_ascii=False)}: "
                              f"{json.dumps(self[k], ensure_ascii=False, separators=(',', ':'))}"
                              for k in sorted(self))
            _write(CACHE_PATH, "{\n" + body + "\n}\n")
            self.dirty = 0


def _query(layer: int, where: str, fields: str, with_geometry: bool = True, **extra) -> list[dict]:
    """GeoJSON features of a MapServer layer query, in WGS84 (the server's default S-JTSK ->
    WGS84 transformation is the 7-parameter one, ~1 m)."""
    params = {"where": where, "outFields": fields, "returnGeometry": str(with_geometry).lower(),
              "outSR": 4326, "geometryPrecision": 6, "f": "geojson", **extra}
    for attempt in range(RETRIES):
        time.sleep(PAUSE)
        try:
            r = httpx.get(f"{SERVICE}/{layer}/query", params=params, timeout=TIMEOUT)
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise RuntimeError(d["error"])
            if d.get("exceededTransferLimit") or d.get("properties", {}).get("exceededTransferLimit"):
                log.warning("transfer limit hit for %s", where)
            return d["features"]
        except (httpx.HTTPError, RuntimeError, ValueError) as e:
            if attempt == RETRIES - 1:
                raise
            log.warning("ČÚZK query failed (%r), retrying", e)
            time.sleep(2 ** attempt * 2)
    return []


def _cached(cache: Cache, key: str, fetch):
    if key not in cache:
        if cache.offline:
            raise LookupError(key)
        cache.put(key, fetch())
    return cache[key]


def _bbox_params() -> dict:
    return {"geometry": ",".join(map(str, BBOX)), "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}


def _merge(geoms: list[dict]) -> dict | None:
    """One geometry from several features (a street or parcel can come in parts)."""
    geoms = [g for g in geoms if g]
    if len(geoms) <= 1:
        return geoms[0] if geoms else None
    kind = geoms[0]["type"].removeprefix("Multi")
    parts = []
    for g in geoms:
        parts += g["coordinates"] if g["type"].startswith("Multi") else [g["coordinates"]]
    return {"type": "Multi" + kind, "coordinates": parts}


def streets(cache: Cache) -> list[list]:
    return _cached(cache, f"streets:{OBEC}", lambda: sorted(
        [f["properties"]["kod"], f["properties"]["nazev"]]
        for f in _query(L_STREET, f"obec={OBEC}", "kod,nazev", with_geometry=False)))


def parts(cache: Cache) -> list[str]:
    return _cached(cache, f"parts:{OBEC}", lambda: sorted(
        f["properties"]["nazev"] for f in _query(L_PART, f"obec={OBEC}", "nazev", with_geometry=False)))


def momc_polygon(cache: Cache) -> dict:
    return _cached(cache, f"momc:{MOMC}", lambda: _merge(
        [f["geometry"] for f in _query(L_MOMC, f"kod={MOMC}", "kod", maxAllowableOffset=0.00002)]))


def street_geometry(cache: Cache, kod: int) -> dict | None:
    return _cached(cache, f"street:{kod}", lambda: _merge(
        [f["geometry"] for f in _query(L_STREET, f"kod={kod}", "kod", maxAllowableOffset=0.00001)]))


def addresses(cache: Cache, field: str, n: int) -> list[dict]:
    """Address points around Pardubice with čp. (`cp`) or č. o. (`co`) = n."""
    col = {"cp": "cislodomovni", "co": "cisloorientacni"}[field]

    def fetch():
        out = []
        for f in _query(L_ADDRESS, f"{col}={n}", "kod,adresa,cislodomovni,cisloorientacni,ulice",
                        **_bbox_params()):
            p = f["properties"]
            out.append({"kod": p["kod"], "adresa": p["adresa"], "cp": p["cislodomovni"],
                        "co": p["cisloorientacni"], "ulice": p["ulice"],
                        "point": f["geometry"]["coordinates"]})
        return sorted(out, key=lambda a: a["kod"])
    return _cached(cache, f"{field}:{n}", fetch)


def _parcel_key(ku: int, druh: int, kmen: int, pod: int | None) -> str:
    return f"parcel:{ku}:{druh}:{kmen}" + (f"/{pod}" if pod else "")


def fetch_parcels(cache: Cache, wanted: set[tuple]) -> None:
    """Fill the cache for (ku, druh, kmen, pod) in batches; parcels not found are cached as None."""
    todo = defaultdict(list)
    for w in sorted(wanted, key=lambda w: (*w[:3], w[3] or 0)):
        if _parcel_key(*w) not in cache:
            todo[w[:2]].append(w[2:])
    if todo and cache.offline:
        raise LookupError(f"{sum(map(len, todo.values()))} parcels not in cache")
    for (ku, druh), nums in todo.items():
        for i in range(0, len(nums), BATCH):
            chunk = nums[i:i + BATCH]
            ors = " OR ".join(f"(kmenovecislo={k} AND poddelenicisla"
                              + (f"={p})" if p else " IS NULL)") for k, p in chunk)
            found = defaultdict(list)
            for f in _query(L_PARCEL, f"katastralniuzemi={ku} AND druhcislovanikod={druh} AND ({ors})",
                            "kmenovecislo,poddelenicisla", maxAllowableOffset=0.000003):
                p = f["properties"]
                found[(p["kmenovecislo"], p["poddelenicisla"])].append(f["geometry"])
            for k, p in chunk:
                cache.put(_parcel_key(ku, druh, k, p), _merge(found.get((k, p), [])))


# --- parsing -----------------------------------------------------------------------------

def _key(s: str) -> str:
    """Folded, dashes unified, a space after every abbreviation dot, single spaces."""
    s = fold(s)
    s = re.sub(r"[–—−‐]", "-", s).replace("×", " x ").replace("⨯", " x ")
    s = re.sub(r"[„“”\"'()]", " ", s)
    s = re.sub(r"\.(?=[^\s.,])", ". ", s)
    return re.sub(r"\s+", " ", s).strip()


class Names:
    """Matcher for Pardubice street names and town parts inside a place string."""

    def __init__(self, street_rows: list[list], part_names: list[str]):
        self.kod = {name: kod for kod, name in street_rows}
        exact = {_key(name): name for name in self.kod}
        variants = defaultdict(set)
        for k, name in exact.items():
            for v in self._variants(k):
                variants[v].add(name)
        index = dict(exact)
        index.update({v: next(iter(ns)) for v, ns in variants.items() if len(ns) == 1 and v not in exact})
        index.update({a: n for a, n in ALIASES.items() if n in self.kod})
        self.streets = index
        self.parts = {_key(p): p for p in part_names}
        self._re_street = self._alternation(self.streets)
        self._re_part = self._alternation(self.parts)

    @staticmethod
    def _variants(k: str) -> set[str]:
        words, out = k.split(), set()
        for w, ab in GENERIC.items():
            if w in words:
                out.add(" ".join(ab if x == w else x for x in words))
                if len(words) > 1:
                    out.add(" ".join(x for x in words if x != w))
        # "Artura Krause" -> "a. krause", "Josefa Ressla" -> "j. ressla"
        if len(words) >= 2 and all(w.isalpha() and len(w) > 2 for w in words[:-1]) \
                and not set(words) & set(GENERIC):
            out.add(" ".join(w[0] + "." for w in words[:-1]) + " " + words[-1])
        return out

    @staticmethod
    def _alternation(keys) -> re.Pattern:
        alts = "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True))
        return re.compile(rf"(?<![\w.])(?:{alts})(?!\w)")

    def find(self, s: str, which: str) -> tuple[list[str], str]:
        """Names found in `s` and `s` with them blanked out."""
        rx, table = (self._re_street, self.streets) if which == "street" else (self._re_part, self.parts)
        found = [table[m.group(0)] for m in rx.finditer(s)]
        return list(dict.fromkeys(found)), rx.sub(" ", s)


CP_RE = re.compile(r"(?<!\w)(?:c\. ?p\.?|cp\.?)(?!\w)")
KU_RE = re.compile(r"(?:k\. ?u\.?|katastralnim uzemi)\s*(?:a obec\s+)?([a-z]+(?: [a-z]+)?)")
NUM_RE = re.compile(r"(?<![\w/])(\d+)(?:/(\d+)[a-z]?)?(?:\s*-\s*(?:c\. ?p\. ?)?(\d+))?(?![\w/])")


def _ku_code(name: str) -> str | None:
    """'pardubice, na spravedlnosti' -> 'pardubice' (longest known k. ú. at the start)."""
    for k in sorted(KU, key=len, reverse=True):
        if name == k or name.startswith((k + " ", k + ",")):
            return k
    return None


def _numbers(s: str) -> list[tuple[int, int | None]]:
    """'2449-52' -> 2449..2452, '996/20' -> (996, 20), '2224, 2225 a 2227' -> three."""
    out = []
    for a, co, b in NUM_RE.findall(s):
        a = int(a)
        if b:
            b = int(b)
            if b < a:   # "2449-52": the end repeats only the last digits
                b = int(str(a)[:len(str(a)) - len(str(b))] + str(b))
            out += [(n, None) for n in range(a, b + 1)] if 0 <= b - a < MAX_RANGE else [(a, None), (b, None)]
        else:
            out.append((a, int(co) if co else None))
    return list(dict.fromkeys(out))


def parse_place(text: str, names: Names) -> dict | None:
    """{kind: address|street, ...} or None for a general place."""
    s = _key(text)
    s = KU_RE.sub(" , ", s)
    s = re.sub(r",?\s*pardubice$", "", s).strip(" ,")
    marker = bool(CP_RE.search(s))
    s = CP_RE.sub(" ", s)
    found, rest = names.find(s, "street")
    part = None
    if not found:
        ps, rest2 = names.find(s, "part")
        if len(ps) == 1:
            part, rest = ps[0], rest2
    nums = _numbers(rest)
    leftover = [w for w in (t.strip(".") for t in re.split(r"[\s,;:\-]+", NUM_RE.sub(" ", rest)))
                if w and w not in DECOR]
    if len(found) > 1:
        return None
    if leftover and not marker and not (nums and set(leftover) <= DESCRIPTORS):
        return None
    if found and not nums:
        return None if leftover else {"kind": "street", "street": found[0]}
    if nums and (found or part or marker):
        return {"kind": "address", "street": found[0] if found else None, "part": part,
                "numbers": nums, "explicit_cp": marker}
    return None


def parse_parcel(text: str, default_ku: str) -> dict | None:
    """{ku, druh (None = unknown), numbers: [(kmen, pod)], ku_inferred} or None."""
    t = re.sub(r"(?<=\d)O|O(?=\d)", "0", text)        # OCR: "2483/1O"
    t = re.sub(r"(?<![\w])l(?=\d)", "1", t)            # OCR: "l2047/4"
    s = _key(t)
    m = KU_RE.search(s)
    ku = _ku_code(m.group(1)) if m else default_ku
    if not ku:
        return None
    body = s[:m.start()] if m else s
    if re.search(r"(?<!\w)(?:st|stp)\.|(?<!\w)stavebni|parc\. st", body):
        druh = STAVEBNI
    elif re.search(r"(?<!\w)p\. ?p\. ?c|pozem|c\. ?p\. ?p|p\. c\. p\.", body):
        druh = POZEMKOVA
    else:
        druh = None
    nums = [(int(k), int(p) if p else None) for k, p in re.findall(r"(?<![\w/])(\d+)(?:/(\d+))?(?![\w/])", body)]
    if not nums or re.search(r"[a-z]{3,}", re.sub(r"stavebni|stp|parc[a-z]*|pozem[a-z]*|cislo", "", body)):
        return None
    return {"ku": ku, "druh": druh, "numbers": nums, "ku_inferred": not m}


def _resolution_ku(r: dict) -> str | None:
    """The k. ú. a resolution names, if it names exactly one."""
    kus = {_ku_code(m.group(1)) for s in r.get("places", []) + r.get("parcels", [])
           for m in KU_RE.finditer(_key(s))} - {None}
    return kus.pop() if len(kus) == 1 else None


def context(r: dict, names: Names) -> set[str]:
    """Folded street and town-part names among a resolution's places (k. ú. names not: they
    are too coarse, `_resolution_ku` handles them)."""
    out = set()
    for t in r.get("places", []):
        k = KU_RE.sub(" , ", _key(t))
        for which in ("street", "part"):
            out |= {fold(n) for n in names.find(k, which)[0]}
    return out


# --- geocoding ---------------------------------------------------------------------------

def _inside(pt, geom: dict) -> bool:
    x, y = pt
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    hit = False
    for rings in polys:
        for ring in rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                    hit = not hit
    return hit


def _coords(g: dict):
    c = g["coordinates"]
    depth = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2,
             "Polygon": 2, "MultiPolygon": 3}[g["type"]]
    stack = [(c, depth)]
    while stack:
        c, d = stack.pop()
        if d == 0:
            yield c
        else:
            stack += [(x, d - 1) for x in c]


def in_bbox(g: dict) -> bool:
    xs, ys = zip(*_coords(g))
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return BBOX[0] <= cx <= BBOX[2] and BBOX[1] <= cy <= BBOX[3]


def _one_place(cands: list[dict]) -> dict | None:
    """Several address points of one building (entrances) are fine; different buildings are not."""
    if not cands:
        return None
    xs, ys = [a["point"][0] for a in cands], [a["point"][1] for a in cands]
    if max(xs) - min(xs) > 0.002 or max(ys) - min(ys) > 0.0015:
        return None
    return min(cands, key=lambda a: (a["co"] or 0, a["kod"]))


def _street_of(adresa: str) -> str:
    return re.sub(r"\s+(?:č\.\s?[pe]v?\.\s*)?\d+(?:/\d+\w?)?$", "", adresa.split(",")[0])


def _runs(ns: list[int]) -> str:
    ns, out, i = sorted(set(ns)), [], 0
    while i < len(ns):
        j = i
        while j + 1 < len(ns) and ns[j + 1] == ns[j] + 1:
            j += 1
        out.append(str(ns[i]) if i == j else f"{ns[i]}–{ns[j]}")
        i = j + 1
    return ", ".join(out)


def _near(pt, line: dict, tol: float = 0.0015) -> bool:
    """Point within ~`tol` degrees of latitude (≈ 150 m) of a (multi)line."""
    k = 0.643  # cos(50°): a degree of longitude is shorter
    x, y = pt[0] * k, pt[1]
    parts = line["coordinates"] if line["type"] == "MultiLineString" else [line["coordinates"]]
    for seg in parts:
        for (x1, y1), (x2, y2) in zip(seg, seg[1:]):
            x1, x2 = x1 * k, x2 * k
            dx, dy = x2 - x1, y2 - y1
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy or 1)))
            if (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2 <= tol * tol:
                return True
    return False


def _in_part(a: dict, part: str) -> bool:
    adr = fold(a["adresa"])
    return adr.startswith(part + " ") or f", {part}," in adr


def _mentions(a: dict, ctx: set[str]) -> bool:
    adr = fold(a["adresa"])
    return fold(_street_of(a["adresa"])) in ctx or any(f", {c}," in adr for c in ctx)


def geocode_address(cache: Cache, p: dict, names: Names, ctx: set[str],
                    ku_hint: str | None) -> tuple[dict | None, str]:
    """(GeoJSON point/multipoint, label) of a parsed address; geometry None if nothing matched.

    `ctx` holds the (folded) streets and town parts the whole resolution mentions; it decides
    between buildings that share a bare čp. inside MO V (Dražkovice 153 vs Široká 153)."""
    kod = names.kod.get(p["street"]) if p["street"] else None
    hits = []
    for n, co in p["numbers"]:
        cands = addresses(cache, "cp", n)
        if kod:
            sel = [a for a in cands if a["ulice"] == kod and (co is None or a["co"] == co)]
            if not sel and co is None and not p["explicit_cp"]:
                sel = [a for a in addresses(cache, "co", n) if a["ulice"] == kod]
            if not sel and co is None:
                # the minutes name a corner building after the other street ("Wolkerova čp. 2116"
                # is Teplého 2116): accept that čp. if it stands right by the named street
                line, poly = street_geometry(cache, kod), momc_polygon(cache)
                sel = [a for a in cands if _inside(a["point"], poly) and line and _near(a["point"], line)]
        elif p["part"]:
            pf = fold(p["part"])
            sel = [a for a in cands if _in_part(a, pf)]
        else:
            poly = momc_polygon(cache)
            sel = [a for a in cands if _inside(a["point"], poly)]
            if len(sel) > 1:
                sel = [a for a in sel if _mentions(a, ctx)] or sel
            if len(sel) > 1 and ku_hint:
                # town parts share their k. ú.'s name (Dražkovice, Nové Jesenčany); k. ú.
                # Pardubice is everything else
                if ku_hint == "pardubice":
                    other = [fold(v) for k, v in KU_NAME.items() if k != ku_hint]
                    sel = [a for a in sel if not any(_in_part(a, o) for o in other)]
                else:
                    sel = [a for a in sel if _in_part(a, fold(KU_NAME[ku_hint]))]
        a = _one_place(sel)
        if a:
            hits.append(a)
    hits = list({a["kod"]: a for a in hits}.values())
    if not hits:
        return None, ""
    streets_ = {_street_of(a["adresa"]) for a in hits}
    if len(hits) == 1:
        label = hits[0]["adresa"].split(",")[0]
    elif len(streets_) == 1:
        label = f"{streets_.pop()} {_runs([a['cp'] for a in hits])}"
    else:
        label = "; ".join(a["adresa"].split(",")[0] for a in hits)
    pts = [a["point"] for a in hits]
    geom = {"type": "Point", "coordinates": pts[0]} if len(pts) == 1 else {"type": "MultiPoint", "coordinates": pts}
    return geom, label


def _parcel_label(druh: int, kmen: int, pod: int | None, ku: str) -> str:
    num = f"{kmen}/{pod}" if pod else str(kmen)
    return f"{'st. p. č.' if druh == STAVEBNI else 'p. p. č.'} {num}, k. ú. {KU_NAME[ku]}"


# --- build -------------------------------------------------------------------------------

def resolutions():
    """(uid, enrich record) of every resolution; uid as in build.py: slug of the number."""
    for f in sorted((DATA / "extracted").glob("*.enrich.json")):
        for r in json.loads(f.read_text())["result"]["resolutions"]:
            yield slug(r["number"]), r


def _features(cache: Cache, names: Names, r: dict, parsed: dict, stats: dict) -> list[dict]:
    """Geometry of one record's `places` and `parcels` (parcels already parsed and fetched)."""
    feats = []

    def add(kind, label, src, geom):
        if not in_bbox(geom):
            stats["outside"][src] += 1
            return
        feats.append({"kind": kind, "label": label, "source_text": src, "geometry": geom})
        stats["kinds"][kind] += 1

    for t in r.get("parcels", []):
        p = parsed[t]
        if not p:
            stats["unparsed"]["parcel: " + t] += 1
            continue
        stats["inferred_ku"] += p["ku_inferred"]
        ok = False
        for kmen, pod in p["numbers"]:
            for druh in [p["druh"]] if p["druh"] else [POZEMKOVA, STAVEBNI]:
                g = cache[_parcel_key(KU[p["ku"]], druh, kmen, pod)]
                if g:
                    add("parcel", _parcel_label(druh, kmen, pod, p["ku"]), t, g)
                    ok = True
                    break
        stats["strings"]["parcel" if ok else "parcel (miss)"] += 1
        if not ok:
            stats["unmatched"]["parcel: " + t] += 1

    ku, ctx = _resolution_ku(r), context(r, names)
    for t in r.get("places", []):
        p = parse_place(t, names)
        if not p:
            stats["general"][t] += 1
            continue
        if p["kind"] == "street":
            g, label = street_geometry(cache, names.kod[p["street"]]), p["street"]
        else:
            g, label = geocode_address(cache, p, names, ctx, ku)
        if g:
            add(p["kind"], label, t, g)
            stats["strings"][p["kind"]] += 1
        else:
            stats["strings"][p["kind"] + " (miss)"] += 1
            stats["unmatched"][f"{p['kind']}: {t}"] += 1
    seen, uniq = set(), []
    for f in feats:
        if (f["kind"], f["label"]) not in seen:
            seen.add((f["kind"], f["label"]))
            uniq.append(f)
    return uniq


def _stats() -> dict:
    return {"kinds": Counter(), "strings": Counter(), "general": Counter(), "unparsed": Counter(),
            "unmatched": Counter(), "outside": Counter(), "inferred_ku": 0}


def locate(places: list[str], parcels: list[str] = (), offline: bool = False) -> list[dict]:
    """Geometry for a handful of place/parcel strings outside the resolutions (e.g. a notice
    on the úřední deska). Same rules and cache as `build`; general places are skipped."""
    cache = Cache(offline)
    try:
        names = Names(streets(cache), parts(cache))
        r = {"places": list(places), "parcels": list(parcels)}
        ku = _resolution_ku(r)
        parsed = {t: parse_parcel(t, ku or "pardubice") for t in r["parcels"]}
        fetch_parcels(cache, {(KU[p["ku"]], d, k, pod) for p in parsed.values() if p
                              for d in ([p["druh"]] if p["druh"] else [POZEMKOVA, STAVEBNI])
                              for k, pod in p["numbers"]})
        return _features(cache, names, r, parsed, _stats())
    finally:
        cache.save()


def build(offline: bool = False) -> dict:
    cache = Cache(offline)
    stats = _stats()
    try:
        names = Names(streets(cache), parts(cache))
        rs = list(resolutions())
        parsed_parcels = {}
        for uid, r in rs:
            ku = _resolution_ku(r)
            for t in r.get("parcels", []):
                parsed_parcels[(uid, t)] = parse_parcel(t, ku or "pardubice")
        wanted = {(KU[p["ku"]], d, k, pod) for p in parsed_parcels.values() if p
                  for d in ([p["druh"]] if p["druh"] else [POZEMKOVA, STAVEBNI]) for k, pod in p["numbers"]}
        fetch_parcels(cache, wanted)

        out = {}
        for uid, r in rs:
            uniq = _features(cache, names, r, {t: parsed_parcels[(uid, t)] for t in r.get("parcels", [])}, stats)
            if uniq:
                out[uid] = uniq
    finally:
        cache.save()
    body = ",\n".join(f"{json.dumps(uid)}: {json.dumps(fs, ensure_ascii=False, separators=(',', ':'))}"
                      for uid, fs in sorted(out.items()))
    _write(OUT_PATH, "{\n" + body + "\n}\n")
    stats["total"] = len(rs)
    stats["with_input"] = sum(1 for _, r in rs if r.get("places") or r.get("parcels"))
    stats["with_geometry"] = len(out)
    stats["by_kind_resolutions"] = Counter(k for fs in out.values() for k in {f["kind"] for f in fs})
    return stats


def report(st: dict) -> str:
    lines = [(f"resolutions: {st['total']}, with places/parcels: {st['with_input']}, "
              f"with ≥1 geometry: {st['with_geometry']}"),
             "features: " + ", ".join(f"{k} {v}" for k, v in st["kinds"].most_common()),
             "resolutions per kind: " + ", ".join(f"{k} {v}" for k, v in st["by_kind_resolutions"].most_common()),
             "strings: " + ", ".join(f"{k} {v}" for k, v in sorted(st["strings"].items())),
             f"parcels with k. ú. inferred: {st['inferred_ku']}"]
    for k, title in (("general", "general places (skipped)"), ("unparsed", "unparsed parcels"),
                     ("unmatched", "parsed but not found"), ("outside", "outside bbox")):
        c = st[k]
        lines.append(f"{title}: {sum(c.values())} ({len(c)} distinct)")
        lines += [f"  {n:3}× {t}" for t, n in c.most_common(15)]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build data/usneseni/geo.json from ČÚZK RÚIAN")
    ap.add_argument("--offline", action="store_true", help="use only the cache, never the network")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        print(report(build(a.offline)))
    except LookupError as e:
        sys.exit(f"not in cache: {e}")


if __name__ == "__main__":
    main()
