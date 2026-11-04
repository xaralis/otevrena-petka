"""Reading notices: list and full-text search (pages, API, MCP), counts, export rows."""

import re

from .. import db
from ..usneseni.text import fold
from .source import BY_ID, KIND_LABEL

COLUMNS = """n.id, n.board, n.url, n.title, n.published, n.valid_until, n.agenda, n.kind,
             n.reference, n.file_mark, n.department, n.attachments, n.is_mo5, n.redacted,
             n.first_seen, n.last_seen, n.removed_at,
             (n.removed_at AT TIME ZONE 'Europe/Prague')::date AS removed_on,
             (SELECT d.data FROM notice_digests d WHERE d.notice_id = n.id AND d.status = 'published') AS digest"""

# annexes shown inside a published card don't get a row of their own
NOT_MEMBER = """NOT EXISTS (SELECT 1 FROM notice_digests x WHERE x.status = 'published' AND n.id = ANY(x.members))"""

STOPWORDS = set("""a i o u v k s z ve ke se ze na do od po pro pri za nad pod mezi bez
    je jsou byl byla bylo by kdy kde jak co kdo ktery ktera ktere ten ta to tom tech
    jeho jejich nebo ale ani take tak jen uz jiz""".split())


def tsquery(q: str, op: str = "&") -> str | None:
    """Accent-insensitive prefix query: 'parkování' -> 'parkova:*' (crude Czech stemming, the
    same as the resolutions' search: long words lose the inflected ending)."""
    words = [w for w in re.findall(r"[0-9a-z]+", fold(q)) if len(w) > 1 and w not in STOPWORDS]
    if not words:
        return None
    return f" {op} ".join(f"{_stem(w)}:*" for w in dict.fromkeys(words))


def _stem(w: str) -> str:
    return w if w.isdigit() or len(w) <= 5 else w[:max(5, len(w) - 2)]


def _where(mo5: bool, active: bool, kind: str | None) -> tuple[list[str], list]:
    w, p = ["n.removed_at IS NULL" if active else "n.removed_at IS NOT NULL", NOT_MEMBER], []
    if mo5:
        w.append("n.is_mo5")
    if kind:
        w.append("n.kind = %s"); p.append(kind)
    return w, p


def search(q: str = "", mo5: bool = True, active: bool = True, kind: str | None = None,
           limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    """Notices newest first (taken-down ones: most recently taken down first). With `q`, those
    whose title, reference or department has all the words; if none has, any of them."""
    w, p = _where(mo5, active, kind)
    order = ("n.published DESC NULLS LAST, n.id DESC" if active
             else "n.removed_at DESC, n.published DESC NULLS LAST, n.id DESC")
    with db.pool().connection() as conn:
        for op in ("&", "|") if q.strip() else (None,):
            ww, pp = list(w), list(p)
            if op:
                tq = tsquery(q, op)
                if not tq:
                    return [], 0
                ww.append("n.tsv @@ to_tsquery('simple', %s)"); pp.append(tq)
            where = " AND ".join(ww)
            total = conn.execute(f"SELECT count(*) AS n FROM notices n WHERE {where}", pp).fetchone()["n"]
            if total:
                break
        rows = conn.execute(f"SELECT {COLUMNS} FROM notices n WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s",
                            pp + [limit, offset]).fetchall()
    return [_row(r) for r in rows], total


def notice(nid: str) -> dict | None:
    with db.pool().connection() as conn:
        r = conn.execute(f"SELECT {COLUMNS} FROM notices n WHERE n.id = %s", (nid,)).fetchone()
    return _row(r) if r else None


def _row(r: dict) -> dict:
    return {**r, "kind_label": KIND_LABEL.get(r["kind"], r["kind"]),
            "board_name": BY_ID[r["board"]].name if r["board"] in BY_ID else r["board"]}


def members(ids: list[str]) -> list[dict]:
    """The annexes of a card (notices posted separately), as rows."""
    if not ids:
        return []
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT {COLUMNS} FROM notices n WHERE n.id = ANY(%s) ORDER BY n.id", (ids,)).fetchall()
    return [_row(r) for r in rows]


def draft(nid: str) -> dict | None:
    """One proposed card with its notice (the preview page)."""
    with db.pool().connection() as conn:
        r = conn.execute(f"""SELECT {COLUMNS}, d.data AS draft FROM notice_digests d
                             JOIN notices n ON n.id = d.notice_id
                             WHERE d.notice_id = %s AND d.status = 'draft'""", (nid,)).fetchone()
    return _row(r) if r else None


def drafts() -> list[dict]:
    """Proposed cards waiting for a person, newest notice first (the preview page)."""
    with db.pool().connection() as conn:
        rows = conn.execute(
            f"""SELECT {COLUMNS}, d.data AS draft, d.status AS draft_status
                FROM notice_digests d JOIN notices n ON n.id = d.notice_id
                WHERE d.status = 'draft' ORDER BY n.published DESC NULLS LAST, n.id DESC""").fetchall()
    return [_row(r) for r in rows]


def kinds(mo5: bool = True, active: bool = True) -> list[dict]:
    """Kinds with counts for the filter, most common first."""
    w, p = _where(mo5, active, None)
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT n.kind, count(*) AS n FROM notices n WHERE {' AND '.join(w)} "
                            "GROUP BY n.kind ORDER BY count(*) DESC, n.kind", p).fetchall()
    return [{"kind": r["kind"], "label": KIND_LABEL.get(r["kind"], r["kind"]), "n": r["n"]} for r in rows]


def stats() -> dict:
    """Counts and the state of each board (for the page, the home page and the catalog)."""
    with db.pool().connection() as conn:
        s = conn.execute(
            """SELECT count(*) FILTER (WHERE removed_at IS NULL AND is_mo5) AS posted_mo5,
                      count(*) FILTER (WHERE removed_at IS NULL) AS posted,
                      count(*) FILTER (WHERE removed_at IS NOT NULL AND is_mo5) AS removed_mo5,
                      count(*) FILTER (WHERE removed_at IS NOT NULL) AS removed,
                      count(*) AS total, (min(first_seen) AT TIME ZONE 'Europe/Prague')::date AS since
               FROM notices""").fetchone()
        boards = conn.execute("""SELECT id, name, url, page, checked_at, changed_at, n_items,
                                        checked_at AT TIME ZONE 'Europe/Prague' AS checked_local
                                 FROM notice_boards""").fetchall()
    order = list(BY_ID)
    boards.sort(key=lambda b: order.index(b["id"]) if b["id"] in order else 99)
    checked = [b for b in boards if b["checked_at"]]
    oldest = min(checked, key=lambda b: b["checked_at"]) if checked else None
    return {**s, "boards": boards, "checked_at": oldest and oldest["checked_at"],
            "checked_local": oldest and oldest["checked_local"]}


EXPORT_FIELDS = ["id", "board", "is_mo5", "title", "kind", "published", "valid_until", "removed_at",
                 "first_seen", "last_seen", "reference", "file_mark", "department", "agenda", "url",
                 "attachments", "redacted"]


def export_rows() -> list[dict]:
    """Every notice we have seen, including taken-down ones, newest first."""
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT {COLUMNS} FROM notices n ORDER BY n.published DESC NULLS LAST, n.id DESC").fetchall()
    return [{k: r[k] for k in EXPORT_FIELDS} for r in rows]
