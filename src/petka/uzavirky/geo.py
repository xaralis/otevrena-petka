"""Where a traffic record lies in the town: its stretch drawn on the street it is on, and its
share in each obvod. Pure functions over the town's streets and obvody (`Town`), testable
without a database; `town` reads them from the ruian_cache table the ulice job fills.

NDIC gives only the stretch's two ends (S-JTSK points on the Global Network, which we don't
have). Both ends lying on one street of the town (one within SNAP m, the other within SNAP_END),
the stretch is that street between them; otherwise a straight line between them, or the point itself.
"""

from dataclasses import dataclass

from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring, unary_union

from ..cisteni.geocode import to_m, to_wgs

SNAP = 25           # m: an end this close to a street lies on it
SNAP_END = 40       # m: the other end may be this far: a stretch ending at a crossing has its point
                    # in the crossing's middle, and RÚIAN's line stops short of it (Wolkerova at Sokolovská: 28 m)
MIN_STRETCH = 5     # m: shorter than this on the street is a point, not a stretch
NEAR_TOWN = 50      # m: a record this close to the town's border is still the town's


@dataclass
class Town:
    obvody: dict[str, BaseGeometry]           # {obvod id: polygon in the local plane (m)}
    streets: list[tuple[str, BaseGeometry]]   # [(name, line in the local plane)]

    def __post_init__(self):
        self.area = unary_union(list(self.obvody.values())).buffer(NEAR_TOWN) if self.obvody else None


def _lines(g) -> list:
    """A street's line as continuous parts: RÚIAN splits it at every crossing, so its pieces are
    merged first (a stretch from one crossing to the next is one line)."""
    if isinstance(g, MultiLineString):
        g = linemerge(g)
    if isinstance(g, LineString):
        return [g]
    if isinstance(g, MultiLineString):
        return list(g.geoms)
    return []


def place(points: list[tuple[float, float]], town: Town) -> tuple[dict | None, str, str | None]:
    """(GeoJSON in WGS84, method, street name) of a record's points (lon, lat): street | straight
    | point; (None, "none", None) without points."""
    if not points:
        return None, "none", None
    pts = [to_m({"type": "Point", "coordinates": p}) for p in points]
    if len(pts) == 1:
        return {"type": "Point", "coordinates": list(points[0])}, "point", None
    a, b = pts[0], pts[-1]
    best = None
    for name, geom in town.streets:
        for line in _lines(geom):
            da, db = line.distance(a), line.distance(b)
            if max(da, db) <= SNAP_END and min(da, db) <= SNAP and (best is None or da + db < best[0]):
                best = (da + db, name, line)
    if best:
        _, name, line = best
        s, e = sorted((line.project(a), line.project(b)))
        if e - s >= MIN_STRETCH:
            return to_wgs(substring(line, s, e)), "street", name
    if a.distance(b) < MIN_STRETCH:
        return {"type": "Point", "coordinates": list(points[0])}, "point", None
    return {"type": "LineString", "coordinates": [list(p) for p in points]}, "straight", None


def shares(geometry: dict | None, town: Town) -> dict[str, float]:
    """{obvod: share} of a geometry: by length for a stretch, 1 for the obvod a point is in;
    empty outside the town (NEAR_TOWN m around it counts as the nearest obvod)."""
    if not geometry or town.area is None:
        return {}
    g = to_m(geometry)
    if not g.intersects(town.area):
        return {}
    if g.length > 0:
        parts = {k: g.intersection(p).length / g.length for k, p in town.obvody.items()}
        out = {k: round(v, 2) for k, v in parts.items() if v >= 0.01}
        if out:
            return out
    near = min(town.obvody.items(), key=lambda kv: kv[1].distance(g))
    return {near[0]: 1.0}


def town(conn) -> Town:
    """The town's obvody and streets from the RÚIAN cache (filled by `petka ulice-update`)."""
    from ..usneseni.geo import OBEC
    rows = {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM ruian_cache WHERE key = ANY(%s) OR key LIKE 'street:%%'",
        ([f"streets:{OBEC}", f"momc_all:{OBEC}"],))}
    names = {int(k): n for k, n in (rows.get(f"streets:{OBEC}") or [])}
    obvody = {k: to_m(v) for k, v in (rows.get(f"momc_all:{OBEC}") or {}).items() if v}
    streets = [(names.get(int(k.split(":", 1)[1]), ""), to_m(v)) for k, v in rows.items()
               if k.startswith("street:") and v]
    return Town(obvody, streets)

