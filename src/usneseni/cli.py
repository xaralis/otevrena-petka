"""Command line: `usneseni <command>`."""

import argparse
import logging
import sys

from . import pipeline, store


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="usneseni")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="index pardubice.eu, download new PDFs, extract text")
    p.add_argument("--only")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("process", help="parse + enrich missing meetings through the LLM backend")
    p.add_argument("ids", nargs="*")

    p = sub.add_parser("check", help="build a meeting from stored results and print issues")
    p.add_argument("ids", nargs="*")

    p = sub.add_parser("status", help="which meetings have text / parse / enrich")

    for stage in ("parse", "enrich"):
        p = sub.add_parser(f"agent-prepare-{stage}", help=f"write prompt files for a subagent ({stage})")
        p.add_argument("id")
        p = sub.add_parser(f"agent-accept-{stage}", help=f"validate and store work/<id>/{stage}.json")
        p.add_argument("id")

    p = sub.add_parser("load", help="rebuild the database from the data directory")
    p.add_argument("ids", nargs="*")
    sub.add_parser("embed", help="compute missing embeddings")
    sub.add_parser("export", help="write open-data files")
    sub.add_parser("update", help="cron: fetch, process, load, embed, export")
    p = sub.add_parser("serve", help="run the web app, API and MCP server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)

    a = ap.parse_args()

    if a.cmd == "fetch":
        print("\n".join(pipeline.fetch(only=a.only, force=a.force)))
    elif a.cmd == "status":
        for mid in pipeline.meeting_ids():
            src = pipeline.source(mid)
            t = store.text_path(mid).exists()
            print(f"{mid:24} text={'y' if t else ('SCAN' if src.get('needs_transcription') else 'n')}"
                  f" parse={'y' if t and store.extracted(mid, 'parse') else 'n'}"
                  f" enrich={'y' if t and store.extracted(mid, 'enrich') else 'n'}")
    elif a.cmd == "check":
        bad = 0
        for mid in a.ids or pipeline.meeting_ids():
            m = pipeline.meeting(mid)
            if m is None:
                print(f"{mid}: not parsed")
                continue
            bad += m.status != "ok"
            print(pipeline.summarize(m))
        sys.exit(1 if bad else 0)
    elif a.cmd == "process":
        from . import llm
        for mid in a.ids or pipeline.meeting_ids():
            if store.extracted(mid, "parse") and store.extracted(mid, "enrich"):
                continue
            m = pipeline.process(mid, via=llm.BACKEND)
            print(pipeline.summarize(m))
    elif a.cmd.startswith("agent-prepare-"):
        fn = getattr(pipeline, a.cmd.replace("-", "_"))
        print(fn(a.id))
    elif a.cmd.startswith("agent-accept-"):
        ok, report = getattr(pipeline, a.cmd.replace("-", "_"))(a.id)
        print(("ACCEPTED\n" if ok else "REJECTED\n") + report)
        sys.exit(0 if ok else 1)
    elif a.cmd in ("load", "embed", "export", "update"):
        from . import jobs
        getattr(jobs, a.cmd)(*([a.ids] if a.cmd == "load" else []))
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("usneseni.web.app:app", host=a.host, port=a.port, proxy_headers=True,
                    forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
