"""Reading the harmonogram for an obvod: its cleanings (one item per place and date), the places
as GeoJSON, the streets and the state of the data. Shaping (streets, slugs, the next cleaning,
the nearest streets) is pure and testable without a database.

A place belongs to an obvod when at least MIN_SHARE of it lies there (geocode.MIN_SHARE), so a
street on the border is listed in both obvody.
"""

import datetime as dt
import json
import math
import re
from collections import defaultdict

from .. import db
from ..usneseni.text import slug
from . import places

MIN_SHARE = 0.05


def year_start(today: dt.date) -> dt.date:
    return dt.date(today.year, 1, 1)


def items(obvod: str, since: dt.date, slugs: list[str] | None = None) -> list[dict]:
    """The obvod's cleanings from `since`, by date and time; with `slugs` only those streets."""
    with db.pool().connection() as conn:
        rows = conn.execute(
            """SELECT p.key, p.texts, p.main_street, p.streets, p.side, p.status, p.method,
                      p.geometry IS NOT NULL AS located, d.date, d.time, d.before
               FROM cleaning_places p JOIN cleaning_dates d ON d.place_key = p.key
               WHERE (p.obvody->>%s)::float >= %s AND d.date >= %s
               ORDER BY d.date, d.time NULLS LAST, p.main_street NULLS LAST, p.key""",
            (obvod, MIN_SHARE, since)).fetchall()
    out = [shape(r) for r in rows]
    return [i for i in out if i["slug"] in slugs] if slugs is not None else out


def shape(r: dict) -> dict:
    """A row of `items` with what pages and the API need: the street it is listed under, its
    slug and the short wording."""
    text = r["texts"][0]
    street = r["main_street"]
    return {**r, "text": text, "street": street or text, "slug": slug(street) if street else None,
            "short": places.short(text, street) if street else ""}


def geometries(obvod: str) -> dict[str, dict]:
    """{place key: GeoJSON geometry} of the obvod's located places."""
    with db.pool().connection() as conn:
        return {r["key"]: r["geometry"] for r in conn.execute(
            """SELECT key, geometry FROM cleaning_places
               WHERE (obvody->>%s)::float >= %s AND geometry IS NOT NULL""", (obvod, MIN_SHARE))}


def checked() -> dt.datetime | None:
    """When the sheet was last downloaded successfully ("Stav k")."""
    with db.pool().connection() as conn:
        r = conn.execute("SELECT max(checked_at) AS t FROM cleaning_sources").fetchone()
    return r["t"] if r else None


# --- shaping --------------------------------------------------------------------------------

def streets(its: list[dict]) -> dict[str, str]:
    """{slug: name} of the streets the items are listed under, by name (accent-blind)."""
    out = {i["slug"]: i["street"] for i in its if i["slug"]}
    return dict(sorted(out.items(), key=lambda kv: places.fold(kv[1])))


def find(q: str, names: dict[str, str]) -> list[str]:
    """Slugs of the streets a search means: the exact name (accents and case ignored), else
    every name that contains it."""
    k = slug(q)
    if not k:
        return []
    if k in names:
        return [k]
    return [s for s in names if k in s]


def next_date(its: list[dict], today: dt.date) -> dt.date | None:
    return min((i["date"] for i in its if i["date"] >= today), default=None)


def map_anchors(its: list[dict], geoms: dict[str, dict], today: dt.date) -> list[dict]:
    """One anchor per stretch on the overview map (where its tooltip hangs, focusable). Places
    drawn as the same line (the left and the right side of a street) are one stretch with all
    their `keys`. The street, the stretch's short wording, its dates still to come this year
    with their sides like on the front page and its street's page. A stretch with nothing left
    this year isn't on the overview (its street page keeps the history). The soonest first, so
    the keyboard meets them in that order."""
    from ..ulice.queries import cleaning_when, point_on
    by: dict[str, list[dict]] = {}
    for i in its:
        if i["key"] in geoms:
            by.setdefault(json.dumps(geoms[i["key"]], sort_keys=True), []).append(i)
    out = []
    for xs in by.values():
        ahead = [x for x in xs if x["date"] >= today]
        if not ahead:
            continue
        i = ahead[0]
        when = cleaning_when(ahead)
        # the side goes to the dates line
        what = re.sub(r",?\s*(obě strany|pravá strana|levá strana)$", "", i["short"]) if i["side"] else i["short"]
        what = what if i["slug"] and what else "Blokové čištění"
        lng, lat = point_on(geoms[i["key"]])
        out.append({"keys": list(dict.fromkeys(x["key"] for x in xs)), "street": i["street"], "what": what,
                    "when": when, "lng": lng, "lat": lat, "area": is_area(geoms[i["key"]]),
                    "href":f"/verejny-prostor/blokove-cisteni/ulice/{i['slug']}" if i["slug"] else None,
                    "label": f"Blokové čištění: {i['street']}, " + (f"{what}, " if what != "Blokové čištění" else "") + when,
                    "next": min(x["date"] for x in ahead)})
    out.sort(key=lambda a: (a["next"], places.fold(a["street"])))
    for a in out:
        del a["next"]
    return out


ON_STREET = 25         # metres: a stretch this close to the street's line lies on it


def on_street(stretch: dict, street: dict, tol: float = ON_STREET) -> bool:
    """Whether a cleaned stretch (a line) lies on the street's RÚIAN line: at most a tenth of it
    further than `tol` metres away. The harmonogram files places under a street that can lie
    elsewhere (a block whose houses have the street's addresses)."""
    from shapely.affinity import scale
    from shapely.geometry import shape
    if stretch["type"] not in ("LineString", "MultiLineString"):
        return False
    a, b = shape(stretch), shape(street)
    k = math.cos(math.radians(b.centroid.y))
    a, b = (scale(g, 111_320 * k, 110_540, origin=(0, 0)) for g in (a, b))   # roughly metres
    return a.length > 0 and a.difference(b.buffer(tol)).length <= 0.1 * a.length


def is_area(g: dict | None) -> bool:
    """A parkoviště or vnitroblok: cleaned whole, drawn as a polygon (its shape is an estimate).
    The maps show it as a marker at a point inside and its outline only while pointed at."""
    return bool(g) and g["type"] in ("Polygon", "MultiPolygon")


def _coords(g: dict):
    c = g["coordinates"]
    depth = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}[g["type"]]
    stack = [(c, depth)]
    while stack:
        c, d = stack.pop()
        if d == 0:
            yield c
        else:
            stack += [(x, d - 1) for x in c]


def centre(gs: list[dict]) -> tuple[float, float] | None:
    """Mean of all vertices (a street's rough middle); None without geometry."""
    pts = [p for g in gs for p in _coords(g)]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def nearby(slug_: str, its: list[dict], geoms: dict[str, dict], today: dt.date, n: int = 5) -> list[dict]:
    """The n streets whose middle is nearest to this street's, each with its next cleaning."""
    by = defaultdict(list)
    for i in its:
        if i["slug"]:
            by[i["slug"]].append(i)
    mid = {s: centre([geoms[i["key"]] for i in xs if i["key"] in geoms]) for s, xs in by.items()}
    here = mid.get(slug_)
    if not here:
        return []
    k = math.cos(math.radians(here[1]))

    def dist(p):
        return math.hypot((p[0] - here[0]) * k, p[1] - here[1])

    near = sorted((s for s, p in mid.items() if p and s != slug_), key=lambda s: dist(mid[s]))[:n]
    return [{"slug": s, "street": by[s][0]["street"], "next": next_date(by[s], today)} for s in near]
