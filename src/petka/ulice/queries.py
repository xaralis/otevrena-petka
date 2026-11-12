"""What the front page and a street page put together from the other sections: blokové čištění
(petka.cisteni), podněty (petka.podnety), usnesení (full-text search, petka.usneseni.search)
and the úřední deska (petka.uredni_deska).

Reading is here; shaping (the next cleaning, the reports' counts, one dated feed of everything)
is pure and testable without a database. A feed item is a dict: date, source (the grey line),
text, href, and optionally status (word, classes of .st), vote (the resolution's main vote),
next (the next cleaning, drawn dark)."""

import datetime as dt
from dataclasses import dataclass

from .. import db
from ..cisteni import queries as cq
from ..cisteni.words import clock
from ..podnety import stats as ps
from ..usneseni import search as us
from ..uredni_deska.queries import tsquery as deska_tsquery

FEED_HOME = 7           # items of "Co se děje" on the front page
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
    return text, f"/blokove-cisteni/ulice/{slug}" if slug else "/blokove-cisteni"


def resolution_item(r: dict) -> dict:
    return {"date": r["date"], "source": "Zastupitelstvo" if r["body"] == "zmo" else "Rada",
            "number": r["number"], "text": r["title"] or r["agenda_title"] or f"Usnesení {r['number']}",
            "href": f"/usneseni/{r['uid']}", "vote": r.get("mainvote"), "body": r["body"]}


def report_item(r: dict, href: str) -> dict:
    return {"date": r["reported_at"].date(), "source": "Závady",
            "text": r["category"] + (f", {r['street']}" if r.get("street") else ""),
            "href": href, "status": ps.status_word(r)}


def notice_item(n: dict) -> dict:
    head = (n.get("digest") or {}).get("headline")
    return {"date": n["published"], "source": "Úřední deska", "text": head or n["title"],
            "href": f"/uredni-deska/{n['id']}"}


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


def latest_notices(n: int = 3) -> list[dict]:
    from ..uredni_deska import queries as dq
    # deliveries to named people are not news (and personal), as on /prehled
    return [x for x in dq.search(limit=20)[0] if x["kind"] != "doruceni"][:n]
