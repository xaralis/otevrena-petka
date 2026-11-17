"""The export /api/v1/parkovani (docs/parkovani.md): the lots of a daily build joined with the
curated data (SMS codes by area number, the regulation's price by locality), with every record's
`obvody`. Pure: the lots, the files and the obvody's polygons come in.

The document keeps the app's bundled files as they were, one key each, so the app swaps a file
for a key: `parking` (lots and machines), `zones`, `adjacent`, `localities` (with `tariffs`),
`sections`; besides them `smsCodes` and `sources` (where each part comes from, checked when).

`?obvod=` narrows what lies at a place – lots, machines, street sections. The regulation's areas
(zones, the adjacent area, localities and visitor places) and the price list and SMS codes are
rules of the whole town and always come whole; they carry `obvody` too.
"""

import datetime as dt
import re

import shapely
from shapely.geometry import Polygon

from ..cisteni.geocode import KX, KY, LAT0, LON0
from ..mista.where import Obvody
from ..obvody import ObvodFilter
from . import data

VERSION = 1
SOURCE = "https://otevrenapetka.cz/data#parkovani"
LOTS_SOURCE = {"source": "ChytřejšíParking (DPMP), neoficiální API aplikace, bez licence", "url": "https://pardubice.chytrejsiparking.cz/"}
MIN_AREA_SHARE = 0.01       # an area lies in an obvod when this much of it is there


def iso(t: dt.datetime | None) -> str | None:
    if t is None:
        return None
    return t.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --- lots -------------------------------------------------------------------------------------

def price_conflicts(prices: list[dict], tariff: dict) -> tuple[bool, bool]:
    """Whether the operator's price list disagrees with the regulation: (on what it costs, on
    when it applies). The operator writes a price as „first hour/every other hour Kč“, a day's
    price as „5/5 Kč“, and knows neither half hours nor a day's cap."""
    if "wholeDay" in tariff:
        expected = f"{tariff['wholeDay']}/{tariff['wholeDay']}"
    else:
        expected = f"{tariff['firstHour']}/{tariff['nextHour']}"
    differ = any(p["price"].replace(" Kč", "") != expected for p in prices)
    hours = sorted((p["day"].replace("-", "–"), re.sub(r"\b0(\d:)", r"\1", p["time"].replace(" - ", "–")))
                   for p in prices)
    return differ, hours != sorted((h["day"], h["time"]) for h in tariff["hours"])


def lot(src: dict, codes: dict[str, dict], tariffs: dict[str, dict]) -> tuple[dict, list[str]]:
    """A lot of the export from the source's facts (petka.parkovani.source.lots_of), and what
    the join noticed. The SMS code and zone come from DPMP's table by the area's number, the
    price from the regulation by the locality; a paid lot's description only repeats how its
    prices work, so `note` is kept for the others (who may park there)."""
    paid, locality = src["paid"], src.get("locality") or None
    code = codes.get(src["number"], {}) if paid else {}
    tariff = None
    notes = []
    if paid and locality in tariffs:
        tariff = dict(tariffs[locality])
        prices_differ, hours_differ = price_conflicts(src.get("prices") or [], tariff)
        if prices_differ:
            notes.append(f"price differs from the regulation: {src['name']} {locality} "
                         f"{[p['price'] for p in src.get('prices') or []]}")
        if hours_differ:
            notes.append(f"hours differ from the regulation: {src['name']} {locality}")
            tariff["hoursDiffer"] = True
    elif paid:
        notes.append(f"paid lot without a known price: {src['name']} {locality}")
    return {"id": src["id"], "name": src["name"], "area": src["area"], "zone": code.get("zone") or None,
            "smsCode": code.get("sms") or None, "paid": paid, "note": "" if paid else src.get("description") or "",
            "at": src["at"], "locality": locality, "tariff": tariff, "kind": src.get("kind"),
            "capacity": src.get("capacity")}, notes


def lots(srcs: list[dict]) -> tuple[list[dict], list[str]]:
    """Every lot of a build joined with the curated files, by id; and the notes of the join."""
    codes = {r["number"]: r for r in data.payload("smsCodes")}
    tariffs = data.payload("tariffs")
    out, notes = [], []
    for s in sorted(srcs, key=lambda s: s["id"]):
        lt, n = lot(s, codes, tariffs)
        out.append(lt)
        notes += n
    return out, notes


# --- obvody -----------------------------------------------------------------------------------

class Placer:
    """Which obvody a point or an area lies in, by the obvody's polygons from RÚIAN
    (petka.mista.where; none known = every record lies in none)."""

    def __init__(self, polygons: dict[str, dict] | None):
        self.obvody = Obvody(polygons or {})

    def point(self, at) -> list[str]:
        return self.obvody.of(at[0], at[1])

    def ring(self, ring) -> list[str]:
        """The obvody holding at least MIN_AREA_SHARE of a closed ring's area."""
        if len(ring) < 4 or not self.obvody.polys:
            return []
        poly = Polygon([((lon - LON0) * KX, (lat - LAT0) * KY) for lon, lat in ring])
        if not poly.is_valid:
            poly = shapely.make_valid(poly)
        if poly.area <= 0:
            return []
        return sorted(k for k, p in self.obvody.polys.items() if p.intersection(poly).area / poly.area >= MIN_AREA_SHARE)

    def rings(self, rings) -> list[str]:
        """The obvody of a group of small rings (a street's bands): where their centres lie."""
        out: set[str] = set()
        for r in rings:
            if r:
                out.update(self.point([sum(p[0] for p in r) / len(r), sum(p[1] for p in r) / len(r)]))
        return sorted(out)


def document(built: dt.datetime, srcs: list[dict], placer: Placer) -> tuple[dict, list[str]]:
    """The whole export (every obvod) of a build, and the notes of the join."""
    ls, notes = lots(srcs)
    for lt in ls:
        lt["obvody"] = placer.point(lt["at"])
    machines = [{**m, "obvody": placer.point(m["at"])} for m in data.payload("machines")]
    zones = [{**z, "obvody": placer.ring(z["ring"])} for z in data.payload("zones")]
    adjacent = {**data.payload("adjacent")}
    adjacent["obvody"] = placer.ring(adjacent["ring"])
    loc = data.payload("localities")
    localities = {
        "localities": [{**x, "obvody": placer.ring(x["ring"])} for x in loc["localities"]],
        "visitor": [{**v, "obvody": sorted(set(placer.point(v["at"])) | set(placer.rings([v["sections"]])))}
                    for v in loc["visitor"]],
        "tariffs": data.payload("tariffs"),
    }
    sections = [{**s, "obvody": placer.rings(s["rings"])} for s in data.payload("sections")]
    lot_obvody = {lt["id"]: lt["obvody"] for lt in ls}
    areas = [{**a, "obvody": sorted({o for i in a["lots"] for o in lot_obvody.get(i, [])})} for a in data.payload("areas")]
    sources = {"lots": {**LOTS_SOURCE, "fetched": iso(built)}}
    sources.update({k: data.meta(k) for k in data.FILES})
    return {"v": VERSION, "built": iso(built), "source": SOURCE, "sources": sources,
            "parking": {"lots": ls, "machines": machines}, "zones": zones, "adjacent": adjacent,
            "localities": localities, "sections": sections, "areas": areas, "smsCodes": data.payload("smsCodes")}, notes


def narrowed(doc: dict, obvod: ObvodFilter) -> dict:
    """The document with only the lots, machines and street sections of the obvody."""
    if obvod.whole_town:
        return doc
    keep = lambda xs: [x for x in xs if obvod.matches(x["obvody"])]
    return {**doc, "parking": {"lots": keep(doc["parking"]["lots"]), "machines": keep(doc["parking"]["machines"])},
            "sections": keep(doc["sections"])}
