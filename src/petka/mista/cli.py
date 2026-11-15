"""Commands of the místa section (`petka mista-…`)."""

import json
from pathlib import Path

from ..section import Command


def _args(p) -> None:
    p.add_argument("--soubor", type=Path, help="read a saved Overpass answer (JSON) instead of asking Overpass")
    p.add_argument("--force", action="store_true", help="store even when the 70 %% guard would refuse the build")


def update(a) -> int:
    from . import jobs
    report = jobs.update(a.soubor, force=a.force)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if report["failures"] else 0


COMMANDS = [
    Command("mista-update",
            "download the town's places from OpenStreetMap (Co je v okolí, bike racks, waste containers, "
            "recycling centres) and replace the export unless it shrank below 70 %% (idempotent, daily)",
            update, _args),
]
