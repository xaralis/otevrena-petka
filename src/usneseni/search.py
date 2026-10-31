"""Search over resolutions: full text, semantic, or both merged (reciprocal rank fusion).

Full text uses an unaccented `simple` tsvector (Postgres has no Czech stemmer) with prefix
matching on every query word, so "parkov" finds "parkování" and "parkovišť". Inflection
beyond prefixes is left to the semantic side (bge-m3 embeddings).
"""

import re
from dataclasses import dataclass, field

from . import db, embed
from .text import fold

RRF_K = 60


@dataclass
class Filters:
    body: str | None = None        # zmo | rmo
    term: str | None = None
    year: int | None = None
    date_from: str | None = None
    date_to: str | None = None
    topic: str | None = None
    kind: str | None = None
    status: str | None = None      # prijato | neprijato | castecne | neovereno
    member: str | None = None      # member id …
    member_choice: str | None = None  # … voted pro | proti | zdrzel | nehlasoval

    def sql(self) -> tuple[str, list]:
        w, p = [], []
        if self.body:
            w.append("r.body = %s"); p.append(self.body)
        if self.term:
            w.append("m.term = %s"); p.append(self.term)
        if self.year:
            w.append("extract(year FROM r.date) = %s"); p.append(self.year)
        if self.date_from:
            w.append("r.date >= %s"); p.append(self.date_from)
        if self.date_to:
            w.append("r.date <= %s"); p.append(self.date_to)
        if self.topic:
            w.append("%s = ANY(r.topics)"); p.append(self.topic)
        if self.kind:
            w.append("r.kind = %s"); p.append(self.kind)
        if self.status:
            w.append("r.status = %s"); p.append(self.status)
        if self.member:
            w.append("""EXISTS (SELECT 1 FROM votes v JOIN ballots b ON b.vote_id = v.id
                        WHERE v.resolution_uid = r.uid AND b.member_id = %s
                        AND (%s::text IS NULL OR b.choice = %s))""")
            p += [self.member, self.member_choice, self.member_choice]
        return (" AND ".join(w) or "TRUE"), p


@dataclass
class Hit:
    uid: str
    score: float
    fulltext_rank: int | None = None
    semantic_rank: int | None = None
    row: dict = field(default_factory=dict)


def tsquery(q: str) -> str | None:
    words = re.findall(r"[0-9a-z]+", fold(q))
    words = [w for w in words if len(w) > 1]
    if not words:
        return None
    return " & ".join(f"{w}:*" for w in words)


COLUMNS = """r.uid, r.number, r.body, r.date, r.meeting_id, r.status, r.title, r.summary,
             r.agenda_title, r.topics, r.kind, r.keywords, left(r.text, 400) AS text_start"""


def search(q: str, mode: str = "hybrid", filters: Filters | None = None, limit: int = 20,
           offset: int = 0) -> tuple[list[Hit], dict]:
    """Returns hits and info {mode_used, semantic_available, total_fulltext}."""
    f = filters or Filters()
    where, params = f.sql()
    info = {"mode": mode, "semantic_available": embed.enabled()}
    pool_size = max(100, limit + offset)
    with db.pool().connection() as conn:
        if not q.strip():
            rows = conn.execute(
                f"""SELECT {COLUMNS} FROM resolutions r JOIN meetings m ON m.id = r.meeting_id
                    WHERE {where} ORDER BY r.date DESC, r.seq LIMIT %s OFFSET %s""",
                params + [limit, offset]).fetchall()
            total = conn.execute(f"""SELECT count(*) AS n FROM resolutions r JOIN meetings m
                                     ON m.id = r.meeting_id WHERE {where}""", params).fetchone()["n"]
            info.update(mode="browse", total=total)
            return [Hit(r["uid"], 0, row=r) for r in rows], info

        ft: list[str] = []
        tq = tsquery(q)
        if mode in ("hybrid", "fulltext") and tq:
            ft = [r["uid"] for r in conn.execute(
                f"""SELECT r.uid FROM resolutions r JOIN meetings m ON m.id = r.meeting_id
                    WHERE {where} AND r.tsv @@ to_tsquery('simple', %s)
                    ORDER BY ts_rank_cd(r.tsv, to_tsquery('simple', %s), 32) DESC, r.date DESC
                    LIMIT %s""", params + [tq, tq, pool_size])]
        sem: list[str] = []
        if mode in ("hybrid", "semantic"):
            vec = embed.embed_query(q)
            if vec is None:
                info["mode"] = "fulltext"
            else:
                sem = [r["uid"] for r in conn.execute(
                    f"""SELECT r.uid FROM resolutions r JOIN meetings m ON m.id = r.meeting_id
                        WHERE {where} AND r.embedding IS NOT NULL
                        ORDER BY r.embedding <=> %s::vector LIMIT %s""",
                    params + [vec, pool_size])]
        scores: dict[str, Hit] = {}
        for rank, uid in enumerate(ft, 1):
            h = scores.setdefault(uid, Hit(uid, 0))
            h.score += 1 / (RRF_K + rank)
            h.fulltext_rank = rank
        for rank, uid in enumerate(sem, 1):
            h = scores.setdefault(uid, Hit(uid, 0))
            h.score += 1 / (RRF_K + rank)
            h.semantic_rank = rank
        ranked = sorted(scores.values(), key=lambda h: -h.score)
        info["total"] = len(ranked)
        page = ranked[offset:offset + limit]
        if page:
            rows = {r["uid"]: r for r in conn.execute(
                f"SELECT {COLUMNS} FROM resolutions r WHERE r.uid = ANY(%s)", ([h.uid for h in page],))}
            for h in page:
                h.row = rows[h.uid]
        return page, info
