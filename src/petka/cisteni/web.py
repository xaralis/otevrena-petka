"""Čištění ulic: pages under /cisteni, calendar feeds, the exports and the API under
/api/v1/cisteni. Pages and feeds show the request's obvod (petka.obvody); the exports and the
API cover the whole town and take `?obvod=` (ADR 0002).

    /verejny-prostor/blokove-cisteni                      overview: the next 7 days, a calendar for your streets, the map
                                  and the harmonogram by week (?probehle=1 lists this year's past
                                  cleanings instead; ?ulice= from before goes to the street search)
    /verejny-prostor/blokove-cisteni/ulice/<slug>         301 to the street's page, its section „Blokové
                                  čištění“ (/verejny-prostor/ulice/<slug>#cisteni, petka.ulice)
    /verejny-prostor/blokove-cisteni/kalendar             the subscription link for chosen streets (the form without JS)
    /verejny-prostor/blokove-cisteni/kalendar.ics         feed of chosen streets (?ulice=slug,slug)
    /verejny-prostor/blokove-cisteni/ulice/<slug>.ics     feed of one street
    /verejny-prostor/blokove-cisteni/data/terminy.{json,csv}  one row a place and date
    /api/v1/cisteni               the places as GeoJSON with their dates and obvody

The exports and the API send a weak ETag of the sheet's last check, the day and the parameters
(petka.web.etag); If-None-Match with it gives 304.
"""

import csv
import datetime as dt
import io
import os
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..obvody import ObvodFilter, ObvodParam
from ..web import etag
from ..web.render import tpl
from . import ics, queries as q, source
from .words import merged, weeks

pages = APIRouter(prefix="/verejny-prostor/blokove-cisteni", include_in_schema=False)

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


def subscribe(slugs: list[str]) -> dict:
    path = "/verejny-prostor/blokove-cisteni/kalendar.ics?ulice=" + ",".join(quote(s) for s in slugs)
    origin = _origin()
    return {"webcal": "webcal://" + origin.split("://", 1)[1] + path, "https": origin + path}


PERIODS = (("7", "7 dní", WEEK), ("14", "14 dní", 2 * WEEK), ("rok", "Letos", None))    # the list beside the map


@pages.get("", response_class=HTMLResponse)
def overview(request: Request, ulice: str = "", probehle: str = "", obdobi: str = "7"):
    today = _today()
    obvod = request.state.obvod.id
    its = q.items(obvod, q.year_start(today))
    names = q.streets(its)
    if ulice.strip():           # the search that used to be in the band: streets are found on Ulice
        return RedirectResponse("/verejny-prostor/ulice?q=" + quote(ulice.strip()), status_code=303)
    future = [i for i in its if i["date"] >= today]
    past = [i for i in its if i["date"] < today]
    week = [i for i in future if i["date"] <= today + dt.timedelta(days=WEEK)]
    obdobi = obdobi if obdobi in {k for k, _, _ in PERIODS} else "7"
    within = lambda days: [i for i in future if days is None or i["date"] <= today + dt.timedelta(days=days)]
    periods = [{"key": k, "label": label, "n": len(within(days)), "on": k == obdobi,
                "href": "/verejny-prostor/blokove-cisteni" + ("" if k == "7" else f"?obdobi={k}")} for k, label, days in PERIODS]
    listed = within(dict((k, d) for k, _, d in PERIODS)[obdobi])
    groups = weeks(future, today)
    for g in groups:
        rest = [i for i in g["items"] if i not in week]
        g["phone"] = merged(rest) if g["key"][0] == "m" else rest
        g["above"] = len(g["items"]) - len(rest)
    return tpl.TemplateResponse(request, "cisteni/prehled.html", {
        **_state(today), "week": week, "listed": listed, "periods": periods, "groups": groups, "names": names, "past": sorted(past, key=lambda i: i["date"], reverse=True) if probehle else None,
        "n_past": len(past), "n_dates": len(its), "n_places": len({i["key"] for i in its}),
        "anchors": q.map_anchors(its, q.geometries(obvod), today),
    })


@pages.get("/kalendar")
def subscribe_page(ulice: list[str] = Query(default=[])):
    """The old calendar builder: Můj přehled does it now (with the cleanings chosen)."""
    slugs = [s for s in dict.fromkeys(x for v in ulice for x in v.split(",")) if s]
    return RedirectResponse("/muj-prehled?" + ("ulice=" + ",".join(quote(s) for s in slugs) + "&" if slugs else "")
                            + "co=cisteni", status_code=301)


def _feed(request: Request, its: list[dict], name: str) -> Response:
    base = _origin()
    body = ics.calendar(its, name, dt.datetime.now(dt.UTC),
                        lambda i: base + q.street_url(i["slug"]))
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


@pages.get("/ulice/{slug}")
def street(slug: str):
    """The street's cleaning is a section of the street's page now (13. 11. 2026)."""
    return RedirectResponse(q.street_url(slug), status_code=301)


# --- API ------------------------------------------------------------------------------------

def features(its: list[dict], geoms: dict[str, dict], today: dt.date) -> dict:
    """One feature per place with its dates (geometry null for a place we couldn't locate)."""
    by: dict[str, dict] = {}
    for i in its:
        f = by.get(i["key"])
        if not f:
            f = by[i["key"]] = {"type": "Feature", "id": i["key"], "geometry": geoms.get(i["key"]), "properties": {
                "key": i["key"], "street": i["street"] if i["slug"] else None, "slug": i["slug"],
                "texts": i["texts"], "status": i["status"], "side": i["side"], "obvody": i["obvody"],
                "dates": [], "next": None}}
        p = f["properties"]
        p["dates"].append({"date": i["date"].isoformat(), "time": i["time"].strftime("%H:%M") if i["time"] else None,
                           "before": i["before"]})
        if i["date"] >= today and p["next"] is None:
            p["next"] = i["date"].isoformat()
    return {"type": "FeatureCollection", "features": list(by.values()),
            "attribution": "Služby města Pardubic (" + source.PAGE + "), polohy © ČÚZK RÚIAN, odvozené"}


API_CACHE = "public, max-age=600"
EXPORT_CACHE = "public, max-age=3600"


def _cached(request: Request, what: str, today: dt.date, obvod: ObvodFilter, *params,
            cache: str) -> tuple[dict, Response | None]:
    """The answer's headers (ETag of the sheet's last check, the day, which answer and its
    parameters) and a 304 when the client has it already. The day is in the tag because
    `next` and the default start of the year move with it."""
    checked = q.checked()
    tag = etag.weak(checked.isoformat() if checked else "", today.isoformat(), what, ",".join(obvod.ids), *params)
    headers = {"ETag": tag, "Cache-Control": cache}
    return headers, etag.not_modified(headers) if etag.fresh(request, tag) else None


@pages.get("/data/terminy.json")
def data_json(request: Request, obvod: ObvodParam):
    """This year's cleanings of the town (or `?obvod=`), one row a place and date."""
    today = _today()
    headers, unchanged = _cached(request, "terminy.json", today, obvod, cache=EXPORT_CACHE)
    if unchanged:
        return unchanged
    rows = [{**r, "date": r["date"].isoformat()} for r in q.export_rows(q.year_start(today), obvod)]
    return JSONResponse(rows, headers={**headers, "Content-Disposition": 'inline; filename="terminy.json"'})


@pages.get("/data/terminy.csv")
def data_csv(request: Request, obvod: ObvodParam):
    today = _today()
    headers, unchanged = _cached(request, "terminy.csv", today, obvod, cache=EXPORT_CACHE)
    if unchanged:
        return unchanged
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=q.EXPORT_FIELDS)
    w.writeheader()
    for r in q.export_rows(q.year_start(today), obvod):
        w.writerow({**r, "date": r["date"].isoformat(), "time": r["time"] or "", "side": r["side"] or "",
                    "street": r["street"] or "", "before": "true" if r["before"] else "false",
                    "obvody": ";".join(r["obvody"])})
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={**headers, "Content-Disposition": 'inline; filename="terminy.csv"'})


@api.get("")
def cleanings(request: Request, obvod: ObvodParam, ulice: str = "", od: str = ""):
    """Blokové čištění v Pardubicích jako GeoJSON: jedno místo z harmonogramu = jeden feature
    s termíny. Celé město, jen některé obvody s `?obvod=mo5` (víc oddělte čárkou).

    ulice: slugy ulic oddělené čárkou (např. `wolkerova,lexova`). od: jen termíny od toho dne
    RRRR-MM-DD (výchozí 1. ledna letošního roku). `obvody`: obvody, kterými místo vede (aspoň
    5 % jeho délky nebo plochy); místo bez polohy má `geometry: null`. `status`: auto = poloha
    z textu harmonogramu, approx/partial = přibližně, manual = ručně zakreslené nebo (bez
    geometrie) neurčené.
    `next` = nejbližší termín od dneška. Platí text harmonogramu (`texts`), poloha je odvozená.
    Odpověď má ETag; s `If-None-Match` vrátí 304, dokud se harmonogram znovu nezkontroluje."""
    today = _today()
    try:
        since = dt.date.fromisoformat(od) if od.strip() else q.year_start(today)
    except ValueError:
        raise HTTPException(422, "od: datum RRRR-MM-DD")
    slugs = [s.strip() for s in ulice.split(",") if s.strip()] or None
    headers, unchanged = _cached(request, "api", today, obvod, since.isoformat(), ",".join(slugs or []),
                                 cache=API_CACHE)
    if unchanged:
        return unchanged
    return JSONResponse(features(q.items(obvod, since, slugs), q.geometries(obvod), today),
                        media_type="application/geo+json", headers=headers)
