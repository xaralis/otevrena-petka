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

    def now(self, at: dt.datetime) -> bool:
        return self.starts is None or self.starts <= at


def place(text: str) -> str:
    """Where, from NDIC's text: what comes before the obvod („ulice Wolkerova, Pardubice V, …“)."""
    head = text.split(", Pardubice")[0].split(", okr. ")[0].strip(" ,")
    head = head.removeprefix("ulice ").strip()
    return head[:1].upper() + head[1:] if head else "Místní komunikace"


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
                           obvody.share_ids(best["obvody"], MIN_SHARE), sorted(r["id"] for r in rs)))
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


def checked() -> dt.datetime | None:
    """When the last snapshot was downloaded: „Stav k“."""
    with db.pool().connection() as conn:
        r = conn.execute("SELECT max(checked_at) AS at FROM traffic_snapshots").fetchone()
    return r["at"] if r else None
