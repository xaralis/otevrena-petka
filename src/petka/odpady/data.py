"""What the Odpady section knows, from files (no database): the year's harmonogram of the
velkoobjemové kontejnery (data/odpady/vok-<year>.yaml, transcribed from SmP's scanned PDF), the
separační dvory (dvory.json: in DATA_DIR as the `odpady-update` job last read it, else the image's
copy) and where each place lies (mista.yaml: a point, how it was found, approx).

`dates` turns a stanoviště's ISO weeks and day into dates; `status` says whether a yard is open
at a moment and when it opens or closes.
"""

import datetime as dt
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3] / "data" / "odpady"
DAYS = ("po", "út", "st", "čt", "pá", "so", "ne")
DAY_WORD = {"po": "pondělí", "út": "úterý", "st": "středa", "čt": "čtvrtek", "pá": "pátek", "so": "sobota", "ne": "neděle"}


@dataclass(frozen=True)
class Drop:
    """One přistavení of a kontejner."""
    key: str                # the stanoviště: its place's slug and day
    place: str              # „Češkova – Kašparova u školy“
    obvod: str              # the table's block (mo1–mo7)
    date: dt.date
    time: str               # „14.00–15.30“, „od 13.00“, ""
    note: str
    point: list | None      # [lon, lat]
    approx: bool


def _slug(s: str) -> str:
    import re
    from ..ulice.streets import fold
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")


@lru_cache
def places() -> dict[str, dict]:
    return yaml.safe_load((ROOT / "mista.yaml").read_text())["places"]


@lru_cache
def harmonogram(year: int) -> dict | None:
    f = ROOT / f"vok-{year}.yaml"
    return yaml.safe_load(f.read_text()) if f.exists() else None


def drops(year: int) -> list[Drop]:
    """Every přistavení of the year, by date."""
    h = harmonogram(year)
    if not h:
        return []
    out = []
    for s in h["sites"]:
        p = places().get(s["place"]) or {}
        for w in s["weeks"]:
            out.append(Drop(f"{_slug(s['place'])}-{s['day']}", s["place"], s["obvod"],
                            dt.date.fromisocalendar(year, w, DAYS.index(s["day"]) + 1), s.get("time", ""),
                            s.get("note", ""), p.get("point"), bool(p.get("approx"))))
    return sorted(out, key=lambda d: (d.date, d.place))


def yards() -> dict:
    """{file, checked, yards: [...]} as the job last read them, each with its point."""
    live = Path(os.environ.get("DATA_DIR", "")) / "odpady" / "dvory.json" if os.environ.get("DATA_DIR") else None
    d = json.loads((live if live and live.exists() else ROOT / "dvory.json").read_text())
    for y in d["yards"]:
        p = places().get(y["place"]) or {}
        y["point"], y["approx"] = p.get("point"), bool(p.get("approx"))
    return d


def _hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def status(y: dict, at: dt.datetime) -> tuple[bool, str]:
    """(open now, the words): „otevřeno do 17.00“, „otevře dnes ve 14.00“, „otevře út 13.00“."""
    fmt = lambda t: f"{t.hour}.{t.minute:02d}"
    today = DAYS[at.weekday()]
    for h in y["hours"]:
        if today in h["days"] and _hm(h["from"]) <= at.time() < _hm(h["to"]):
            return True, f"otevřeno do {fmt(_hm(h['to']))}"
    for k in range(0, 8):
        d = DAYS[(at.weekday() + k) % 7]
        starts = sorted(_hm(h["from"]) for h in y["hours"] if d in h["days"] and (k > 0 or _hm(h["from"]) > at.time()))
        if starts:
            word = "dnes" if k == 0 else ("zítra" if k == 1 else d)
            return False, f"otevře {word} {'ve' if starts[0].hour in (2, 3, 4, 12, 13, 14) else 'v'} {fmt(starts[0])}"
    return False, "zavřeno"


def hours_text(y: dict) -> str:
    """„po, út, čt, pá 6.30–15.00, st 6.30–17.00“."""
    fmt = lambda s: s.replace(":", ".")
    return ", ".join(f"{', '.join(h['days'])} {fmt(h['from'])}–{fmt(h['to'])}" for h in y["hours"])


# --- svoz směsného odpadu (svoz-tko.json, petka.odpady.svoz) -----------------------------------

@lru_cache
def svoz_rows() -> list[dict]:
    return json.loads((ROOT / "svoz-tko.json").read_text())["rows"]


def _days_text(days: list[str]) -> str:
    words = [DAY_WORD[d] for d in days]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " a " + words[-1]


def svoz(street: str) -> list[dict]:
    """The street's rows: [{who: "popelnice"|"kontejnery"|"", part, days, words}], words like „čtvrtek“
    or „pondělí a čtvrtek“."""
    return [{"who": r["bins"], "part": r["part"], "days": r["days"], "words": _days_text(r["days"])}
            for r in svoz_rows() if r.get("street") == street]


def svoz_text(street: str) -> str:
    """One line: „popelnice čtvrtek, kontejnery pondělí a čtvrtek“, „středa“, „" when unknown."""
    rows = svoz(street)
    if len({tuple(r["days"]) for r in rows}) == 1:          # the same days everywhere in the street
        return rows[0]["words"]
    parts = []
    for r in rows:
        who = " ".join(x for x in (r["who"], f"({r['part']})" if r["part"] and r["who"] else r["part"]) if x)
        parts.append(f"{who} {r['words']}".strip())
    return ", ".join(dict.fromkeys(parts))
