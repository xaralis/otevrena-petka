"""One runner for the sections' update jobs (`deska-update`, `rozpocet-update`, …).

A job is a list of units (a board, a unit-year of the budget) and how to bring one unit up to
date. The runner owns what every job did the same way: migrate the database, open one HTTP
client and one connection, run each unit in its own transaction (a unit that fails is rolled
back, logged and reported; the others still run), shape the report and raise one alert at
the end when anything failed.

Report: {<unit key path>: summary, …, "failures": ["<unit label>: <error>", …]}; a unit's
key is a path (("mo5", 2024) → report["mo5"][2024]), a failed unit's summary is {"error": …}.
"""

import logging
import os
from dataclasses import dataclass
from typing import Callable, Iterable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Unit:
    key: tuple                  # where its summary goes in the report
    label: str                  # how logs and failures name it ("mo5", "mo5 2024")
    run: Callable[[object, object], dict]   # (conn, client) -> summary; the runner commits


def sentry_alert(message: str) -> None:
    """Report a failed job to Sentry/GlitchTip, if configured."""
    if os.environ.get("SENTRY_DSN"):
        import sentry_sdk
        sentry_sdk.init(os.environ["SENTRY_DSN"])
        sentry_sdk.capture_message(message, level="error")
        sentry_sdk.flush()


def _put(report: dict, key: tuple, value) -> None:
    for k in key[:-1]:
        report = report.setdefault(k, {})
    report[key[-1]] = value


def run(job: str, name: str, units: Callable[[object, object], Iterable[Unit]], *,
        client: dict | None = None, finish: Callable[[object], None] | None = None,
        alert: Callable[[str], None] | None = None, logger: logging.Logger | None = None,
        connect=None, migrate=None, http=None) -> dict:
    """Run `job` (its CLI name, e.g. "deska-update"; `name` is how logs call it, e.g. "deska").

    `units(conn, client)` yields the units; it may do work between them (save state, pause),
    and an error there stops the job. `finish(conn)` runs after the last unit (it commits
    itself). `connect`, `migrate` and `http` default to the database and httpx; tests pass fakes."""
    from . import db
    logger = logger or log
    alert = alert or sentry_alert
    (migrate or db.migrate)()
    if http is None:
        import httpx
        http = httpx.Client
    report, failures = {}, []
    with http(**(client or {})) as c, (connect or db.connect)() as conn:
        for unit in units(conn, c):
            try:
                summary = unit.run(conn, c)
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.exception("%s %s failed", name, unit.label)
                failures.append(f"{unit.label}: {e}")
                summary = {"error": str(e)}
            _put(report, unit.key, summary)
            logger.info("%s %s: %s", name, unit.label, summary)
        if finish:
            finish(conn)
    if failures:
        alert(f"{job}: " + "; ".join(failures))
    report["failures"] = failures
    return report
