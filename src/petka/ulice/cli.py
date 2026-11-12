"""Commands of the street pages (`petka ulice-…`)."""

import json

from ..section import Command


def update(a) -> int:
    """Fetch every street of the town from RÚIAN into ruian_cache (only those missing), and the
    obvody's polygons, so each obvod knows all its streets (petka.ulice.streets)."""
    import psycopg
    from psycopg.rows import dict_row

    from .. import db, obvody
    from ..cisteni.ruian import Ruian
    from . import streets
    with psycopg.connect(db.URL, autocommit=True, row_factory=dict_row) as conn:
        r = Ruian(conn)
        r.prefetch(kod for kod, _ in r.streets())
        r.obvody()
        fetched = r.cache.fetched
    streets._cache.clear()
    print(json.dumps({"fetched": fetched, "streets": {o: len(streets.streets(o)) for o in obvody.BY_ID}},
                     ensure_ascii=False))
    return 0


COMMANDS = [
    Command("ulice-update", "fetch the town's streets from RÚIAN (ČÚZK) for the street pages, only what "
            "is missing (idempotent)", update),
]
