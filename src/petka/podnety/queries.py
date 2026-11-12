"""Reading the podněty: a list with filters, the ones near a point, a summary for an obvod.
Turning rows into GeoJSON and the distance are pure functions, testable without a database.

Distances are on a sphere (haversine); a bounding box in degrees narrows the rows first so the
(lat, lng) index is used. Fine for the few hundred metres an app asks about."""

import datetime as dt
import math
from dataclasses import dataclass

from .. import db
from . import source

EARTH = 6_371_000       # metres
LIMIT = 2000            # most features one answer carries


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
    obvod: str
    categories: tuple[int, ...] = ()
    statuses: tuple[int, ...] = ()
    date_from: dt.date | None = None
    date_to: dt.date | None = None          # inclusive
    near: tuple[float, float] | None = None
    radius: float = 500                     # metres, with `near`

    def sql(self) -> tuple[str, list]:
        w, p = ["obvod = %s"], [self.obvod]
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
        return " AND ".join(w), p


def search(f: Filters, limit: int = 500) -> list[dict]:
    """Reports matching the filters, newest first; with `near` only those within the radius,
    nearest first, each with `distance` in metres."""
    where, params = f.sql()
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT * FROM citizen_reports WHERE {where} ORDER BY reported_at DESC, id DESC"
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


# --- GeoJSON --------------------------------------------------------------------------------

def feature(r: dict) -> dict:
    props = {"id": r["id"], "category_id": r["category_id"], "category": r["category"],
             "status_id": r["status"], "status": source.STATUSES.get(r["status"], str(r["status"])),
             "reported_at": r["reported_at"].isoformat(timespec="minutes"), "street": r["street"],
             "obvod": r["obvod"],
             "status_changed_at": r["status_changed_at"].isoformat() if r.get("status_changed_at") else None,
             "detail": source.HOME}
    if "distance" in r:
        props["distance"] = r["distance"]
    return {"type": "Feature", "id": r["id"],
            "geometry": {"type": "Point", "coordinates": [round(r["lng"], 6), round(r["lat"], 6)]},
            "properties": props}


def geojson(rows: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": [feature(r) for r in rows],
            "attribution": "Dej Tip, Statutární město Pardubice (" + source.HOME + ")"}
