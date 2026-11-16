"""Reading parking from the database: the served build of the lots and the export made of it
(kept in memory per build), the free places now, and the history's statistics."""

import datetime as dt

from .. import db
from . import build

_cache: dict = {}
STALE_LOT = dt.timedelta(days=1)     # a lot the source has not had for this long leaves the occupancy


def last_build() -> dict | None:
    """{id, built_at, lots} of the last accepted build; None before the first."""
    with db.pool().connection() as conn:
        return conn.execute("SELECT id, built_at, lots FROM parkovani_builds WHERE accepted "
                            "ORDER BY built_at DESC, id DESC LIMIT 1").fetchone()


def built() -> tuple[int, dt.datetime] | None:
    """(id, built_at) of the last accepted build, without its lots."""
    with db.pool().connection() as conn:
        r = conn.execute("SELECT id, built_at FROM parkovani_builds WHERE accepted "
                         "ORDER BY built_at DESC, id DESC LIMIT 1").fetchone()
    return (r["id"], r["built_at"]) if r else None


def polygons() -> dict:
    """The obvody's polygons from ruian_cache, {} when they are not there (never asked from here)."""
    from ..usneseni.geo import OBEC
    with db.pool().connection() as conn:
        r = conn.execute("SELECT value FROM ruian_cache WHERE key = %s", (f"momc_all:{OBEC}",)).fetchone()
    return (r["value"] if r else None) or {}


def document(build_id: int) -> dict | None:
    """The whole export of the build `build_id` (the last accepted one when it is), made once
    per process and build."""
    if _cache.get("id") != build_id:
        b = last_build()
        if b is None:
            return None
        doc, _ = build.document(b["built_at"], b["lots"], build.Placer(polygons()))
        _cache.update(id=b["id"], doc=doc, obvody={lt["id"]: lt["obvody"] for lt in doc["parking"]["lots"]},
                      names={lt["id"]: lt["name"] for lt in doc["parking"]["lots"]})
    return _cache["doc"]


def lot_obvody() -> dict[str, list[str]]:
    """{lot id: obvody} and the lots' names of the served build ({} before the first)."""
    b = built()
    if b is None:
        return {}
    document(b[0])
    return _cache.get("obvody", {})


def lot_names() -> dict[str, str]:
    b = built()
    if b is None:
        return {}
    document(b[0])
    return _cache.get("names", {})


def state() -> dict | None:
    """{fetched_at, tried_at, error} of the fetcher; None before its first run."""
    with db.pool().connection() as conn:
        return conn.execute("SELECT fetched_at, tried_at, error FROM parkovani_state").fetchone()


def now_rows() -> list[dict]:
    """The free places of each lot the source had within STALE_LOT of the last successful fetch."""
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT id, free, total, changed_at FROM parkovani_now
               WHERE seen_at >= (SELECT fetched_at FROM parkovani_state) - %s ORDER BY id""", (STALE_LOT,)).fetchall()


def history_rows(since: dt.datetime, ids: list[str] | None) -> list[dict]:
    """The history since a moment grouped as the statistics need it: per lot, weekday (1 =
    Monday) and hour in Prague's time, the samples, the sum of occupied and of total places,
    the samples with at most a tenth free; `ids` = only these lots (None = all)."""
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT l.id, extract(isodow FROM h.at AT TIME ZONE 'Europe/Prague')::int AS dow,
                      extract(hour FROM h.at AT TIME ZONE 'Europe/Prague')::int AS hour,
                      count(*) AS n, sum(h.total - h.free) AS occupied, sum(h.total) AS total,
                      count(*) FILTER (WHERE h.free * 10 <= h.total) AS full
               FROM parkovani_history h JOIN parkovani_lots l ON l.n = h.lot
               WHERE h.at >= %s AND h.total > 0 AND (%s::text[] IS NULL OR l.id = ANY(%s::text[]))
               GROUP BY 1, 2, 3""", (since, ids, ids)).fetchall()


def history_span() -> dict:
    """{first, last}: the first and the last slot of the history (None, None when empty)."""
    with db.pool().connection() as conn:
        return conn.execute("SELECT min(at) AS first, max(at) AS last FROM parkovani_history").fetchone() or {}
