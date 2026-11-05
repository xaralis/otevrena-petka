"""Usnesení section: pages under /usneseni, data files under /usneseni/data, API under
/api/v1/usneseni."""

import datetime as dt
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, RedirectResponse, FileResponse, HTMLResponse, PlainTextResponse

from ..web.render import tpl
from . import embed, queries, search, store
from .enrich import vocab

pages = APIRouter(prefix="/usneseni", include_in_schema=False)
api = APIRouter(prefix="/api/v1/usneseni", tags=["usnesení"])


def _filters(organ, rok, tema, druh, stav, clen, volba) -> search.Filters:
    return search.Filters(body=organ or None, year=rok, topic=tema or None, kind=druh or None,
                          status=None if stav == "vse" else (stav or None),
                          member=(queries.find_member(clen) if clen else None),
                          member_choice=volba or None)


# --- pages --------------------------------------------------------------------------------

@pages.get("", response_class=HTMLResponse)
def home(request: Request, q: str = "", rezim: str = "hybrid", organ: str = "",
         rok: str = "", tema: str = "", druh: str = "", stav: str = "",
         clen: str = "", volba: str = "", strana: str = "1", razeni: str = ""):
    # defaults: only real resolutions (not rejected proposals), newest first
    stav = stav or "usneseni"
    razeni = razeni or "datum"
    # empty <select> options arrive as "" – treat anything non-numeric as "any year"
    rok = int(rok) if rok.strip().isdigit() else None
    strana = max(1, int(strana)) if strana.strip().isdigit() else 1
    f = _filters(organ, rok, tema, druh, stav, clen, volba)
    per = 20
    hits, info = search.search(q, rezim, f, limit=per, offset=(strana - 1) * per,
                               newest_first=razeni == "datum")
    stats = queries.stats()
    return tpl.TemplateResponse(request, "usneseni/home.html", {
        "razeni": razeni, "q": q, "rezim": rezim, "hits": hits, "info": info, "stats": stats,
        "f": {"organ": organ, "rok": rok, "tema": tema, "druh": druh, "stav": stav,
              "clen": clen, "volba": volba},
        "vocab": vocab(), "strana": strana, "per": per, "semantic": embed.enabled(),
        "member_names": queries.member_surnames(),
        "years": list(range(2018, (stats["last_date"] or dt.date.today()).year + 1))[::-1],
    })


@pages.get("/jednani", response_class=HTMLResponse)
def meetings_page(request: Request, organ: str = ""):
    return tpl.TemplateResponse(request, "usneseni/meetings.html",
                                {"meetings": queries.meetings(organ or None), "organ": organ})


@pages.get("/jednani/{mid}", response_class=HTMLResponse)
def meeting_page(request: Request, mid: str):
    m = queries.meeting(mid)
    if not m:
        raise HTTPException(404)
    return tpl.TemplateResponse(request, "usneseni/meeting.html", {"m": m})


@pages.get("/mapa", response_class=HTMLResponse)
def map_page(request: Request, organ: str = "", rok: str = "", tema: str = "", stav: str = ""):
    stav = stav or "usneseni"
    rok_i = int(rok) if rok.strip().isdigit() else None
    params = {k: v for k, v in {"organ": organ, "rok": rok_i or "", "tema": tema, "stav": stav}.items() if v}
    return tpl.TemplateResponse(request, "usneseni/map.html", {
        "f": {"organ": organ, "rok": rok_i, "tema": tema, "stav": stav},
        "years": list(range(2018, (queries.stats()["last_date"] or dt.date.today()).year + 1))[::-1],
        "vocab": vocab(), "index": queries.place_index(),
        "geojson_url": "/api/v1/usneseni/places.geojson" + ("?" + urlencode(params) if params else ""),
    })


@pages.get("/clenove", response_class=HTMLResponse)
def members_page(request: Request):
    terms: dict[str, dict[str, list]] = {}
    # seats are what the election gave (volby.cz), so someone elected who never sat still counts
    for m in queries.members() + queries.elected_without_votes():
        terms.setdefault(m["term"], {}).setdefault(m["list"], []).append(m)
    # Strongest club first; ties alphabetically
    clubs = {t: sorted(({"name": k, "people": v, "seats": sum(1 for m in v if m["elected"])}
                        for k, v in lists.items()), key=lambda c: (-c["seats"], c["name"].casefold()))
             for t, lists in terms.items()}
    return tpl.TemplateResponse(request, "usneseni/members.html", {"terms": clubs})


@pages.get("/clenove/ucast", response_class=HTMLResponse)
def attendance_page(request: Request, obdobi: str = ""):
    terms = [t for t in queries.terms() if t >= "2018"]
    term = obdobi if obdobi in terms else terms[0]
    rows = queries.attendance(term)
    return tpl.TemplateResponse(request, "usneseni/attendance.html", {
        "terms": terms, "term": term,
        "zmo": [r for r in rows if r["body"] == "zmo"], "rmo": [r for r in rows if r["body"] == "rmo"],
    })


MEMBER_PER_PAGE = 50


@pages.get("/clenove/{mid}", response_class=HTMLResponse)
def member_page(request: Request, mid: str, odlisne: bool = False, strana: str = "1"):
    m = queries.member(mid)
    if not m:
        raise HTTPException(404)
    strana = max(1, int(strana)) if strana.strip().isdigit() else 1
    votes = queries.member_votes(mid, dissent_only=odlisne, procedural=False,
                                 limit=MEMBER_PER_PAGE, offset=(strana - 1) * MEMBER_PER_PAGE)
    total = votes[0]["total"] if votes else 0
    meetings = queries.member_meetings(mid)
    groups: dict[tuple, list] = {}
    for mt in meetings:
        groups.setdefault((mt["term"], mt["body"]), []).append(mt)
    presence = [{"term": t, "body": b, "meetings": ms,
                 "present": sum(1 for x in ms if x["state"] == "present"),
                 "excused": sum(1 for x in ms if x["state"] == "excused")}
                for (t, b), ms in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] == "rmo"), reverse=True)]
    return tpl.TemplateResponse(request, "usneseni/member.html", {
        "m": m, "votes": votes, "odlisne": odlisne, "strana": strana,
        "pages": -(-total // MEMBER_PER_PAGE), "total": total, "presence": presence,
    })


# --- data: page, files (static routes before /{uid}) --------------------------------------

@pages.get("/feed.xml", include_in_schema=False)
def feed():
    """Atom feed of the newest resolutions (rejected proposals left out), for feed readers."""
    import os
    from xml.sax.saxutils import escape
    base = os.environ.get("PUBLIC_URL", "https://otevrenapetka.cz").rstrip("/")
    hits, _ = search.search("", filters=search.Filters(status="usneseni"), limit=50)
    rows = [h.row for h in hits]
    body_name = {"zmo": "zastupitelstvo", "rmo": "rada"}
    entries = "".join(
        f"""<entry><id>{base}/usneseni/{r['uid']}</id><title>{escape(r['number'] + ': ' + (r['title'] or ''))}</title>
<link href="{base}/usneseni/{r['uid']}"/><updated>{r['date'].isoformat()}T00:00:00Z</updated>
<category term="{r['body']}" label="{body_name.get(r['body'], r['body'])}"/>
<summary>{escape(r['summary'] or '')}</summary></entry>""" for r in rows)
    updated = rows[0]["date"].isoformat() if rows else "2018-01-01"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="cs"><id>{base}/usneseni/feed.xml</id>
<title>Usnesení MO Pardubice V – Otevřená Pětka</title><link rel="self" href="{base}/usneseni/feed.xml"/>
<link href="{base}/usneseni"/><updated>{updated}T00:00:00Z</updated><author><name>Otevřená Pětka</name></author>
{entries}</feed>"""
    return Response(xml, media_type="application/atom+xml")


@pages.get("/metodika", response_class=HTMLResponse)
def method(request: Request):
    return tpl.TemplateResponse(request, "usneseni/method.html", {})


@pages.get("/data", include_in_schema=False)
def dataset_moved():
    return RedirectResponse("/data#usneseni", status_code=301)


def opendata_updated():
    p = store.DATA / "opendata" / "datapackage.json"
    return dt.datetime.fromtimestamp(p.stat().st_mtime).date() if p.exists() else None


def _file(path, media_type=None):
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type=media_type)


@pages.get("/data/text/{name}")
def text_file(name: str):
    if "/" in name or not name.endswith(".txt"):
        raise HTTPException(404)
    return _file(store.DATA / "text" / name, "text/plain; charset=utf-8")


@pages.get("/data/extracted/{name}")
def extracted_file(name: str):
    """Raw parse/enrich results per meeting (the snapshot workflow mirrors them into git)."""
    if "/" in name or not name.endswith(".json"):
        raise HTTPException(404)
    return _file(store.DATA / "extracted" / name)


@pages.get("/data/texts.txt", response_class=PlainTextResponse)
def texts_index():
    return "\n".join(sorted(p.name for p in (store.DATA / "text").glob("*.txt")))


@pages.get("/data/extracted.txt", response_class=PlainTextResponse)
def extracted_index():
    return "\n".join(sorted(p.name for p in (store.DATA / "extracted").glob("*.json")))


@pages.get("/data/{name}")
def opendata_file(name: str):
    if "/" in name:
        raise HTTPException(404)
    top = {"sources.json", "embeddings.jsonl", "geo.json", "geo_cache.json"}   # live in the section's data root, not opendata/
    return _file(store.DATA / (name if name in top else f"opendata/{name}"))


@pages.get("/pdf/{mid}.pdf")
def pdf(mid: str):
    if "/" in mid:
        raise HTTPException(404)
    return _file(store.DATA / "pdf" / f"{mid}.pdf", "application/pdf")


@pages.get("/{uid}", response_class=HTMLResponse)
def resolution_page(request: Request, uid: str):
    r = queries.resolution(uid)
    if not r:
        raise HTTPException(404)
    return tpl.TemplateResponse(request, "usneseni/resolution.html", {"r": r, "vocab": vocab()})


def opendata_files() -> list[str]:
    d = store.DATA / "opendata"
    return sorted(p.name for p in d.glob("*")) if d.exists() else []


# --- REST API -----------------------------------------------------------------------------

@api.get("/resolutions")
def api_search(q: str = "", mode: str = Query("hybrid", pattern="^(hybrid|fulltext|semantic)$"),
               body: str | None = Query(None, pattern="^(zmo|rmo)$"), year: int | None = None,
               topic: str | None = None, kind: str | None = None,
               status: str | None = Query(None, pattern="^(prijato|neprijato|castecne|neovereno|usneseni)$"),
               member: str | None = None,
               member_choice: str | None = Query(None, pattern="^(pro|proti|zdrzel|nehlasoval)$"),
               newest_first: bool = False,
               limit: int = Query(20, le=100), offset: int = 0):
    """Hledání v usneseních. `status=usneseni` = jen skutečná usnesení (bez nepřijatých návrhů);
    `neprijato` = nepřijaté návrhy, které nejsou usneseními, i když mají číslo ze zápisu."""
    f = search.Filters(body=body, year=year, topic=topic, kind=kind, status=status,
                       member=queries.find_member(member) if member else None,
                       member_choice=member_choice)
    hits, info = search.search(q, mode, f, limit=limit, offset=offset, newest_first=newest_first)
    return {"info": info, "results": [{**h.row, "score": h.score} for h in hits]}


@api.get("/places.geojson")
def api_places(organ: str = "", rok: str = "", tema: str = "", stav: str = "usneseni"):
    """Places of resolutions (parcels, addresses, streets) as GeoJSON; same filters as the site."""
    rok_i = int(rok) if rok.strip().isdigit() else None
    f = _filters(organ, rok_i, tema, "", stav, "", "")
    return JSONResponse(queries.places_geojson(f), media_type="application/geo+json",
                        headers={"Cache-Control": "public, max-age=600"})


@api.get("/resolutions/{uid}")
def api_resolution(uid: str):
    r = queries.resolution(uid)
    if not r:
        raise HTTPException(404)
    return r


@api.get("/meetings")
def api_meetings(body: str | None = None, year: int | None = None):
    return queries.meetings(body, year)


@api.get("/meetings/{mid}")
def api_meeting(mid: str):
    m = queries.meeting(mid)
    if not m:
        raise HTTPException(404)
    return m


@api.get("/members")
def api_members(term: str | None = None):
    return queries.members(term)


@api.get("/members/{mid}/votes")
def api_member_votes(mid: str, dissent_only: bool = False, choice: str | None = None,
                     limit: int = Query(50, le=500), offset: int = 0):
    m = queries.member(mid)
    if not m:
        raise HTTPException(404)
    return {"member": m, "votes": queries.member_votes(mid, dissent_only=dissent_only,
                                                       choice=choice, limit=limit, offset=offset)}


@api.get("/stats")
def api_stats():
    return queries.stats()
