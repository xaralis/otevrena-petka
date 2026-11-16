"""Parkování: the page /verejny-prostor/parkovani (free places now, the typical week and the
busiest lots, of the obvod or with ?kde=mesto the whole town) and the API for the app and
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
           "profile": stats.grid(rows), "lots": stats.lots(rows, names, lot_obvody, profiles)}
    _stats[key] = (time.monotonic(), out)
    return out


@api.get("/statistiky")
def statistiky(request: Request, obvod: ObvodParam,
               dni: int = Query(DAYS, ge=1, le=366, description="Za kolik posledních dní (1–366)."),
               profily: bool = Query(False, description="Přidat ke každému parkovišti jeho typický týden.")):
    """Statistiky obsazenosti z historie (vzorek každých 5 minut): typický týden (průměrná obsazenost
    podle dne v týdnu a hodiny, `profile`) a parkoviště od nejvytíženějšího (`lots`: průměrná
    obsazenost, podíl času, kdy bylo plno). S `?profily=true` i typický týden každého parkoviště,
    např. pro „v tuhle dobu tu bývá plno“. Přepočítává se nejvýš každých 10 minut."""
    out = statistics(obvod, dni, profily)
    tag = etag.weak(out["to"], out["from"], dni, profily, ",".join(obvod.ids))
    headers = {"ETag": tag, "Cache-Control": STATS_CACHE}
    if etag.fresh(request, tag):
        return etag.not_modified(headers)
    return JSONResponse(out, headers=headers)


# --- the page -----------------------------------------------------------------------------------

BINS = (0.2, 0.4, 0.6, 0.8)     # the heat map's steps of occupancy
MIN_LOTS = 3                    # an obvod with fewer lots with sensors shows the whole town
RANK_MIN = 5                    # places: a smaller lot (often one sensor) is full or empty, not busy; left out of the page's ranking


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


@pages.get("", response_class=HTMLResponse)
def overview(request: Request, kde: str = ""):
    at = _now()
    obvod = request.state.obvod
    town = kde == "mesto"
    lot_obvody = q.lot_obvody()
    names = q.lot_names()
    mine = ObvodFilter.only(obvod.id)
    n_mine = sum(1 for o in lot_obvody.values() if mine.matches(o))
    # most lots with sensors are in the centre (mo1): an obvod with hardly any shows the town
    fallback = bool(not town and lot_obvody and n_mine < MIN_LOTS)
    where = ObvodFilter() if town or fallback else mine
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
            rows.append({"name": names.get(r["id"], r["id"]), "area": lt.get("area", ""), "free": r["free"],
                         "total": r["total"], "share": r["free"] / r["total"] if r["total"] else 0,
                         "changed": _ago(r["changed_at"], at), "paid": lt.get("paid")})
        rows.sort(key=lambda x: (-x["free"], x["name"]))
    s = statistics(where, DAYS, False)
    has_history = any(v is not None for day in s["profile"]["occupancy"] for v in day)
    return tpl.TemplateResponse(request, "parkovani/prehled.html", {
        "obvod": obvod, "town": town or fallback, "fallback": fallback, "n_mine": n_mine, "n_town": len(lot_obvody),
        "rows": rows, "free": sum(r["free"] for r in rows), "total": sum(r["total"] for r in rows),
        "fetched": _ago(st["fetched_at"], at) if st and st["fetched_at"] else None,
        "stale": bool(st and st["fetched_at"] and at - st["fetched_at"] > dt.timedelta(minutes=15)),
        "heat": heat(s["profile"]) if has_history else None, "peaks": stats.busiest_hours(s["profile"]),
        "busiest": [{**x, "occ": _pct(x["occupancy"]), "full_pct": _pct(x["full"]),
                     "w": round(100 * (x["occupancy"] or 0), 1)} for x in s["lots"] if (x["capacity"] or 0) >= RANK_MIN][:10],
        "history_from": s["history_from"] and dt.datetime.fromisoformat(s["history_from"].replace("Z", "+00:00")).astimezone(TZ).date(),
        "days": DAYS, "source_url": SOURCE_URL,
        "checked": (st["fetched_at"].astimezone(TZ).date() if st and st["fetched_at"] else None)})
