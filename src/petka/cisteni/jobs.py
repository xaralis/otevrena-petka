"""`petka cisteni-update`: download the harmonogram of blokové čištění and bring the places and
dates in line with it. Idempotent; once a day is plenty (SmP changes the sheet a few times a
season).

The sheet is one file for the whole town, so the job has one unit; the obvody come from the
places' geometry (cleaning_places.obvody), not from the job. A sheet with the same content as
the last one only gets its check recorded. Otherwise:

- new places are geocoded (petka.cisteni.geocode); a known place keeps its geometry, because
  its key is its text: same text, same place. `--znovu` geocodes every place again (after a
  change of the algorithm). ČÚZK answers are cached in ruian_cache.
- manual geometry from data/cisteni/overrides.geojson wins over the automatic one;
- future dates are replaced by the sheet's, past dates stay (a sheet that drops what already
  happened doesn't erase it);
- a place left without any date is deleted.
"""

import datetime as dt
import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path

from .. import jobs as runner
from ..jobs import Unit
from . import places, source
from .geocode import to_m

log = logging.getLogger(__name__)

OVERRIDES = Path(__file__).resolve().parents[3] / "data" / "cisteni" / "overrides.geojson"


def load_overrides(path: Path = OVERRIDES) -> dict[str, dict]:
    """{place key: feature} of the hand-drawn geometry. The file is a GeoJSON FeatureCollection;
    each feature has `properties.key` (the place's key as /api/v1/cisteni gives it) and may have
    `properties.note`."""
    if not path.exists():
        return {}
    fc = json.loads(path.read_text())
    return {f["properties"]["key"]: f for f in fc.get("features", []) if f.get("geometry")}


def grouped(rows: list[source.Row]) -> dict[str, list[source.Row]]:
    out = defaultdict(list)
    for r in rows:
        out[places.place_key(r.place)].append(r)
    return dict(out)


def store(conn, rows: list[source.Row], geo_factory, today: dt.date, overrides: dict | None = None,
          regeocode: bool = False) -> dict:
    """Bring cleaning_places and cleaning_dates in line with the cleaned rows of a sheet.
    `geo_factory()` gives a petka.cisteni.geocode.Geo; it is only called when something has to
    be geocoded."""
    by_key = grouped(rows)
    overrides = overrides or {}
    known = {r["key"]: r for r in conn.execute("SELECT key, texts FROM cleaning_places")}
    todo = [k for k in by_key if regeocode or k not in known]
    geo = None
    if todo or overrides:
        geo = geo_factory()
        if hasattr(geo.r, "prefetch"):
            names = {f[0] for k in todo for f in geo.names.find(k)}
            geo.r.prefetch(geo.names.kod[n] for n in names)
    for k in todo:
        rec = geo.place(k)
        conn.execute(
            """INSERT INTO cleaning_places (key, texts, pattern, main_street, streets, side, method, status,
                                            geometry, obvody, note, updated_at)
               VALUES (%(key)s, %(texts)s, %(pattern)s, %(main_street)s, %(streets)s, %(side)s, %(method)s,
                       %(status)s, %(geometry)s::jsonb, %(obvody)s::jsonb, %(note)s, now())
               ON CONFLICT (key) DO UPDATE SET pattern = EXCLUDED.pattern, main_street = EXCLUDED.main_street,
                 streets = EXCLUDED.streets, side = EXCLUDED.side, method = EXCLUDED.method,
                 status = EXCLUDED.status, geometry = EXCLUDED.geometry, obvody = EXCLUDED.obvody,
                 note = EXCLUDED.note, updated_at = now()""",
            {**rec, "texts": sorted({r.place for r in by_key[k]}),
             "geometry": json.dumps(rec["geometry"]) if rec["geometry"] else None,
             "obvody": json.dumps(rec["obvody"])})
    for k, rs in by_key.items():        # new wordings of a known place
        if k in known and k not in todo:
            texts = sorted(set(known[k]["texts"]) | {r.place for r in rs})
            if texts != sorted(known[k]["texts"]):
                conn.execute("UPDATE cleaning_places SET texts = %s, updated_at = now() WHERE key = %s", (texts, k))
    overridden = 0
    for k, f in overrides.items():
        if k not in by_key and k not in known:
            continue
        shares = geo.shares(to_m(f["geometry"]))
        overridden += conn.execute(
            """UPDATE cleaning_places SET geometry = %s::jsonb, method = 'override', status = 'manual',
                 obvody = %s::jsonb, note = %s, updated_at = now() WHERE key = %s""",
            (json.dumps(f["geometry"]), json.dumps(shares), f["properties"].get("note") or "drawn by hand", k)).rowcount

    removed = conn.execute("DELETE FROM cleaning_dates WHERE date >= %s", (today,)).rowcount
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO cleaning_dates (place_key, date, time, before, source_row)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (place_key, date) DO NOTHING""",
            [(k, r.date, r.time, r.before, r.row) for k, rs in by_key.items() for r in rs])
    added = conn.execute("SELECT count(*) AS n FROM cleaning_dates WHERE date >= %s", (today,)).fetchone()["n"]
    orphans = conn.execute("""DELETE FROM cleaning_places p WHERE NOT EXISTS
                              (SELECT 1 FROM cleaning_dates d WHERE d.place_key = p.key)""").rowcount
    return {"rows": len(rows), "places": len(by_key), "geocoded": len(todo), "overrides": overridden,
            "future_dates": {"removed": removed, "now": added}, "places_removed": orphans,
            "obvody": coverage(conn)}


def coverage(conn) -> dict:
    """Per obvod: places, dates this year, share of places with geometry."""
    out = {}
    for r in conn.execute(
            """SELECT o.key AS obvod, count(DISTINCT p.key) AS places, count(d.*) AS dates,
                      count(DISTINCT p.key) FILTER (WHERE p.status = 'auto') AS auto,
                      count(DISTINCT p.key) FILTER (WHERE p.geometry IS NOT NULL) AS geometry
               FROM cleaning_places p CROSS JOIN LATERAL jsonb_each(p.obvody) o
               JOIN cleaning_dates d ON d.place_key = p.key
               WHERE (o.value)::float >= 0.05 GROUP BY 1 ORDER BY 1"""):
        out[r["obvod"]] = {"places": r["places"], "dates": r["dates"], "auto": r["auto"],
                           "geometry": r["geometry"], "geometry_share": round(r["geometry"] / r["places"], 2)}
    return out


def _geo_factory():
    """A Geo over RÚIAN with the cache on its own autocommit connection (kept on failure)."""
    import psycopg
    from psycopg.rows import dict_row

    from .. import db
    from .geocode import Geo
    from .ruian import Ruian
    conn = psycopg.connect(db.URL, autocommit=True, row_factory=dict_row)
    return Geo(Ruian(conn))


def update(force: bool = False, regeocode: bool = False, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()

    def run(conn, client) -> dict:
        url, xlsx = source.fetch(client)
        sha = hashlib.sha256(xlsx).hexdigest()
        last = conn.execute("SELECT sha256 FROM cleaning_sources ORDER BY checked_at DESC LIMIT 1").fetchone()
        rows, issues = source.clean(source.parse(xlsx))
        if last and last["sha256"] == sha and not (force or regeocode):
            conn.execute("INSERT INTO cleaning_sources (url, sha256, rows, changed) VALUES (%s, %s, %s, false)",
                         (url, sha, len(rows)))
            return {"url": url, "changed": False, "rows": len(rows)}
        summary = store(conn, rows, _geo_factory, today, load_overrides(), regeocode)
        conn.execute("INSERT INTO cleaning_sources (url, sha256, rows, changed) VALUES (%s, %s, %s, true)",
                     (url, sha, len(rows)))
        return {"url": url, "changed": True, **summary,
                "issues": [f"{kind} (řádek {row}): {detail}" for kind, row, detail in issues]}

    return runner.run("cisteni-update", "čištění", lambda conn, client: [Unit(("pardubice",), "pardubice", run)],
                      logger=log, client={"timeout": source.TIMEOUT, "headers": source.HEADERS,
                                          "follow_redirects": True})
