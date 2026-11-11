"""`usneseni rozpocet-update`: download the GORDIC reports for a unit's years and replace that
year's rows when the content changed. Idempotent; once a day is plenty (the source is current
to the day and slow to render).

A year whose content didn't change only gets `checked_at` and `as_of` moved. A changed year
replaces all its rows in one transaction and keeps the downloaded files in budget_snapshots,
so a parser fix can be re-run over the history.
"""

import datetime as dt
import hashlib
import json
import logging
import os
import time

import httpx

from .. import db
from . import source

log = logging.getLogger(__name__)


def years_to_refresh(today: dt.date, known: dict[int, dt.date]) -> list[int]:
    """Which years to download now. `known` maps a year already in the database to the day
    we last downloaded it (checked_at, not "Stav ke dni": a closed year's state stays at the
    day the books were closed for good).

    Every year from source.FIRST_YEAR is wanted (the point is the development over time), so
    a missing year is always fetched. The current year changes daily. A past year still moves
    while the books are closed (2018 was last touched on 14. 3. 2019, 2022 on 6. 2. 2023), so
    it is fetched again until we have downloaded it after 30. 6. of the next year; after that
    it is final."""
    out = []
    for year in range(source.FIRST_YEAR, today.year + 1):
        if year not in known or year == today.year or known[year] <= dt.date(year + 1, 6, 30):
            out.append(year)
    return out


def content_hash(parsed: dict) -> str:
    return hashlib.sha256(json.dumps(parsed, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def parse(files: dict[str, bytes], year: int) -> dict:
    items = source.item_codes(files["polozky"])
    invoices = source.parse_faktury(files["faktury"], items)
    # names as GORDIC spells them, with the codes the faktury reports give them
    known = {"polozka": {name: code for code, name in items},
             "paragraf": {i["paragraph_name"]: i["paragraph"] for i in invoices}}

    def code(name, kind):
        return known[kind].get(name) or source.code_for(name, kind, year)

    lines = [{**r, "paragraph": code(r["paragraph_name"], "paragraf"),
              "item": code(r["item_name"], "polozka")} for r in source.parse_odbory(files["odbory"])]
    return {
        "as_of": source.as_of(source.rows(files["rekapitulace"])).isoformat(),
        "totals": source.parse_rekapitulace(files["rekapitulace"]),
        "sectors": source.parse_odvetvi(files["odvetvi"]),
        "lines": lines,
        "invoices": invoices,
    }


def store(conn, unit: str, year: int, files: dict[str, bytes], parsed: dict) -> bool:
    """Bring one unit-year in line with a download. Returns True when the content changed."""
    as_of = dt.date.fromisoformat(parsed["as_of"])
    sha = content_hash({k: v for k, v in parsed.items() if k != "as_of"})
    prev = conn.execute("SELECT sha256 FROM budget_years WHERE unit = %s AND year = %s",
                        (unit, year)).fetchone()
    if prev and prev["sha256"] == sha:
        conn.execute("UPDATE budget_years SET as_of = %s, checked_at = now() WHERE unit = %s AND year = %s",
                     (as_of, unit, year))
        return False
    key = (unit, year)
    for table in ("budget_totals", "budget_sectors", "budget_lines", "budget_invoices"):
        conn.execute(f"DELETE FROM {table} WHERE unit = %s AND year = %s", key)
    for t in parsed["totals"]:
        conn.execute("""INSERT INTO budget_totals VALUES (%s, %s, %s, %s, %s, %s)""",
                     (*key, t["kind"], t["approved"], t["revised"], t["actual"]))
    for s in parsed["sectors"]:
        conn.execute("""INSERT INTO budget_sectors VALUES (%s, %s, %s, %s, %s, %s)""",
                     (*key, s["sector"], s["approved"], s["revised"], s["actual"]))
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO budget_lines VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(*key, n, r["department"], r["paragraph"], r["paragraph_name"], r["item"], r["item_name"],
              r["approved"], r["revised"], r["actual"]) for n, r in enumerate(parsed["lines"], 1)])
        cur.executemany(
            """INSERT INTO budget_invoices VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(*key, n, i["group"], i["group_name"], i["paragraph"], i["paragraph_name"], i["item"],
              i["item_name"], i["description"], i["amount"]) for n, i in enumerate(parsed["invoices"], 1)])
    for report, xlsx in files.items():
        conn.execute("""INSERT INTO budget_snapshots (unit, year, report, as_of, xlsx)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (unit, year, report, as_of) DO UPDATE SET xlsx = EXCLUDED.xlsx,
                          fetched_at = now()""", (*key, report, as_of, xlsx))
    conn.execute(
        """INSERT INTO budget_years (unit, year, as_of, checked_at, changed_at, sha256)
           VALUES (%s, %s, %s, now(), now(), %s)
           ON CONFLICT (unit, year) DO UPDATE SET as_of = EXCLUDED.as_of, checked_at = now(),
             changed_at = now(), sha256 = EXCLUDED.sha256""", (*key, as_of, sha))
    return True


def update(units: list[str] | None = None, years: list[int] | None = None,
           today: dt.date | None = None) -> dict:
    """Download and store the given (or due) years of each unit. A year that fails is
    reported and left as it was; the others still update."""
    db.migrate()
    today = today or dt.date.today()
    report, failures = {}, []
    with httpx.Client(timeout=source.TIMEOUT, follow_redirects=True, headers=source.HEADERS) as client, \
            db.connect() as conn:
        for unit in units or ["mo5"]:
            known = {r["year"]: r["checked"] for r in conn.execute(
                "SELECT year, checked_at::date AS checked FROM budget_years WHERE unit = %s", (unit,))}
            todo = years or years_to_refresh(today, known)
            report[unit] = {}
            for i, year in enumerate(todo):
                if i:
                    time.sleep(source.PAUSE)
                try:
                    files = source.fetch_all(unit, year, client)
                    parsed = parse(files, year)
                    changed = store(conn, unit, year, files, parsed)
                    conn.commit()
                    summary = {"as_of": parsed["as_of"], "changed": changed,
                               "lines": len(parsed["lines"]), "invoices": len(parsed["invoices"])}
                except Exception as e:
                    conn.rollback()
                    log.exception("rozpočet %s %s failed", unit, year)
                    failures.append(f"{unit} {year}: {e}")
                    summary = {"error": str(e)}
                report[unit][year] = summary
                log.info("rozpočet %s %s: %s", unit, year, summary)
    if failures and os.environ.get("SENTRY_DSN"):
        import sentry_sdk
        sentry_sdk.init(os.environ["SENTRY_DSN"])
        sentry_sdk.capture_message("rozpocet-update: " + "; ".join(failures), level="error")
        sentry_sdk.flush()
    report["failures"] = failures
    return report
