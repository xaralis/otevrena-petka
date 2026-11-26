"""`petka mista-update`: the places of the town from OpenStreetMap, rebuilt once a day.

One Overpass query for the whole town (petka.mista.osm), each place put in its obvod
(petka.mista.where), then the guard: a build with fewer than GUARD of the last accepted
build's places, in total or in a kind that had at least GUARD_MIN, is refused – Overpass
sometimes answers with part of the area – and the last accepted places stay served. An
accepted build replaces mista_places in one transaction. Idempotent: running it twice gives
the same places and a second build row.
"""

import json
import logging
from pathlib import Path

from .. import jobs as runner
from ..jobs import Unit
from . import osm, where

log = logging.getLogger(__name__)

GUARD = 0.7
# A kind smaller than this is not guarded on its own: a couple of places deleted in OSM would
# refuse the build (a partial answer shows in the total and the big kinds anyway).
GUARD_MIN = 10


def problem(new: dict[str, int], last: dict[str, int] | None) -> str | None:
    """Why a build with counts `new` ({kind: places}) must not replace the last accepted one
    (`last`, None before the first), or None."""
    total = sum(new.values())
    if not total:
        return "no places"
    if not last:
        return None
    short = []
    if total < GUARD * sum(last.values()):
        short.append(f"total {total} < {GUARD:.0%} of {sum(last.values())}")
    for kind, n in last.items():
        if n >= GUARD_MIN and new.get(kind, 0) < GUARD * n:
            short.append(f"{kind} {new.get(kind, 0)} < {GUARD:.0%} of {n}")
    return "; ".join(short) or None


class Refused(RuntimeError):
    pass


def store(conn, places: list[dict], force: bool = False) -> dict:
    """Guard and store one build (the places with their obvody). A refused build is recorded,
    committed and raises Refused, so the job fails and alerts."""
    counts = osm.counts(places)
    last = conn.execute("SELECT counts FROM mista_builds WHERE accepted ORDER BY built_at DESC, id DESC LIMIT 1"
                        ).fetchone()
    why = None if force else problem(counts, last["counts"] if last else None)
    if why:
        conn.execute("INSERT INTO mista_builds (counts, total, accepted, reason) VALUES (%s, %s, false, %s)",
                     (json.dumps(counts), sum(counts.values()), why))
        conn.commit()
        raise Refused(f"build refused, the last accepted stays: {why}")
    conn.execute("DELETE FROM mista_places")
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO mista_places (id, kind, name, what, address, lon, lat, hours, obvody, odpad, capacity,
                                       phone, web, email, pruvodce)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(p["id"], p["kind"], p["name"], p["what"], p["address"], p["at"][0], p["at"][1], p["hours"],
              p["obvody"], p.get("odpad"), p.get("capacity"), p.get("phone"), p.get("web"), p.get("email"),
              p.get("pruvodce"))
             for p in places])
    conn.execute("INSERT INTO mista_builds (counts, total, accepted) VALUES (%s, %s, true)",
                 (json.dumps(counts), sum(counts.values())))
    by_obvod: dict[str, int] = {}
    for p in places:
        for o in p["obvody"] or ["mimo"]:
            by_obvod[o] = by_obvod.get(o, 0) + 1
    return {"places": len(places), "kinds": counts, "obvody": dict(sorted(by_obvod.items()))}


def _obvody() -> where.Obvody:
    """The obvody's polygons over their own autocommit connection (what ČÚZK answers is cached
    even when the job fails)."""
    import psycopg
    from psycopg.rows import dict_row

    from .. import db
    with psycopg.connect(db.URL, autocommit=True, row_factory=dict_row) as conn:
        return where.town_obvody(conn)


def _city_yards() -> list[dict]:
    """The town's separační dvory (SmP's list, petka.odpady), to tell them from private centres."""
    from ..odpady import data as od
    return od.yards()["yards"]


def update(path: Path | None = None, force: bool = False) -> dict:
    """Ask Overpass (or read its saved answer at `path`) and store the build. `force` stores it
    even when the guard would refuse it (after a real drop in OSM)."""
    def run(conn, client) -> dict:
        data = json.loads(path.read_text()) if path else osm.fetch(client)
        places = where.place_all(osm.split_yards(osm.places_of(data.get("elements") or []), _city_yards()), _obvody())
        return store(conn, places, force)

    return runner.run("mista-update", "místa", lambda conn, client: [Unit(("pardubice",), "pardubice", run)],
                      logger=log, client={"follow_redirects": True})
