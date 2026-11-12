"""Commands of the rozpočet section (`petka rozpocet-…`)."""

import json
import sys

from ..section import Command


def _args(p) -> None:
    p.add_argument("--unit", default="mo5", metavar="mo5|mmp|all")
    p.add_argument("years", nargs="*", type=int, metavar="ROK")


def update(a) -> int:
    from . import jobs, source
    units = list(source.UNITS) if a.unit == "all" else [a.unit]
    if any(u not in source.UNITS for u in units):
        print(f"unknown unit, use one of: {', '.join(source.UNITS)}, all", file=sys.stderr)
        return 2
    report = jobs.update(units, a.years or None)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if report["failures"] else 0


COMMANDS = [
    Command("rozpocet-update",
            "download the city's rozklikávací rozpočet (GORDIC) for the unit's due years (or the given "
            "ones) and replace changed years (idempotent)", update, _args),
]
