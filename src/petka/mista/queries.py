"""Reading Místa from the database: when the served build was made and its places. The places
change once a day, so a process keeps them in memory per build."""

import datetime as dt

from .. import db
from . import export

_cache: dict = {}


def built() -> dt.datetime | None:
    """When the last accepted build was made; None before the first."""
    with db.pool().connection() as conn:
        r = conn.execute("SELECT max(built_at) AS at FROM mista_builds WHERE accepted").fetchone()
    return r["at"] if r else None


def places(at: dt.datetime) -> list[dict]:
    """The places of the build made `at`, as the file has them, sorted by kind and id."""
    if _cache.get("at") != at:
        with db.pool().connection() as conn:
            rows = conn.execute("""SELECT id, kind, name, what, address, lon, lat, hours, obvody, odpad, capacity
                                   FROM mista_places ORDER BY kind, id""").fetchall()
        _cache.update(at=at, places=[export.place(r) for r in rows])
    return _cache["places"]


def counts() -> dict:
    """{kind: places} of the served build, for the data catalog."""
    with db.pool().connection() as conn:
        r = conn.execute("SELECT counts, total, built_at FROM mista_builds WHERE accepted "
                         "ORDER BY built_at DESC, id DESC LIMIT 1").fetchone()
    return dict(r) if r else {}
