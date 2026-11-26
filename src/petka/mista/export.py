"""The export of Místa (docs/mista.md): the file version 2 and the same places as GeoJSON, for
the whole town or a filter of obvody and kinds. Pure; petka.mista.queries reads the database.
"""

import datetime as dt

from ..obvody import ObvodFilter
from ..web.etag import weak
from .osm import KINDS

VERSION = 2
LICENCE = "© přispěvatelé OpenStreetMap, ODbL 1.0"
SOURCE = "https://otevrenapetka.cz/data#mista"
CONTACT = ("phone", "web", "email")


def parse_kinds(value: str | None) -> tuple[str, ...]:
    """`?druh=` as given: kinds separated by commas, case and spaces ignored; none = every kind.
    Raises ValueError (Czech, listing the valid kinds) for an unknown one."""
    asked = {x.strip().lower() for x in (value or "").split(",") if x.strip()}
    unknown = sorted(asked - set(KINDS))
    if unknown:
        raise ValueError(f"Neznámý druh: {', '.join(unknown)}. Platné jsou {', '.join(KINDS)}, "
                         "víc jich oddělte čárkou; bez parametru všechny.")
    return tuple(k for k in KINDS if k in asked)


def place(row: dict) -> dict:
    """A place of the file from a row of mista_places: odpad only for kontejner and dvur,
    capacity only for stojan, pruvodce only for a place of Průvodce městem, phone, web and email only where OSM has them. Where OSM has no hours
    (or phone, web) the place's supplement (petka.mista.doplnky) gives them, and `hours_from`
    says which source, `hours_url` the page they are from."""
    p = {"id": row["id"], "kind": row["kind"], "name": row["name"], "what": row["what"],
         "address": row["address"], "at": [row["lon"], row["lat"]], "hours": row["hours"],
         "obvody": list(row["obvody"] or [])}
    if not p["hours"] and row.get("d_hours"):
        p["hours"] = row["d_hours"]
        p["hours_from"] = row["d_source"]
        if row.get("d_url"):
            p["hours_url"] = row["d_url"]
    for k in CONTACT:
        if v := row.get(k) or row.get(f"d_{k}"):
            p[k] = v
    if row["kind"] in ("kontejner", "dvur", "vykupna"):
        p["odpad"] = list(row["odpad"] or [])
    if row["kind"] == "stojan":
        p["capacity"] = row["capacity"]
    if row.get("pruvodce"):
        p["pruvodce"] = row["pruvodce"]
    return p


def chosen(places: list[dict], obvod: ObvodFilter, kinds: tuple[str, ...]) -> list[dict]:
    return [p for p in places if (not kinds or p["kind"] in kinds) and obvod.matches(p["obvody"])]


def _iso(built: dt.datetime) -> str:
    return built.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_v2(built: dt.datetime, places: list[dict]) -> dict:
    return {"v": VERSION, "built": _iso(built), "licence": LICENCE, "source": SOURCE, "places": places}


def geojson(built: dt.datetime, places: list[dict]) -> dict:
    """A FeatureCollection of Points; properties are the place's fields without `at`."""
    return {"type": "FeatureCollection", "built": _iso(built), "licence": LICENCE, "source": SOURCE,
            "features": [{"type": "Feature", "id": p["id"], "geometry": {"type": "Point", "coordinates": p["at"]},
                          "properties": {k: v for k, v in p.items() if k != "at"}} for p in places]}


def etag(built: dt.datetime, what: str, obvod: ObvodFilter, kinds: tuple[str, ...]) -> str:
    """A weak ETag (gzip changes the bytes, not the content) of a build and a filter."""
    return weak(_iso(built), what, ",".join(obvod.ids), ",".join(kinds))
