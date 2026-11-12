"""Czech words for the čištění pages: plurals, dates, weekdays, the genitive of a street's
name, and the harmonogram grouped by week. Pure; templates get them via the section's
`template` hook."""

import datetime as dt

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
