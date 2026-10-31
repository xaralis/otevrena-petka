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


STOPWORDS = set("""a i o u v k s z ve ke se ze na do od po pro pri za nad pod mezi bez
    je jsou byl byla bylo by kdy kde jak co kdo ktery ktera ktere ten ta to tom tech
    jeho jejich nebo ale ani take tak jen uz jiz rada rady zastupitelstvo zastupitelstva
    usneseni resil resila resilo resili schvalil schvalila zmo rmo mo""".split())


def _stem(w: str) -> str:
    """Crude Czech stemming for prefix search: drop the inflected ending.

    'protihlukove' -> 'protihlukov' matches 'protihlukových'; 'parkovani' -> 'parkova'
    matches 'parkování' and 'parkovací'. Numbers and short words stay whole.
    """
    if w.isdigit() or len(w) <= 5:
        return w
    return w[:max(5, len(w) - 2)]


def tsquery(q: str, op: str = "&") -> str | None:
    words = [w for w in re.findall(r"[0-9a-z]+", fold(q)) if len(w) > 1 and w not in STOPWORDS]
    if not words:
        return None
    return f" {op} ".join(f"{_stem(w)}:*" for w in dict.fromkeys(words))


# `|| ''` detoasts the whole value first: Postgres 16 slices compressed TOAST text by bytes
# for left()/substr() and fails when the cut lands inside a multibyte character.
COLUMNS = """r.uid, r.number, r.body, r.date, r.meeting_id, r.status, r.title, r.summary,
             r.agenda_title, r.topics, r.kind, r.keywords, left(r.text || '', 400) AS text_start,
             (SELECT string_agg(x.type || ':' || x.scope || ':' || s.number, ';')
                FROM resolution_relations x JOIN resolutions s ON s.uid = x.source_uid
               WHERE x.target_uid = r.uid AND x.effective) AS revoked_by,
             (SELECT json_build_object('pro', v.n_pro, 'proti', v.n_proti, 'zdrzel', v.n_zdrzel,
                'nehl', coalesce(v.n_nehlasoval, 0), 'quorum', v.quorum, 'present', v.n_present,
                'parts', (SELECT count(*) FROM votes p WHERE p.resolution_uid = r.uid AND p.part IS NOT NULL),
                'whole', v.part IS NULL,
                'parts_ok', (SELECT count(*) FROM votes p WHERE p.resolution_uid = r.uid AND p.part IS NOT NULL AND p.outcome = 'prijato'))
              FROM votes v WHERE v.resolution_uid = r.uid
              ORDER BY (v.part IS NULL) DESC, v.seq DESC LIMIT 1) AS mainvote"""


def search(q: str, mode: str = "hybrid", filters: Filters | None = None, limit: int = 20,
           offset: int = 0, newest_first: bool = False) -> tuple[list[Hit], dict]:
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

        vec = None
        if mode in ("hybrid", "semantic"):
            vec = embed.embed_query(q)
            if vec is None:  # embedder off or down: answer from full text instead of failing
                mode = info["mode"] = "fulltext"
        ft: list[str] = []
        if mode in ("hybrid", "fulltext"):
            # all words first; a natural-language question rarely matches all, so fall
            # back to any word, ranked by how many and how important the matches are
            for op in ("&", "|"):
                tq = tsquery(q, op)
                if not tq:
                    break
                ft = [r["uid"] for r in conn.execute(
                    f"""SELECT r.uid FROM resolutions r JOIN meetings m ON m.id = r.meeting_id
                        WHERE {where} AND r.tsv @@ to_tsquery('simple', %s)
                        ORDER BY ts_rank_cd(r.tsv, to_tsquery('simple', %s), 32) DESC, r.date DESC
                        LIMIT %s""", params + [tq, tq, pool_size])]
                if len(ft) >= 5:
                    break
        sem: list[str] = []
        if vec is not None:
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
        if newest_first and ranked:
            dates = {r["uid"]: (r["date"], r["seq"]) for r in conn.execute(
                "SELECT uid, date, seq FROM resolutions WHERE uid = ANY(%s)", ([h.uid for h in ranked],))}
            ranked.sort(key=lambda h: (dates[h.uid][0], -dates[h.uid][1]), reverse=True)
        info["total"] = len(ranked)
        page = ranked[offset:offset + limit]
        if page:
            rows = {r["uid"]: r for r in conn.execute(
                f"SELECT {COLUMNS} FROM resolutions r WHERE r.uid = ANY(%s)", ([h.uid for h in page],))}
            for h in page:
                h.row = rows[h.uid]
        return page, info
