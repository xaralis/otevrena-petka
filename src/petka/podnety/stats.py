"""What the /verejny-prostor/zavady page says about the reports of one period: how many, how they stand, how
long they take, by month, by category and on the map. Pure functions over report rows
(dicts as stored in citizen_reports), testable without a database.

Every report has one outcome:
  vyreseno  Dej Tip status 3
  ceka      statuses 1 Evidováno, 2 V řešení, 9 Zařazeno do plánu
  jinam     statuses 6 Nepřísluší and 8 Předáno, and every report of a FORWARDED category
  nelze     status 4
FORWARDED categories are handled outside the office (the strážníci, the transport company):
their reports stay "Evidováno" in Dej Tip for good, so counting them as waiting would blame the
obvod for what it never gets to solve."""

import datetime as dt
import math
import statistics
from dataclasses import dataclass

from . import words as w

RESOLVED = 3
UNRESOLVABLE = 4
WAITING = (1, 2, 9)
IN_PROGRESS = (2, 9)            # "v řešení" (9 = zařazeno do plánu), the rest of WAITING is only received
PASSED_ON = (6, 8)
FORWARDED = ("Městská policie", "Zastávky MHD")
OUTCOMES = ("vyreseno", "ceka", "jinam", "nelze")

MIN_MEDIAN = 5                  # fewer resolved reports with a note than this: no "obvykle za"
MIN_HIGHLIGHT = 10              # a category needs this many reports in the period to be highlighted
CELL = 150                      # metres, the grid of a street page's map (ulice)
TOP = 5                         # "Čeho se týkají": this many categories, then "ostatní"


def forwarded(r: dict) -> bool:
    return r["category"] in FORWARDED


def outcome(r: dict) -> str:
    if forwarded(r) or r["status"] in PASSED_ON:
        return "jinam"
    if r["status"] == RESOLVED:
        return "vyreseno"
    if r["status"] == UNRESOLVABLE:
        return "nelze"
    return "ceka"


# --- the period -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Period:
    key: str                    # "12m" or the year
    start: dt.date              # inclusive
    end: dt.date                # exclusive
    phrase: str                 # "za posledních 12 měsíců", "v roce 2025"
    phrase_m: str               # the phone's shorter "za 12 měsíců"

    def months(self) -> list[tuple[int, int]]:
        y, m, out = self.start.year, self.start.month, []
        last = self.end - dt.timedelta(days=1)
        while (y, m) <= (last.year, last.month):
            out.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out


def period(key: str, today: dt.date) -> Period:
    """'12m' (default; from this day a year ago through today) or a calendar year (up to
    today if it is this year). Anything else is the default."""
    if key.isdigit() and 2000 <= int(key) <= today.year:
        y = int(key)
        end = dt.date(y + 1, 1, 1) if y < today.year else today + dt.timedelta(days=1)
        return Period(key, dt.date(y, 1, 1), end, f"v roce {y}", f"v roce {y}")
    start = today.replace(year=today.year - 1, day=28 if (today.month, today.day) == (2, 29) else today.day)
    return Period("12m", start, today + dt.timedelta(days=1), "za posledních 12 měsíců", "za 12 měsíců")


def switch(years: list[int], current: str) -> list[dict]:
    """The period switch: 12 months first, then each year with data, newest first."""
    out = [{"key": "12m", "label": "Posledních 12 měsíců", "label_m": "12 měsíců", "on": current == "12m"}]
    out += [{"key": str(y), "label": str(y), "label_m": str(y), "on": current == str(y)}
            for y in sorted(set(years), reverse=True)]
    return out


# --- durations ------------------------------------------------------------------------------

def hours_between(a: dt.datetime | None, b: dt.datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds() / 3600)


def resolution_days(r: dict) -> float | None:
    """From the report to the office's last note (for a closed report, about when it closed)."""
    h = hours_between(r["reported_at"], r.get("last_note_at"))
    return None if h is None else h / 24


def response_hours(r: dict) -> float | None:
    return hours_between(r["reported_at"], r.get("first_note_at"))


def buckets(values: list[float | None], edges: list[float], labels: list[tuple[str, str]],
            none: tuple[str, str] | None = None) -> list[dict]:
    """Counts of values below each edge, then above the last; None into the `none` bucket
    (muted, last). Each with its share of all values in percent."""
    counts = [0] * (len(edges) + 1)
    missing = 0
    for v in values:
        if v is None:
            missing += 1
            continue
        counts[next((i for i, e in enumerate(edges) if v < e), len(edges))] += 1
    total = len(values) or 1
    out = [{"label": l, "label_m": lm, "n": n, "pct": round(100 * n / total, 1), "muted": False}
           for (l, lm), n in zip(labels, counts)]
    if none:
        out.append({"label": none[0], "label_m": none[1], "n": missing, "pct": round(100 * missing / total, 1),
                    "muted": True})
    return out


RESOLVED_IN = ([1, 7, 30], [("do 1 dne", "do 1 dne"), ("1 až 7 dní", "1–7 dní"), ("1 až 4 týdny", "1–4 týdny"),
                            ("déle než měsíc", "přes měsíc")], ("úřad nic nenapsal", "bez odpovědi"))
WAITING_FOR = ([7, 30, 91], [("do týdne", "do týdne"), ("1 až 4 týdny", "1–4 týdny"),
                             ("1 až 3 měsíce", "1–3 měsíce"), ("déle než 3 měsíce", "přes 3 měsíce")], None)
ANSWERED_IN = ([4, 24, 72], [("do 4 hodin", "do 4 hodin"), ("4 až 24 hodin", "4–24 hodin"), ("1 až 3 dny", "1–3 dny"),
                             ("déle než 3 dny", "přes 3 dny")], ("zatím bez odpovědi", "bez odpovědi"))


def median_days(rs: list[dict]) -> str:
    """"Vyřešeno obvykle za": the median resolution of resolved reports with a note, or "–"
    with fewer than MIN_MEDIAN of them."""
    ds = [d for d in (resolution_days(r) for r in rs if outcome(r) == "vyreseno") if d is not None]
    return w.days(statistics.median(ds)) if len(ds) >= MIN_MEDIAN else "–"


# --- by month -------------------------------------------------------------------------------

def nice_step(top: int) -> int:
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if top / s <= 4:
            return s
    return 10000


def months(rows: list[dict], p: Period, today: dt.date) -> dict:
    """The column chart: every month of the period (empty ones too), its count and resolved,
    the running month flagged `now`; ticks; the two busiest months for the sentence."""
    by = {ym: [0, 0] for ym in p.months()}
    for r in rows:
        ym = (r["reported_at"].year, r["reported_at"].month)
        if ym in by:
            by[ym][0] += 1
            by[ym][1] += outcome(r) == "vyreseno"
    step = nice_step(max([n for n, _ in by.values()] + [1]))
    top = step * max(1, math.ceil(max([n for n, _ in by.values()] + [1]) / step))
    cols, prev_year = [], None
    names = [m for _, m in by]
    for i, ((y, m), (n, done)) in enumerate(by.items()):
        tip = f"{w.MONTH[m - 1]} {y}"
        if i == 0 and p.start.day > 1:
            tip += f" (od {w.dm(p.start)})"
        now = (y, m) == (today.year, today.month) and p.end > today
        if now:
            tip += f" (do {w.dm(today)})"
        cols.append({"y": y, "m": m, "n": n, "done": done, "now": now, "h": n / top, "dh": done / top,
                     "tip": f"{tip}: {w.podnetu(n)}, vyřešeno {done}",
                     "abbr": w.MONTH_ABBR[m - 1], "year_m": y if y != prev_year else None})
        prev_year = y
    busiest = sorted((c for c in cols if c["n"]), key=lambda c: (-c["n"], -c["y"], -c["m"]))[:2]

    def where(c):
        return w.MONTH_IN[c["m"] - 1] + (f" {c['y']}" if names.count(c["m"]) > 1 else "")

    top_c = busiest[0] if busiest else None
    return {"cols": cols, "ticks": [{"v": v, "f": v / top} for v in range(0, top + 1, step)],
            "busiest": [f"{where(c)} ({c['n']})" for c in busiest],
            "label": (f"Počet podnětů po měsících od {w.MONTH_GEN[cols[0]['m'] - 1]} {cols[0]['y']} do "
                      f"{w.MONTH_GEN[cols[-1]['m'] - 1]} {cols[-1]['y']}"
                      + (f"; nejvíc {w.MONTH_IN[top_c['m'] - 1]} {top_c['y']} ({top_c['n']})" if top_c else ""))}


# --- by category ----------------------------------------------------------------------------

def categories(rows: list[dict]) -> list[dict]:
    """One row per category: the obvod's own by count (Jiné last), then the forwarded ones."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["category"], []).append(r)
    out = []
    for name, rs in by.items():
        n = len(rs)
        c = {o: sum(outcome(r) == o for r in rs) for o in OUTCOMES}
        out.append({"id": rs[0]["category_id"], "name": name, "n": n, **c,
                    "forwarded": name in FORWARDED, "note": w.FORWARDED_NOTE.get(name),
                    "median": "–" if name in FORWARDED else median_days(rs),
                    "pct": {o: round(100 * c[o] / n, 1) for o in OUTCOMES}})
    out.sort(key=lambda c: (c["forwarded"], c["name"] == "Jiné", -c["n"], c["name"]))
    return out


def highlight(rows: list[dict], cats: list[dict], p: Period) -> dict | None:
    """The category with the worst waiting share among those with MIN_HIGHLIGHT reports."""
    pool = [c for c in cats if not c["forwarded"] and c["n"] >= MIN_HIGHLIGHT and c["ceka"]]
    if not pool:
        return None
    c = max(pool, key=lambda c: (c["ceka"] / c["n"], c["n"]))
    short, full, phone = w.phrase(c["name"])
    oldest = min((r for r in rows if r["category"] == c["name"] and outcome(r) == "ceka"),
                 key=lambda r: r["reported_at"])
    return {**c, "title": f"Nejdéle čekají podněty {short}", "title_m": f"Nejdéle čekají {phone}",
            "full": full, "oldest": oldest["reported_at"].date(), "street": oldest["street"]}


# --- the map ---------------------------------------------------------------------------------

STAV = (("ceka", "Čeká"), ("vyreseno", "Vyřešeno"), ("", "Vše"))     # the filter above the map, waiting first
LIST = 15                       # rows of the list beside the map, and how many "Další podněty" adds


def stav_key(v: str) -> str:
    """The state filter from the address: none means the default, the waiting reports; "vse"
    means every state (matches() takes "" for that)."""
    if v == "vse":
        return ""
    return v if v in dict(STAV) and v else "ceka"


def stav_url(k: str) -> str:
    """The state filter as the address writes it: the default (waiting) left out, every state "vse"."""
    return "" if k == "ceka" else ("vse" if k == "" else k)


def druh_key(v: str, rows: list[dict]) -> int | None:
    """The category filter: a category id that the period has, else None (every category)."""
    v = (v or "").strip()
    return int(v) if v.isdigit() and any(r["category_id"] == int(v) for r in rows) else None


def matches(r: dict, stav: str = "", druh: int | None = None) -> bool:
    return (not stav or outcome(r) == stav) and (druh is None or r["category_id"] == druh)


def facets(rows: list[dict], stav: str, druh: int | None) -> dict:
    """The counts the filters show: each state within the chosen category, each category
    within the chosen state (in the table's order), as a faceted search does."""
    in_druh = [r for r in rows if matches(r, "", druh)]
    in_stav = [r for r in rows if matches(r, stav)]
    by: dict[int, int] = {}
    for r in in_stav:
        by[r["category_id"]] = by.get(r["category_id"], 0) + 1
    return {"stav": [{"key": k, "url": stav_url(k), "label": label, "n": sum(matches(r, k) for r in in_druh), "on": k == stav}
                     for k, label in STAV],
            "druh": [{"id": c["id"], "name": c["name"], "n": by.get(c["id"], 0), "on": c["id"] == druh}
                     for c in categories(rows)],
            "all": len(in_stav)}


def iso(t: dt.datetime | None) -> str | None:
    return t.isoformat(timespec="minutes") if t else None


def points(rows: list[dict], now: dt.datetime) -> dict:
    """Every report of the period as a point for the map and its card: category, street (no
    house number), the outcome as the page names it, the dates, how long it waits, the masked
    description and a public photo. The filters run in the browser over these."""
    feats = []
    for r in sorted(rows, key=lambda r: (r["reported_at"], r["id"]), reverse=True):
        o = outcome(r)
        props = {"id": r["id"], "o": o, "w": WORD[o][0], "k": r["category_id"], "c": r["category"],
                 "s": r["street"], "t": iso(r["reported_at"]), "a": iso(r.get("first_note_at")),
                 "d": r.get("description"), "p": r.get("photo_url")}
        if o == "ceka":
            props["wd"] = max(0, (now - r["reported_at"]).days)
        feats.append({"type": "Feature", "id": r["id"],
                      "geometry": {"type": "Point", "coordinates": [round(r["lng"], 6), round(r["lat"], 6)]},
                      "properties": {k: v for k, v in props.items() if v is not None}})
    if not feats:
        return {"type": "FeatureCollection", "features": [], "bounds": None}
    lngs = [f["geometry"]["coordinates"][0] for f in feats]
    lats = [f["geometry"]["coordinates"][1] for f in feats]
    return {"type": "FeatureCollection", "features": feats,
            "bounds": [[min(lngs), min(lats)], [max(lngs), max(lats)]]}


def grid(rows: list[dict], cell: float = CELL) -> dict:
    """The reports counted on a grid of about `cell` metres, one point per cell at its centre
    (never a report's own position): n, how many wait, and the categories with counts."""
    if not rows:
        return {"type": "FeatureCollection", "features": [], "bounds": None}
    lat0 = sum(r["lat"] for r in rows) / len(rows)
    dlat = cell / 111_320
    dlng = cell / (111_320 * math.cos(math.radians(lat0)))
    cells: dict[tuple[int, int], dict] = {}
    for r in rows:
        k = (math.floor(r["lat"] / dlat), math.floor(r["lng"] / dlng))
        c = cells.setdefault(k, {"n": 0, "waiting": 0, "cats": {}})
        c["n"] += 1
        c["waiting"] += outcome(r) == "ceka"
        c["cats"][r["category"]] = c["cats"].get(r["category"], 0) + 1
    feats = []
    for (i, j), c in sorted(cells.items(), key=lambda kv: -kv[1]["n"]):
        lat, lng = (i + .5) * dlat, (j + .5) * dlng
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lng, 5), round(lat, 5)]},
                      "properties": {"n": c["n"], "waiting": c["waiting"],
                                     "cats": sorted(c["cats"].items(), key=lambda kv: (-kv[1], kv[0]))}})
    lats = [f["geometry"]["coordinates"][1] for f in feats]
    lngs = [f["geometry"]["coordinates"][0] for f in feats]
    return {"type": "FeatureCollection", "features": feats,
            "bounds": [[min(lngs), min(lats)], [max(lngs), max(lats)]]}


# --- the page -------------------------------------------------------------------------------

def summary(rows: list[dict], p: Period, now: dt.datetime) -> dict:
    """Everything the page shows about the period's rows."""
    today = now.date()
    n = len(rows)
    count = {o: sum(outcome(r) == o for r in rows) for o in OUTCOMES}
    pct = {o: round(100 * count[o] / n, 1) if n else 0 for o in OUTCOMES}
    resolved = [r for r in rows if outcome(r) == "vyreseno"]
    waiting = [r for r in rows if outcome(r) == "ceka"]
    handled = [r for r in rows if not forwarded(r)]
    answered = [h for h in (response_hours(r) for r in handled) if h is not None]
    cats = categories(rows)

    by_cat: dict[tuple, int] = {}
    for r in waiting:
        by_cat[(r["category_id"], r["category"])] = by_cat.get((r["category_id"], r["category"]), 0) + 1
    top = sorted(by_cat.items(), key=lambda kv: (-kv[1], kv[0][1]))
    oldest = min(waiting, key=lambda r: r["reported_at"]) if waiting else None

    return {
        "n": n, "count": count, "pct": pct,
        "done_pct": round(100 * count["vyreseno"] / n) if n else 0,
        "first_response": w.hours(statistics.median(answered)) if answered else "–",
        "resolved_in": buckets([resolution_days(r) for r in resolved], *RESOLVED_IN),
        "silent_resolved": sum(r.get("last_note_at") is None for r in resolved),
        "waiting_for": buckets([(now - r["reported_at"]).total_seconds() / 86400 for r in waiting], *WAITING_FOR),
        "waiting_cats": [{"id": i, "name": nm, "n": k} for (i, nm), k in top[:TOP]],
        "waiting_rest": sum(k for _, k in top[TOP:]),
        "waiting_top_m": [f"{w.short(nm)} ({k})" for (_, nm), k in top[:3]],
        "in_progress": sum(r["status"] in IN_PROGRESS for r in waiting),
        "received": sum(r["status"] not in IN_PROGRESS for r in waiting),
        "oldest_waiting": oldest["reported_at"].date() if oldest else None,
        "answered_in": buckets([response_hours(r) for r in handled], *ANSWERED_IN),
        "handled": len(handled),
        "silent_resolved_handled": sum(r.get("first_note_at") is None for r in resolved if not forwarded(r)),
        "months": months(rows, p, today),
        "categories": cats,
        "highlight": highlight(rows, cats, p),
    }


WORD = {"vyreseno": ("vyřešeno", "st"), "ceka": ("čeká", "st st-no"), "jinam": ("předáno", "st"),
        "nelze": ("nelze vyřídit", "st")}


def status_word(r: dict) -> tuple[str, str]:
    """The status as the page writes it: (word, classes of the existing .st)."""
    return WORD[outcome(r)]
