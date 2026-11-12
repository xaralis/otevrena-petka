"""The streets of an obvod, from RÚIAN: every street of the town whose line lies at least
MIN_SHARE in the obvod (so a street on the border belongs to both), with its geometry.

The answers come from the ruian_cache table the čištění job fills (petka.cisteni.ruian); the
command `petka ulice-update` fetches every street of the town into it, so a street without a
cleaning gets its geometry too. The list is read once per process and kept for TTL seconds.

Matching a search to a street and the streets around one are pure functions, testable without
a database.
"""

import math
import time
from dataclasses import dataclass

from shapely.geometry import shape

from .. import db
from ..cisteni.queries import MIN_SHARE, centre
from ..usneseni.geo import OBEC
from ..usneseni.text import fold, slug

TTL = 3600


@dataclass(frozen=True)
class Street:
    slug: str
    name: str
    kod: int
    geometry: dict
    share: float            # how much of the street lies in the obvod, 0–1


def in_obvod(names: list[list], geoms: dict[int, dict | None], polygon: dict, min_share: float = MIN_SHARE) -> list[Street]:
    """Streets of the town (RÚIAN [kod, name] pairs) with their share inside the obvod's polygon;
    those under `min_share` or without geometry are left out. By name, accent-blind."""
    area = shape(polygon)
    out = {}
    for kod, name in names:
        g = geoms.get(kod)
        if not g:
            continue
        line = shape(g)
        if not line.length or not line.intersects(area):
            continue
        share = line.intersection(area).length / line.length
        if share >= min_share:
            s = slug(name)
            if s not in out or share > out[s].share:     # two streets of one name: the one more inside
                out[s] = Street(s, name, kod, g, round(share, 3))
    return sorted(out.values(), key=lambda s: fold(s.name))


_cache: dict[str, tuple[float, dict[str, Street]]] = {}


def streets(obvod: str) -> dict[str, Street]:
    """{slug: Street} of the obvod (empty until RÚIAN has been fetched into the cache)."""
    hit = _cache.get(obvod)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    with db.pool().connection() as conn:
        rows = {r["key"]: r["value"] for r in conn.execute(
            "SELECT key, value FROM ruian_cache WHERE key = ANY(%s) OR key LIKE 'street:%%'",
            ([f"streets:{OBEC}", f"momc_all:{OBEC}"],))}
    names = rows.get(f"streets:{OBEC}") or []
    polygon = (rows.get(f"momc_all:{OBEC}") or {}).get(obvod)
    geoms = {int(k.split(":", 1)[1]): v for k, v in rows.items() if k.startswith("street:")}
    out = {s.slug: s for s in in_obvod(names, geoms, polygon)} if polygon else {}
    _cache[obvod] = (time.monotonic(), out)
    return out


def find(q: str, names: dict[str, str]) -> list[str]:
    """Slugs of the streets a search means: the exact name (accents and case ignored, "ul."
    dropped), else every name that contains it, those that start with it first."""
    k = slug(q.strip().removeprefix("ul.").removeprefix("ulice "))
    if not k:
        return []
    if k in names:
        return [k]
    starts = [s for s in names if s.startswith(k)]
    return starts + [s for s in names if k in s and s not in starts]


def around(slug_: str, all_: dict[str, Street], n: int = 4) -> list[Street]:
    """The streets that touch this one (crossings, junctions) nearest first, then the nearest
    others, n in all."""
    here = all_.get(slug_)
    if not here:
        return []
    line = shape(here.geometry)
    mid = centre([here.geometry])
    k = math.cos(math.radians(mid[1]))

    def dist(s: Street) -> float:
        c = centre([s.geometry])
        return math.hypot((c[0] - mid[0]) * k, c[1] - mid[1])

    others = [s for s in all_.values() if s.slug != slug_]
    touching = sorted((s for s in others if line.distance(shape(s.geometry)) < 1e-5), key=dist)
    rest = sorted((s for s in others if s not in touching), key=dist)
    return (touching + rest)[:n]
