"""`petka doprava-update`: the NDIC snapshot of traffic information, kept for the whole town.

Idempotent; the cluster runs it every 10 minutes. The snapshot holds every record valid now
or later in the country; we keep those in the town (petka.uzavirky.geo), each with its share
in the obvody. A known record is updated when its version changes; one that is no longer in
the snapshot is over (gone_at). Without settings (NDIC_URL, NDIC_USER, NDIC_PASSWORD) the job
does nothing: ŘSD assigns them to the subscription.
"""

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path

from .. import jobs as runner
from ..jobs import Unit
from . import geo, source

log = logging.getLogger(__name__)


def store(conn, published: dt.datetime | None, records: list[source.Record], town: geo.Town, sha: str) -> dict:
    """Keep the snapshot's records in the town; mark the town's records that left it as over."""
    kept, on_street = [], 0
    for r in records:
        geometry, method, _ = geo.place(r.points, town)
        obvody = geo.shares(geometry, town)
        if not obvody:
            continue
        kept.append(r.id)
        on_street += method == "street"
        conn.execute(
            """INSERT INTO traffic_records (id, situation, version, kind, details, starts_at, ends_at, comment,
                                            source, road, geometry, method, obvody, version_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
               ON CONFLICT (id) DO UPDATE SET situation = EXCLUDED.situation, version = EXCLUDED.version,
                 kind = EXCLUDED.kind, details = EXCLUDED.details, starts_at = EXCLUDED.starts_at,
                 ends_at = EXCLUDED.ends_at, comment = EXCLUDED.comment, source = EXCLUDED.source,
                 road = EXCLUDED.road, geometry = EXCLUDED.geometry, method = EXCLUDED.method,
                 obvody = EXCLUDED.obvody, version_at = EXCLUDED.version_at, last_seen = now(), gone_at = NULL""",
            (r.id, r.situation, r.version, r.kind, r.details, r.starts_at, r.ends_at, r.comment, r.source,
             r.road, json.dumps(geometry) if geometry else None, method, json.dumps(obvody), r.version_at))
    gone = conn.execute("""UPDATE traffic_records SET gone_at = now()
                           WHERE gone_at IS NULL AND NOT (id = ANY(%s::text[]))""", (kept,)).rowcount
    conn.execute("""INSERT INTO traffic_snapshots (published_at, sha256, records, in_town, changed)
                    VALUES (%s, %s, %s, %s, true)""", (published, sha, len(records), len(kept)))
    return {"records": len(records), "in_town": len(kept), "on_street": on_street, "gone": gone}


def update(path: Path | None = None) -> dict:
    """Download the snapshot (or read `path`, for a test or a backfill) and store it."""
    cfg = source.settings()
    if path is None and cfg is None:
        log.info("doprava: NDIC_URL/NDIC_USER/NDIC_PASSWORD not set, nothing to do")
        return {"skipped": "no NDIC settings", "failures": []}

    def run(conn, client) -> dict:
        xml = path.read_bytes() if path else source.fetch(client, *cfg)  # type: ignore[misc]
        sha = hashlib.sha256(xml).hexdigest()
        last = conn.execute("SELECT sha256 FROM traffic_snapshots ORDER BY checked_at DESC LIMIT 1").fetchone()
        published, records = source.parse(xml)
        if last and last["sha256"] == sha:
            conn.execute("""INSERT INTO traffic_snapshots (published_at, sha256, records, in_town, changed)
                            SELECT %s, %s, %s, in_town, false FROM traffic_snapshots
                            ORDER BY checked_at DESC LIMIT 1""", (published, sha, len(records)))
            return {"changed": False, "records": len(records)}
        return {"changed": True, **store(conn, published, records, geo.town(conn), sha)}

    return runner.run("doprava-update", "doprava", lambda conn, client: [Unit(("pardubice",), "pardubice", run)],
                      logger=log, client={"timeout": source.TIMEOUT, "follow_redirects": True})
