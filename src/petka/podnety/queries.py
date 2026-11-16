"""Reading the podněty: a list with filters (one obvod for the portal's pages and MCP, the
`?obvod=` filter of the whole town for the API), the ones near a point, a summary for an obvod.
Turning rows into GeoJSON and the distance are pure functions, testable without a database.

Distances are on a sphere (haversine); a bounding box in degrees narrows the rows first so the
(lat, lng) index is used. Fine for the few hundred metres an app asks about."""

import datetime as dt
import math
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .. import db
from ..obvody import WHOLE_TOWN, ObvodFilter
from . import photos, source

EARTH = 6_371_000       # metres
LIMIT = 2000            # most features one answer carries
TZ = ZoneInfo("Europe/Prague")      # reported_at and the notes are local time without a zone
# When a report last moved (local time): reported, the office's last note or a status change we saw.
CHANGED_SQL = "GREATEST(reported_at, last_note_at, status_changed_at AT TIME ZONE 'Europe/Prague')"


def meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * EARTH * math.asin(math.sqrt(a))


def box(lat: float, lng: float, radius: float) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lng_min, lng_max) around a point, a little larger than the circle."""
    dlat = math.degrees(radius / EARTH)
    dlng = math.degrees(radius / (EARTH * math.cos(math.radians(lat))))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


@dataclass
class Filters:
    """Which reports to read. `obvod` is one obvod's id (a page, MCP) or the API's filter of
    the town's obvody (default the whole town). `max_age` keeps reports that moved (were
    reported, answered by the office or changed status) in the last N days before `today`."""
    obvod: str | ObvodFilter = WHOLE_TOWN
    categories: tuple[int, ...] = ()
    statuses: tuple[int, ...] = ()
    date_from: dt.date | None = None
    date_to: dt.date | None = None          # inclusive
    near: tuple[float, float] | None = None
    radius: float = 500                     # metres, with `near`
    max_age: int | None = None              # days, counted back from `today`
    today: dt.date | None = None

    def sql(self) -> tuple[str, list]:
        if isinstance(self.obvod, str):
            w, p = ["obvod = %s"], [self.obvod]
        else:
            cond, p = self.obvod.sql_one("obvod")
            w = [] if self.obvod.whole_town else [cond]
        if self.categories:
            w.append("category_id = ANY(%s::int[])"); p.append(list(self.categories))
        if self.statuses:
            w.append("status = ANY(%s::int[])"); p.append(list(self.statuses))
        if self.date_from:
            w.append("reported_at >= %s"); p.append(self.date_from)
        if self.date_to:
            w.append("reported_at < %s"); p.append(self.date_to + dt.timedelta(days=1))
        if self.near:
            la0, la1, ln0, ln1 = box(*self.near, self.radius)
            w.append("lat BETWEEN %s AND %s AND lng BETWEEN %s AND %s"); p += [la0, la1, ln0, ln1]
        if self.max_age is not None:
            since = dt.datetime.combine((self.today or dt.date.today()) - dt.timedelta(days=self.max_age), dt.time())
            w.append(f"{CHANGED_SQL} >= %s")
            p.append(since)
        return " AND ".join(w) or "TRUE", p


def search(f: Filters, limit: int = 500) -> list[dict]:
    """Reports matching the filters, newest first; with `near` only those within the radius,
    nearest first, each with `distance` in metres."""
    where, params = f.sql()
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT *, {photos.VERSION_SQL} FROM citizen_reports WHERE {where}"
                            " ORDER BY reported_at DESC, id DESC"
                            + ("" if f.near else " LIMIT %s"), params + ([] if f.near else [min(limit, LIMIT)])
                            ).fetchall()
    if f.near:
        for r in rows:
            r["distance"] = round(meters(*f.near, r["lat"], r["lng"]))
        rows = sorted((r for r in rows if r["distance"] <= f.radius), key=lambda r: r["distance"])[:min(limit, LIMIT)]
    return rows


def near(obvod: str, lat: float, lng: float, radius: float = 500, limit: int = 100) -> list[dict]:
    return search(Filters(obvod, near=(lat, lng), radius=radius), limit)


def summary(obvod: str, date_from: dt.date | None = None) -> dict:
    """Counts by category and by status, and the span of the data."""
    f = Filters(obvod, date_from=date_from)
    where, params = f.sql()
    with db.pool().connection() as conn:
        cats = conn.execute(f"""SELECT category_id, category, count(*) AS n FROM citizen_reports WHERE {where}
                                GROUP BY 1, 2 ORDER BY 3 DESC, 2""", params).fetchall()
        stats = conn.execute(f"""SELECT status, count(*) AS n FROM citizen_reports WHERE {where}
                                 GROUP BY 1 ORDER BY 2 DESC""", params).fetchall()
        span = conn.execute(f"""SELECT count(*) AS n, min(reported_at) AS first, max(reported_at) AS last,
                                       max(last_seen) AS checked FROM citizen_reports WHERE {where}""",
                            params).fetchone()
    return {"total": span["n"], "first": span["first"], "last": span["last"], "checked": span["checked"],
            "categories": cats,
            "statuses": [{**s, "name": source.STATUSES.get(s["status"], str(s["status"]))} for s in stats]}


ROW = """id, category_id, category, status, reported_at, lat, lng, street,
         first_note_at, last_note_at, description, photo_url, """ + photos.VERSION_SQL + """,
         (SELECT min(s.seen_at) AT TIME ZONE 'Europe/Prague' FROM citizen_report_statuses s
           WHERE s.id = citizen_reports.id AND s.status = 3 AND NOT s.initial) AS resolved_seen_at"""
# lower case without the Czech accents, as petka.usneseni.text.fold writes a name
FOLD_SQL = "translate(lower(street), 'áäčďéěëíňóöřšťúůüýž', 'aacdeeeinoorstuuuyz')"


def period_rows(obvod: str, start: dt.date, end: dt.date) -> list[dict]:
    """The obvod's reports with start <= reported_at < end (dates), what the page counts."""
    with db.pool().connection() as conn:
        return conn.execute(f"""SELECT {ROW} FROM citizen_reports WHERE obvod = %s AND reported_at >= %s AND reported_at < %s
                                ORDER BY reported_at""", (obvod, start, end)).fetchall()


def street_rows(obvod: str, folded: str) -> list[dict]:
    """Every report of the obvod filed under one street (its name folded: lower case, no
    accents), oldest first."""
    with db.pool().connection() as conn:
        return conn.execute(f"""SELECT {ROW} FROM citizen_reports WHERE obvod = %s AND {FOLD_SQL} = %s
                                ORDER BY reported_at""", (obvod, folded)).fetchall()


def years(obvod: str) -> list[int]:
    with db.pool().connection() as conn:
        return [r["y"] for r in conn.execute(
            "SELECT DISTINCT extract(year FROM reported_at)::int AS y FROM citizen_reports WHERE obvod = %s",
            (obvod,))]


def version() -> str:
    """The data's version for the API's ETag: when any obvod was last downloaded successfully
    and the state of the photos (the job is the only writer; every run of an obvod moves the
    first, a stored or removed photo the second)."""
    with db.pool().connection() as conn:
        r = conn.execute("""SELECT (SELECT max(checked_at) FROM citizen_report_obvody) AS t,
                                   (SELECT max(fetched_at) FROM citizen_report_photos) AS p,
                                   (SELECT count(*) FROM citizen_report_photos) AS n""").fetchone()
    return "|".join("" if v is None else str(v) for v in (r["t"], r["p"], r["n"]))


def checked(obvod: str) -> dt.datetime | None:
    """When the job last downloaded the obvod successfully ("Stav k"): every run touches
    last_seen of every report it got."""
    with db.pool().connection() as conn:
        r = conn.execute("SELECT max(last_seen) AS t FROM citizen_reports WHERE obvod = %s", (obvod,)).fetchone()
    return r["t"] if r else None


# --- GeoJSON --------------------------------------------------------------------------------

def changed_at(r: dict) -> dt.datetime:
    """When a report last moved, local time without a zone: reported, the office's last note
    or a status change the job saw (what the API's `stari` counts, as CHANGED_SQL does)."""
    seen = r.get("status_changed_at")
    if seen is not None and seen.tzinfo is not None:
        seen = seen.astimezone(TZ).replace(tzinfo=None)
    return max(t for t in (r["reported_at"], r.get("last_note_at"), seen) if t is not None)


def feature(r: dict) -> dict:
    """One report as a GeoJSON Feature. A report lies in one obvod (Dej Tip's CS_MUNICODE):
    `obvod` is its id, `obvody` the same as a list, as every source of the whole town has it.
    `photo` is the portal's copy of a public photo (absolute URL), never Dej Tip's."""
    props = {"id": r["id"], "category_id": r["category_id"], "category": r["category"],
             "status_id": r["status"], "status": source.STATUSES.get(r["status"], str(r["status"])),
             "reported_at": r["reported_at"].isoformat(timespec="minutes"), "street": r["street"],
             "obvod": r["obvod"], "obvody": [r["obvod"]],
             "status_changed_at": r["status_changed_at"].isoformat() if r.get("status_changed_at") else None,
             "changed_at": changed_at(r).isoformat(timespec="minutes"),
             "description": r.get("description"),
             "photo": photos.href(r["id"], r.get("photo_version"), photos.PUBLIC_URL),
             "detail": source.detail(r["id"])}
    if "distance" in r:
        props["distance"] = r["distance"]
    return {"type": "Feature", "id": r["id"],
            "geometry": {"type": "Point", "coordinates": [round(r["lng"], 6), round(r["lat"], 6)]},
            "properties": props}


def geojson(rows: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": [feature(r) for r in rows],
            "attribution": "Dej Tip, Statutární město Pardubice (" + source.HOME + ")"}
