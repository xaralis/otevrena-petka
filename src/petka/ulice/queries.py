"""What the front page and a street page put together from the other sections: blokové čištění
(petka.cisteni), podněty (petka.podnety), usnesení (full-text search, petka.usneseni.search)
and the úřední deska (petka.uredni_deska).

Reading is here; shaping (the next cleaning, the reports' counts, one dated feed of everything)
is pure and testable without a database. A feed item is a dict: date, source (the grey line),
text, href, and optionally status (word, classes of .st), vote (the resolution's main vote),
next (the next cleaning, drawn dark)."""

import datetime as dt
import re
from dataclasses import dataclass

from .. import db
from ..cisteni import queries as cq
from ..cisteni.words import clock
from ..podnety import stats as ps
from ..usneseni import search as us
from ..uredni_deska.queries import tsquery as deska_tsquery

FEED_STREET = 8
SIDES = {"obe": "obě strany", "prava": "pravá strana", "leva": "levá strana"}


# --- shaping ----------------------------------------------------------------------------------

@dataclass
class Cleaning:
    next: dt.date | None
    on_next: list[dict]       # the places cleaned that day
    upcoming: list[dict]
    past: list[dict]          # this year, newest first

    @property
    def whole(self) -> bool:
        return bool(self.on_next) and all(i["method"] == "whole" for i in self.on_next)

    @property
    def side(self) -> str | None:
        sides = {i["side"] for i in self.on_next}
        return SIDES.get(sides.pop()) if len(sides) == 1 else None

    @property
    def time(self) -> str:
        return clock(self.on_next[0]) if self.on_next else ""


def cleaning(its: list[dict], today: dt.date) -> Cleaning:
    """One street's cleanings this year (items of petka.cisteni.queries.items)."""
    nxt = cq.next_date(its, today)
    return Cleaning(nxt, [i for i in its if i["date"] == nxt], [i for i in its if i["date"] >= today],
                    sorted((i for i in its if i["date"] < today), key=lambda i: i["date"], reverse=True))


def cleaning_text(cl: Cleaning) -> str:
    """What the next cleaning covers: 'Celá ulice, obě strany, od 7:00', or the places' short
    wording from the harmonogram."""
    if cl.whole:
        text = "Celá ulice" + (f", {cl.side}" if cl.side else "")
    else:
        text = "; ".join(dict.fromkeys(i["short"] or i["text"] for i in cl.on_next))
        text = text[:1].upper() + text[1:]
    return text + (f", {cl.time}" if cl.time else "")


def thousands(n: int) -> str:
    """'1 026' (a non-breaking space between thousands)."""
    return f"{n:,}".replace(",", "\u00a0")


def since_word(d: dt.datetime | dt.date | None) -> str:
    """'od listopadu 2024'."""
    from ..podnety.words import MONTH_GEN
    return f"od {MONTH_GEN[d.month - 1]} {d.year}" if d else ""


def reports(rows: list[dict]) -> dict:
    """Counts of a street's podněty: all, waiting, resolved, and since when we have them."""
    out = {o: sum(ps.outcome(r) == o for r in rows) for o in ps.OUTCOMES}
    return {"n": len(rows), **out, "since": min((r["reported_at"] for r in rows), default=None)}


def next_cleaning_line(its: list[dict]) -> tuple[str, str | None]:
    """The places cleaned on one day as a line of the feed and where it links: 'Milheimova
    a Josefa Ressla, pravá strana'."""
    names = list(dict.fromkeys(i["street"] for i in its))
    text = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " a " + names[-1]
    sides = {i["side"] for i in its}
    if len(sides) == 1 and None not in sides:
        text += ", " + SIDES[sides.pop()]
    slug = next((i["slug"] for i in its if i["slug"]), None)
    return text, f"/verejny-prostor/blokove-cisteni/ulice/{slug}" if slug else "/verejny-prostor/blokove-cisteni"


def resolution_item(r: dict) -> dict:
    return {"date": r["date"], "source": "Zastupitelstvo" if r["body"] == "zmo" else "Rada",
            "number": r["number"], "text": r["title"] or r["agenda_title"] or f"Usnesení {r['number']}",
            "href": f"/radnice/usneseni/{r['uid']}", "vote": r.get("mainvote"), "body": r["body"]}


def report_item(r: dict, href: str) -> dict:
    return {"date": r["reported_at"].date(), "source": "Podněty",
            "text": r["category"] + (f", {r['street']}" if r.get("street") else ""),
            "href": href, "status": ps.status_word(r)}


def feed(items: list[dict], n: int) -> list[dict]:
    """The `next` item (an upcoming cleaning) first, then the rest newest first, n in all."""
    first = [i for i in items if i.get("next")][:1]
    rest = sorted((i for i in items if not i.get("next") and i["date"]), key=lambda i: i["date"], reverse=True)
    return (first + rest)[:n]


# --- reading ----------------------------------------------------------------------------------

def street_reports(obvod: str, name: str) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute("""SELECT id, category_id, category, status, reported_at, lat, lng, street
                               FROM citizen_reports WHERE obvod = %s AND lower(street) = lower(%s)
                               ORDER BY reported_at DESC, id DESC""", (obvod, name)).fetchall()


def resolutions(name: str, limit: int = 4) -> tuple[list[dict], int]:
    """Resolutions that name the street, newest first, and how many there are: whole-word full
    text only (a loose match of any one word of "Boženy Němcové" says nothing about the street)."""
    hits, info = us.search(name, "fulltext", us.Filters(status="usneseni"), limit=limit, newest_first=True)
    if info.get("loose"):
        return [], 0
    return [h.row for h in hits], info.get("total", 0)


def notices_posted(name: str) -> int:
    """Notices of the obvod on the board now that name the street (every word)."""
    tq = deska_tsquery(name, "&")
    if not tq:
        return 0
    with db.pool().connection() as conn:
        return conn.execute("""SELECT count(*) AS n FROM notices n WHERE n.is_mo5 AND n.removed_at IS NULL
                               AND n.tsv @@ to_tsquery('simple', %s)""", (tq,)).fetchone()["n"]


# --- "Aktuálně": the front page's map --------------------------------------------------------

WEEK = 7                # days ahead: cleanings shown, traffic measures that start soon enough
NB = " "
SIDE_SHORT = {"obe": "obě", "prava": "pravá", "leva": "levá"}


def dm(d: dt.date) -> str:
    """'18. 11.' with a non-breaking space."""
    return f"{d.day}.{NB}{d.month}."


def dmy(d: dt.date) -> str:
    return f"{dm(d)}{NB}{d.year}"


def days(ds: list[dt.date]) -> str:
    """'18. 11.', '18. a 19. 11.', '18., 19. a 20. 11.', '30. 11. a 1. 12.' (the month always there)."""
    ds = sorted(set(ds))
    if len({(d.year, d.month) for d in ds}) == 1:
        head = [f"{d.day}." for d in ds[:-1]] + [dm(ds[-1])]
    else:
        head = [dm(d) for d in ds]
    return head[0] if len(head) == 1 else ", ".join(head[:-1]) + " a " + head[-1]


def period(a: dt.date | None, b: dt.date | None) -> str:
    """'16. 11. – 16. 12. 2026', '15. 11. 2026 – 31. 8. 2028', '5. 11. 2026'."""
    if a and b and a != b:
        return f"{dm(a) if a.year == b.year else dmy(a)} – {dmy(b)}"
    return dmy(b or a)


def short_until(a: dt.date | None, b: dt.date, today: dt.date) -> str:
    """The box's right column: 'od 20. 11.' (not yet), 'do 16. 12.', 'do 31. 8. 2028'."""
    if a and a > today:
        return "od " + (dm(a) if a.year == today.year else dmy(a))
    return "do " + (dm(b) if b.year == today.year else dmy(b))


def point_on(geometry: dict, at: float = 0.5) -> tuple[float, float]:
    """A point on a street's line `at` of its length (its longest connected piece)."""
    from shapely.geometry import shape
    from shapely.ops import linemerge
    g = shape(geometry)
    if g.geom_type == "MultiLineString":
        g = linemerge(g)
    if g.geom_type == "MultiLineString":
        g = max(g.geoms, key=lambda x: x.length)
    if g.geom_type == "LineString":
        p = g.interpolate(at, normalized=True)
    else:
        p = g.representative_point()
    return round(p.x, 6), round(p.y, 6)


def cleaning_when(its: list[dict]) -> str:
    """A street's cleanings in the week as its tooltip line: 'obě strany 20. 11.', 'pravá strana
    18. 11., levá 19. 11.', '18. a 19. 11.' (the sheet doesn't say the side)."""
    by: dict = {}
    for i in sorted(its, key=lambda i: i["date"]):
        by.setdefault(i["side"], []).append(i["date"])
    parts = []
    for n, (side, ds) in enumerate(by.items()):
        word = (SIDES if n == 0 else SIDE_SHORT).get(side)
        parts.append(f"{word} {days(ds)}" if word else days(ds))
    return ", ".join(parts)


def week_cleanings(its: list[dict], geoms: dict, today: dt.date) -> dict:
    """Cleanings in the next WEEK days: the located places as lines (`key`, `sid` = the street),
    one anchor per street (where its tooltip hangs) and the box's rows by day. An area (a
    parkoviště or a vnitroblok, drawn as a polygon) is its own `sid` and its anchor is a marker
    (`area`) at a point inside; the map draws its outline only while it is pointed at."""
    from ..cisteni.words import WD
    is_area = cq.is_area
    week = [i for i in its if today <= i["date"] <= today + dt.timedelta(days=WEEK) and i["key"] in geoms]

    def sid(i: dict) -> str:
        return i["key"] if is_area(geoms[i["key"]]) else i["slug"] or i["key"]

    lines, seen = [], set()
    for i in week:
        if i["key"] not in seen:
            seen.add(i["key"])
            lines.append({"type": "Feature", "geometry": geoms[i["key"]],
                          "properties": {"key": i["key"], "sid": sid(i), "area": is_area(geoms[i["key"]])}})
    streets: dict[str, list[dict]] = {}
    for i in week:
        streets.setdefault(sid(i), []).append(i)
    anchors = []
    for s, xs in streets.items():
        area = is_area(geoms[xs[0]["key"]])
        lng, lat = point_on(geoms[xs[0]["key"]])
        when = cleaning_when(xs)
        href = f"/verejny-prostor/blokove-cisteni/ulice/{xs[0]['slug']}" if xs[0]["slug"] else "/verejny-prostor/blokove-cisteni"
        what = (re.sub(r",?\s*(obě strany|pravá strana|levá strana)$", "", xs[0]["short"]) or "Blokové čištění") \
            if area and xs[0]["slug"] else "Blokové čištění"
        anchors.append({"sid": s, "street": xs[0]["street"], "what": what, "when": when, "lng": lng, "lat": lat,
                        "href": href, "area": area,
                        "label": f"Blokové čištění: {xs[0]['street']}, " + (f"{what}, " if what != "Blokové čištění" else "")
                                 + days([x["date"] for x in xs])})
    rows = []
    for d in sorted({i["date"] for i in week}):
        on = [i for i in week if i["date"] == d]
        rows.append({"date": d, "day": f"{WD[d.weekday()]} {dm(d)}", "text": next_cleaning_line(on)[0],
                     "keys": list(dict.fromkeys(i["key"] for i in on)),
                     "sids": list(dict.fromkeys(sid(i) for i in on))})
    return {"lines": {"type": "FeatureCollection", "features": lines}, "anchors": anchors, "rows": rows}


SPOTS = (0.5, 0.32, 0.68, 0.2, 0.8, 0.1, 0.9, 0.4, 0.6)
CLEAR = 0.001         # degrees, ~70–110 m here, about a marker at the overview zoom: a mark this close to a cleaned stretch or another mark covers it


def board_marks(notices: list[dict], streets: dict, today: dt.date, avoid: list[dict] | None = None) -> list[dict]:
    """Notices on the board that name a street of the obvod, one mark per street, on its line.
    Traffic orders show their measure's validity (gone once it ended, not yet when it starts
    more than WEEK days ahead); the others, and orders we couldn't read, when they were posted.
    A notice with a published plain-language card speaks with the card's headline, and an annex
    shown inside another notice's card is that card: one mark and one link per card. Marks keep
    clear of the `avoid` geometries (this week's cleaned stretches) and of each other where the
    street allows, so each stays pointable."""
    from shapely.geometry import Point, shape
    from shapely.ops import unary_union
    from ..uredni_deska.measures import streets_in, subject
    from ..uredni_deska.source import KIND_LABEL
    by_name = {s.name: s for s in streets.values()}
    blocked = [unary_union([shape(g) for g in avoid])] if avoid else []
    out, seen = [], set()

    def spot(geometry: dict) -> tuple[float, float]:
        best, far = None, -1.0
        for at in SPOTS:
            lng, lat = point_on(geometry, at)
            p = Point(lng, lat)
            d = min([g.distance(p) for g in blocked] + [p.distance(Point(m["lng"], m["lat"])) for m in out] + [9.0])
            if d >= CLEAR:
                return lng, lat
            if d > far:
                best, far = (lng, lat), d
        return best

    for n in sorted(notices, key=lambda n: (n["published"] or dt.date.min, n["id"]), reverse=True):
        found = streets_in(n["title"], list(by_name))
        if not found:
            continue
        traffic = n["kind"] == "doprava"
        a, b = n.get("valid_from"), n.get("valid_to")
        if traffic and b and (b < today or (a and a > today + dt.timedelta(days=WEEK))):
            continue
        if n.get("card"):
            what = n["card"]
        elif traffic:
            what = n.get("what") or "Přechodná úprava provozu"
        else:
            what = f"{KIND_LABEL.get(n['kind'], 'Úřední deska')}: {subject(n['title'], found)}"
        dated = traffic and b
        when = period(a, b) if dated else (f"vyvěšeno {dm(n['published'])}" if n["published"] else "")
        link = n.get("owner") or n["id"]      # the card's notice where this one is its annex
        for name in found:
            key = (name, what, when)
            if key in seen or (link, name) in seen:   # an annex or the same order posted twice
                continue
            seen.update({key, (link, name)})
            lng, lat = spot(by_name[name].geometry)
            label = (f"Dopravní omezení: {name}, {what}" if traffic else f"{name}, {what}") + (f", {when}" if when else "")
            out.append({"id": f"m{len(out)}", "nid": link, "kind": n["kind"], "traffic": traffic,
                        "street": name, "what": what, "when": when, "label": label,
                        "box": short_until(a, b, today) if dated else when, "lng": lng, "lat": lat,
                        "order": (a > today, a if a and a > today else b) if dated else (True, dt.date.max)})
    return out


def place_notices() -> list[dict]:
    """Posted notices of the obvod that can be about a place, with what we read from them."""
    from ..uredni_deska.measures import PLACE_KINDS
    with db.pool().connection() as conn:
        return conn.execute(
            """SELECT n.id, n.title, n.kind, n.published, m.valid_from, m.valid_to, m.what,
                      COALESCE(d.data->>'headline', o.data->>'headline') AS card, o.notice_id AS owner
               FROM notices n LEFT JOIN notice_measures m ON m.notice_id = n.id
               LEFT JOIN notice_digests d ON d.notice_id = n.id AND d.status = 'published'
               LEFT JOIN notice_digests o ON o.status = 'published' AND n.id = ANY(o.members)
               WHERE n.is_mo5 AND n.removed_at IS NULL AND n.kind = ANY(%s)""", (list(PLACE_KINDS),)).fetchall()
