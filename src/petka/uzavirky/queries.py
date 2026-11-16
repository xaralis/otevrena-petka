"""Reading the town's traffic records as closures: one closure per NDIC situation (a closure is
usually two records, the restriction and its cause, with the same text and stretch).

`closures` shapes rows without a database (tests pass dicts); `rows` reads the records valid now
or later of some obvody (`ObvodFilter`, ADR 0002).

What we show is ours (the place, what is restricted, the stretch on the street) next to NDIC's
own text, unchanged. The terms of ŘSD (docs/ndic-podminky-1.0.4.pdf) let us show the data as part
of our service; the unchanged text carries the sentence ATTRIBUTION (point 5), what we derived
must not name NDIC as its source, and ŘSD is not answerable for any of it (point 3).
"""

import datetime as dt
import re
from dataclasses import dataclass, field

from .. import db, obvody

MIN_SHARE = 0.1         # a closure lies in an obvod when this much of it is there
ATTRIBUTION = "Zdrojem digitalizovaných informací o silničním provozu je NDIC."
TERMS = "https://dopravniinfo.gov.cz"

# what is restricted (the restriction record's *Type values), the first one known wins
RESTRICTION = {
    "roadClosed": "Uzavřeno", "carriagewayClosures": "Uzavřeno", "laneClosures": "Uzavřený jízdní pruh",
    "narrowLanes": "Zúžené jízdní pruhy", "singleAlternateLineTraffic": "Kyvadlový provoz",
    "heightRestrictionInOperation": "Omezená výška", "weightRestrictionInOperation": "Omezená hmotnost",
    "widthRestrictionInOperation": "Omezená šířka", "speedRestrictionInOperation": "Omezená rychlost",
    "contraflow": "Provoz v protisměru", "detourInOperation": "Objížďka",
}
# why (the cause record's *Type values)
CAUSE = {
    "roadworks": "práce na silnici", "resurfacingWork": "oprava povrchu", "constructionWork": "stavební práce",
    "maintenanceWork": "údržba", "roadMaintenance": "údržba", "repairWork": "opravy",
}
KIND = {"Accident": "Nehoda", "VehicleObstruction": "Překážka", "AnimalPresenceObstruction": "Zvíře na silnici",
        "GeneralObstruction": "Překážka", "PoorEnvironmentConditions": "Špatné počasí", "AbnormalTraffic": "Kolona"}


@dataclass
class Closure:
    id: str                         # the NDIC situation
    place: str                      # „Wolkerova“, „silnice II/355 (ulice Dašická)“
    what: str                       # „Uzavřeno, oprava povrchu“
    closed: bool                    # the road is closed (not just narrowed)
    starts: dt.datetime | None
    ends: dt.datetime | None
    text: str                       # NDIC's own text, unchanged
    geometry: dict | None
    method: str                     # street | straight | point | none: how we placed it
    obvody: list[str] = field(default_factory=list)
    records: list[str] = field(default_factory=list)
    seen: dt.datetime | None = None     # when we first had it (Můj přehled: when it is news)

    def now(self, at: dt.datetime) -> bool:
        return self.starts is None or self.starts <= at


def place(text: str) -> str:
    """Where, from NDIC's text: what comes before the obvod („ulice Wolkerova, Pardubice V, …“),
    or the street a sentence names („Od … ; v ulici Češkova v obci Pardubice, délka 62m; nehoda“)."""
    if not text.startswith(("ulice ", "silnice ", "místní komunikace")):
        m = re.search(r"\bv ulici ([^,;]+?)(?= v obci| v Pardubic|\s*[,;]|$)", text)
        if m:
            return m.group(1).strip()
    head = text.split(", Pardubice")[0].split(", okr. ")[0].strip(" ,")
    head = head.removeprefix("ulice ").strip()
    if not head or len(head) > 60:
        return "Místní komunikace"
    return head[:1].upper() + head[1:]


def closures(rows: list[dict], at: dt.datetime) -> list[Closure]:
    """Rows of traffic_records → closures, one per situation, those going on first (ending
    soonest), then those to come (starting soonest)."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["situation"], []).append(r)
    out = []
    for sid, rs in by.items():
        details = [d for r in rs for d in (r["details"] or [])]
        restr = next((RESTRICTION[d] for d in details if d in RESTRICTION), None)
        cause = next((CAUSE[d] for d in details if d in CAUSE), None)
        kind = next((KIND[r["kind"]] for r in rs if r["kind"] in KIND), None)
        what = ", ".join(x for x in (restr or kind or "Omezení", cause) if x)
        best = min(rs, key=lambda r: {"street": 0, "straight": 1, "point": 2}.get(r["method"], 3))
        text = max((r["comment"] or "" for r in rs), key=len)
        starts = min((r["starts_at"] for r in rs if r["starts_at"]), default=None)
        ends = max((r["ends_at"] for r in rs if r["ends_at"]), default=None)
        out.append(Closure(sid, place(text), what, "roadClosed" in details or "carriagewayClosures" in details,
                           starts, ends, text, best["geometry"], best["method"],
                           obvody.share_ids(best["obvody"], MIN_SHARE), sorted(r["id"] for r in rs),
                           min((r["first_seen"] for r in rs if r.get("first_seen")), default=None)))
    far = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    return sorted(out, key=lambda c: (not c.now(at), c.ends or far, c.starts or far) if c.now(at)
                  else (True, c.starts or far, c.ends or far))


def rows(where: obvody.ObvodFilter, now: dt.datetime) -> list[dict]:
    """The records still valid (not over, not ended) of the obvody."""
    cond, params = where.sql("obvody", MIN_SHARE)
    with db.pool().connection() as conn:
        return conn.execute(f"""SELECT id, situation, kind, details, starts_at, ends_at, comment, geometry, method, obvody
                                FROM traffic_records
                                WHERE gone_at IS NULL AND (ends_at IS NULL OR ends_at > %s) AND {cond}""",
                            [now, *params]).fetchall()


def seen_since(where: obvody.ObvodFilter, since: dt.datetime) -> list[dict]:
    """The records of the obvody we first had since a moment, over or not (Můj přehled's news)."""
    cond, params = where.sql("obvody", MIN_SHARE)
    with db.pool().connection() as conn:
        return conn.execute(f"""SELECT id, situation, kind, details, starts_at, ends_at, comment, geometry, method, obvody,
                                       first_seen FROM traffic_records WHERE first_seen >= %s AND {cond}""",
                            [since, *params]).fetchall()


def names(c: Closure, street: str) -> bool:
    """Whether a closure is in a street: its place, or its text naming it as a whole word."""
    return c.place == street or re.search(rf"(?<![\w-]){re.escape(street)}(?![\w-])", c.text) is not None


def checked() -> dt.datetime | None:
    """When the last snapshot was downloaded: „Stav k“."""
    with db.pool().connection() as conn:
        r = conn.execute("SELECT max(checked_at) AS at FROM traffic_snapshots").fetchone()
    return r["at"] if r else None


def version(now: dt.datetime) -> str:
    """The API's answer's version for its ETag: when the job last stored a changed snapshot
    (a run that found the same snapshot changes nothing) and the last start or end of a live
    record already passed at `now` (`now` of a closure and which records are still valid move
    with those moments, not with the clock)."""
    with db.pool().connection() as conn:
        r = conn.execute("""SELECT (SELECT max(checked_at) FROM traffic_snapshots WHERE changed) AS stored,
                                   (SELECT max(t) FROM traffic_records, LATERAL (VALUES (starts_at), (ends_at)) b(t)
                                    WHERE gone_at IS NULL AND t <= %s) AS passed""", [now]).fetchone()
    return "|".join("" if v is None else v.isoformat() for v in (r["stored"], r["passed"]))
