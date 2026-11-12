"""Commands of the usnesení section (`petka <command>`, also `usneseni <command>`)."""

import sys

from ..section import Command
from . import pipeline, store


def _fetch_args(p):
    p.add_argument("--only")
    p.add_argument("--force", action="store_true")


def _ids(p):
    p.add_argument("ids", nargs="*")


def _id(p):
    p.add_argument("id")


def fetch(a):
    print("\n".join(pipeline.fetch(only=a.only, force=a.force)))


def status(a):
    for mid in pipeline.meeting_ids():
        src = pipeline.source(mid)
        t = store.text_path(mid).exists()
        print(f"{mid:24} text={'y' if t else ('SCAN' if src.get('needs_transcription') else 'n')}"
              f" parse={'y' if t and store.extracted(mid, 'parse') else 'n'}"
              f" enrich={'y' if t and store.extracted(mid, 'enrich') else 'n'}")


def check(a):
    bad = 0
    for mid in a.ids or pipeline.meeting_ids():
        m = pipeline.meeting(mid)
        if m is None:
            print(f"{mid}: not parsed")
            continue
        bad += m.status != "ok"
        print(pipeline.summarize(m))
    sys.exit(1 if bad else 0)


def process(a):
    from .. import llm
    for mid in a.ids or pipeline.meeting_ids():
        if store.extracted(mid, "parse") and store.extracted(mid, "enrich"):
            continue
        m = pipeline.process(mid, via=llm.default().backend)
        print(pipeline.summarize(m))


def _agent_prepare(stage):
    def run(a):
        print(getattr(pipeline, f"agent_prepare_{stage}")(a.id))
    return run


def _agent_accept(stage):
    def run(a):
        ok, report = getattr(pipeline, f"agent_accept_{stage}")(a.id)
        print(("ACCEPTED\n" if ok else "REJECTED\n") + report)
        sys.exit(0 if ok else 1)
    return run


def _job(name):
    def run(a):
        from . import jobs
        getattr(jobs, name)(*([a.ids] if name == "load" else []))
    return run


COMMANDS = [
    Command("fetch", "index pardubice.eu, download new PDFs, extract text", fetch, _fetch_args),
    Command("process", "parse + enrich missing meetings through the LLM backend", process, _ids),
    Command("check", "build a meeting from stored results and print issues", check, _ids),
    Command("status", "which meetings have text / parse / enrich", status),
    *[c for stage in ("parse", "enrich") for c in (
        Command(f"agent-prepare-{stage}", f"write prompt files for a subagent ({stage})", _agent_prepare(stage), _id),
        Command(f"agent-accept-{stage}", f"validate and store work/<id>/{stage}.json", _agent_accept(stage), _id))],
    Command("load", "rebuild the database from the data directory", _job("load"), _ids),
    Command("embed", "compute missing embeddings", _job("embed")),
    Command("export", "write open-data files", _job("export")),
    Command("update", "cron: fetch, process, load, embed, export", _job("update")),
]
