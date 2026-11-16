"""Uzavírky: the page at /verejny-prostor/uzavirky (the obvod's closures on a map with their
list, then each with NDIC's own text) and the API /api/v1/uzavirky (the town's, `?obvod=`).

Both carry what ŘSD's terms ask (petka.uzavirky.queries): NDIC's text unchanged with the
attribution sentence, our placing said to be ours, and the terms' link.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..obvody import ObvodFilter, ObvodParam
from ..web.render import tpl
from . import queries as q

pages = APIRouter(prefix="/verejny-prostor/uzavirky", include_in_schema=False)
api = APIRouter(prefix="/api/v1/uzavirky", tags=["uzavírky"])
TZ = ZoneInfo("Europe/Prague")
NB = "\u00a0"
RED, INK, GREY = "#de091c", "#191c1f", "#8a9097"
VIEWS = (("aktualni", "Aktuální"), ("planovane", "Plánované"), ("vse", "Všechny"))


def _now() -> dt.datetime:
    return dt.datetime.now(TZ)


def _dm(d: dt.datetime | None) -> str:
    if d is None:
        return ""
    d = d.astimezone(TZ)
    return f"{d.day}.{NB}{d.month}." + (f"{NB}{d.year}" if d.year != _now().year else "")


def _dmt(d: dt.datetime | None) -> str:
    """„30. 11. 16:00“: the time unless it is a whole day's edge."""
    if d is None:
        return ""
    t = d.astimezone(TZ)
    return _dm(d) + ("" if (t.hour, t.minute) in ((0, 0), (23, 59)) else f"{NB}{t.hour}:{t.minute:02d}")


def view(c: q.Closure, at: dt.datetime) -> dict:
    """A closure as the page's row and card."""
    now = c.now(at)
    return {"id": c.id, "place": c.place, "what": c.what, "closed": c.closed, "now": now,
            "date": _dm(c.starts) if c.starts else "", "status": (f"do {_dm(c.ends)}" if c.ends else "") if now
            else f"od {_dm(c.starts)}", "range": " – ".join(x for x in (_dmt(c.starts), _dmt(c.ends)) if x),
            "text": c.text, "mapped": c.geometry is not None, "method": c.method}


def features(cs: list[q.Closure], at: dt.datetime) -> dict:
    """GeoJSON of closures (also for the page's map: color, width, dash by how and when)."""
    out = []
    for c in cs:
        now = c.now(at)
        out.append({"type": "Feature", "id": c.id, "geometry": c.geometry, "properties": {
            "id": c.id, "place": c.place, "what": c.what, "closed": c.closed,
            "starts": c.starts.isoformat() if c.starts else None, "ends": c.ends.isoformat() if c.ends else None,
            "now": now, "text": c.text, "placed": c.method, "obvody": c.obvody, "records": c.records,
            "key": c.id, "color": (RED if c.closed else INK) if now else GREY, "width": 5 if now else 4,
            "dash": c.method != "street"}})
    return {"type": "FeatureCollection", "attribution": q.ATTRIBUTION, "terms": q.TERMS,
            "note": ("Text (`text`) je převzatý z NDIC beze změny. Místo (`place`), popis omezení (`what`) a umístění "
                     "úseku na ulici (`placed`: street = podle ulice, straight = spojnice konců úseku, point = bod) "
                     "odvodila Otevřená Pětka; za ně ŘSD neodpovídá. ŘSD neodpovídá ani za úplnost a přesnost "
                     "dopravních informací a za škody vzniklé jejich použitím. Kdo data použije dál, řídí se "
                     "podmínkami použití digitalizovaných informací o silničním provozu ŘSD."),
            "features": out}


@pages.get("", response_class=HTMLResponse)
def overview(request: Request, kdy: str = "aktualni"):
    at = _now()
    every = q.closures(q.rows(ObvodFilter.only(request.state.obvod.id), at), at)
    kdy = kdy if kdy in dict(VIEWS) else "aktualni"
    pick = {"aktualni": lambda c: c.now(at), "planovane": lambda c: not c.now(at), "vse": lambda c: True}
    views = [{"key": k, "label": label, "n": sum(map(pick[k], every)), "on": k == kdy,
              "href": "/verejny-prostor/uzavirky" + ("" if k == "aktualni" else f"?kdy={k}")} for k, label in VIEWS]
    shown = [c for c in every if pick[kdy](c)]
    return tpl.TemplateResponse(request, "uzavirky/prehled.html", {
        "views": views, "rows": [view(c, at) for c in shown], "fc": features(shown, at),
        "attribution": q.ATTRIBUTION, "terms": q.TERMS, "obvod": request.state.obvod,
        "checked": (c.astimezone(TZ).date() if (c := q.checked()) else None)})


@api.get("")
def closures(obvod: ObvodParam):
    """Uzavírky a dopravní omezení v Pardubicích (Národní dopravní informační centrum, ŘSD) jako
    GeoJSON: jedna uzavírka = jeden feature, platné teď i ohlášené dopředu. Celé město, jen některé
    obvody s `?obvod=mo5` (víc oddělte čárkou).

    `text` je text NDIC beze změny; `place`, `what` a poloha jsou odvozené (`placed`: street =
    úsek podle ulice, straight = spojnice konců, point = bod). `now`: platí už teď. `obvody`:
    obvody, kterými uzavírka vede (aspoň 10 % délky). Kolekce nese `attribution` a `terms`:
    kdo data použije dál, řídí se podmínkami ŘSD. Aktualizace každých 10 minut."""
    at = _now()
    return JSONResponse(features(q.closures(q.rows(obvod, at), at), at), media_type="application/geo+json",
                        headers={"Cache-Control": "public, max-age=300"})
