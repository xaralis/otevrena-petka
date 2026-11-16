"""What is new in the streets someone follows: one list of events for the RSS feed of chosen
streets (and, later, its push notifications).

An event is a report filed in the street or resolved there (Dej Tip), a notice of the board that
names it, a resolution that mentions it, and a cleaning of it a week before it comes. Events of the
last WINDOW days, newest first; nothing about the reader is stored (the streets are in the URL).

`events` takes the sources as functions, so tests pass fakes and need no database.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Callable
from zoneinfo import ZoneInfo

from ..cisteni import words as cw
from ..podnety import source as psource, stats as ps
from . import queries as q

TZ = ZoneInfo("Europe/Prague")
WINDOW = 60             # days back the feed reaches
AHEAD = 7               # a cleaning shows up this many days before it
LIMIT = 80              # items in the feed at most
NB = " "


@dataclass(frozen=True)
class Event:
    key: str            # stable: a reader's guid, a notification's id
    kind: str           # podnet | vyreseno | deska | usneseni | cisteni
    at: dt.datetime     # when it happened (a cleaning: when it shows up, AHEAD days before)
    street: str
    title: str
    text: str
    path: str           # where on the portal (or an absolute link)
    head: str = ""      # a row of the page's preview: its bold line,
    sub: str = ""       # its grey line,
    status: tuple = ("", "")   # and its status word with its class (st-no: waiting, ul-done: past)


@dataclass
class Sources:
    reports: Callable[[str], list[dict]]            # a street's reports (podnety.queries.street_rows)
    notices: Callable[[str, dt.date], list[dict]]   # notices naming a street, posted since
    resolutions: Callable[[str], list[dict]]        # resolutions mentioning a street
    cleanings: Callable[[str], list[dict]]          # the street's cleanings this year (cisteni items)


def sources(obvod: str) -> Sources:
    """The sources from the database: the obvod's reports, notices, resolutions and this year's
    cleanings (read once)."""
    from ..cisteni import queries as cq
    from ..podnety.queries import street_rows
    from . import streets as st
    its = cq.items(obvod, cq.year_start(dt.date.today()))
    return Sources(reports=lambda name: street_rows(obvod, st.fold(name)), notices=q.street_notices,
                   resolutions=lambda name: q.resolutions(name)[0],
                   cleanings=lambda name: [i for i in its if i["street"] == name])


def _local(d: dt.datetime | dt.date, hour: int = 8) -> dt.datetime:
    if isinstance(d, dt.datetime):
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    return dt.datetime.combine(d, dt.time(hour), TZ)


def street_events(name: str, slug: str, src: Sources, now: dt.datetime) -> list[Event]:
    since = now - dt.timedelta(days=WINDOW)
    page = f"/verejny-prostor/ulice/{slug}"
    out: list[Event] = []
    for r in src.reports(name):
        at = _local(r["reported_at"])
        if at >= since:
            out.append(Event(f"podnet-{r['id']}", "podnet", at, name, f"{name}: nový podnět – {r['category']}",
                             (r.get("description") or "").strip() or f"Podnět z Dej Tipu, stav {ps.status_word(r)[0]}.",
                             psource.detail(r["id"]), r["category"], f"{name}, nový podnět",
                             ("čeká", "st-no") if ps.outcome(r) == "ceka" else (ps.status_word(r)[0], "")))
        done = r.get("resolved_seen_at")
        if done and ps.outcome(r) == "vyreseno" and _local(done) >= since:
            days = max(0, (_local(done).date() - at.date()).days)
            out.append(Event(f"vyreseno-{r['id']}", "vyreseno", _local(done), name, f"{name}: vyřešeno – {r['category']}",
                             f"Podnět z {q.dmy(at.date())} je podle Dej Tipu vyřešený, po {days} {cw.plural(days, 'dni', 'dnech', 'dnech')}.",
                             psource.detail(r["id"]), r["category"], f"{name}, vyřešený podnět", ("vyřešeno", "")))
    for n in src.notices(name, since.date()):
        out.append(Event(f"deska-{n['id']}", "deska", _local(n["published"]), name,
                         f"{name}: na úřední desce – {n.get('card') or n['title']}",
                         f"Oznámení, které jmenuje ulici {name}." + (f" Úředně: {n['title']}" if n.get("card") else ""),
                         f"/radnice/uredni-deska/{n['id']}", "Úřední deska", f"{name}, {n.get('card') or n['title']}"))
    for r in src.resolutions(name):
        at = _local(r["date"])
        if at >= since:
            body = "zastupitelstvo" if r["body"] == "zmo" else "rada"
            out.append(Event(f"usneseni-{r['uid']}", "usneseni", at, name,
                             f"{name}: {body} – {r['title'] or r.get('agenda_title') or 'usnesení ' + r['number']}",
                             f"Usnesení {r['number']} ze dne {q.dmy(r['date'])} zmiňuje ulici {name}.",
                             f"/radnice/usneseni/{r['uid']}", f"Usnesení {r['number']}",
                             f"{name}, {r['title'] or r.get('agenda_title') or body}"))
    for d in sorted({i["date"] for i in src.cleanings(name)}):
        shows = _local(d - dt.timedelta(days=AHEAD), 18)
        if since <= shows <= now:
            its = [i for i in src.cleanings(name) if i["date"] == d]
            where = cw.where(its)
            out.append(Event(f"cisteni-{slug}-{d:%Y%m%d}", "cisteni", shows, name,
                             f"{name}: blokové čištění {cw.WD[d.weekday()]} {q.dm(d)}",
                             f"Čistí se {where}{', ' + cw.clock(its[0]) if cw.clock(its[0]) else ''}. Auto přeparkujte nejpozději večer předem.",
                             f"{page}#cisteni", "Blokové čištění",
                             f"{name}, {cw.WD[d.weekday()]} {q.dm(d)}{' ' + cw.clock(its[0]) if cw.clock(its[0]) else ''}",
                             ("proběhlo", "ul-done") if d < now.date() else (cw.until(d, now.date()), "")))
    return out


KINDS = (("podnety", "Podněty z Dej Tipu", "Dej Tip je městská aplikace, kde lidé hlásí problémy ve veřejném prostoru, "
             "třeba černou skládku, rozbité dětské hřiště nebo díru v chodníku. Dáme vám vědět o novém hlášení i o tom, kdy se vyřeší."),
         ("deska", "Úřední deska", "Oficiální zprávy z úřadu městského obvodu: uzavírky, stavby, prodeje pozemků "
             "a další oznámení, která se týkají vybraných ulic."),
         ("usneseni", "Usnesení", "Co o ulici rozhodla rada nebo zastupitelstvo, třeba oprava chodníku nebo nová zakázka."),
         ("cisteni", "Blokové čištění", "Týden předem: kdy se v ulici čistí a do kdy musíte přeparkovat."))
PREVIEW = 60            # days the page's preview shows, and its counts by kind cover
GROUP = {"podnet": "podnety", "vyreseno": "podnety", "deska": "deska", "usneseni": "usneseni", "cisteni": "cisteni"}


def events(streets: list[tuple[str, str]], src: Sources, now: dt.datetime, kinds: set[str] | None = None) -> list[Event]:
    """The events of the streets ((name, slug) pairs) of the chosen kinds (KINDS keys; None: every
    one), newest first, at most LIMIT."""
    seen, out = set(), []
    for name, slug in streets:
        for e in street_events(name, slug, src, now):
            if kinds is not None and GROUP[e.kind] not in kinds:
                continue
            if e.key not in seen:
                seen.add(e.key)
                out.append(e)
    return sorted(out, key=lambda e: (e.at, e.key), reverse=True)[:LIMIT]


def rss(evs: list[Event], names: list[str], base: str, self_url: str) -> str:
    """RSS 2.0 of the events."""
    from email.utils import format_datetime
    from xml.sax.saxutils import escape
    title = "Otevřená Pětka – " + (names[0] if len(names) == 1 else ", ".join(names[:3]) + ("…" if len(names) > 3 else ""))
    items = []
    for e in evs:
        link = e.path if e.path.startswith("http") else base + e.path
        items.append(f"""<item><title>{escape(e.title)}</title><link>{escape(link)}</link><guid isPermaLink="false">{base}/feed/{e.key}</guid>
<description>{escape(e.text)}</description><category>{e.kind}</category><pubDate>{format_datetime(e.at)}</pubDate></item>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>
<title>{escape(title)}</title><link>{base}/verejny-prostor/ulice</link>
<atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>
<description>Co je nového ve vybraných ulicích městského obvodu Pardubice V: podněty z Dej Tipu, úřední deska, usnesení a blokové čištění týden předem.</description>
<language>cs</language>
{chr(10).join(items)}
</channel></rss>"""
