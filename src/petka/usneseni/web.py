"""Usnesení section: pages under /usneseni, data files under /usneseni/data, API under
/api/v1/usneseni."""

import datetime as dt

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

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


@pages.get("/clenove", response_class=HTMLResponse)
def members_page(request: Request):
    return tpl.TemplateResponse(request, "usneseni/members.html", {"members": queries.members()})


@pages.get("/clenove/{mid}", response_class=HTMLResponse)
def member_page(request: Request, mid: str, odlisne: bool = False):
    m = queries.member(mid)
    if not m:
        raise HTTPException(404)
    votes = queries.member_votes(mid, dissent_only=odlisne, procedural=False, limit=300)
    return tpl.TemplateResponse(request, "usneseni/member.html",
                                {"m": m, "votes": votes, "odlisne": odlisne})


# --- data: page, files (static routes before /{uid}) --------------------------------------

@pages.get("/data", response_class=HTMLResponse)
def dataset(request: Request):
    import os
    base = os.environ.get("PUBLIC_URL", "https://opendata.mov.varecha.work").rstrip("/")
    return tpl.TemplateResponse(request, "usneseni/dataset.html", {
        "tables": queries.opendata_tables(), "stats": queries.stats(), "base": base,
        "updated": opendata_updated(),
    })


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
    top = {"sources.json", "embeddings.jsonl"}   # live in the section's data root, not opendata/
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
