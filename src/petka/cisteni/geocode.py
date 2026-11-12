"""A Místo of the harmonogram as geometry, from RÚIAN streets and address points.

What a place's text says and what we draw (`method`, with `status` auto unless said):

- "Wolkerova", "Wolkerova v celé délce", "… celá": the whole street line (`whole`).
- "X od ul. A k/po ul. B": X cut between the points where A and B come closest to it, along
  X's own network (shortest path, gaps in RÚIAN lines bridged), `segment`. An endpoint can be
  a čp. ("k č. p. 1334"). A cross street is found by name in its Czech case forms; a fuzzy
  match (word stems) only for endpoints, and only when that street comes close to X.
- "X od ul. A" without an end: the whole street, `approx`.
- "parkoviště před č. p. 2116–2118": the hull of those buildings' address points, buffered,
  `hull` (`partial` when some čp. weren't found; a spread over ~700 m means a wrong building
  and is rejected).
- "vnitroblok mezi ul. A, B, C": the city block the named streets close (a hole in the union
  of their buffered lines touching all of them), `block`, `approx`.
- anything else: no geometry (`manual`); data/cisteni/overrides.geojson can draw it by hand.

Which obvod a place is in comes from its geometry (share of its length or area inside each
obvod's polygon), else from its street(s). It is never decided up front: "the address that lies
in MO V" would pick the obvod by itself, so an address is looked up on the named street, near
it, or in the named part of the town.

Geometry is computed in a local metric plane (equirectangular around Pardubice, good to well
under 1 % here) and returned as GeoJSON in WGS84.
"""

import heapq
import math
import re
from collections import defaultdict
from typing import Protocol

import numpy as np
import shapely
from shapely import ops
from shapely.geometry import LineString, MultiPoint, Point, Polygon, mapping, shape

from . import places
from .places import fold, key

# local plane: metres east/north of this point
LAT0, LON0 = 50.03, 15.77
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574

SNAP_MAX = 130      # m: a cross street farther than this from the main street is no endpoint
SNAP = 45           # m: a fuzzy-matched cross street must come this close
ADDR_NEAR = 160     # m: a čp. must lie this close to the street the text names
HULL_BUF = 25       # m: buffer around the hull of address points
HULL_MAX = 700      # m: half the perimeter of the points' box; more = a wrong building
JOIN_END = 15       # m: loose ends of a street's parts closer than this are joined
JOIN_GAP = 250      # m: separate parts of a street are bridged up to this
OBVOD_TOL = 15      # m: an obvod's polygon is grown by this (streets run along borders)
MIN_SHARE = 0.05    # an obvod with less than this share of a place doesn't have it
MAX_RANGE = 12      # "2449-52" is four houses; "153-174" is two ends of a stretch

GENERIC = {"namesti": "nam.", "trida": "tr.", "nabrezi": "nabr."}
ALIASES = {"csa": "Čs. armády", "ceskoslovenske armady": "Čs. armády", "cs. armady": "Čs. armády",
           "resslova": "Josefa Ressla", "dukelske namesti": "náměstí Dukelských hrdinů"}
NUM_RE = re.compile(r"(?<![\w/])(\d{1,4})(?:/\d+[a-z]?)?(?:\s*-\s*(?:c\. p\. ?)?(\d{1,4}))?(?![\w/])")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}


class Ruian(Protocol):
    """What the geocoder asks RÚIAN (petka.cisteni.ruian; tests pass a fake)."""
    def streets(self) -> list[list]: ...                 # [[kod, name], …] of the town
    def street(self, kod: int) -> dict | None: ...       # GeoJSON (multi)line, WGS84
    def addresses(self, cp: int) -> list[dict]: ...      # {kod, adresa, cp, co, ulice, point}
    def parts(self) -> list[str]: ...                    # names of the town's parts
    def obvody(self) -> dict[str, dict]: ...             # {obvod id: GeoJSON polygon}


def to_m(g: dict):
    """GeoJSON (WGS84) -> shapely geometry in the local plane."""
    return shapely.transform(shape(g), lambda c: (c[:, :2] - (LON0, LAT0)) * (KX, KY))


def to_wgs(g) -> dict:
    return mapping(shapely.transform(g, lambda c: np.round(c / (KX, KY) + (LON0, LAT0), 6)))


def obvod_id(name: str) -> str | None:
    """'Pardubice V' (RÚIAN's name of a městský obvod) -> 'mo5', the portal's obvod id."""
    m = re.search(r"\b([IVX]+)$", name.strip())
    return f"mo{ROMAN[m[1]]}" if m and m[1] in ROMAN else None


def numbers(s: str) -> list[int]:
    """'1895-1893' -> 1893…1895, '2449-52' -> 2449…2452, '2270-2214' -> the two ends."""
    out = []
    for a, b in NUM_RE.findall(s):
        a = int(a)
        if b:
            b = int(b)
            if len(str(b)) < len(str(a)) and b < a:
                b = int(str(a)[:len(str(a)) - len(str(b))] + str(b))
            lo, hi = min(a, b), max(a, b)
            out += list(range(lo, hi + 1)) if hi - lo < MAX_RANGE else [a, b]
        else:
            out.append(a)
    return list(dict.fromkeys(out))


# --- street names ---------------------------------------------------------------------------

def _cases(k: str) -> set[str]:
    """Czech case forms of a folded street name, crude but enough for the harmonogram:
    'dasicka' -> 'dasicke', 'dasickou'; 'sukova trida' -> 'sukovy tridy'."""
    out, w = set(), k.split()
    last = w[-1]
    for a, bs in (("ska", ["ske", "skou"]), ("cka", ["cke", "ckou"]), ("ova", ["ovy", "ove", "ovou"]),
                  ("ina", ["iny", "ine"]), ("na", ["ne", "nou"]), ("trida", ["tridy", "tride", "tridou"]),
                  ("namesti", []), ("a", ["y", "e", "ou"])):
        if last.endswith(a):
            out |= {" ".join(w[:-1] + [last[:-len(a)] + b]) for b in bs}
            break
    if len(w) == 2 and w[0].endswith("ova") and w[1].startswith("tri"):
        out |= {w[0][:-3] + "ovy tridy", w[0][:-3] + "ovy tride"}
    return out


class Streets:
    """Street names of the town inside a place's key: exact, abbreviated ('nam.', 'a. krause'),
    by the last word ('palacha'), in case forms; a variant shared by two streets is dropped."""

    def __init__(self, rows: list[list]):
        self.kod = {name: kod for kod, name in rows}
        exact = {key(n): n for n in self.kod}
        variants = defaultdict(set)
        for k, n in exact.items():
            ws = k.split()
            for g, ab in GENERIC.items():
                if g in ws:
                    variants[" ".join(ab if x == g else x for x in ws)].add(n)
            if len(ws) >= 2 and all(x.isalpha() and len(x) > 2 for x in ws[:-1]) and not set(ws) & set(GENERIC):
                variants[" ".join(x[0] + "." for x in ws[:-1]) + " " + ws[-1]].add(n)
                variants[ws[-1]].add(n)
            for v in _cases(k):
                variants[v].add(n)
        index = {v: next(iter(ns)) for v, ns in variants.items() if len(ns) == 1 and v not in exact}
        index.update(exact)
        index.update({k.replace("-", " "): n for k, n in exact.items() if "-" in k})
        index.update({a: n for a, n in ALIASES.items() if n in self.kod})
        self.index = index
        alts = "|".join(re.escape(k) for k in sorted(index, key=len, reverse=True))
        self.rx = re.compile(rf"(?<![\w.])(?:{alts})(?!\w)")

    def find(self, s: str) -> list[tuple[str, int, int]]:
        """[(name, start, end)] of the streets in a key()-ed string."""
        return [(self.index[m[0]], m.start(), m.end()) for m in self.rx.finditer(s)]

    def fuzzy(self, s: str) -> str | None:
        """The longest name whose every word's stem (all but the last two letters, at least
        three) begins consecutive words of `s`: other case forms and typos at word ends."""
        ws = re.sub(r"\bul(ice|ici)?\.?\s", " ", s).split()
        best = None
        for v, n in self.index.items():
            vw = v.split()
            stems = [w if w.endswith(".") or len(w) <= 3 else w[:max(3, len(w) - 2)] for w in vw]
            for i in range(len(ws) - len(vw) + 1):
                if all(ws[i + j].startswith(st) for j, st in enumerate(stems)):
                    if best is None or len(v) > len(best[1]):
                        best = (n, v)
        return best[0] if best else None


# --- cutting a street between two points ----------------------------------------------------

def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def reach(line: LineString, p: Point, q: Point | None) -> LineString:
    """`line` with the end nearest to p carried on to q, the point on the cross street: RÚIAN's
    reference lines stop a few metres short of a junction, so a cut stretch would end in the
    middle of nowhere on the map. Only for short gaps (≤ SNAP)."""
    if q is None or not 0.5 < p.distance(q) <= SNAP:
        return line
    cs = list(line.coords)
    if Point(cs[0]).distance(p) <= Point(cs[-1]).distance(p):
        return LineString([q.coords[0]] + cs)
    return LineString(cs + [q.coords[0]])


def cut(line, p1: Point, p2: Point) -> LineString | None:
    """The shortest way along `line`'s own network between the points nearest to p1 and p2.
    Loose ends closer than JOIN_END are joined, separate parts bridged up to JOIN_GAP (RÚIAN
    draws a street in pieces)."""
    graph: dict = defaultdict(dict)
    segs = []

    def edge(a, b):
        graph[a][b] = graph[b][a] = _dist(a, b)

    for part in getattr(line, "geoms", [line]):
        cs = [tuple(c[:2]) for c in part.coords]
        for a, b in zip(cs, cs[1:]):
            if a != b:
                segs.append((a, b))
                edge(a, b)
    if not segs:
        return None
    ends = [n for n in graph if len(graph[n]) == 1]
    for i, a in enumerate(ends):
        for b in ends[i + 1:]:
            if _dist(a, b) < JOIN_END:
                edge(a, b)
    comps = _components(graph)
    while len(comps) > 1:
        d, a, b = min((_dist(a, b), a, b) for c in comps[1:] for b in c for a in comps[0])
        if d > JOIN_GAP:
            break
        edge(a, b)
        comps = _components(graph)

    def insert(p: Point, tag: int):
        a, b = min(segs, key=lambda s: LineString(s).distance(p))
        s = LineString((a, b))
        q = s.interpolate(s.project(p))
        node = (q.x, q.y, tag)
        graph[a][node] = graph[node][a] = _dist(a, node)
        graph[b][node] = graph[node][b] = _dist(b, node)
        return node

    path = _shortest(graph, insert(p1, 1), insert(p2, 2))
    coords = [n[:2] for n in path] if path else []
    return LineString(coords) if len(coords) > 1 else None


def _components(graph: dict) -> list[set]:
    seen, out = set(), []
    for n in graph:
        if n in seen:
            continue
        comp, stack = set(), [n]
        while stack:
            x = stack.pop()
            if x not in comp:
                comp.add(x)
                stack += [y for y in graph[x] if y not in comp]
        seen |= comp
        out.append(comp)
    return out


def _shortest(graph: dict, a, b) -> list | None:
    """Dijkstra."""
    dist, prev, todo = {a: 0.0}, {}, [(0.0, a)]
    while todo:
        d, x = heapq.heappop(todo)
        if x == b:
            path = [b]
            while path[-1] != a:
                path.append(prev[path[-1]])
            return path[::-1]
        if d > dist.get(x, math.inf):
            continue
        for y, w in graph[x].items():
            if d + w < dist.get(y, math.inf):
                dist[y], prev[y] = d + w, x
                heapq.heappush(todo, (d + w, y))
    return None


# --- the geocoder ---------------------------------------------------------------------------

class Geo:
    def __init__(self, ruian: Ruian):
        self.r = ruian
        self.names = Streets(ruian.streets())
        self.obvody = {k: to_m(g).buffer(OBVOD_TOL) for k, g in ruian.obvody().items()}
        self.parts = sorted({fold(x) for x in ruian.parts()} - {"pardubice"}, key=len, reverse=True)
        self._line: dict = {}

    def line(self, name: str):
        if name not in self._line:
            g = self.r.street(self.names.kod[name])
            self._line[name] = to_m(g) if g else None
        return self._line[name]

    def shares(self, g) -> dict[str, float]:
        """{obvod id: share of the geometry inside it} for obvody with at least MIN_SHARE."""
        out = {}
        gg = g if (g.length or g.area) else g.buffer(1)
        for k, poly in self.obvody.items():
            inter = gg.intersection(poly)
            share = inter.area / gg.area if gg.area else inter.length / gg.length
            if share >= MIN_SHARE:
                out[k] = round(min(share, 1.0), 2)
        return out

    def addr_points(self, nums: list[int], near=None, street: str | None = None,
                    part: str | None = None) -> tuple[list, list]:
        """Points of čp. `nums`: on the named street, else near it, else in the named part of
        the town; (points, numbers not found). Never "whichever lies in the obvod"."""
        pts, miss = [], []
        kod = self.names.kod.get(street) if street else None
        for n in nums:
            cands = self.r.addresses(n)
            sel = [a for a in cands if kod and a["ulice"] == kod]
            if not sel and near is not None:
                sel = [a for a in cands if to_m({"type": "Point", "coordinates": a["point"]}).distance(near) < ADDR_NEAR]
            if not sel and part:
                sel = [a for a in cands if f", {part}," in fold(a["adresa"]) or fold(a["adresa"]).startswith(part + " ")]
            if not sel or len({(round(a["point"][0], 3), round(a["point"][1], 3)) for a in sel}) > 2:
                miss.append(n)
                continue
            pts += [to_m({"type": "Point", "coordinates": a["point"]}) for a in sel]
        return pts, miss

    def endpoint(self, text: str, main_line, main: str):
        """(point on the main line, why, point on the cross street or None) for 'ul. Dašická',
        'č. p. 531', 'Sukovy třídy'; (None, why, None) when it isn't one."""
        t = text.strip()
        if "c. p." in t:
            nums = numbers(t)
            pts, _ = self.addr_points(nums[:1], near=main_line, street=main)
            if pts:
                return main_line.interpolate(main_line.project(pts[0])), f"čp {nums[0]}", None
            return None, f"čp {nums[:1]} not found", None
        found = [f[0] for f in self.names.find(t) if f[0] != main]
        if not found:
            fz = self.names.fuzzy(t)
            found = [fz] if fz and fz != main else []
            if found and self.line(found[0]) is not None and main_line.distance(self.line(found[0])) > SNAP:
                return None, f"fuzzy '{found[0]}' too far", None
        if not found:
            return None, f"no street in '{t}'", None
        other = self.line(found[0])
        if other is None:
            return None, f"{found[0]}: no geometry", None
        d = main_line.distance(other)
        if d > SNAP_MAX:
            return None, f"{found[0]} {d:.0f} m away", None
        p, q = ops.nearest_points(main_line, other)
        return p, found[0] + (f" (~{d:.0f} m)" if d > SNAP else ""), q

    def block(self, names: list[str]):
        """The block the named streets enclose, or None when they don't close a ring."""
        ls = [self.line(n) for n in names if self.line(n) is not None]
        if len(ls) < 2:
            return None
        u = ops.unary_union([x.buffer(18) for x in ls])
        holes = [Polygon(ring) for poly in getattr(u, "geoms", [u]) for ring in poly.interiors]
        holes = [h for h in holes if all(h.distance(x) < 30 for x in ls) and h.area < 250_000]
        return min(holes, key=lambda h: h.area).buffer(10) if holes else None

    def place(self, k: str) -> dict:
        """Everything we know about one place key (see the module's doc)."""
        sd, core = places.side(k)
        pat = places.pattern(k)
        found = self.names.find(core)
        main = found[0][0] if found and found[0][1] <= 1 else None
        if not main:
            head = " ".join(core.split()[:4])
            fz = self.names.fuzzy(head)
            if fz and head[:3] == key(fz)[:3]:
                main = fz
        streets = list(dict.fromkeys(f[0] for f in found))
        rec = {"key": k, "pattern": pat, "side": sd, "main_street": main, "streets": streets,
               "method": None, "status": "manual", "note": "", "geometry": None, "obvody": {}}
        main_line = self.line(main) if main else None
        geom = None

        seg = re.match(r"^(?P<m>.+?)\s*-?\s*\bod (?P<a>.+?)\s+(?:k|ke|po|do)\s+(?P<b>.+?)(?:,|\bvc\.|\s-\s|\(|$)", core)
        only_from = re.match(r"^(?P<m>.+?)\s*-?\s*\bod (?P<a>.+?)(?:,|\bvc\.|\s-\s|$)", core)
        tail = core[found[0][2]:] if main and found and found[0][0] == main else core[len(main or ""):]
        bare = main and not re.search(r"\d|parkovist|vnitroblo|mezi|slepa|cast|chodnik|stezk|tocn", tail)

        if main_line is not None and pat == "usek od-k" and seg:
            p1 = p2 = q1 = q2 = None
            why1 = why2 = "no split"
            od = core.find(" od ") + 4 if " od " in core else core.find("od ") + 3
            rest = re.split(r",|\bvc\.|\s-\s|\(", core[od:])[0]
            for sp in re.finditer(r"\s(?:k|ke|po|do)\s", rest):
                p1, why1, q1 = self.endpoint(rest[:sp.start()], main_line, main)
                p2, why2, q2 = self.endpoint(rest[sp.end():], main_line, main)
                if p1 is not None and p2 is not None:
                    break
            if p1 is not None and p2 is not None:
                geom = cut(main_line, p1, p2)
                if geom is not None and geom.length > 5:
                    geom = reach(reach(geom, p1, q1), p2, q2)
                    rec.update(method="segment", status="auto", note=f"{why1} → {why2}")
                else:
                    geom = None
                    rec["note"] = f"cut failed ({why1} → {why2})"
            else:
                rec["note"] = f"endpoint: {why1 if p1 is None else why2}"
        elif re.search(r"\d\. ?cast", k):
            rec["note"] = "numbered part (N. část): extent not in the text"
        elif main_line is not None and (bare or (re.search(r"\bcela\b(?! sire)", tail) and "c. p." not in tail)):
            geom = main_line
            rec.update(method="whole", status="auto")
        elif main_line is not None and pat == "jen od" and only_from and "c. p." not in core:
            geom = main_line
            rec.update(method="whole", status="approx", note="od X, end not given")

        if geom is None and "c. p." in core:
            nums = numbers(core[core.find("c. p."):])
            near = main_line
            if near is None and streets:
                ls = [self.line(x) for x in streets if self.line(x) is not None]
                near = ops.unary_union(ls) if ls else None
            part = next((p for p in self.parts if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", core)), None)
            pts, miss = self.addr_points(nums, near=near, street=main, part=part)
            spread = MultiPoint(pts).minimum_rotated_rectangle.length / 2 if len(pts) > 1 else 0
            if pts and spread >= HULL_MAX:
                rec["note"] = f"čp points {spread:.0f} m apart: wrong building?"
                pts = []
            if pts:
                geom = MultiPoint(pts).convex_hull.buffer(HULL_BUF)
                rec.update(method="hull", status="partial" if miss else "auto",
                           note=f"čp {len(nums) - len(miss)}/{len(nums)}" + (f", missing {miss}" if miss else ""))
            elif not rec["note"]:
                rec["note"] = f"čp not found {nums}"
        if geom is None and pat in ("vnitroblok", "mezi ulicemi") and len(streets) >= 2:
            blk = self.block(streets)
            if blk is not None:
                geom = blk
                rec.update(method="block", status="approx", note="")
        if geom is None and not rec["note"]:
            rec["note"] = "no rule" if main else "no main street"

        # obvody from the geometry, else from the main street, else from every named street
        basis = geom if geom is not None else main_line
        if basis is None and streets:
            ls = [self.line(s) for s in streets if self.line(s) is not None]
            basis = ops.unary_union(ls) if ls else None
        if basis is not None:
            rec["obvody"] = self.shares(basis)
        if geom is not None:
            rec["geometry"] = to_wgs(geom)
            # a whole street through several obvody: the harmonogram may mean only a part
            if rec["method"] == "whole" and rec["status"] == "auto" and max(rec["obvody"].values(), default=1) < 0.8:
                rec.update(status="approx", note="whole street across obvody, extent unsure")
        # a place without its own street at the start ("vnitroblok v ul. Wolkerova") is listed
        # under the one street it names
        if not main and len(streets) == 1:
            rec["main_street"] = streets[0]
        return rec
