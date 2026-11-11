"""Command line of the portal (`usneseni <command>`, also installed as `petka`).

Úřední deska commands are handled here; everything else goes to the usnesení CLI
(petka.usneseni.cli). `bootstrap` (the web pod's init container) also refreshes the boards,
best effort, so a fresh deploy shows current notices.
"""

import json
import logging
import sys

from .usneseni import cli as usneseni_cli

DESKA_HELP = """  deska-update        download the úřední deska boards and update the notices (idempotent)
  deska-auto [ID…]    write, score and publish cards for new MO V notices; poor ones wait for a person
  deska-score [ID…]   score published cards (all or the given ids), nothing else changes
  deska-improve [ID…] rewrite published cards that aren't green; a green rewrite replaces the card
  deska-drafts [ID…]  propose plain-language cards for posted MO V notices without one (or the given ids)
  deska-publish ID…   approve drafts (move to data/uredni_deska/digests, then commit + sync)
  deska-reject ID…    reject drafts (kept so they aren't proposed again)
  deska-load          load card directories into the database (after seed / sync)
  deska-receive       replace the cards with a tar from stdin, then load (scripts/deska-sync.sh)"""

ROZPOCET_HELP = """  rozpocet-update [--unit mo5|mmp|all] [ROK…]
                      download the city's rozklikávací rozpočet (GORDIC) for the unit's due
                      years (or the given ones) and replace changed years (idempotent)"""


def rozpocet_update(args: list[str]) -> int:
    from .rozpocet import jobs, source
    units = ["mo5"]
    if args[:1] == ["--unit"] and len(args) > 1:
        units = list(source.UNITS) if args[1] == "all" else [args[1]]
        args = args[2:]
    if any(u not in source.UNITS for u in units):
        print(f"unknown unit, use one of: {', '.join(source.UNITS)}, all", file=sys.stderr)
        return 2
    report = jobs.update(units, [int(a) for a in args] or None)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if report["failures"] else 0


def deska_update() -> int:
    from .uredni_deska import jobs
    report = jobs.update()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report["failures"] else 0


def deska_load() -> int:
    from . import db
    from .uredni_deska import digest
    digest.seed()
    db.migrate()
    with db.connect() as conn:
        with conn.transaction():
            n = digest.load(conn)
    print(json.dumps({"cards": n}))
    return 0


def deska_cards(cmd: str, args: list[str]) -> int:
    from .uredni_deska import digest
    if cmd == "deska-auto":
        report = digest.auto(ids=args or None)
    elif cmd == "deska-score":
        report = digest.rescore(ids=args or None)
    elif cmd == "deska-improve":
        report = digest.improve(ids=args or None)
    elif cmd == "deska-drafts":
        report = digest.drafts(ids=args or None)
    elif cmd == "deska-publish":
        report = digest.publish(args)
    else:
        report = digest.reject(args)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if any(isinstance(r, dict) and r.get("error") for r in report) else 0


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd.startswith("deska-"):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        if cmd == "deska-update":
            sys.exit(deska_update())
        if cmd == "deska-load":
            sys.exit(deska_load())
        if cmd == "deska-receive":            # tar on stdin from scripts/deska-sync.sh
            from .uredni_deska import digest
            print(json.dumps(digest.receive(sys.stdin.buffer)))
            sys.exit(deska_load())
        if cmd in ("deska-auto", "deska-score", "deska-improve", "deska-drafts", "deska-publish", "deska-reject"):
            sys.exit(deska_cards(cmd, sys.argv[2:]))
    if cmd == "rozpocet-update":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        sys.exit(rozpocet_update(sys.argv[2:]))
    if cmd in ("-h", "--help", ""):
        print("section úřední deska:\n" + DESKA_HELP + "\n")
        print("section rozpočet:\n" + ROZPOCET_HELP + "\n")
    usneseni_cli.main()
    if cmd == "bootstrap":
        try:
            deska_update()
            deska_load()
        except Exception:
            logging.getLogger(__name__).exception("bootstrap: úřední deska not refreshed")


if __name__ == "__main__":
    main()
