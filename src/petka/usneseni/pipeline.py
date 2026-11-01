"""Steps from the published PDF to stored parse/enrich results, and the agent workflow.

`fetch` indexes and downloads; `process` runs parse + enrich through `llm` (API or CLI);
`agent_prepare_*` / `agent_accept_*` let a Claude Code subagent do the LLM part by hand:
it reads the prepared prompt files, writes JSON into work/<id>/, and `accept` validates it
exactly like `process` would before storing it.
"""

import datetime as dt
import json
import logging
import subprocess
import tempfile
from pathlib import Path

from . import build as builder
from . import enrich as enricher
from . import parse as parser
from . import scrape, store
from .parse import number_lines

log = logging.getLogger(__name__)
WORK = store.ROOT / "work" / "usneseni"


# --- fetch -------------------------------------------------------------------------------

def pdf_text(pdf: bytes) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "doc.pdf"
        p.write_bytes(pdf)
        return subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True,
                              text=True, check=True).stdout


def fetch(only: str | None = None, force: bool = False) -> list[str]:
    """Index pardubice.eu, download new/changed PDFs, extract text. Returns changed ids."""
    known = {d["url"]: d for d in store.sources()}
    changed = []
    with scrape.client() as http:
        docs = scrape.index(http)
        out = []
        for d in docs:
            rec = {"id": d.meeting_id, "body": d.body, "year": d.year, "url": d.url,
                   "title": d.title, "number": d.number, "kind": d.kind,
                   "date": d.date.isoformat() if d.date else None,
                   "is_attachment": d.is_attachment}
            old = known.get(d.url, {})
            for k in ("sha256", "fetched_at", "needs_transcription"):
                if k in old:
                    rec[k] = old[k]
            if rec["is_attachment"] or rec["id"] is None:
                rec["id"] = rec["id"] or None
                out.append(rec)
                continue
            if only and rec["id"] != only:
                out.append(rec)
                continue
            pdf_path = store.DATA / "pdf" / f"{rec['id']}.pdf"
            # also fills in archive copies missing on a fresh volume (no re-extraction then)
            if force or "sha256" not in rec or not store.text_path(rec["id"]).exists() \
                    or not pdf_path.exists():
                pdf, sha = scrape.download(http, d.url)
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(pdf)
                if sha != rec.get("sha256") or not store.text_path(rec["id"]).exists():
                    txt = pdf_text(pdf)
                    rec["needs_transcription"] = len("".join(txt.split())) < 300
                    if not rec["needs_transcription"]:
                        store._write(store.text_path(rec["id"]), txt)
                    rec["sha256"] = sha
                    rec["fetched_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
                    changed.append(rec["id"])
                    log.info("fetched %s", rec["id"])
            out.append(rec)
    if not docs:
        raise RuntimeError("empty index")
    store.save_sources(out)
    return changed


def source(mid: str) -> dict:
    for d in store.sources():
        if d["id"] == mid:
            return d
    raise KeyError(mid)


def meeting_ids() -> list[str]:
    return sorted({d["id"] for d in store.sources() if d["id"] and not d["is_attachment"]})


# --- build from stored results -------------------------------------------------------------

def meeting(mid: str) -> builder.Meeting | None:
    p = store.extracted(mid, "parse")
    if not p:
        return None
    ov = store.override(mid)
    m = builder.build(source(mid), store.text(mid), p["result"],
                      accepted_issues=frozenset(ov.get("accept", [])))
    if m.id != mid:
        m.issues.append(builder.Issue("error", "id-mismatch", f"built {m.id} from {mid}"))
    return m


# --- automatic processing (API or claude -p) ------------------------------------------------

def process(mid: str, via: str) -> builder.Meeting:
    src = source(mid)
    if src.get("needs_transcription") and not store.text_path(mid).exists():
        from . import llm
        store._write(store.text_path(mid), llm.transcribe_pdf(store.DATA / "pdf" / f"{mid}.pdf"))
    if not store.extracted(mid, "parse"):
        store.save_extracted(mid, "parse", parser.PROMPT_VERSION,
                             parser.parse(store.text(mid)), via)
    m = meeting(mid)
    if not store.extracted(mid, "enrich"):
        lines, _ = number_lines(store.text(mid))
        result = enricher.enrich(m, lines)
        problems = enricher.check(m, result)
        if problems:
            raise RuntimeError(f"{mid} enrich: {problems}")
        store.save_extracted(mid, "enrich", enricher.PROMPT_VERSION, result, via)
    return m


# --- subagent workflow --------------------------------------------------------------------

def agent_prepare_parse(mid: str) -> Path:
    w = WORK / mid
    w.mkdir(parents=True, exist_ok=True)
    _, numbered = number_lines(store.text(mid))
    (w / "numbered.txt").write_text(numbered + "\n")
    (w / "parse-system.md").write_text(parser.SYSTEM)
    (w / "parse-schema.json").write_text(json.dumps(parser.SCHEMA, ensure_ascii=False, indent=1))
    return w


def agent_accept_parse(mid: str) -> tuple[bool, str]:
    w = WORK / mid
    result = json.loads((w / "parse.json").read_text())
    errs = validate_schema(result, parser.SCHEMA)
    if errs:
        return False, "schema errors:\n" + "\n".join(errs[:30])
    ov = store.override(mid)
    m = builder.build(source(mid), store.text(mid), result,
                      accepted_issues=frozenset(ov.get("accept", [])))
    report = summarize(m)
    if m.status != "ok":
        return False, report
    store.save_extracted(mid, "parse", parser.PROMPT_VERSION, result, "agent")
    return True, report


def agent_prepare_enrich(mid: str) -> Path:
    m = meeting(mid)
    if m is None:
        raise RuntimeError("accept the parse first")
    w = WORK / mid
    lines, _ = number_lines(store.text(mid))
    (w / "enrich-system.md").write_text(enricher.system())
    (w / "enrich-schema.json").write_text(json.dumps(enricher.SCHEMA, ensure_ascii=False, indent=1))
    (w / "enrich-input.txt").write_text(enricher.payload(m, lines))
    return w


def agent_accept_enrich(mid: str) -> tuple[bool, str]:
    m = meeting(mid)
    result = json.loads((WORK / mid / "enrich.json").read_text())
    errs = validate_schema(result, enricher.SCHEMA) + enricher.check(m, result)
    if errs:
        return False, "\n".join(errs[:30])
    store.save_extracted(mid, "enrich", enricher.PROMPT_VERSION, result, "agent")
    return True, f"{len(result['resolutions'])} resolutions enriched"


def summarize(m: builder.Meeting) -> str:
    out = [f"{m.id}: {m.status}; {len(m.resolutions)} resolutions, {len(m.votes)} votes"]
    st = {}
    for v in m.votes:
        st[v["ballots_status"]] = st.get(v["ballots_status"], 0) + 1
    out.append(f"ballots: {st}")
    rs = {}
    for r in m.resolutions:
        rs[r["status"]] = rs.get(r["status"], 0) + 1
    out.append(f"resolution status: {rs}")
    for i in m.issues:
        out.append(f"  [{i.severity}] {i.code} (line {i.line}): {i.message}")
    if m.model_notes:
        out.append("model notes: " + " | ".join(m.model_notes))
    return "\n".join(out)


def validate_schema(obj, schema: dict) -> list[str]:
    import jsonschema

    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in v.iter_errors(obj)]
