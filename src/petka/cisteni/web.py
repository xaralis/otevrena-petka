"""Čištění ulic: pages under /cisteni, calendar feeds and the API under /api/v1/cisteni. The
obvod is the request's (petka.obvody).

    /blokove-cisteni                      overview: the next 7 days, a calendar for your streets, the map
                                  and the harmonogram by week (?ulice= finds a street,
                                  ?probehle=1 lists this year's past cleanings instead)
    /blokove-cisteni/ulice/<slug>         one street: the next cleaning, its map, this year's dates
    /blokove-cisteni/kalendar             the subscription link for chosen streets (the form without JS)
    /blokove-cisteni/kalendar.ics         feed of chosen streets (?ulice=slug,slug)
    /blokove-cisteni/ulice/<slug>.ics     feed of one street
    /api/v1/cisteni               the places as GeoJSON with their dates
"""

import datetime as dt
import json
import os
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..web.render import tpl
from . import ics, queries as q, source
from .words import SIDE_ON, genitive, merged, weeks

pages = APIRouter(prefix="/blokove-cisteni", include_in_schema=False)

WEEK = 7       # "Příštích 7 dní": today and the seven days after it
api = APIRouter(prefix="/api/v1/cisteni", tags=["čištění ulic"])

# --- pages ----------------------------------------------------------------------------------

def _today() -> dt.date:
    return dt.date.today()


def _state(today: dt.date) -> dict:
    checked = q.checked()
    return {"checked": checked.date() if checked else None, "today": today, "source": source.PAGE}


def _origin() -> str:
    """The portal's public origin for absolute links (calendar feeds are cached and copied
    into other apps, so never the request's Host header)."""
    return os.environ.get("PUBLIC_URL", "https://otevrenapetka.cz").rstrip("/")


def _subscribe(request: Request, slugs: list[str]) -> dict:
    path = "/blokove-cisteni/kalendar.ics?ulice=" + ",".join(quote(s) for s in slugs)
    origin = _origin()
    return {"webcal": "webcal://" + origin.split("://", 1)[1] + path, "https": origin + path}


@pages.get("", response_class=HTMLResponse)
def overview(request: Request, ulice: str = "", probehle: str = ""):
    today = _today()
    obvod = request.state.obvod.id
    its = q.items(obvod, q.year_start(today))
    names = q.streets(its)
    found = None
    if ulice.strip():
        found = q.find(ulice, names)
        if len(found) == 1:
            return RedirectResponse(f"/blokove-cisteni/ulice/{found[0]}", status_code=303)
    future = [i for i in its if i["date"] >= today]
    past = [i for i in its if i["date"] < today]
    week = [i for i in future if i["date"] <= today + dt.timedelta(days=WEEK)]
    groups = weeks(future, today)
    for g in groups:
        rest = [i for i in g["items"] if i not in week]
        g["phone"] = merged(rest) if g["key"][0] == "m" else rest
        g["above"] = len(g["items"]) - len(rest)
    return tpl.TemplateResponse(request, "cisteni/prehled.html", {
        **_state(today), "week": week, "groups": groups, "names": names, "query": ulice.strip(),
        "found": found, "past": sorted(past, key=lambda i: i["date"], reverse=True) if probehle else None,
        "n_past": len(past), "n_dates": len(its), "n_places": len({i["key"] for i in its}),
        "anchors": q.map_anchors(its, q.geometries(obvod), today),
    })


@pages.get("/kalendar", response_class=HTMLResponse)
def subscribe_page(request: Request, ulice: list[str] = Query(default=[]), pridat: str = ""):
    """The calendar form without JavaScript lands here: the chosen streets and their link."""
    today = _today()
    names = q.streets(q.items(request.state.obvod.id, q.year_start(today)))
    chosen = [s for s in dict.fromkeys(x for v in ulice for x in v.split(",")) if s in names]
    missing = None
    if pridat.strip():
        hits = q.find(pridat, names)
        if len(hits) == 1:
            chosen = list(dict.fromkeys(chosen + hits))
        else:
            missing = pridat.strip()
    return tpl.TemplateResponse(request, "cisteni/kalendar.html", {
        **_state(today), "chosen": [(s, names[s]) for s in chosen], "missing": missing, "names": names,
        **(_subscribe(request, chosen) if chosen else {})})


def _feed(request: Request, its: list[dict], name: str) -> Response:
    base = _origin()
    body = ics.calendar(its, name, dt.datetime.now(dt.UTC),
                        lambda i: f"{base}/blokove-cisteni/ulice/{i['slug']}" if i["slug"] else f"{base}/blokove-cisteni")
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=3600",
                             "Content-Disposition": 'inline; filename="cisteni.ics"'})


@pages.get("/kalendar.ics")
def feed(request: Request, ulice: str = ""):
    slugs = [s for s in ulice.split(",") if s.strip()]
    if not slugs:
        raise HTTPException(404)
    its = q.items(request.state.obvod.id, q.year_start(_today()), slugs)
    names = list(dict.fromkeys(i["street"] for i in its))
    return _feed(request, its, "Blokové čištění – " + (", ".join(names) or "vybrané ulice"))


@pages.get("/ulice/{slug}.ics")
def street_feed(request: Request, slug: str):
    its = q.items(request.state.obvod.id, q.year_start(_today()), [slug])
    if not its:
        raise HTTPException(404)
    return _feed(request, its, f"Blokové čištění – {its[0]['street']}")


@pages.get("/ulice/{slug}", response_class=HTMLResponse)
def street(request: Request, slug: str):
    today = _today()
    obvod = request.state.obvod.id
    every = q.items(obvod, q.year_start(today))
    its = [i for i in every if i["slug"] == slug]
    if not its:
        raise HTTPException(404)
    name = its[0]["street"]
    nxt = q.next_date(its, today)
    upcoming = [i for i in its if i["date"] >= today]
    rows = upcoming + sorted((i for i in its if i["date"] < today), key=lambda i: i["date"], reverse=True)
    on_next = [i for i in its if i["date"] == nxt]
    geoms = q.geometries(obvod)
    feats = []
    for i in its:
        if i["key"] in geoms:
            when = "next" if i["date"] == nxt else "past" if i["date"] < today else "later"
            feats.append({"type": "Feature", "geometry": geoms[i["key"]],
                          "properties": {"when": when, "label": i["text"], "date": i["date"].isoformat()}})
    # the next cleaning first, so it is drawn on top of the same place's other dates
    feats.sort(key=lambda f: {"next": 2, "later": 1, "past": 0}[f["properties"]["when"]])
    whole = all(i["method"] == "whole" for i in on_next)
    return tpl.TemplateResponse(request, "cisteni/ulice.html", {
        **_state(today), "name": name, "slug": slug, "gen": genitive(name), "next": nxt, "on_next": on_next,
        "first": on_next[0] if on_next else None,
        "whole": whole, "rows": rows, "geojson": {"type": "FeatureCollection", "features": feats},
        "has_later": any(f["properties"]["when"] == "later" for f in feats),
        "has_past": any(f["properties"]["when"] == "past" for f in feats),
        "near": q.nearby(slug, every, geoms, today), **_subscribe(request, [slug]),
        "ics": f"/blokove-cisteni/ulice/{slug}.ics", "side_on": SIDE_ON})


# --- API ------------------------------------------------------------------------------------

def features(its: list[dict], geoms: dict[str, dict], today: dt.date) -> dict:
    """One feature per place with its dates (geometry null for a place we couldn't locate)."""
    by: dict[str, dict] = {}
    for i in its:
        f = by.get(i["key"])
        if not f:
            f = by[i["key"]] = {"type": "Feature", "id": i["key"], "geometry": geoms.get(i["key"]), "properties": {
                "key": i["key"], "street": i["street"] if i["slug"] else None, "slug": i["slug"],
                "texts": i["texts"], "status": i["status"], "side": i["side"], "dates": [], "next": None}}
        p = f["properties"]
        p["dates"].append({"date": i["date"].isoformat(), "time": i["time"].strftime("%H:%M") if i["time"] else None,
                           "before": i["before"]})
        if i["date"] >= today and p["next"] is None:
            p["next"] = i["date"].isoformat()
    return {"type": "FeatureCollection", "features": list(by.values()),
            "attribution": "Služby města Pardubic (" + source.PAGE + "), polohy © ČÚZK RÚIAN, odvozené"}


@api.get("")
def cleanings(request: Request, ulice: str = "", od: str = ""):
    """Blokové čištění v obvodu jako GeoJSON: jedno místo z harmonogramu = jeden feature s termíny.

    ulice: slugy ulic oddělené čárkou (např. `wolkerova,lexova`). od: jen termíny od toho dne
    RRRR-MM-DD (výchozí 1. ledna letošního roku). `status`: auto = poloha z textu harmonogramu,
    approx/partial = přibližně, manual = ručně zakreslené nebo (bez geometrie) neurčené.
    `next` = nejbližší termín od dneška. Platí text harmonogramu (`texts`), poloha je odvozená."""
    today = _today()
    try:
        since = dt.date.fromisoformat(od) if od.strip() else q.year_start(today)
    except ValueError:
        raise HTTPException(422, "od: datum RRRR-MM-DD")
    slugs = [s for s in ulice.split(",") if s.strip()] or None
    obvod = request.state.obvod.id
    return JSONResponse(features(q.items(obvod, since, slugs), q.geometries(obvod), today),
                        media_type="application/geo+json", headers={"Cache-Control": "public, max-age=600"})
