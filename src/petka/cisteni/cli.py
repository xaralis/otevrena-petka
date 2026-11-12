"""Commands of the čištění section (`petka cisteni-…`)."""

import json

from ..section import Command


def _args(p) -> None:
    p.add_argument("--force", action="store_true", help="store even when the sheet didn't change")
    p.add_argument("--znovu", action="store_true", help="geocode every place again (after an algorithm change)")


def update(a) -> int:
    from . import jobs
    report = jobs.update(force=a.force, regeocode=a.znovu)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if report["failures"] else 0


COMMANDS = [
    Command("cisteni-update",
            "download the harmonogram of blokové čištění (Služby města Pardubic), geocode new places "
            "and replace future dates (idempotent, daily)", update, _args),
]
