"""Commands of the uzavírky section (`petka doprava-…`)."""

import json
from pathlib import Path

from ..section import Command


def _args(p) -> None:
    p.add_argument("--soubor", type=Path, help="read the snapshot from this file instead of NDIC")


def update(a) -> int:
    from . import jobs
    report = jobs.update(a.soubor)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if report["failures"] else 0


COMMANDS = [
    Command("doprava-update",
            "download the NDIC snapshot of traffic information (closures, road works, accidents) and keep "
            "the town's records (idempotent, every 10 minutes)", update, _args),
]
