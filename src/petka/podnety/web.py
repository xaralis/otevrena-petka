"""Podněty: the page /verejny-prostor/podnety and the API under /api/v1/podnety for the city app. The page
shows the request's obvod (petka.obvody); the API covers the whole town and takes `?obvod=`
(ADR 0002), with a weak ETag of the data's version and the parameters (304 on If-None-Match).
Everything else comes as query parameters.

    /verejny-prostor/podnety            the period's reports in numbers, on the map and by category
                        ?obdobi=12m|<year>  ?detail=mesice|vyreseno|ceka|odpoved (the open tile,
                        for a browser without JS)  ?stav=vyreseno|vse (waiting by default) and ?druh=<category id>
                        filter the map and its list (podnety.js does the same in place), as does
                        ?ulice=<slug> (one street of the obvod, by the name Dej Tip gives),
                        ?pocet=N rows of the list  ?druhy=vse lists every category on a phone
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..obvody import ObvodParam
from ..web import etag
from ..web.render import tpl
from . import queries, source, stats, words

pages = APIRouter(prefix="/verejny-prostor/podnety", include_in_schema=False)
api = APIRouter(prefix="/api/v1/podnety", tags=["podněty"])

DETAILS = ("mesice", "vyreseno", "ceka", "odpoved", "zadny")     # zadny: every tile closed
DEFAULT_DETAIL = "mesice"     # the first tile opens by default
REPORT = source.HOME
TZ = ZoneInfo("Europe/Prague")


def _now() -> dt.datetime:
    """Local time without a zone, as reported_at is stored."""
    return dt.datetime.now(TZ).replace(tzinfo=None)


def link(period: str, **params) -> str:
    """'/verejny-prostor/podnety?obdobi=2025&detail=mesice': the period kept (unless the default), empty
    parameters left out."""
    ps = {"obdobi": "" if period == "12m" else period, **params}
    query = "&".join(f"{k}={v}" for k, v in ps.items() if v)
    return "/verejny-prostor/podnety" + ("?" + query if query else "")


@pages.get("", response_class=HTMLResponse)
def overview(request: Request, obdobi: str = "12m", detail: str = DEFAULT_DETAIL, stav: str = "", druh: str = "",
             kategorie: str = "", druhy: str = "", pocet: int = stats.LIST, ulice: str = ""):
    now = _now()
    obvod = request.state.obvod.id
    p = stats.period(obdobi, now.date())
    rows = queries.period_rows(obvod, p.start, p.end)
    s = stats.summary(rows, p, now)
    detail = detail if detail in DETAILS else DEFAULT_DETAIL
    # ?ulice=<slug>: the map, its list and the filters' counts only for one street of the obvod
    from ..ulice.streets import streets
    street = streets(obvod).get(ulice.strip()) if ulice.strip() else None
    here = [r for r in rows if stats.on_street(r, street.name)] if street else rows
    stav, kind = stats.stav_key(stav), stats.druh_key(druh or kategorie, here)    # kategorie: older links
    shown = sorted((r for r in here if stats.matches(r, stav, kind)), key=lambda r: (r["reported_at"], r["id"]),
                   reverse=True)
    pocet = max(stats.LIST, min(pocet, len(shown)))
    keep = {"detail": "", "stav": stats.stav_url(stav), "druh": kind or "",    # links never carry the open tile
            "ulice": street.slug if street else ""}
    checked = queries.checked(obvod)
    return tpl.TemplateResponse(request, "podnety/prehled.html", {
        "per": p, "s": s, "switch": stats.switch(queries.years(obvod), p.key), "detail": detail,
        "q": lambda **kw: link(p.key, **kw), "link": link, "all_kinds": druhy == "vse",
        "f": lambda **kw: link(p.key, **{**keep, **kw}), "keep": keep,
        "stav": stav, "druh": kind, "facets": stats.facets(here, stav, kind), "street": street,
        "shown": shown[:pocet], "shown_n": len(shown), "more": pocet + stats.LIST if pocet < len(shown) else None,
        "points": json.dumps(stats.points(rows, now), ensure_ascii=False).replace("<", "\\u003c"),
        "checked": checked.date() if checked else None, "report": REPORT, "detail_url": source.detail,
        "status_word": stats.status_word, "segments": stats.SEGMENTS, "w": words, "plural": words.plural,
    })


def _ints(v: str, name: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split(",") if x.strip())
    except ValueError:
        raise HTTPException(422, f"{name}: čísla oddělená čárkou")


def _date(v: str, name: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(v) if v.strip() else None
    except ValueError:
        raise HTTPException(422, f"{name}: datum RRRR-MM-DD")


def _point(v: str) -> tuple[float, float] | None:
    if not v.strip():
        return None
    try:
        lat, lng = (float(x) for x in v.split(","))
    except ValueError:
        raise HTTPException(422, "near: lat,lng")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(422, "near: lat,lng mimo rozsah")
    return lat, lng


API_CACHE = "public, max-age=600"
STARI_DOC = ("Jen podněty, které se za posledních N dní pohnuly: byly nahlášené, úřad k nim napsal "
             "nebo se jim změnil stav (pole `changed_at`). S `stav=1,2,8,9` jen otevřené, s `stav=3` "
             "nedávno vyřešené.")


@api.get("")
def reports(request: Request, obvod: ObvodParam, kategorie: str = "", stav: str = "", od: str = "",
            do: str = "", stari: int | None = Query(None, ge=1, le=3650, description=STARI_DOC, examples=[90]),
            near: str = "", r: int = 500, limit: int = 500):
    """Podněty z aplikace Dej Tip v Pardubicích jako GeoJSON, nejnovější první (s `near` nejbližší).
    Celé město, jen některé obvody s `?obvod=mo5` (víc oddělte čárkou).

    kategorie, stav: id z číselníků Dej Tip, víc oddělených čárkou. od, do: den nahlášení
    RRRR-MM-DD (včetně). stari=N: jen podněty, které se za posledních N dní pohnuly (nahlášení,
    poznámka úřadu, změna stavu; `changed_at`), např. `stav=1,2,8,9&stari=90` otevřené a
    `stav=3&stari=90` nedávno vyřešené. near=lat,lng a r (metry, nejvýš 5000): jen podněty
    v tom okruhu, s `distance`. `obvody`: obvod, ve kterém podnět je (podle Dej Tipu). Místo
    jen jako ulice bez čísla domu. `description` je popis od občana se skrytými telefony
    a e-maily, `photo` fotka jen tam, kde ji autor na Dej Tipu zveřejnil (načítá se z Dej
    Tipu), `detail` odkaz na podnět v Dej Tipu. Poznámky úřadu ne. Odpověď má ETag;
    s `If-None-Match` vrátí 304, dokud se podněty znovu nestáhnou (každé 4 hodiny)."""
    today = _now().date()
    f = queries.Filters(obvod, _ints(kategorie, "kategorie"), _ints(stav, "stav"),
                        _date(od, "od"), _date(do, "do"), _point(near), max(1, min(r, 5000)),
                        stari, today if stari else None)
    limit = max(1, limit)
    version = queries.version()
    tag = etag.weak(version.isoformat() if version else "", ",".join(f.obvod.ids),
                    ",".join(map(str, f.categories)), ",".join(map(str, f.statuses)), f.date_from, f.date_to,
                    f.near, f.radius, stari, f.today, limit)
    headers = {"ETag": tag, "Cache-Control": API_CACHE}
    if etag.fresh(request, tag):
        return etag.not_modified(headers)
    rows = queries.search(f, limit)
    return JSONResponse(queries.geojson(rows), media_type="application/geo+json", headers=headers)
