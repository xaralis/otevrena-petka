"""Commands of the podněty section (`petka podnety-…`)."""

import datetime as dt
import json
import sys

from ..section import Command


def _args(p) -> None:
    from .. import obvody
    p.add_argument("--obvod", action="append", metavar="|".join(obvody.BY_ID),
                   help="only this obvod (repeatable; default: all)")
    p.add_argument("--od", type=dt.date.fromisoformat, metavar="RRRR-MM-DD",
                   help="download from this day instead of the usual window (backfill)")


def update(a) -> int:
    from .. import obvody
    from . import jobs
    if any(o not in obvody.BY_ID for o in a.obvod or []):
        print(f"unknown obvod, use one of: {', '.join(obvody.BY_ID)}", file=sys.stderr)
        return 2
    report = jobs.update(a.obvod, a.od)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if report["failures"] else 0


COMMANDS = [
    Command("podnety-update",
            "mirror the obvody's citizen reports from Dej Tip (two years on the first run, then the "
            "last 120 days for status changes; idempotent)", update, _args),
]
