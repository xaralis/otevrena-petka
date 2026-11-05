"""Batch jobs: load the database from the data directory, embed, export open data, update."""

import array
import base64
import csv
import io
import json
import logging
import os
import sys

from .. import db
from . import embed as embedder, members as reg, opendata_schema, pipeline, relations, store
from .text import fold

log = logging.getLogger(__name__)
OPENDATA = store.DATA / "opendata"


# --- load ---------------------------------------------------------------------------------

def _members(conn) -> None:
    registry, terms = reg.registry()
    for m in registry.values():
        conn.execute(
            """INSERT INTO members (id, name, first_name, last_name, name_fold)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name""",
            (m.id, m.full_name, m.first, m.last, fold(m.name)))
    for t in terms:
        for mid, lst in t.lists.items():
            conn.execute(
                """INSERT INTO memberships (member_id, term, list, elected) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (member_id, term) DO UPDATE SET list = EXCLUDED.list,
                   elected = EXCLUDED.elected""", (mid, t.id, lst, mid in t.elected))


def _in_rada(conn) -> None:
    """Who sat on the board in a term, from the attendance of its meetings – recomputed, never only
    switched on, so a meeting moved to another term takes its members with it."""
    conn.execute("""UPDATE memberships s SET in_rada = EXISTS (
                      SELECT 1 FROM meetings mt WHERE mt.body = 'rmo' AND mt.term = s.term
                        AND s.member_id = ANY(mt.present || mt.excused || mt.absent))""")


def _tsv_sql() -> str:
    return """
      setweight(to_tsvector('simple', f_unaccent(lower(coalesce(number,'') || ' ' || coalesce(title,'')))), 'A') ||
      setweight(to_tsvector('simple', f_unaccent(lower(array_to_string(keywords || places || organizations || parcels, ' ')))), 'B') ||
      setweight(to_tsvector('simple', f_unaccent(lower(coalesce(summary,'') || ' ' || coalesce(agenda_title,'')))), 'C') ||
      setweight(to_tsvector('simple', f_unaccent(lower(text))), 'D')"""


def load_meeting(conn, mid: str) -> str:
    m = pipeline.meeting(mid)
    if m is None:
        return "not-parsed"
    enr = store.extracted(mid, "enrich")
    by_number = {r["number"]: r for r in (enr["result"]["resolutions"] if enr else [])}
    disc = {r["no"]: r["discussion"] for r in (enr["result"]["agenda"] if enr else [])}
    parsed_via = store.extracted(mid, "parse")["via"]
    with conn.transaction():
        conn.execute("DELETE FROM meetings WHERE id = %s", (mid,))
        for pid, p in m.members.items():
            if pid.startswith("x-"):
                conn.execute("""INSERT INTO members (id, name, first_name, last_name, name_fold)
                                VALUES (%s, %s, '', %s, %s) ON CONFLICT DO NOTHING""",
                             (pid, p["name"], p["name"], fold(p["name"])))
        conn.execute(
            """INSERT INTO meetings (id, body, term, number, kind, date, place, source_url,
                 source_title, status, issues, model_notes, present, excused, absent, parsed_via)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (m.id, m.body, m.term, m.number, m.kind, m.date, m.place, m.source_url,
             m.source_title, m.status, json.dumps([i.__dict__ for i in m.issues], ensure_ascii=False),
             json.dumps(m.model_notes, ensure_ascii=False), m.attendance["present"],
             m.attendance["excused"], m.attendance["absent"], parsed_via))
        for seq, a in enumerate(m.agenda_items, 1):
            conn.execute("""INSERT INTO agenda_items (meeting_id, seq, no, title, speakers, discussion)
                            VALUES (%s,%s,%s,%s,%s,%s)""",
                         (m.id, seq, a["no"], a["title"], a["speakers"], disc.get(a["no"])))
        for seq, r in enumerate(m.resolutions, 1):
            e = by_number.get(r["number"], {})
            conn.execute(
                f"""INSERT INTO resolutions (uid, number, meeting_id, body, date, seq, agenda_no,
                      agenda_title, text, responsible, deadline, status, verbs, title, summary,
                      keywords, topics, kind, places, parcels, organizations, amounts)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (r["uid"], r["number"], m.id, m.body, m.date, seq, r["agenda_no"], r["agenda_title"],
                 r["text"], r["responsible"], r["deadline"], r["status"], r["verbs"],
                 e.get("title"), e.get("summary"), e.get("keywords", []), e.get("topics", []),
                 e.get("kind"), e.get("places", []), e.get("parcels", []),
                 e.get("organizations", []), e.get("amounts", [])))
        conn.execute(f"UPDATE resolutions SET tsv = {_tsv_sql()} WHERE meeting_id = %s", (m.id,))
        uids = {r["number"]: r["uid"] for r in m.resolutions}
        for v in m.votes:
            vid = f"{m.id}-{v['seq']}"
            conn.execute(
                """INSERT INTO votes (id, meeting_id, seq, resolution_uid, part, subject, proposer,
                     motion_text, procedural, n_pro, n_proti, n_zdrzel, n_nehlasoval, n_present,
                     quorum, passed, outcome, stated_outcome, ballots_status, raw)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (vid, m.id, v["seq"], uids.get(v["resolution"]), v["part"], v["subject"],
                 v["proposer"], v["motion_text"], v["procedural"], v["pro"], v["proti"],
                 v["zdrzel"], v["nehlasoval"], v["present"], v["quorum"], v["passed"],
                 v["outcome"], v["stated_outcome"], v["ballots_status"], v["raw"]))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO ballots (vote_id, member_id, choice, provenance) VALUES (%s,%s,%s,%s)",
                    [(vid, b["member"], b["choice"], b["provenance"]) for b in v["ballots"]])
        # embeddings survive reloads through the cache
        conn.execute("""UPDATE resolutions r SET embedding = c.embedding, embed_hash = c.hash
                        FROM embedding_cache c
                        WHERE r.meeting_id = %s AND c.hash = encode(sha256(convert_to(
                          %s || r.uid || coalesce(r.title,'') || coalesce(r.summary,'') || r.text, 'UTF8')), 'hex')""",
                     (m.id, embedder.MODEL))
    return m.status


def load(ids: list[str] | None = None) -> None:
    db.migrate()
    ids = ids or pipeline.meeting_ids()
    stats: dict[str, int] = {}
    with db.connect() as conn:
        with conn.transaction():
            _members(conn)
            n_emb = import_embeddings(conn)  # load_meeting picks them up from the cache
        log.info("embeddings file: %d vectors", n_emb)
        if not ids or ids == pipeline.meeting_ids():
            conn.execute("DELETE FROM meetings WHERE NOT (id = ANY(%s))", (pipeline.meeting_ids(),))
        for mid in ids:
            try:
                st = load_meeting(conn, mid)
            except Exception:
                log.exception("load %s failed", mid)
                st = "failed"
            stats[st] = stats.get(st, 0) + 1
            if st not in ("ok", "not-parsed"):
                log.warning("%s: %s", mid, st)
        with conn.transaction():
            _in_rada(conn)
            n = _relations(conn)
            n_places = _places(conn)
        conn.commit()
    log.info("load: %s, %d resolution links, %d places", stats, n, n_places)


def _coords(g: dict):
    c = g["coordinates"]
    depth = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2,
             "Polygon": 2, "MultiPolygon": 3}[g["type"]]
    stack = [(c, depth)]
    while stack:
        x, d = stack.pop()
        if d == 0:
            yield x
        else:
            stack.extend((y, d - 1) for y in x)


def _places(conn) -> int:
    """Replace resolution_places from geo.json (built by `python -m petka.usneseni.geo`)."""
    f = store.DATA / "geo.json"
    conn.execute("DELETE FROM resolution_places")
    if not f.exists():
        return 0
    known = {r["uid"] for r in conn.execute("SELECT uid FROM resolutions")}
    n = 0
    for uid, feats in json.loads(f.read_text()).items():
        if uid not in known:
            continue
        for ft in feats:
            pts = list(_coords(ft["geometry"]))
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            conn.execute(
                """INSERT INTO resolution_places (uid, kind, label, source_text, geometry, lon, lat, bbox)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (uid, ft["kind"], ft["label"], ft.get("source_text"), json.dumps(ft["geometry"]),
                 sum(xs) / len(xs), sum(ys) / len(ys), [min(xs), min(ys), max(xs), max(ys)]))
            n += 1
    return n


def _relations(conn) -> int:
    """Recompute revoke/amend links across the whole database (targets may be in any meeting)."""
    conn.execute("DELETE FROM resolution_relations")
    rows = conn.execute("SELECT uid, number, body, status, text FROM resolutions").fetchall()
    by_number = {r["number"]: r["uid"] for r in rows}
    n = 0
    for r in rows:
        for link in relations.links(r["text"], r["body"]):
            if link["target"] == r["number"]:
                continue
            conn.execute(
                """INSERT INTO resolution_relations (source_uid, type, target_number, target_uid,
                     scope, detail, effective) VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (r["uid"], link["type"], link["target"], by_number.get(link["target"]),
                 link["scope"], link["detail"], r["status"] in ("prijato", "castecne")))
            n += 1
    return n


# --- embeddings ---------------------------------------------------------------------------
#
# Computing them is the only expensive part of a rebuild (≈17 min on CPU), so they are also
# kept in the data directory: data/usneseni/embeddings.jsonl, one line per vector,
# {"hash", "model", "v": base64 float32 little-endian}, keyed by the hash of the embedded
# text. The database imports the file on load; `embed` rewrites it after every run.

EMB_FILE = store.DATA / "embeddings.jsonl"
_EMB_HASH_SQL = ("encode(sha256(convert_to(%s || r.uid || coalesce(r.title,'') || "
                 "coalesce(r.summary,'') || r.text, 'UTF8')), 'hex')")


def _pack(vec) -> str:
    a = array.array("f", vec.to_list() if hasattr(vec, "to_list") else vec)
    if sys.byteorder != "little":
        a.byteswap()
    return base64.b64encode(a.tobytes()).decode()


def _unpack(s: str) -> list[float]:
    a = array.array("f")
    a.frombytes(base64.b64decode(s))
    if sys.byteorder != "little":
        a.byteswap()
    return a.tolist()


def import_embeddings(conn) -> int:
    """Embedding cache from the data directory; returns the number of vectors read."""
    if not EMB_FILE.exists():
        return 0
    rows = [(d["hash"], d["model"], _unpack(d["v"]))
            for d in map(json.loads, filter(str.strip, EMB_FILE.read_text().splitlines()))]
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO embedding_cache (hash, model, embedding) VALUES (%s,%s,%s)
                           ON CONFLICT (hash) DO NOTHING""", rows)
    return len(rows)


def apply_cached_embeddings(conn) -> int:
    """Set embeddings on resolutions whose current text has a cached vector."""
    cur = conn.execute(
        f"""UPDATE resolutions r SET embedding = c.embedding, embed_hash = c.hash
            FROM embedding_cache c
            WHERE c.hash = {_EMB_HASH_SQL} AND r.embed_hash IS DISTINCT FROM c.hash""",
        (embedder.MODEL,))
    return cur.rowcount


def save_embeddings(conn) -> int:
    """Write the vectors of the current resolutions to the data directory (sorted, stable diff)."""
    rows = conn.execute(
        """SELECT DISTINCT c.hash, c.model, c.embedding FROM embedding_cache c
           JOIN resolutions r ON r.embed_hash = c.hash ORDER BY c.hash""").fetchall()
    store._write(EMB_FILE, "".join(
        json.dumps({"hash": r["hash"], "model": r["model"], "v": _pack(r["embedding"])}) + "\n"
        for r in rows))
    return len(rows)


def embed() -> None:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT uid, title, summary, keywords, agenda_title, text, embed_hash,
                 encode(sha256(convert_to(%s || uid || coalesce(title,'') || coalesce(summary,'') || text, 'UTF8')), 'hex') AS h
               FROM resolutions""", (embedder.MODEL,)).fetchall()
        conn.commit()  # end the read transaction: every batch below commits on its own
        todo = [r for r in rows if r["h"] != r["embed_hash"]]
        log.info("embed: %d of %d resolutions", len(todo), len(rows))
        # small batches leave room for live search queries on the same server
        for i in range(0, len(todo), 4):
            batch = todo[i:i + 4]
            vecs = embedder.embed_documents([embedder.document_text(r) for r in batch])
            with conn.transaction():  # a real transaction (no outer one), committed per batch
                for r, vec in zip(batch, vecs):
                    conn.execute("""INSERT INTO embedding_cache (hash, model, embedding) VALUES (%s,%s,%s)
                                    ON CONFLICT (hash) DO NOTHING""", (r["h"], embedder.MODEL, vec))
                    conn.execute("UPDATE resolutions SET embedding = %s, embed_hash = %s WHERE uid = %s",
                                 (vec, r["h"], r["uid"]))
        log.info("embeddings file: %d vectors written", save_embeddings(conn))
        conn.commit()


# --- open data ----------------------------------------------------------------------------

EXPORTS = {
    "meetings": """SELECT id, body, term, number, kind, date, place, status, source_url,
                     array_to_string(present, ';') AS present, array_to_string(excused, ';') AS excused,
                     array_to_string(absent, ';') AS absent
                   FROM meetings ORDER BY date, body""",
    "resolutions": """SELECT uid, number, meeting_id, body, date, agenda_no, agenda_title, status,
                        text, responsible, deadline, array_to_string(verbs, ';') AS verbs,
                        title, summary, array_to_string(keywords, ';') AS keywords,
                        array_to_string(topics, ';') AS topics, kind,
                        array_to_string(places, ';') AS places, array_to_string(parcels, ';') AS parcels,
                        array_to_string(organizations, ';') AS organizations,
                        array_to_string(amounts, ';') AS amounts
                      FROM resolutions ORDER BY date, body, seq""",
    "votes": """SELECT id, meeting_id, seq, resolution_uid, part, subject, proposer, procedural,
                  n_pro, n_proti, n_zdrzel, n_nehlasoval, n_present, quorum, passed, outcome,
                  stated_outcome, ballots_status, raw
                FROM votes ORDER BY meeting_id, seq""",
    "ballots": """SELECT b.vote_id, b.member_id, b.choice, b.provenance
                  FROM ballots b JOIN votes v ON v.id = b.vote_id ORDER BY v.meeting_id, v.seq, b.member_id""",
    "relations": """SELECT x.source_uid, s.number AS source_number, x.type, x.target_number,
                      x.target_uid, x.scope, x.detail, x.effective
                    FROM resolution_relations x JOIN resolutions s ON s.uid = x.source_uid
                    ORDER BY s.date, x.source_uid""",
    "members": """SELECT m.id, m.name, s.term, s.list, s.elected, s.in_rada
                  FROM members m LEFT JOIN memberships s ON s.member_id = m.id
                  WHERE EXISTS (SELECT 1 FROM ballots b WHERE b.member_id = m.id)
                  ORDER BY m.last_name, m.first_name, s.term""",
    "places": """SELECT p.uid, r.number, p.kind, p.label, p.source_text,
                   round(p.lon::numeric, 6) AS lon, round(p.lat::numeric, 6) AS lat, p.geometry::text AS geometry
                 FROM resolution_places p JOIN resolutions r ON r.uid = p.uid
                 ORDER BY r.date, r.seq, p.id""",
}


def export() -> None:
    OPENDATA.mkdir(parents=True, exist_ok=True)
    resources = []
    with db.connect() as conn:
        for name, sql in EXPORTS.items():
            cur = conn.execute(sql)
            cols = [d.name for d in cur.description]
            rows = cur.fetchall()
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(cols)
            for r in rows:
                w.writerow(["" if r[c] is None else str(r[c]).lower() if isinstance(r[c], bool) else r[c]
                            for c in cols])
            store._write(OPENDATA / f"{name}.csv", buf.getvalue())
            store._write(OPENDATA / f"{name}.json", json.dumps(
                [{c: r[c] for c in cols} for r in rows], ensure_ascii=False, default=str) + "\n")
            t = opendata_schema.TABLES[name]
            fields = [fd for fd in t["fields"] if fd["name"] in cols]
            missing = set(cols) - {fd["name"] for fd in fields}
            if missing:
                raise RuntimeError(f"{name}: columns without schema {missing}")
            schema = {"fields": fields, **{k: t[k] for k in ("primaryKey", "foreignKeys") if k in t}}
            resources.append({"name": name, "title": t["title"], "description": t["description"],
                              "path": f"{name}.csv", "format": "csv", "mediatype": "text/csv",
                              "encoding": "utf-8", "schema": schema})
    with db.connect() as conn:  # the same places as one GeoJSON file, for GIS tools
        feats = [{"type": "Feature", "geometry": r["geometry"],
                  "properties": {k: r[k] for k in ("uid", "number", "kind", "label", "source_text")}}
                 for r in conn.execute(
                     """SELECT p.uid, r.number, p.kind, p.label, p.source_text, p.geometry
                        FROM resolution_places p JOIN resolutions r ON r.uid = p.uid ORDER BY r.date, r.seq, p.id""")]
    store._write(OPENDATA / "places.geojson", json.dumps(
        {"type": "FeatureCollection", "features": feats}, ensure_ascii=False) + "\n")
    store._write(OPENDATA / "datapackage.json", json.dumps({
        "name": "usneseni-mo-pardubice-v",
        "title": "Usnesení a hlasování zastupitelstva a rady městského obvodu Pardubice V",
        "version": "1.0",
        "homepage": "https://otevrenapetka.cz/data/usneseni",
        "licenses": [{"name": "CC-BY-4.0", "path": "https://creativecommons.org/licenses/by/4.0/"}],
        "sources": [{"title": "Statutární město Pardubice – zápisy z jednání ZMO a RMO Pardubice V",
                     "path": "https://pardubice.eu/obvod5"}],
        "description": "Usnesení, hlasování a hlasy zastupitelů vytěžené z PDF zápisů. Specifikace: "
                       "https://github.com/xaralis/otevrena-petka/blob/main/docs/otevrena-data.md",
        "resources": resources,
    }, ensure_ascii=False, indent=1) + "\n")
    log.info("export: %s", [r["name"] for r in resources])


# --- bootstrap (init container) -----------------------------------------------------------

def bootstrap() -> None:
    """Seed the volume from the image and load what changed; quick when nothing did."""
    changed = store.seed()
    db.migrate()
    with db.connect() as conn:
        empty = conn.execute("SELECT count(*) AS n FROM meetings").fetchone()["n"] == 0
    if empty:
        load(None)
    elif changed & set(pipeline.meeting_ids()):
        load(sorted(changed & set(pipeline.meeting_ids())))  # also refreshes links and places
    elif "geo" in changed:  # only the places changed: no need to reload meetings
        with db.connect() as conn:
            with conn.transaction():
                log.info("bootstrap: %d places", _places(conn))
    with db.connect() as conn:  # vectors from the image (git) or the volume, no recompute
        import_embeddings(conn)
        n = apply_cached_embeddings(conn)
        conn.commit()
    if n:
        log.info("bootstrap: %d embeddings restored from the data directory", n)
    if empty or changed or not (OPENDATA / "datapackage.json").exists():
        export()
    log.info("bootstrap: %s", "full load" if empty else f"{len(changed)} changed")


# --- update (cron) ------------------------------------------------------------------------

def update() -> None:
    from . import llm

    store.seed()
    failures = []
    changed = pipeline.fetch()
    todo = [mid for mid in pipeline.meeting_ids()
            if store.text_path(mid).exists() or pipeline.source(mid).get("needs_transcription")]
    todo = [mid for mid in todo if not (store.text_path(mid).exists()
                                        and store.extracted(mid, "parse") and store.extracted(mid, "enrich"))]
    attempts = _attempts()
    for mid in todo:
        key = f"{mid}:{store.text_sha(mid) if store.text_path(mid).exists() else 'scan'}"
        if attempts.get(key, 0) >= MAX_ATTEMPTS:
            failures.append(f"{mid}: gave up after {MAX_ATTEMPTS} attempts, needs a person")
            continue
        try:
            m = pipeline.process(mid, via=llm.BACKEND)
            log.info(pipeline.summarize(m))
        except Exception as e:
            log.exception("process %s failed", mid)
            failures.append(f"{mid}: {e}")
            attempts[key] = attempts.get(key, 0) + 1
            store._write(store.DATA / "attempts.json", json.dumps(attempts, indent=1))
    try:  # places → geometry; only new strings go to ČÚZK, the rest comes from geo_cache.json
        from . import geo
        geo.build()
    except Exception as e:
        log.exception("geo build failed")
        failures.append(f"geo: {e}")
    load(None)
    embed()
    export()
    with db.connect() as conn:
        review = [r["id"] for r in conn.execute("SELECT id FROM meetings WHERE status <> 'ok'")]
    if review:
        failures.append(f"needs review: {review}")
    _report(changed, todo, failures)
    if failures:
        sys.exit(1)


MAX_ATTEMPTS = 2  # paid API calls per meeting and text version before a person has to look


def _attempts() -> dict:
    p = store.DATA / "attempts.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _report(changed, processed, failures) -> None:
    msg = f"usneseni update: {len(changed)} new/changed PDFs, {len(processed)} processed"
    if failures:
        msg += "; " + "; ".join(failures)
    log.info(msg)
    if failures and os.environ.get("SENTRY_DSN"):
        import sentry_sdk
        sentry_sdk.init(os.environ["SENTRY_DSN"])
        sentry_sdk.capture_message(msg, level="error")
        sentry_sdk.flush()
    push = os.environ.get("KUMA_PUSH_URL")
    if push and not failures:
        import httpx
        httpx.get(push, params={"status": "up", "msg": "OK"}, timeout=10)

