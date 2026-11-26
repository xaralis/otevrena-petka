"""Reading Místa from the database: when the served places last changed and the places. They
change once a day (and once a week their supplements), so a process keeps them in memory per
change."""

import datetime as dt

from .. import db
from . import export

_cache: dict = {}


def built() -> dt.datetime | None:
    """When the served places last changed: the last accepted build, or the last write of the
    supplements (petka.mista.doplnky) after it, so that the weekly supplements are served – and
    the ETag changes – without waiting for the next day's build. None before the first build."""
    with db.pool().connection() as conn:
        r = conn.execute("""SELECT (SELECT max(built_at) FROM mista_builds WHERE accepted) AS at,
                                   (SELECT max(checked_at) FROM mista_doplnky) AS sup""").fetchone()
    if not r or not r["at"]:
        return None
    return max(r["at"], r["sup"]) if r["sup"] else r["at"]


def places(at: dt.datetime) -> list[dict]:
    """The places of the build made `at`, as the file has them, sorted by kind and id."""
    if _cache.get("at") != at:
        with db.pool().connection() as conn:
            # The first supplement of a place by SOURCES' order (mesto, alltheplaces, web).
            rows = conn.execute("""SELECT p.id, p.kind, p.name, p.what, p.address, p.lon, p.lat, p.hours, p.obvody,
                                          p.odpad, p.capacity, p.phone, p.web, p.email,
                                          d.source AS d_source, d.hours AS d_hours, d.phone AS d_phone,
                                          d.web AS d_web, d.url AS d_url
                                   FROM mista_places p
                                   LEFT JOIN LATERAL (SELECT * FROM mista_doplnky x WHERE x.id = p.id
                                                      ORDER BY array_position(ARRAY['mesto','alltheplaces','web'], x.source)
                                                      LIMIT 1) d ON true
                                   ORDER BY p.kind, p.id""").fetchall()
        _cache.update(at=at, places=[export.place(r) for r in rows])
    return _cache["places"]


def counts() -> dict:
    """{kind: places} of the served build, for the data catalog."""
    with db.pool().connection() as conn:
        r = conn.execute("SELECT counts, total, built_at FROM mista_builds WHERE accepted "
                         "ORDER BY built_at DESC, id DESC LIMIT 1").fetchone()
    return dict(r) if r else {}
