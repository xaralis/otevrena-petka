"""Which obvod a place lies in: the town's eight městské obvody from RÚIAN (the polygons the
čištění job caches in ruian_cache as momc_all:<obec>, petka.cisteni.ruian) and a point in them.

OSM's town boundary and RÚIAN's polygons (simplified to ~2 m) don't meet exactly, so a point
outside every polygon but within NEAR m of one belongs to the nearest; farther out it lies in
none (`obvody: []`).
"""

import shapely
from shapely.geometry.base import BaseGeometry

from ..cisteni.geocode import KX, KY, LAT0, LON0, to_m

NEAR = 20       # m


class Obvody:
    """The obvody's polygons in the local plane; `of(lon, lat)` -> ids of the obvod it lies in."""

    def __init__(self, polygons: dict[str, dict]):
        self.polys: dict[str, BaseGeometry] = {k: to_m(g) for k, g in sorted(polygons.items()) if g}
        for p in self.polys.values():
            shapely.prepare(p)

    def of(self, lon: float, lat: float) -> list[str]:
        pt = shapely.Point((lon - LON0) * KX, (lat - LAT0) * KY)
        for k, p in self.polys.items():
            if p.covers(pt):
                return [k]
        if not self.polys:
            return []
        k, d = min(((k, p.distance(pt)) for k, p in self.polys.items()), key=lambda kd: kd[1])
        return [k] if d <= NEAR else []


def place_all(places: list[dict], obvody: Obvody) -> list[dict]:
    """The places with `obvody` set from their position (in place)."""
    for p in places:
        p["obvody"] = obvody.of(*p["at"])
    return places


def town_obvody(conn) -> Obvody:
    """The polygons from ruian_cache; when the cache lacks them, asked from ČÚZK and cached
    (on `conn`, which should be autocommit so that a failed job keeps them)."""
    from ..cisteni.ruian import Ruian
    from ..usneseni.geo import OBEC
    row = conn.execute("SELECT value FROM ruian_cache WHERE key = %s", (f"momc_all:{OBEC}",)).fetchone()
    value = row["value"] if isinstance(row, dict) else row[0] if row else None
    return Obvody(value or Ruian(conn).obvody())
