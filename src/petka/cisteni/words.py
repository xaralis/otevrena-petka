"""Czech words for the čištění pages: plurals, dates, weekdays, the genitive of a street's
name, and the harmonogram grouped by week. Pure; templates get them via the section's
`template` hook."""

import datetime as dt
import re

from . import places

WEEKDAY = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
WD = ["po", "út", "st", "čt", "pá", "so", "ne"]
ON_DAY = ["v pondělí", "v úterý", "ve středu", "ve čtvrtek", "v pátek", "v sobotu", "v neděli"]
MONTH = ["Leden", "Únor", "Březen", "Duben", "Květen", "Červen", "Červenec", "Srpen", "Září", "Říjen",
         "Listopad", "Prosinec"]
SIDE_ON = {"obe": "na obou stranách ulice", "prava": "na pravé straně ulice", "leva": "na levé straně ulice"}
PREPOSITIONS = {"k", "ke", "na", "v", "ve", "u", "pod", "za", "nad", "pred", "mezi", "do", "po", "pri"}


def plural(n: int, one: str, few: str, many: str) -> str:
    """Czech plural: 1 ulice, 2–4 ulice, 5+ ulic (0 counts as many)."""
    return one if n == 1 else few if 2 <= n <= 4 else many


def dm(d: dt.date) -> str:
    return f"{d.day}. {d.month}."


def clock(i: dict) -> str:
    """'od 7:00', 'před 6:00' or '' (the sheet didn't say)."""
    t = i["time"]
    return f"{'před' if i['before'] else 'od'} {t.hour}:{t.minute:02d}" if t else ""


def until(d: dt.date, today: dt.date) -> str:
    n = (d - today).days
    return "dnes" if n == 0 else "zítra" if n == 1 else f"za {n} {plural(n, 'den', 'dny', 'dní')}"


NB = " "
SIDE_PO = {"obe": "po obou stranách", "prava": "po pravé straně", "leva": "po levé straně"}
_SIDE_END = re.compile(r",\s*(obě strany|pravá strana|levá strana)$")
_SIDE_WORD = {"obě strany": "obe", "pravá strana": "prava", "levá strana": "leva"}
# a short wording that starts with one of these is an ordinary noun, lowercase after „Čistí se“
_COMMON = ("vnitroblo", "mistni", "komunikace", "parkoviste", "chodnik", "propoj", "spojovaci")


def nbdm(d: dt.date) -> str:
    """'9. 12.' kept on one line."""
    return f"{d.day}.{NB}{d.month}."


def where(its: list[dict]) -> str:
    """What is cleaned on one day of a street, to follow „Čistí se “: 'v celé ulici, po obou
    stranách', 'od kpt. Nálepky k Wolkerova, po pravé straně', 'parkoviště před č. p. 1'. Names
    stay in the case the harmonogram uses."""
    parts: list[tuple[str, str | None]] = []
    for i in its:
        if i["method"] == "whole" or not i["short"] or i["short"].startswith("v celé délce"):
            text, side = "v celé ulici", i["side"]
        else:
            text, side = i["short"], None
            m = _SIDE_END.search(text)
            if m:
                text, side = text[:m.start()], _SIDE_WORD[m[1]]
            if places.fold(text).startswith(_COMMON):
                text = text[:1].lower() + text[1:]
        if (text, side) not in parts:
            parts.append((text, side))
    sides = {s for _, s in parts}
    if len(parts) > 1 and len(sides) == 1:
        side = sides.pop()
        texts = [t for t, _ in parts]
        joined = ("; ".join(texts) if any("," in t for t in texts) else
                  ", ".join(texts[:-1]) + " a " + texts[-1])
        return joined + (f", {SIDE_PO[side]}" if side in SIDE_PO else "")
    return "; ".join(t + (f", {SIDE_PO[s]}" if s in SIDE_PO else "") for t, s in parts)


def next_panel(on_next: list[dict], today: dt.date) -> dict:
    """The street page's „Příští čištění“ panel for the places cleaned on the next date: the
    countdown line (`lead` + bold `count`), the heading (`on` + red `date` + `clock`), what is
    cleaned (`where`), by when to move the car (`move` + bold `by`) and the sign's plate."""
    first = on_next[0]
    d = first["date"]
    n = (d - today).days
    if n == 0:
        lead, count = "Čistí se ", "dnes"
    elif n == 1:
        lead, count = "Příští čištění ", "zítra"
    else:
        lead, count = "Příští čištění za ", f"{n}{NB}{plural(n, 'den', 'dny', 'dní')}"
    eve = d - dt.timedelta(days=1)
    if n == 0:
        move, by = "Auto přeparkujte ", "co nejdřív"
    elif n == 1:
        move, by = "Auto přeparkujte nejpozději ", "dnes večer"
    else:
        move, by = "Auto přeparkujte nejpozději ", f"{ON_DAY[eve.weekday()]} {nbdm(eve)} večer"
    on = ON_DAY[d.weekday()]
    return {"lead": lead, "count": count, "on": on[:1].upper() + on[1:], "date": nbdm(d),
            "clock": clock(first).replace(" ", NB), "where": where(on_next), "move": move, "by": by,
            "plate": [nbdm(d), clock(first).replace(" ", NB)]}


def genitive(name: str) -> str:
    """'Wolkerova' -> 'Wolkerovy', 'Sokolovská' -> 'Sokolovské'; a name that is already in the
    genitive ('Josefa Ressla', 'Gorkého', 'Čs. armády') stays; one that can't be declined
    simply ('K Barvírně', 'Na Záboří') gets 'ulice'."""
    words = name.split()
    first = places.fold(words[0]).rstrip(".")
    if first in PREPOSITIONS:
        return f"ulice {name}"
    if len(words) == 2 and places.fold(words[1]) == "trida" and words[0].endswith("a"):
        return f"{words[0][:-1]}y třídy"
    if len(words) > 1 or name.endswith(("ého", "ho", "ů", "ých")):
        return name
    if name.endswith("ova"):
        return name[:-1] + "y"
    if name.endswith("á"):
        return name[:-1] + "é"
    return f"ulice {name}"


def _simple(name: str) -> bool:
    """A one-word adjective name we decline ('Wolkerova', 'Sokolovská'); the rest get 'ulice'."""
    return " " not in name and name.endswith(("ova", "á"))


def accusative(name: str) -> str:
    """'Wolkerova' -> 'Wolkerovu', 'Sokolovská' -> 'Sokolovskou', else 'ulici Josefa Ressla'."""
    if not _simple(name):
        return f"ulici {name}"
    return name[:-1] + ("u" if name.endswith("ova") else "ou")


def locative(name: str) -> str:
    """With its preposition: 'v Jiránkově', 've Wolkerově', 'v Sokolovské', else 'v ulici
    Josefa Ressla'."""
    if not _simple(name):
        return f"v ulici {name}"
    word = name[:-1] + ("ě" if name.endswith("ova") else "é")
    return ("ve " if places.fold(name[0]) in "vfw" else "v ") + word


def span(a: dt.date, b: dt.date) -> str:
    """'16.–22. 11.', '30. 11.–6. 12.', '18. 11.'."""
    if a == b:
        return dm(a)
    return f"{a.day}.–{dm(b)}" if a.month == b.month else f"{dm(a)}–{dm(b)}"


def weeks(its: list[dict], today: dt.date) -> list[dict]:
    """Items grouped by week from this one: "Tento týden", "Příští týden", "Za dva týdny", then
    by month (of the week's Thursday, so a week stays whole)."""
    monday = today - dt.timedelta(days=today.weekday())
    groups: list[dict] = []
    for i in its:
        w = (i["date"] - monday).days // 7
        start = monday + dt.timedelta(weeks=w)
        if w <= 2:
            label = ["Tento týden", "Příští týden", "Za dva týdny"][max(w, 0)]
            key = ("w", w)
            rng = span(max(start, today) if w == 0 else start, start + dt.timedelta(days=6))
        else:
            thu = start + dt.timedelta(days=3)
            key, label, rng = ("m", thu.year, thu.month), MONTH[thu.month - 1], None
        if not groups or groups[-1]["key"] != key:
            groups.append({"key": key, "label": label, "range": rng, "items": []})
        groups[-1]["items"].append(i)
    for g in groups:
        if g["range"] is None:
            g["range"] = span(g["items"][0]["date"], g["items"][-1]["date"])
    return groups


def merged(its: list[dict]) -> list[dict]:
    """Items of one day joined into one row ("Devotyho, Gorkého, … – 3 úseky, obě strany"), as
    the phone list shows later months."""
    out = []
    for i in its:
        if out and out[-1]["date"] == i["date"]:
            out[-1]["all"].append(i)
        else:
            out.append({**i, "all": [i]})
    for o in out:
        n = len(o["all"])
        if n > 1:
            o["street"] = ", ".join(dict.fromkeys(x["street"] for x in o["all"]))
            sides = {x["side"] for x in o["all"]}
            o["short"] = f"{n} {plural(n, 'úsek', 'úseky', 'úseků')}" + (
                f", {places.SIDE_TEXT[sides.pop()]}" if len(sides) == 1 and None not in sides else "")
            o["status"] = "auto" if all(x["status"] == "auto" for x in o["all"]) else "approx"
            o["located"] = all(x["located"] for x in o["all"])
    return out


TEMPLATE_GLOBALS = {"cl_plural": plural, "cl_until": until}
TEMPLATE_FILTERS = {"cl_dm": dm, "cl_clock": clock,
                    "cl_wd": lambda d: WD[d.weekday()], "cl_weekday": lambda d: WEEKDAY[d.weekday()],
                    "cl_on": lambda d: ON_DAY[d.weekday()], "cl_month": lambda m: MONTH[m - 1],
                    "cl_cap1": lambda s: s[:1].upper() + s[1:]}
