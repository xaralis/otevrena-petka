"""Reading the harmonogram for an obvod: its cleanings (one item per place and date), the places
as GeoJSON, the streets and the state of the data. Shaping (streets, slugs, the next cleaning,
the nearest streets) is pure and testable without a database.

A place belongs to an obvod when at least MIN_SHARE of it lies there (geocode.MIN_SHARE), so a
street on the border is listed in both obvody.
"""

import datetime as dt
import math
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
