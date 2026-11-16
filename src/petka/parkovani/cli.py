"""Commands of the parkování section (`petka parkovani-…`)."""

import json
from pathlib import Path

from ..section import Command


def _update_args(p) -> None:
    p.add_argument("--obsazenost", type=Path, help="read a saved occupancy answer (JSON) instead of asking the source")
    p.add_argument("--lokality", type=Path, help="read a saved locations answer (JSON); needs --obsazenost")
    p.add_argument("--force", action="store_true", help="store even when the 70 %% guard would refuse the build")


def update(a) -> int:
    from . import jobs
    report = jobs.update(a.obsazenost, a.lokality, force=a.force)
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 1 if report["failures"] else 0


def _watch_args(p) -> None:
    p.add_argument("--smycka", action="store_true", help="keep fetching until stopped (a long-running worker)")
    p.add_argument("--kazdych", type=float, default=60, help="seconds between two fetches with --smycka (default 60)")


def watch(a) -> int:
    from . import jobs
    last = jobs.watch(a.kazdych, once=not a.smycka)
    print(json.dumps(last, ensure_ascii=False, default=str))
    return 1 if "error" in last else 0


COMMANDS = [
    Command("parkovani-update",
            "download the town's car parks from ChytřejšíParking and keep them as the day's build unless "
            "they shrank below 70 %% (idempotent, daily)", update, _update_args),
    Command("parkovani-obsazenost",
            "fetch the free places of every car park once, or with --smycka every 60 s; every 5 minutes "
            "into the history (idempotent)", watch, _watch_args),
]
