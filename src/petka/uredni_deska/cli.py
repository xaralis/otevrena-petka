"""Commands of the úřední deska section (`petka deska-…`)."""

import json
import logging
import sys

from ..section import Command

log = logging.getLogger(__name__)


def update(a=None) -> int:
    from . import jobs
    report = jobs.update()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report["failures"] else 0


def load(a=None) -> int:
    from .. import db
    from . import digest
    digest.seed()
    db.migrate()
    with db.connect() as conn:
        with conn.transaction():
            n = digest.load(conn)
    print(json.dumps({"cards": n}))
    return 0


def receive(a) -> int:
    """Tar on stdin from scripts/deska-sync.sh."""
    from . import digest
    print(json.dumps(digest.receive(sys.stdin.buffer)))
    return load()


def _cards(fn_name: str, all_when_empty: bool = True):
    def run(a) -> int:
        from . import digest
        report = getattr(digest, fn_name)(ids=a.ids or None) if all_when_empty else getattr(digest, fn_name)(a.ids)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 1 if any(isinstance(r, dict) and r.get("error") for r in report) else 0
    return run


def bootstrap() -> None:
    """Best effort: a fresh deploy should show current notices, but must not fail on the boards."""
    try:
        update()
        load()
    except Exception:
        log.exception("bootstrap: úřední deska not refreshed")


def _ids(p):
    p.add_argument("ids", nargs="*", metavar="ID")


COMMANDS = [
    Command("deska-update", "download the úřední deska boards and update the notices (idempotent)", update),
    Command("deska-auto", "write, score and publish cards for new MO V notices; poor ones wait for a person",
            _cards("auto"), _ids),
    Command("deska-score", "score published cards (all or the given ids), nothing else changes",
            _cards("rescore"), _ids),
    Command("deska-improve", "rewrite published cards that aren't green; a green rewrite replaces the card",
            _cards("improve"), _ids),
    Command("deska-drafts", "propose plain-language cards for posted MO V notices without one (or the given ids)",
            _cards("drafts"), _ids),
    Command("deska-publish", "approve drafts (move to data/uredni_deska/digests, then commit + sync)",
            _cards("publish", all_when_empty=False), _ids),
    Command("deska-reject", "reject drafts (kept so they aren't proposed again)",
            _cards("reject", all_when_empty=False), _ids),
    Command("deska-load", "load card directories into the database (after seed / sync)", load),
    Command("deska-receive", "replace the cards with a tar from stdin, then load (scripts/deska-sync.sh)", receive),
]
