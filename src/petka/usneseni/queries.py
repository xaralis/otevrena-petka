"""Read models shared by the web pages, the REST API and the MCP tools."""

from .. import db
from .text import fold

CHOICE_LABEL = {"pro": "pro", "proti": "proti", "zdrzel": "zdržel se", "nehlasoval": "nehlasoval",
                "omluven": "omluven", "nepritomen": "nepřítomen"}
STATUS_LABEL = {"prijato": "PŘIJATO", "neprijato": "NEPŘIJATO", "castecne": "ČÁSTEČNĚ PŘIJATO",
                "neovereno": "NEOVĚŘENO"}
BODY_LABEL = {"zmo": "Zastupitelstvo", "rmo": "Rada"}


def resolution(uid: str) -> dict | None:
    with db.pool().connection() as conn:
        r = conn.execute(
            """SELECT r.*, m.term, m.number AS meeting_number, m.kind AS meeting_kind,
                 m.source_url, m.source_title, m.status AS meeting_status
               FROM resolutions r JOIN meetings m ON m.id = r.meeting_id WHERE r.uid = %s""",
            (uid,)).fetchone()
        if not r:
            return None
        r.pop("embedding", None)
        r.pop("tsv", None)
        r["votes"] = _votes(conn, "v.resolution_uid = %s", uid)
        r["revoked_by"] = conn.execute(
            """SELECT x.type, x.scope, x.detail, x.effective, s.uid, s.number, s.date, s.status
               FROM resolution_relations x JOIN resolutions s ON s.uid = x.source_uid
               WHERE x.target_uid = %s ORDER BY s.date""", (uid,)).fetchall()
        r["revokes"] = conn.execute(
            """SELECT x.type, x.scope, x.detail, x.effective, x.target_number, x.target_uid
               FROM resolution_relations x WHERE x.source_uid = %s""", (uid,)).fetchall()
        return r


def _votes(conn, where: str, arg) -> list[dict]:
    votes = conn.execute(
        f"""SELECT v.* FROM votes v WHERE {where} ORDER BY v.meeting_id, v.seq""", (arg,)).fetchall()
    if not votes:
        return []
    ballots = conn.execute(
        """SELECT b.vote_id, b.member_id, b.choice, b.provenance, m.name, s.list
           FROM ballots b JOIN members m ON m.id = b.member_id
           JOIN votes v ON v.id = b.vote_id JOIN meetings mt ON mt.id = v.meeting_id
           LEFT JOIN memberships s ON s.member_id = b.member_id AND s.term = mt.term
           WHERE b.vote_id = ANY(%s) ORDER BY m.last_name""", ([v["id"] for v in votes],)).fetchall()
    by_vote: dict[str, list] = {}
    for b in ballots:
        by_vote.setdefault(b["vote_id"], []).append(b)
    for v in votes:
        v["ballots"] = by_vote.get(v["id"], [])
    return votes


def meeting(mid: str) -> dict | None:
    with db.pool().connection() as conn:
        m = conn.execute("SELECT * FROM meetings WHERE id = %s", (mid,)).fetchone()
        if not m:
            return None
        names = {r["id"]: r["name"] for r in conn.execute(
            "SELECT id, name FROM members WHERE id = ANY(%s)",
            (m["present"] + m["excused"] + m["absent"],))}
        m["names"] = names
        m["agenda"] = conn.execute(
            "SELECT * FROM agenda_items WHERE meeting_id = %s ORDER BY seq", (mid,)).fetchall()
        m["resolutions"] = conn.execute(
            """SELECT r.uid, r.number, r.body, r.title, r.status, r.agenda_no, r.agenda_title, r.summary,
                 left(r.text || '', 300) AS text_start, (SELECT json_build_object('pro', v.n_pro, 'proti', v.n_proti, 'zdrzel', v.n_zdrzel,
                'nehl', coalesce(v.n_nehlasoval, 0), 'quorum', v.quorum, 'present', v.n_present,
                'parts', (SELECT count(*) FROM votes p WHERE p.resolution_uid = r.uid AND p.part IS NOT NULL),
                'whole', v.part IS NULL,
                'parts_ok', (SELECT count(*) FROM votes p WHERE p.resolution_uid = r.uid AND p.part IS NOT NULL AND p.outcome = 'prijato'))
              FROM votes v WHERE v.resolution_uid = r.uid
              ORDER BY (v.part IS NULL) DESC, v.seq DESC LIMIT 1) AS mainvote,
                 (SELECT string_agg(x.type || ':' || x.scope || ':' || s.number, ';')
                    FROM resolution_relations x JOIN resolutions s ON s.uid = x.source_uid
                   WHERE x.target_uid = r.uid AND x.effective) AS revoked_by
               FROM resolutions r WHERE r.meeting_id = %s ORDER BY r.seq""", (mid,)).fetchall()
        m["other_votes"] = _votes(conn, "v.meeting_id = %s AND v.resolution_uid IS NULL", mid)
        return m


def meetings(body: str | None = None, year: int | None = None) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT m.id, m.body, m.number, m.kind, m.date, m.status, m.term,
                 (SELECT count(*) FROM resolutions r WHERE r.meeting_id = m.id AND r.status <> 'neprijato') AS n_resolutions,
                 (SELECT count(*) FROM resolutions r WHERE r.meeting_id = m.id AND r.status = 'neprijato') AS n_rejected,
                 (SELECT count(*) FROM resolutions r WHERE r.meeting_id = m.id AND r.status = 'castecne') AS n_partial
               FROM meetings m
               WHERE (%s::text IS NULL OR m.body = %s) AND (%s::int IS NULL OR extract(year FROM m.date) = %s)
               ORDER BY m.date DESC, m.body""", (body, body, year, year)).fetchall()


def members(term: str | None = None) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT m.id, m.name, s.term, s.list, s.elected, s.in_rada,
                 (SELECT count(*) FROM ballots b JOIN votes v ON v.id = b.vote_id
                    JOIN meetings mt ON mt.id = v.meeting_id
                  WHERE b.member_id = m.id AND mt.term = s.term) AS n_ballots
               FROM members m JOIN memberships s ON s.member_id = m.id
               WHERE (%s::text IS NULL OR s.term = %s)
                 AND EXISTS (SELECT 1 FROM ballots b JOIN votes v ON v.id = b.vote_id
                             JOIN meetings mt ON mt.id = v.meeting_id
                             WHERE b.member_id = m.id AND mt.term = s.term)
               ORDER BY s.term DESC, m.last_name""", (term, term)).fetchall()


def member(mid: str) -> dict | None:
    with db.pool().connection() as conn:
        m = conn.execute("SELECT * FROM members WHERE id = %s", (mid,)).fetchone()
        if not m:
            return None
        m["terms"] = conn.execute(
            "SELECT * FROM memberships WHERE member_id = %s ORDER BY term DESC", (mid,)).fetchall()
        m["stats"] = conn.execute(
            """SELECT mt.term, mt.body, b.choice, count(*) AS n
               FROM ballots b JOIN votes v ON v.id = b.vote_id JOIN meetings mt ON mt.id = v.meeting_id
               WHERE b.member_id = %s GROUP BY 1, 2, 3 ORDER BY 1 DESC, 2""", (mid,)).fetchall()
        m["attendance"] = conn.execute(
            """SELECT body, term,
                 count(*) FILTER (WHERE %s = ANY(present)) AS present,
                 count(*) FILTER (WHERE %s = ANY(excused)) AS excused,
                 count(*) FILTER (WHERE %s = ANY(absent)) AS absent
               FROM meetings WHERE %s = ANY(present || excused || absent)
               GROUP BY 1, 2 ORDER BY 2 DESC, 1""", (mid, mid, mid, mid)).fetchall()
        return m


def member_votes(mid: str, *, dissent_only: bool = False, choice: str | None = None,
                 procedural: bool = True, limit: int = 50, offset: int = 0) -> list[dict]:
    """A member's ballots with the resolution; dissent = voted differently than the outcome."""
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT v.id AS vote_id, mt.date, mt.body, v.part, v.subject, v.outcome,
                 v.n_pro, v.n_proti, v.n_zdrzel, b.choice, b.provenance,
                 r.uid, r.number, r.title, r.status
               FROM ballots b JOIN votes v ON v.id = b.vote_id JOIN meetings mt ON mt.id = v.meeting_id
               LEFT JOIN resolutions r ON r.uid = v.resolution_uid
               WHERE b.member_id = %s AND b.choice NOT IN ('omluven', 'nepritomen')
                 AND (%s::text IS NULL OR b.choice = %s)
                 AND (%s OR NOT v.procedural)
                 AND (NOT %s OR (v.outcome = 'prijato' AND b.choice <> 'pro')
                              OR (v.outcome = 'neprijato' AND b.choice = 'pro'))
               ORDER BY mt.date DESC, v.seq LIMIT %s OFFSET %s""",
            (mid, choice, choice, procedural, dissent_only, limit, offset)).fetchall()


def opendata_tables() -> list[dict]:
    """Published tables with Czech names, descriptions and row counts (dataset page)."""
    from .opendata_schema import TABLES
    counts = {"meetings": "meetings", "resolutions": "resolutions", "votes": "votes",
              "ballots": "ballots", "relations": "resolution_relations"}
    out = []
    with db.pool().connection() as conn:
        for name, t in TABLES.items():
            n = None
            if name in counts:
                n = conn.execute(f"SELECT count(*) AS n FROM {counts[name]}").fetchone()["n"]
            elif name == "members":
                n = conn.execute("SELECT count(DISTINCT member_id) AS n FROM ballots").fetchone()["n"]
            out.append({"name": name, "title": t["title"], "description": t["description"], "rows": n})
    return out


def latest_meetings(n: int = 4) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT m.id, m.body, m.number, m.kind, m.date,
                 (SELECT count(*) FROM resolutions r WHERE r.meeting_id = m.id AND r.status <> 'neprijato') AS n_resolutions,
                 (SELECT count(*) FROM resolutions r WHERE r.meeting_id = m.id AND r.status = 'neprijato') AS n_rejected
               FROM meetings m ORDER BY m.date DESC, m.body LIMIT %s""", (n,)).fetchall()


def member_surnames() -> list[str]:
    with db.pool().connection() as conn:
        return [r["last_name"] for r in conn.execute(
            """SELECT DISTINCT m.last_name FROM members m
               WHERE EXISTS (SELECT 1 FROM ballots b WHERE b.member_id = m.id) ORDER BY 1""")]


def find_member(name_or_id: str) -> str | None:
    """Member id from an id, a full name or a surname ('Vařecha', 'varecha'); None if ambiguous."""
    key = fold(name_or_id).strip()
    with db.pool().connection() as conn:
        exact = conn.execute("SELECT id FROM members WHERE id = %s OR name_fold = %s",
                             (name_or_id, key)).fetchall()
        if len(exact) == 1:
            return exact[0]["id"]
        words = key.split()
        rows = conn.execute(
            "SELECT id, first_name FROM members WHERE f_unaccent(lower(last_name)) = %s",
            (words[-1] if words else "",)).fetchall()
    if len(rows) > 1 and len(words) > 1:
        rows = [r for r in rows if fold(r["first_name"]).startswith(words[0].rstrip("."))]
    return rows[0]["id"] if len(rows) == 1 else None


def stats() -> dict:
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT (SELECT count(*) FROM meetings) AS meetings,
                      (SELECT count(*) FROM resolutions WHERE status <> 'neprijato') AS resolutions,
                      (SELECT count(*) FROM resolutions WHERE status = 'neprijato') AS rejected,
                      (SELECT count(*) FROM resolutions WHERE status <> 'prijato') AS not_passed,
                      (SELECT count(*) FROM votes) AS votes,
                      (SELECT count(*) FROM ballots WHERE provenance <> 'attendance') AS ballots,
                      (SELECT count(*) FROM ballots WHERE provenance = 'named') AS ballots_named,
                      (SELECT min(date) FROM meetings) AS first_date,
                      (SELECT max(date) FROM meetings) AS last_date,
                      (SELECT max(loaded_at) FROM meetings) AS updated_at,
                      (SELECT count(*) FROM meetings WHERE status <> 'ok') AS needs_review""").fetchone()
