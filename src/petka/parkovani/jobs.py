"""The parking jobs.

`petka parkovani-update` (daily): the lots from ChytřejšíParking (petka.parkovani.source), kept
as one build. A build with fewer than GUARD of the last accepted build's lots is refused and the
last accepted one stays served, as with Místa. It also makes sure the obvody's polygons are in
ruian_cache, which the export places every record by.

`petka parkovani-obsazenost` (every 60 s): the free places of every lot. One fetch by default
(a CronJob), or `--smycka` to keep fetching every `--kazdych` seconds in one process (a worker:
the source changes by the minute, and a pod a minute for one HTTP request costs more than the
request). A fetch that fails, or answers with no lots, changes nothing: the last good numbers
stay and `fetched_at` grows old. The first successful fetch in each 5-minute slot also writes
the slot into the history. A run of failures longer than ALERT_AFTER raises one alert.
"""

import datetime as dt
import json
import logging
import signal
import time
from pathlib import Path

from .. import jobs as runner
from ..jobs import Unit
from . import build, source

log = logging.getLogger(__name__)

GUARD = 0.7
SLOT = 300                                  # s: the history's step
ALERT_AFTER = dt.timedelta(minutes=10)


class Refused(RuntimeError):
    pass


# --- lots (daily) -----------------------------------------------------------------------------

def problem(new: int, last: int | None) -> str | None:
    """Why a build with `new` lots must not replace the last accepted one with `last`, or None."""
    if not new:
        return "no lots"
    if last and new < GUARD * last:
        return f"{new} lots < {GUARD:.0%} of {last}"
    return None


def store(conn, lots: list[dict], force: bool = False) -> dict:
    """Guard and store one build of the lots (source facts). A refused build is recorded,
    committed and raises Refused, so the job fails and alerts."""
    _, notes = build.lots(lots)
    last = conn.execute("SELECT total FROM parkovani_builds WHERE accepted ORDER BY built_at DESC, id DESC LIMIT 1"
                        ).fetchone()
    why = None if force else problem(len(lots), last["total"] if last else None)
    report = {"lots": len(lots), "paid": sum(lt["paid"] for lt in lots), "notes": notes}
    if why:
        conn.execute("INSERT INTO parkovani_builds (lots, total, accepted, reason, report) VALUES (%s, %s, false, %s, %s)",
                     (json.dumps(lots), len(lots), why, json.dumps(report)))
        conn.commit()
        raise Refused(f"build refused, the last accepted stays: {why}")
    conn.execute("INSERT INTO parkovani_builds (lots, total, accepted, report) VALUES (%s, %s, true, %s)",
                 (json.dumps(lots, ensure_ascii=False), len(lots), json.dumps(report, ensure_ascii=False)))
    return report


def _polygons() -> None:
    """The obvody's polygons into ruian_cache (asked from ČÚZK only when missing), over their
    own autocommit connection."""
    import psycopg
    from psycopg.rows import dict_row

    from .. import db
    from ..mista import where
    with psycopg.connect(db.URL, autocommit=True, row_factory=dict_row) as conn:
        where.town_obvody(conn)


def update(occupancy: Path | None = None, locations: Path | None = None, force: bool = False) -> dict:
    """Fetch the lots (or read both answers from files, for a test or a backfill) and store the build."""
    def run(conn, client) -> dict:
        if occupancy and locations:
            occ = json.loads(occupancy.read_text())["data"]
            loc = json.loads(locations.read_text())["data"]
        else:
            occ, loc = source.fetch(client, source.OCCUPANCY), source.fetch(client, source.LOCATIONS)
        try:
            _polygons()
        except Exception:
            log.exception("parkování: the obvody's polygons could not be cached; records stay without obvody")
        return store(conn, source.lots_of(occ, loc), force)

    return runner.run("parkovani-update", "parkování", lambda conn, client: [Unit(("pardubice",), "pardubice", run)],
                      logger=log, client={"follow_redirects": True})


# --- occupancy (every 60 s) -------------------------------------------------------------------

def slot(at: dt.datetime) -> dt.datetime:
    """The start of the 5-minute slot `at` is in."""
    return at - dt.timedelta(seconds=at.timestamp() % SLOT)


def save(conn, numbers: dict[str, tuple[int, int]], at: dt.datetime) -> dict:
    """Store one successful fetch: each lot's numbers (changed_at moves only when free or total
    changed), the state, and the slot of the history unless it is written already."""
    if not numbers:
        raise source.SourceError("the answer has no lots with places")
    rows = [(k, f, t, at, at) for k, (f, t) in sorted(numbers.items())]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO parkovani_now AS n (id, free, total, changed_at, seen_at) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET free = EXCLUDED.free, total = EXCLUDED.total, seen_at = EXCLUDED.seen_at,
                 changed_at = CASE WHEN (n.free, n.total) = (EXCLUDED.free, EXCLUDED.total) THEN n.changed_at
                                   ELSE EXCLUDED.changed_at END""", rows)
    # only the new ids: ON CONFLICT alone would still take a number of the small sequence each time
    conn.execute("""INSERT INTO parkovani_lots (id) SELECT x FROM unnest(%s::text[]) x
                    WHERE NOT EXISTS (SELECT 1 FROM parkovani_lots l WHERE l.id = x) ORDER BY x
                    ON CONFLICT (id) DO NOTHING""", (sorted(numbers),))
    s = slot(at)
    written = conn.execute(
        """INSERT INTO parkovani_history (lot, at, free, total)
           SELECT l.n, %s, n.free, n.total FROM parkovani_now n JOIN parkovani_lots l USING (id) WHERE n.id = ANY(%s)
           ON CONFLICT (lot, at) DO NOTHING""", (s, list(numbers))).rowcount
    conn.execute("""INSERT INTO parkovani_state (one, fetched_at, tried_at, error, failing_since, alerted)
                    VALUES (true, %s, %s, NULL, NULL, false)
                    ON CONFLICT (one) DO UPDATE SET fetched_at = EXCLUDED.fetched_at, tried_at = EXCLUDED.tried_at,
                      error = NULL, failing_since = NULL, alerted = false""", (at, at))
    return {"lots": len(numbers), "free": sum(f for f, _ in numbers.values()),
            "total": sum(t for _, t in numbers.values()), "history": written}


def failed(conn, at: dt.datetime, error: str) -> bool:
    """Record a failed fetch; True when the failures have now lasted ALERT_AFTER and nobody has
    been alerted yet (the caller alerts, once per run of failures)."""
    r = conn.execute(
        """INSERT INTO parkovani_state (one, tried_at, error, failing_since) VALUES (true, %s, %s, %s)
           ON CONFLICT (one) DO UPDATE SET tried_at = EXCLUDED.tried_at, error = EXCLUDED.error,
             failing_since = coalesce(parkovani_state.failing_since, EXCLUDED.failing_since)
           RETURNING failing_since, alerted""", (at, error[:500], at)).fetchone()
    if not r["alerted"] and at - r["failing_since"] >= ALERT_AFTER:
        conn.execute("UPDATE parkovani_state SET alerted = true")
        return True
    return False


def fetch_once(conn, client, now=None, alert=None) -> dict:
    """One fetch of the occupancy, stored or recorded as failed; commits."""
    at = (now or (lambda: dt.datetime.now(dt.UTC)))()
    try:
        summary = save(conn, source.occupancy_of(source.fetch(client, source.OCCUPANCY)), at)
        conn.commit()
        return summary
    except Exception as e:
        conn.rollback()
        log.warning("parkování: occupancy fetch failed: %s", e)
        if failed(conn, at, str(e)):
            (alert or runner.sentry_alert)(f"parkovani-obsazenost: failing since {ALERT_AFTER} ago: {e}")
        conn.commit()
        return {"error": str(e)}


def watch(every: float = 60, once: bool = False, connect=None, http=None, sleep=time.sleep, alert=None) -> dict:
    """Fetch once, or every `every` seconds until SIGTERM/SIGINT (between two fetches). Each fetch
    opens its own connection, so a database restart costs one fetch, not the worker."""
    from .. import db
    db.migrate()
    if http is None:
        import httpx
        http = httpx.Client
    stop = {"now": False}
    if not once:
        def _stop(*_):
            stop["now"] = True
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
    last: dict = {}
    with http(follow_redirects=True) as client:
        while True:
            started = time.monotonic()
            try:
                with (connect or db.connect)() as conn:
                    last = fetch_once(conn, client, alert=alert)
            except Exception as e:          # the database itself is away
                log.exception("parkování: occupancy not stored")
                last = {"error": str(e)}
            log.info("parkování obsazenost: %s", last)
            if once or stop["now"]:
                return last
            wait = every - (time.monotonic() - started)
            while wait > 0 and not stop["now"]:
                sleep(min(wait, 1))
                wait -= 1
            if stop["now"]:
                return last
