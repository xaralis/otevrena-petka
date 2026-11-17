"""Parkování: the page /verejny-prostor/parkovani (free places now by area and by lot, the typical
week and the busiest lots, always of the whole town; an area's or a lot's row
opens its own typical week under it: /oblast/{id} and /parkoviste/{id} are those parts), and the API for the app and
anyone else (docs/parkovani.md), all over the whole town with `?obvod=` (ADR 0002):

    /api/v1/parkovani               lots, machines, zones, localities, sections, prices, SMS codes (daily)
    /api/v1/parkovani/obsazenost    free and total places per lot (every 60 s)
    /api/v1/parkovani/statistiky    the typical week and the busiest lots from the history

Every answer has a weak ETag (petka.web.etag); If-None-Match with it gives 304.
"""

import datetime as dt
import time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..obvody import ObvodFilter, ObvodParam
from ..web import etag
from ..web.render import tpl
from . import build, data, stats
from . import queries as q

pages = APIRouter(prefix="/verejny-prostor/parkovani", include_in_schema=False)
api = APIRouter(prefix="/api/v1/parkovani", tags=["parkování"])
TZ = ZoneInfo("Europe/Prague")
NB = " "
CACHE = "public, max-age=3600"
LIVE_CACHE = "public, max-age=30"
STATS_CACHE = "public, max-age=600"
STATS_TTL = 600             # s: the statistics are worked out again at most this often
DAYS = 28                   # the statistics' default window
DAYS_ALLOWED = (7, 28, 91)  # the windows the API offers: a few, so that the cache of answers stays small
STATS_MAX = 64              # answers kept at most (expired ones go first, then the oldest)
SOURCE_URL = "https://pardubice.chytrejsiparking.cz/"
NOTE = ("Obsazenost je z neoficiálního rozhraní aplikace správce parkovišť (ChytřejšíParking, DPMP), čas měření "
        "zdroj neuvádí. `changed_at` je, kdy Otevřená Pětka naposledy viděla změnu čísel parkoviště, "
        "`fetched_at` poslední úspěšné stažení.")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --- /api/v1/parkovani --------------------------------------------------------------------------

@api.get("")
def parkovani(request: Request, obvod: ObvodParam):
    """Parkování v Pardubicích jako jeden soubor pro aplikaci: parkoviště správce (poloha, kapacita,
    druh, zóna, lokalita, SMS kód, ceník podle nařízení), automaty, hranice zón A, B, C, přilehlá
    oblast zóny B, lokality s návštěvnickými místy a ceníky, placené úseky ulic a SMS kódy DPMP.
    Parkoviště se obnovují jednou denně, ostatní jsou ručně udržovaná data se zdrojem a datem ověření
    (`sources`). `?obvod=` zúží parkoviště, automaty a úseky; zóny, lokality, ceník a SMS kódy jsou
    pravidla celého města a přijdou vždy celé. Volná místa jsou v `/api/v1/parkovani/obsazenost`."""
    b = q.built()
    if b is None:
        raise HTTPException(503, "Parkoviště ještě nejsou stažená, zkuste to později.")
    tag = etag.weak(b[0], build.iso(b[1]), data.version(), ",".join(obvod.ids))
    headers = {"ETag": tag, "Cache-Control": CACHE}
    if etag.fresh(request, tag):
        return etag.not_modified(headers)
    doc = q.document(b[0])
    return JSONResponse(build.narrowed(doc, obvod), headers=headers)


# --- /api/v1/parkovani/obsazenost ---------------------------------------------------------------

def occupancy(fetched_at: dt.datetime, rows: list[dict], lot_obvody: dict[str, list[str]], obvod: ObvodFilter) -> dict:
    """The live answer: every lot's free and total places with when they last changed."""
    lots = [{"id": r["id"], "free": r["free"], "total": r["total"], "changed_at": build.iso(r["changed_at"]),
             "obvody": lot_obvody.get(r["id"], [])} for r in rows]
    return {"v": 1, "fetched_at": build.iso(fetched_at), "source": build.SOURCE, "note": NOTE,
            "lots": [x for x in lots if obvod.matches(x["obvody"])]}


@api.get("/obsazenost")
def obsazenost(request: Request, obvod: ObvodParam):
    """Volná a celková místa na parkovištích teď, podle čidel správce (ChytřejšíParking). Otevřená
    Pětka se ptá každých 60 s. `changed_at`: kdy Pětka naposledy viděla změnu čísel parkoviště
    (zdroj čas měření neuvádí); `fetched_at`: poslední úspěšné stažení. Při výpadku zdroje zůstanou
    poslední dobrá čísla a `fetched_at` stárne. ETag se mění s každým úspěšným stažením."""
    st = q.state()
    if not st or not st["fetched_at"]:
        raise HTTPException(503, "Obsazenost ještě není stažená, zkuste to později.")
    b = q.built()
    tag = etag.weak(build.iso(st["fetched_at"]), b[0] if b else "", ",".join(obvod.ids))
    headers = {"ETag": tag, "Cache-Control": LIVE_CACHE}
    if etag.fresh(request, tag):
        return etag.not_modified(headers)
    return JSONResponse(occupancy(st["fetched_at"], q.now_rows(), q.lot_obvody(), obvod), headers=headers)


# --- /api/v1/parkovani/statistiky ---------------------------------------------------------------

_stats: dict = {}


def _remember(key, value) -> None:
    """Keep one answer in the bounded cache: expired entries are dropped, and while it is still
    full, the oldest one."""
    now = time.monotonic()
    for k in [k for k, (t, _) in _stats.items() if now - t >= STATS_TTL]:
        del _stats[k]
    while len(_stats) >= STATS_MAX:
        del _stats[min(_stats, key=lambda k: _stats[k][0])]
    _stats[key] = (now, value)


def statistics(obvod: ObvodFilter, days: int, profiles: bool) -> dict:
    """The statistics of the obvody over the last `days` days, worked out at most every STATS_TTL s."""
    key = (obvod.ids, days, profiles)
    hit = _stats.get(key)
    if hit and time.monotonic() - hit[0] < STATS_TTL:
        return hit[1]
    lot_obvody, names = q.lot_obvody(), q.lot_names()
    ids = None if obvod.whole_town else [k for k, o in lot_obvody.items() if obvod.matches(o)]
    to = _now()
    since = to - dt.timedelta(days=days)
    rows = q.history_rows(since, ids)
    span = q.history_span()
    first = span.get("first")
    out = {"v": 1, "days": days, "from": build.iso(max(since, first) if first else since), "to": build.iso(span.get("last") or to),
           "history_from": build.iso(first), "source": build.SOURCE,
           "note": ("Podíl obsazených míst (0–1) podle vzorků po 5 minutách; `full` = podíl vzorků, kdy byla volná "
                    "nejvýš desetina míst. Mřížky jsou 7 dní (pondělí první) × 24 hodin pražského času, null = bez dat."),
           "profile": stats.grid(rows), "lots": stats.lots(rows, names, lot_obvody, profiles),
           "areas": stats.areas(rows, data.payload("areas"), profiles)}
    _remember(key, out)
    return out


@api.get("/statistiky")
def statistiky(request: Request, obvod: ObvodParam,
               dni: int = Query(DAYS, description="Za kolik posledních dní: 7, 28 nebo 91."),
               profily: bool = Query(False, description="Přidat ke každému parkovišti jeho typický týden.")):
    """Statistiky obsazenosti z historie (vzorek každých 5 minut): typický týden (průměrná obsazenost
    podle dne v týdnu a hodiny, `profile`), parkoviště od nejvytíženějšího (`lots`: průměrná
    obsazenost, podíl času, kdy bylo plno) a oblasti, jak o nich mluví lidé (`areas`: centrum,
    U Mlýnů…, součet jejich parkovišť). S `?profily=true` i typický týden každého parkoviště
    a oblasti, např. pro „v tuhle dobu tu bývá plno“. Přepočítává se nejvýš každých 10 minut."""
    if dni not in DAYS_ALLOWED:
        raise HTTPException(422, f"Neplatné dni: {dni}. Platné jsou {', '.join(map(str, DAYS_ALLOWED))}.")
    out = statistics(obvod, dni, profily)
    tag = etag.weak(out["to"], out["from"], dni, profily, ",".join(obvod.ids))
    headers = {"ETag": tag, "Cache-Control": STATS_CACHE}
    if etag.fresh(request, tag):
        return etag.not_modified(headers)
    return JSONResponse(out, headers=headers)


# --- the page -----------------------------------------------------------------------------------

BINS = (0.2, 0.4, 0.6, 0.8)     # the heat map's steps of occupancy
RANK_MIN = 5                    # places: a smaller lot (often one sensor) is full or empty, not busy; left out of the page's ranking
FREE_OK = 0.3                   # a share of places free from which a bar is green; under it orange
FREE_LOW = 0.1                  # at most this free is red: „plno“, as in the statistics and the app
PEAKS_MIN_DAYS = 7              # the busiest hours are named only after a week of history: before, one evening would be „the fullest“


def _bin(v: float | None) -> int | None:
    return None if v is None else sum(v >= b for b in BINS)


def _pct(v: float | None) -> str:
    return "" if v is None else f"{round(100 * v)}{NB}%"


def _ago(t: dt.datetime | None, at: dt.datetime) -> str:
    if t is None:
        return ""
    m = int((at - t).total_seconds() // 60)
    if m < 1:
        return "právě teď"
    if m < 60:
        return f"před {m}{NB}min"
    h = m // 60
    return f"před {h}{NB}h" if h < 24 else f"{t.astimezone(TZ).day}.{NB}{t.astimezone(TZ).month}."


def heat(g: dict) -> list[dict]:
    """The page's typical week: per day its 24 cells {bin, tip, sr}."""
    out = []
    for d, day in enumerate(g["occupancy"]):
        cells = []
        for h, v in enumerate(day):
            words = "bez dat" if v is None else f"obsazeno {_pct(v)}"
            if v is not None and (f := g["full"][d][h]):
                words += f", plno {_pct(f)} času"
            cells.append({"bin": _bin(v), "tip": f"{stats.DAYS_SHORT[d]} {h}–{h + 1} h: {words}", "sr": words})
        out.append({"day": stats.DAYS[d], "short": stats.DAYS_SHORT[d], "cells": cells})
    return out


def peaks(g: dict, history_from: str | None, at: dt.datetime) -> list[dict]:
    """The busiest hours of a grid, or none while the history is shorter than PEAKS_MIN_DAYS."""
    if not history_from or at - dt.datetime.fromisoformat(history_from.replace("Z", "+00:00")) < dt.timedelta(days=PEAKS_MIN_DAYS):
        return []
    return stats.busiest_hours(g)


def _history_date(s: dict) -> dt.date | None:
    return s["history_from"] and dt.datetime.fromisoformat(s["history_from"].replace("Z", "+00:00")).astimezone(TZ).date()


def _has(g: dict) -> bool:
    return any(v is not None for day in g["occupancy"] for v in day)


def state(free_share: float | None) -> str:
    """'ok', 'low' or 'full' for a share of places free: the bars' green, orange and red."""
    if free_share is None:
        return ""
    return "ok" if free_share >= FREE_OK else "low" if free_share > FREE_LOW else "full"


def _n(x: int) -> str:
    return f"{x:,}".replace(",", NB)


def gauge(free: int, total: int, g: dict, at: dt.datetime) -> dict | None:
    """The town's occupancy now for the page's meter, with the usual occupancy at this weekday and
    hour from the typical week (None while there is none)."""
    if not total:
        return None
    local = at.astimezone(TZ)
    usual = g["occupancy"][local.weekday()][local.hour]
    occ = (total - free) / total
    return {"occ": round(100 * occ), "free": 100 - round(100 * occ), "free_n": _n(free), "total_n": _n(total),
            "st": state(free / total), "usual": round(100 * usual) if usual is not None else None}


def areas_now(now: dict[str, dict], defs: list[dict]) -> list[dict]:
    """Each area with lots seen now: free and total places summed, and its share free."""
    out = []
    for a in defs:
        rs = [now[i] for i in a["lots"] if i in now]
        if not rs:
            continue
        free, total = sum(r["free"] for r in rs), sum(r["total"] for r in rs)
        share = free / total if total else 0
        out.append({"id": a["id"], "name": a["name"], "free": free, "total": total, "lots": len(rs),
                    "share": share, "st": state(share)})
    return out


@pages.get("", response_class=HTMLResponse)
def overview(request: Request, oblast: str = "", parkoviste: str = ""):
    """Always the whole town: people park where they go, not in their obvod (most lots with
    sensors are in the centre)."""
    at = _now()
    lot_obvody = q.lot_obvody()
    names = q.lot_names()
    where = ObvodFilter()
    st = q.state()
    rows = []
    if st and st["fetched_at"]:
        doc_lots = {}
        b = q.built()
        if b:
            doc = q.document(b[0]) or {}
            doc_lots = {lt["id"]: lt for lt in doc.get("parking", {}).get("lots", [])}
        for r in q.now_rows():
            if not where.matches(lot_obvody.get(r["id"], [])):
                continue
            lt = doc_lots.get(r["id"], {})
            rows.append({"id": r["id"], "name": names.get(r["id"], r["id"]), "area": lt.get("area", ""), "free": r["free"],
                         "total": r["total"], "share": r["free"] / r["total"] if r["total"] else 0,
                         "st": state(r["free"] / r["total"] if r["total"] else None),
                         "changed": _ago(r["changed_at"], at), "paid": lt.get("paid")})
        rows.sort(key=lambda x: (-x["free"], x["name"]))
    s = statistics(where, DAYS, False)
    has_history = _has(s["profile"])
    lot_occ = {x["id"]: x["occupancy"] for x in s["lots"]}
    now = {r["id"]: r for r in q.now_rows()} if st and st["fetched_at"] else {}
    defs = [a for a in data.payload("areas") if any(where.matches(lot_obvody.get(i, [])) for i in a["lots"])]
    return tpl.TemplateResponse(request, "parkovani/prehled.html", {
        "free": sum(r["free"] for r in rows), "total": sum(r["total"] for r in rows),
        "gauge": gauge(sum(r["free"] for r in rows), sum(r["total"] for r in rows), s["profile"], at),
        "fetched": _ago(st["fetched_at"], at) if st and st["fetched_at"] else None,
        "stale": bool(st and st["fetched_at"] and at - st["fetched_at"] > dt.timedelta(minutes=15)),
        "heat": heat(s["profile"]) if has_history else None, "peaks": peaks(s["profile"], s["history_from"], at),
        "rows": [{**r, "occ": _pct(lot_occ.get(r["id"]))} for r in rows],
        "areas": [{**a, "occ": _pct(next((x["occupancy"] for x in s["areas"] if x["id"] == a["id"]), None))}
                  for a in areas_now(now, defs)],
        "busiest": [{**x, "occ": _pct(x["occupancy"]), "full_pct": _pct(x["full"]),
                     "w": round(100 * (x["occupancy"] or 0), 1),
                     "st": state(1 - x["occupancy"] if x["occupancy"] is not None else None)} for x in s["lots"] if (x["capacity"] or 0) >= RANK_MIN][:10],
        "history_from": _history_date(s), "days": DAYS, "source_url": SOURCE_URL,
        "checked": _checked(st),
        # without JS a row's link opens its detail here (?oblast= / ?parkoviste=); with JS rozbal.js
        # fetches the same detail from /oblast/{id} or /parkoviste/{id} and puts it under the row
        "open_area": area_detail(oblast) if oblast else None, "open_lot": lot_detail(parkoviste) if parkoviste else None})


def _checked(st: dict | None) -> dt.date | None:
    return st["fetched_at"].astimezone(TZ).date() if st and st["fetched_at"] else None


def _now_map(st: dict | None) -> dict[str, dict]:
    return {r["id"]: r for r in q.now_rows()} if st and st["fetched_at"] else {}


def area_detail(area_id: str) -> dict | None:
    """What opens under an area's row: its lots now and its typical week; None for an unknown id."""
    a = next((x for x in data.payload("areas") if x["id"] == area_id), None)
    if a is None:
        return None
    at, st, names = _now(), q.state(), q.lot_names()
    now = _now_map(st)
    s = statistics(ObvodFilter(), DAYS, True)
    stat = next((x for x in s["areas"] if x["id"] == area_id), None)
    lots = [{"id": i, "name": names.get(i, i), "free": now[i]["free"] if i in now else None,
             "total": now[i]["total"] if i in now else None,
             "share": now[i]["free"] / now[i]["total"] if i in now and now[i]["total"] else 0,
             "st": state(now[i]["free"] / now[i]["total"] if i in now and now[i]["total"] else None)} for i in a["lots"] if i in names]
    g = stat["profile"] if stat else None
    return {"kind": "oblast", "id": area_id, "title": a["name"], "lots": lots,
            "heat": heat(g) if g and _has(g) else None, "peaks": peaks(g, s["history_from"], at) if g else [],
            "occ": _pct(stat["occupancy"]) if stat else "",
            "full_pct": "",  # an area is never all full: its lots fill one by one
            "days": DAYS}


def lot_detail(lot_id: str) -> dict | None:
    """What opens under a lot's row: its typical week; None for an unknown id."""
    names = q.lot_names()
    if lot_id not in names:
        return None
    at, st = _now(), q.state()
    r = _now_map(st).get(lot_id)
    s = statistics(ObvodFilter(), DAYS, True)
    stat = next((x for x in s["lots"] if x["id"] == lot_id), None)
    a = next((x for x in data.payload("areas") if lot_id in x["lots"]), None)
    g = stat["profile"] if stat else None
    return {"kind": "parkoviste", "id": lot_id, "title": names[lot_id], "lots": [], "area": a,
            "changed": _ago(r["changed_at"], at) if r else None,
            "heat": heat(g) if g and _has(g) else None, "peaks": peaks(g, s["history_from"], at) if g else [],
            "occ": _pct(stat["occupancy"]) if stat else "", "full_pct": _pct(stat["full"]) if stat else "",
            "days": DAYS}


@pages.get("/oblast/{area_id}", response_class=HTMLResponse)
def area_part(request: Request, area_id: str):
    """The detail of an area as a part of the page, for rozbal.js."""
    d = area_detail(area_id)
    if d is None:
        raise HTTPException(404, "Takovou oblast neznáme.")
    return tpl.TemplateResponse(request, "parkovani/_detail.html", {"d": d})


@pages.get("/parkoviste/{lot_id}", response_class=HTMLResponse)
def lot_part(request: Request, lot_id: str):
    """The detail of a lot as a part of the page, for rozbal.js."""
    d = lot_detail(lot_id)
    if d is None:
        raise HTTPException(404, "Takové parkoviště neznáme.")
    return tpl.TemplateResponse(request, "parkovani/_detail.html", {"d": d})
