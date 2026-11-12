"""`petka podnety-update`: mirror the Dej Tip reports of each obvod. Idempotent; once a day is
plenty (the status changes are what we follow, and the job sees them to the day).

The first run of an obvod takes two years back; later runs take the last 120 days, which is
where reports still change status (an older report that changes is caught on a backfill with
--od). A report that turned chybné, spam or smazané is deleted here too.
"""

import datetime as dt
import logging

from .. import jobs as runner, obvody
from ..jobs import Unit
from . import source

log = logging.getLogger(__name__)

RECENT = dt.timedelta(days=120)


def window(today: dt.date, known: bool) -> tuple[dt.date, dt.date]:
    """The date range to download: two years back for an obvod we don't have yet, else the
    last 120 days. It ends tomorrow so today's reports are in whatever the source means by
    dateTo."""
    if known:
        start = today - RECENT
    else:
        start = today.replace(year=today.year - 2, day=28 if (today.month, today.day) == (2, 29) else today.day)
    return start, today + dt.timedelta(days=1)


def store(conn, obvod: str, keep: list[dict], drop: list[int]) -> dict:
    """Bring the obvod's reports in line with a download: new ones inserted, known ones
    updated (a status change also goes to citizen_report_statuses), dropped ones deleted."""
    ids = [r["id"] for r in keep]
    known = {r["id"]: r["status"] for r in conn.execute(
        "SELECT id, status FROM citizen_reports WHERE id = ANY(%s::bigint[])", (ids,))}
    new = changed = 0
    for r in keep:
        before = known.get(r["id"])
        conn.execute(
            """INSERT INTO citizen_reports (id, obvod, momc, category_id, category, status, reported_at,
                                            lat, lng, street)
               VALUES (%(id)s, %(obvod)s, %(momc)s, %(category_id)s, %(category)s, %(status)s,
                       %(reported_at)s, %(lat)s, %(lng)s, %(street)s)
               ON CONFLICT (id) DO UPDATE SET obvod = EXCLUDED.obvod, momc = EXCLUDED.momc,
                 category_id = EXCLUDED.category_id, category = EXCLUDED.category, status = EXCLUDED.status,
                 reported_at = EXCLUDED.reported_at, lat = EXCLUDED.lat, lng = EXCLUDED.lng,
                 street = EXCLUDED.street, last_seen = now(),
                 status_changed_at = CASE WHEN citizen_reports.status <> EXCLUDED.status THEN now()
                                          ELSE citizen_reports.status_changed_at END""",
            {**r, "obvod": obvod})
        if before != r["status"]:
            conn.execute("INSERT INTO citizen_report_statuses (id, status, initial) VALUES (%s, %s, %s)",
                         (r["id"], r["status"], before is None))
            new += before is None
            changed += before is not None
    removed = conn.execute("DELETE FROM citizen_reports WHERE id = ANY(%s::bigint[])", (drop,)).rowcount if drop else 0
    return {"reports": len(keep), "new": new, "changed": changed, "removed": removed}


def update(ids: list[str] | None = None, since: dt.date | None = None,
           today: dt.date | None = None) -> dict:
    """Download and store the reports of the given obvody (default: all). One download of
    the city serves every obvod that wants the same range."""
    today = today or dt.date.today()
    todo_obvody = [obvody.BY_ID[i] for i in ids] if ids else obvody.OBVODY
    downloads: dict[tuple, list] = {}

    def unit(o: obvody.Obvod) -> Unit:
        def run(conn, client) -> dict:
            known = conn.execute("SELECT 1 FROM citizen_reports WHERE obvod = %s LIMIT 1", (o.id,)).fetchone()
            start, end = window(today, bool(known))
            start = since or start
            if (start, end) not in downloads:
                downloads[(start, end)] = source.fetch(start, end, client)
            keep, drop = source.reports(downloads[(start, end)], o.momc)
            return {"from": start.isoformat(), **store(conn, o.id, keep, drop)}
        return Unit((o.id,), o.id, run)

    return runner.run("podnety-update", "podněty", lambda conn, client: [unit(o) for o in todo_obvody],
                      logger=log, client={"timeout": source.TIMEOUT, "headers": source.HEADERS})
