"""`petka podnety-update`: mirror the Dej Tip reports of each of the town's eight obvody
(obvody.TOWN, by CS_MUNICODE). Idempotent; the cluster runs it every four hours, which is what
the page promises ("aktualizace každé 4 hodiny").

The first run of an obvod takes two years back; later runs take the last 120 days, which is
where reports still change status (an older report that changes is caught on a backfill with
--od). Which obvody were mirrored is kept in citizen_report_obvody, so an obvod without any
report doesn't take two years again on every run. Obvody that want the same window share one
download of the city. A report that turned chybné, spam or smazané is deleted here too; a
report whose CS_MUNICODE is no obvod of the town is not kept.
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
                                            lat, lng, street, first_note_at, last_note_at, description, photo_url)
               VALUES (%(id)s, %(obvod)s, %(momc)s, %(category_id)s, %(category)s, %(status)s,
                       %(reported_at)s, %(lat)s, %(lng)s, %(street)s, %(first_note_at)s, %(last_note_at)s,
                       %(description)s, %(photo_url)s)
               ON CONFLICT (id) DO UPDATE SET obvod = EXCLUDED.obvod, momc = EXCLUDED.momc,
                 category_id = EXCLUDED.category_id, category = EXCLUDED.category, status = EXCLUDED.status,
                 reported_at = EXCLUDED.reported_at, lat = EXCLUDED.lat, lng = EXCLUDED.lng,
                 street = EXCLUDED.street, first_note_at = EXCLUDED.first_note_at,
                 last_note_at = EXCLUDED.last_note_at, description = EXCLUDED.description,
                 photo_url = EXCLUDED.photo_url, last_seen = now(),
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


def synced(conn, obvod: str) -> bool:
    """Whether the obvod was mirrored before (its first, long run is done)."""
    return conn.execute("SELECT 1 FROM citizen_report_obvody WHERE obvod = %s", (obvod,)).fetchone() is not None


def mark(conn, obvod: str, start: dt.date) -> None:
    """Note a successful download of the obvod from `start`: the API's version moves."""
    conn.execute("""INSERT INTO citizen_report_obvody (obvod, since) VALUES (%s, %s)
                    ON CONFLICT (obvod) DO UPDATE SET since = LEAST(citizen_report_obvody.since, EXCLUDED.since),
                                                      checked_at = now()""", (obvod, start))


def update(ids: list[str] | None = None, since: dt.date | None = None,
           today: dt.date | None = None) -> dict:
    """Download and store the reports of the given obvody (ids of obvody.TOWN; default: all
    eight). One download of the city serves every obvod that wants the same range."""
    today = today or dt.date.today()
    todo_obvody = [obvody.TOWN_BY_ID[i] for i in ids] if ids else obvody.TOWN
    downloads: dict[tuple, list] = {}

    def unit(o: obvody.TownObvod) -> Unit:
        def run(conn, client) -> dict:
            start, end = window(today, synced(conn, o.id))
            start = since or start
            if (start, end) not in downloads:
                downloads[(start, end)] = source.fetch(start, end, client)
            keep, drop = source.reports(downloads[(start, end)], o.momc)
            summary = store(conn, o.id, keep, drop)
            mark(conn, o.id, start)
            return {"from": start.isoformat(), **summary}
        return Unit((o.id,), o.id, run)

    return runner.run("podnety-update", "podněty", lambda conn, client: [unit(o) for o in todo_obvody],
                      logger=log, client={"timeout": source.TIMEOUT, "headers": source.HEADERS})
