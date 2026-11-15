"""What the front page and a street page put together from the other sections: blokové čištění
(petka.cisteni), podněty (petka.podnety), usnesení (full-text search, petka.usneseni.search)
and the úřední deska (petka.uredni_deska).

Reading is here; shaping (the next cleaning, the reports' counts, the rows of a street's
„Aktuálně“ and its two small charts, the front page's map) is pure and testable without a
database."""

import datetime as dt
import re
from dataclasses import dataclass

from .. import db
from ..cisteni import queries as cq
from ..cisteni.words import clock
from ..podnety import stats as ps
from ..usneseni import search as us
from ..uredni_deska.queries import tsquery as deska_tsquery
from ..usneseni.text import fold

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
    return text, cq.street_url(slug)


# --- one street: „Aktuálně“ and the two facts ---------------------------------------------------
# A row of the list is a dict: key (what the map knows it by), kind (rep, month, cl, res, deska),
# date (for the order), label (the date column; `year` under it when not this year), title (bold),
# sub (the grey line), status (word, classes of .st), href, and what it points at on the map:
# ids (reports), keys (cleaned places), mark (a notice's marker).

ROWS = 12               # rows of „Aktuálně“ at most before „Starší události“
CURRENT = 30            # „Aktuálně“: the last 30 days, and what is still to come
RECENT = 30             # days: a report this new keeps its own row, older resolved ones are summed by month
PASSED = {"Městská policie": "předáno strážníkům", "Zastávky MHD": "předáno dopravnímu podniku"}
KIND_ORDER = {"cl": 0, "deska": 1, "res": 2, "rep": 3, "month": 4}     # on one day, upcoming things first


def _label(d: dt.date, today: dt.date) -> dict:
    return {"label": dm(d), "year": d.year if d.year != today.year else None}


def report_sub(r: dict, now: dt.datetime) -> str:
    """The grey line of one report: 'čeká 2 dny', 'předáno strážníkům', 'odpověď úřadu za 16 h'."""
    from ..podnety import words as pw
    o = ps.outcome(r)
    if o == "ceka":
        n = max(0, (now - r["reported_at"]).days)
        return "čeká od dneška" if n < 1 else f"čeká {n}{NB}{pw.plural(n, 'den', 'dny', 'dní')}"
    if o == "predano":
        return PASSED.get(r["category"], "předáno jinam")
    h = ps.response_hours(r)
    return f"odpověď úřadu za {pw.hours(h).replace(' ', NB)}" if h is not None else "podnět z Dej Tipu"


def report_rows(rows: list[dict], now: dt.datetime, slug: str) -> list[dict]:
    """A street's reports as rows: each of the last RECENT days and each not resolved on its
    own, older resolved ones one row per month ('červen: 6 podnětů – odpadky 3, jiné 2'; a
    month with one keeps it as itself)."""
    from collections import Counter
    from ..podnety import source, words as pw
    today, cut = now.date(), now - dt.timedelta(days=RECENT)
    out, months = [], {}

    def one(r):
        d = r["reported_at"].date()
        return {"key": f"r{r['id']}", "kind": "rep", "date": d, **_label(d, today), "title": r["category"],
                "sub": report_sub(r, now), "status": ps.status_word(r), "href": source.detail(r["id"]),
                "ext": True, "ids": [r["id"]], "open": ps.outcome(r) == "ceka"}

    for r in rows:
        if r["reported_at"] >= cut or ps.outcome(r) != "vyreseno":
            out.append(one(r))
        else:
            months.setdefault((r["reported_at"].year, r["reported_at"].month), []).append(r)
    for (y, m), rs in months.items():
        if len(rs) == 1:
            out.append(one(rs[0]))
            continue
        c = Counter(pw.short(r["category"]) for r in rs)
        out.append({"key": f"m{y}{m:02d}", "kind": "month", "date": max(r["reported_at"].date() for r in rs),
                    "label": pw.MONTH_ABBR[m - 1], "year": y if y != today.year else None,   # short: the date column is narrow
                    "title": pw.podnetu(len(rs)).replace(" ", NB),
                    "sub": ", ".join(f"{k}{NB}{v}" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))),
                    "status": ("vyřešeno", "st"), "href": f"/verejny-prostor/podnety?ulice={slug}&stav=vyreseno#kde",
                    "ids": [r["id"] for r in rs]})
    return out


def cleaning_rows(its: list[dict], today: dt.date, href: str) -> list[dict]:
    """This year's cleanings of the street, one row a day: the places in the harmonogram's
    words, „proběhlo“ or how soon."""
    from ..cisteni import words as cw
    out = []
    for d in sorted({i["date"] for i in its}):
        on = [i for i in its if i["date"] == d]
        past = d < today
        sub = re.sub(r"(\d)-(\d)", "\\1–\\2", cw.where(on)).replace("č. p. ", f"č.{NB}p.{NB}")
        if not past and clock(on[0]):
            sub += ", " + clock(on[0]).replace(" ", NB)
        out.append({"key": f"c{d:%Y%m%d}", "kind": "cl", "date": d, **_label(d, today), "title": "Blokové čištění",
                    "sub": sub, "status": ("proběhlo", "st ul-done") if past else (cw.until(d, today).replace(" ", NB), "st"),
                    "href": href, "past": past, "keys": list(dict.fromkeys(i["key"] for i in on))})
    return out


RES_WORD = {"prijato": ("přijato", "st st-ok"), "castecne": ("částečně", "st st-part")}


def resolution_row(r: dict, today: dt.date) -> dict:
    status = ("zrušeno", "st") if r.get("revoked_by") else RES_WORD.get(r.get("status"), ("přijato", "st st-ok"))
    body = "zastupitelstvo" if r["body"] == "zmo" else "rada"
    return {"key": f"z{r['uid']}", "kind": "res", "date": r["date"], **_label(r["date"], today),
            "title": r["title"] or r["agenda_title"] or f"Usnesení {r['number']}",
            "sub": f"{body}, usnesení {r['number'].replace(' ', NB)}", "status": status,
            "href": f"/radnice/usneseni/{r['uid']}"}


def notice_row(m: dict, today: dt.date) -> dict:
    """A notice of the úřední deska that names the street (a mark of board_marks)."""
    d = m.get("date") or today
    return {"key": f"d{m['id']}", "kind": "deska", "date": d, **_label(d, today), "title": m["what"],
            "sub": "úřední deska" + (f", {m['when']}" if m["when"] and m["traffic"] else ""),
            "status": (m["box"], "st") if m["traffic"] else ("visí", "st"),
            "href": f"/radnice/uredni-deska/{m['nid']}" if m["nid"] else None, "mark": m["id"]}


def current(rows: list[dict], today: dt.date) -> list[dict]:
    """What „Aktuálně“ shows by default, in the list and on the map alike: what is still to come
    (an upcoming cleaning), the last CURRENT days and reports still waiting, however old (an
    open report is current); the rest is a click away."""
    since = today - dt.timedelta(days=CURRENT)
    return [r for r in rows if r["date"] >= since or r.get("open")]


def rows(*groups: list[dict]) -> list[dict]:
    """Every row newest first (upcoming cleanings on top); on one day by KIND_ORDER."""
    every = [r for g in groups for r in g]
    return sorted(every, key=lambda r: (r["date"], -KIND_ORDER[r["kind"]]), reverse=True)


def short_title(t: str, n: int = 70) -> str:
    """A resolution's title to follow 'Naposledy 3. 6., ': lower case (unless it starts with an
    abbreviation), cut at a word to about n characters."""
    t = " ".join(t.split())
    if len(t) > 1 and t[1].islower():
        t = t[:1].lower() + t[1:]
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(",;:–-") + "…"
    return t


def report_months(rows: list[dict], today: dt.date) -> dict | None:
    """The reports of the last 12 months by month: the Podněty page's chart and period
    (podnety.stats.months), None when there were none."""
    p = ps.period("12m", today)
    if not any(r["reported_at"].date() >= p.start for r in rows):
        return None
    return ps.months(rows, p, today)


def report_kinds(rows: list[dict], n: int = 5) -> tuple[list[dict], int]:
    """What the street's reports were about: the n most common categories (id, name, count)
    and how many reports the rest are."""
    from collections import Counter
    c = Counter((r["category_id"], r["category"]) for r in rows)
    top = sorted(c.items(), key=lambda kv: (-kv[1], kv[0][1]))
    return [{"id": i, "name": name, "n": k} for (i, name), k in top[:n]], sum(k for _, k in top[n:])


FIRST_YEAR = 2018       # the resolutions we have start here


def resolution_years(res: list[dict], today: dt.date) -> dict | None:
    """The resolutions by year in the shape of podnety.stats.months (every column all dark)."""
    if not res:
        return None
    years = list(range(FIRST_YEAR, today.year + 1))
    n = {y: sum(r["date"].year == y for r in res) for y in years}
    step = ps.nice_step(max(n.values()))
    top = step * max(1, -(-max(n.values()) // step))
    busiest = sorted((y for y in years if n[y]), key=lambda y: (-n[y], -y))[:2]
    return {"cols": [{"n": n[y], "done": n[y], "h": n[y] / top, "dh": n[y] / top, "now": False,
                      "tip": f"{y}: {n[y]} usnesení", "abbr": str(y), "year_m": None} for y in years],
            "ticks": [{"v": v, "f": v / top} for v in range(0, top + 1, step)],
            "busiest": [f"v roce {y} ({n[y]})" for y in busiest],
            "label": "Usnesení podle let: " + ", ".join(f"{y} {n[y]}" for y in years)}


# --- reading ----------------------------------------------------------------------------------

def street_reports(obvod: str, name: str) -> list[dict]:
    """Every report filed under the street (its name as Dej Tip writes it, case and accents
    aside), newest first, with what the map's card shows."""
    from ..podnety.queries import street_rows
    return sorted(street_rows(obvod, fold(name)), key=lambda r: (r["reported_at"], r["id"]), reverse=True)


def resolutions(name: str, limit: int = 300) -> tuple[list[dict], int]:
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
        href = cq.street_url(xs[0]["slug"])
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
                        "box": short_until(a, b, today) if dated else when, "lng": lng, "lat": lat, "date": n["published"],
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
