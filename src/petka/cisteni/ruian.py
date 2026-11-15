"""RÚIAN for the geocoder (petka.cisteni.geocode.Ruian): the queries of petka.usneseni.geo, with
the answers cached in the database (table ruian_cache) instead of a file in the repository,
because the job runs in the cluster. Misses are cached too; a street or address that changes
in RÚIAN is seen after its row is deleted from the cache.
"""

import json
from collections import defaultdict

from ..usneseni import geo
from ..usneseni.geo import L_MOMC, L_STREET, OBEC, _merge, _query
from .geocode import obvod_id

BATCH = 40      # streets per query when prefetching
# the whole town with its outer parts (Staré Čívice, Opočínek, Lány na Důlku, Hostovice), wider
# than the box usneseni.geo looks for addresses in
TOWN_BBOX = (15.62, 49.99, 15.90, 50.08)


def fetch_obvody() -> dict[str, dict]:
    """{obvod id: GeoJSON polygon, WGS84} of every městský obvod of the town, asked from ČÚZK."""
    out = {}
    for f in _query(L_MOMC, f"obec={OBEC}", "kod,nazev", maxAllowableOffset=0.00002):
        k = obvod_id(f["properties"]["nazev"])
        if k:
            out[k] = _merge([out.get(k), f["geometry"]])
    return out


class Cache(dict):
    """The ruian_cache table as the dict usneseni.geo's helpers expect (put / offline)."""

    def __init__(self, conn):
        super().__init__({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM ruian_cache")})
        self.conn, self.offline, self.fetched = conn, False, 0

    def put(self, key: str, value) -> None:
        self[key] = value
        self.fetched += 1
        self.conn.execute("""INSERT INTO ruian_cache (key, value) VALUES (%s, %s::jsonb)
                             ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, fetched_at = now()""",
                          (key, json.dumps(value, ensure_ascii=False)))

    def save(self) -> None:     # every put is written at once
        pass


class Ruian:
    """What the geocoder asks, over the cache. `conn` should be autocommit: what ČÚZK answered
    is kept even when the job's own transaction fails."""

    def __init__(self, conn):
        self.cache = Cache(conn)

    def streets(self) -> list[list]:
        return geo.streets(self.cache)

    def parts(self) -> list[str]:
        return geo.parts(self.cache)

    def street(self, kod: int) -> dict | None:
        return geo.street_geometry(self.cache, kod)

    def addresses(self, cp: int) -> list[dict]:
        return geo.addresses(self.cache, "cp", cp, TOWN_BBOX)

    def obvody(self) -> dict[str, dict]:
        """{obvod id: polygon} of every městský obvod of the town."""
        return geo._cached(self.cache, f"momc_all:{OBEC}", fetch_obvody)

    def prefetch(self, kods) -> None:
        """Street geometries in batches (one query per street is slow for a whole town)."""
        todo = sorted({k for k in kods if f"street:{k}" not in self.cache})
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            found = defaultdict(list)
            for f in _query(L_STREET, f"kod IN ({','.join(map(str, chunk))})", "kod", maxAllowableOffset=0.00001):
                found[f["properties"]["kod"]].append(f["geometry"])
            for k in chunk:
                self.cache.put(f"street:{k}", _merge(found.get(k, [])))

