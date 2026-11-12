"""`usneseni deska-update`: download the boards, upsert their notices, mark the ones that
left the feed as taken down. Idempotent; run it as often as you like (hourly is plenty).

Privacy: a delivery notice (doručení písemnosti) names the person it is addressed to. The
city publishes that only while the notice is posted, so once it is taken down we keep the
record but drop the name (generic title) and the links to its documents. The OFN `popis`
is not stored at all: on these boards it repeats the title and adds dates of birth.
"""

import json
import logging

from psycopg.types.json import Jsonb

from .. import jobs as runner
from ..jobs import Unit
from . import source

log = logging.getLogger(__name__)

REDACTED_TITLE = "Oznámení o doručení písemnosti (adresáta po sejmutí neuvádíme)"


def sync(conn, board: source.Board, rows: list[dict]) -> dict:
    """Upsert one board's current notices and mark the missing ones removed. Same transaction,
    one `now()` for the whole board."""
    active = conn.execute("SELECT count(*) AS n FROM notices WHERE board = %s AND removed_at IS NULL",
                          (board.id,)).fetchone()["n"]
    if not rows and active:
        # an empty feed is far more likely an outage than a board with nothing on it
        raise RuntimeError(f"{board.id}: feed has no notices, {active} are posted – not removing them")
    new = 0
    for r in rows:
        res = conn.execute(
            """INSERT INTO notices (id, board, url, title, published, valid_until, agenda, kind,
                                    reference, file_mark, department, attachments, is_mo5)
               VALUES (%(id)s, %(board)s, %(url)s, %(title)s, %(published)s, %(valid_until)s,
                       %(agenda)s, %(kind)s, %(reference)s, %(file_mark)s, %(department)s,
                       %(attachments)s, %(is_mo5)s)
               ON CONFLICT (id) DO UPDATE SET
                 url = EXCLUDED.url, title = EXCLUDED.title, published = EXCLUDED.published,
                 valid_until = EXCLUDED.valid_until, agenda = EXCLUDED.agenda, kind = EXCLUDED.kind,
                 reference = EXCLUDED.reference, file_mark = EXCLUDED.file_mark,
                 department = EXCLUDED.department, attachments = EXCLUDED.attachments,
                 is_mo5 = EXCLUDED.is_mo5, redacted = false, last_seen = now(), removed_at = NULL
               RETURNING (xmax = 0) AS inserted""",
            {**r, "attachments": Jsonb(r["attachments"])}).fetchone()
        new += res["inserted"]
    removed = conn.execute(
        """UPDATE notices SET removed_at = now()
           WHERE board = %s AND removed_at IS NULL AND NOT (id = ANY(%s))""",
        (board.id, [r["id"] for r in rows])).rowcount
    return {"posted": len(rows), "new": new, "removed": removed}


def redact(conn) -> int:
    return conn.execute(
        # everything that could lead back to the addressee goes: title, files, the notice URL
        # and the file numbers (the city takes the notice down; we keep only that it existed)
        """UPDATE notices SET title = %s, attachments = '[]', url = '', reference = NULL,
             file_mark = NULL, redacted = true
           WHERE removed_at IS NOT NULL AND kind = 'doruceni' AND NOT redacted""",
        (REDACTED_TITLE,)).rowcount


def _save_board(conn, b: source.Board) -> dict:
    conn.execute(
        """INSERT INTO notice_boards (id, name, url, page) VALUES (%s, %s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, page = EXCLUDED.page""",
        (b.id, b.name, b.url, b.page))
    return conn.execute("SELECT * FROM notice_boards WHERE id = %s", (b.id,)).fetchone()


def _unit(b: source.Board, state: dict) -> Unit:
    def run(conn, client) -> dict:
        f = source.fetch(b, state["etag"], state["last_modified"], client)
        if f.status == 304:
            conn.execute("UPDATE notices SET last_seen = now() WHERE board = %s AND removed_at IS NULL", (b.id,))
            summary = {"unchanged": True}
        else:
            rows = source.parse(json.loads(f.body), b)
            summary = sync(conn, b, rows)
            conn.execute(
                """UPDATE notice_boards SET etag = %s, last_modified = %s, n_items = %s,
                     changed_at = CASE WHEN sha256 IS DISTINCT FROM %s THEN now() ELSE changed_at END,
                     sha256 = %s WHERE id = %s""",
                (f.etag, f.last_modified, len(rows), f.sha256, f.sha256, b.id))
        conn.execute("UPDATE notice_boards SET checked_at = now() WHERE id = %s", (b.id,))
        return summary
    return Unit((b.id,), b.id, run)


def update(boards: list[source.Board] | None = None) -> dict:
    """Fetch every board and bring the table in line. Returns {board: summary}; a board that
    fails is reported and left as it was, the others still update."""
    def units(conn, client):
        for b in boards or source.BOARDS:
            state = _save_board(conn, b)
            conn.commit()
            yield _unit(b, state)

    def finish(conn) -> None:
        n = redact(conn)
        conn.commit()
        if n:
            log.info("deska: %d taken-down delivery notices anonymised", n)

    return runner.run("deska-update", "deska", units, client={"timeout": source.TIMEOUT, "follow_redirects": True},
                      finish=finish, logger=log)
