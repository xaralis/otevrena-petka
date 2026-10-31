"""Web app: public pages, REST API (/api/v1, OpenAPI at /api/docs) and MCP (/mcp)."""

import contextlib
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import db, embed, queries, search, store
from ..enrich import vocab
from ..mcp_server import mcp

HERE = Path(__file__).parent

if os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    sentry_sdk.init(os.environ["SENTRY_DSN"], traces_sample_rate=0)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Usnesení MO Pardubice V", lifespan=lifespan, docs_url="/api/docs",
              redoc_url=None, openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.router.routes.extend(mcp.streamable_http_app().routes)  # POST /mcp

tpl = Jinja2Templates(directory=HERE / "templates")
tpl.env.globals.update(STATUS=queries.STATUS_LABEL, BODY=queries.BODY_LABEL,
                       CHOICE=queries.CHOICE_LABEL)


def _date(d) -> str:
    return f"{d.day}. {d.month}. {d.year}" if d else ""


tpl.env.filters["d"] = _date


def _initials(name: str) -> str:
    """'Ing. Lic. Jaroslav Kňava' -> 'JK', 'Jiří Rejda, DiS.' -> 'JR' (tile labels)."""
    from ..text import strip_titles
    t = strip_titles(name)
    return (t[0][0] + t[-1][0]) if len(t) > 1 else (t[0][:2] if t else "?")


tpl.env.filters["initials"] = _initials


def _filters(organ, rok, tema, druh, stav, clen, volba) -> search.Filters:
    return search.Filters(body=organ or None, year=rok, topic=tema or None, kind=druh or None,
                          status=None if stav == "vse" else (stav or None), member=(queries.find_member(clen) if clen else None),
                          member_choice=volba or None)


# --- pages --------------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
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
    return tpl.TemplateResponse(request, "home.html", {
        "razeni": razeni,
        "q": q, "rezim": rezim, "hits": hits, "info": info, "stats": queries.stats(),
        "f": {"organ": organ, "rok": rok, "tema": tema, "druh": druh, "stav": stav,
              "clen": clen, "volba": volba},
        "vocab": vocab(), "strana": strana, "per": per, "semantic": embed.enabled(),
        "member_names": queries.member_surnames(),
        "years": list(range(2018, (queries.stats()["last_date"] or _today()).year + 1))[::-1],
    })


def _today():
    import datetime as dt
    return dt.date.today()


@app.get("/usneseni/{uid}", response_class=HTMLResponse, include_in_schema=False)
def resolution_page(request: Request, uid: str):
    r = queries.resolution(uid)
    if not r:
        raise HTTPException(404)
    return tpl.TemplateResponse(request, "resolution.html", {"r": r, "vocab": vocab()})


@app.get("/jednani", response_class=HTMLResponse, include_in_schema=False)
def meetings_page(request: Request, organ: str = ""):
    return tpl.TemplateResponse(request, "meetings.html",
                                {"meetings": queries.meetings(organ or None), "organ": organ})


@app.get("/jednani/{mid}", response_class=HTMLResponse, include_in_schema=False)
def meeting_page(request: Request, mid: str):
    m = queries.meeting(mid)
    if not m:
        raise HTTPException(404)
    return tpl.TemplateResponse(request, "meeting.html", {"m": m})


@app.get("/clenove", response_class=HTMLResponse, include_in_schema=False)
def members_page(request: Request):
    return tpl.TemplateResponse(request, "members.html", {"members": queries.members()})


@app.get("/clenove/{mid}", response_class=HTMLResponse, include_in_schema=False)
def member_page(request: Request, mid: str, odlisne: bool = False):
    m = queries.member(mid)
    if not m:
        raise HTTPException(404)
    votes = queries.member_votes(mid, dissent_only=odlisne, procedural=False, limit=300)
    return tpl.TemplateResponse(request, "member.html", {"m": m, "votes": votes, "odlisne": odlisne})


@app.get("/otevrena-data", response_class=HTMLResponse, include_in_schema=False)
def opendata_page(request: Request):
    files = sorted(p.name for p in (store.DATA / "opendata").glob("*")) if (store.DATA / "opendata").exists() else []
    return tpl.TemplateResponse(request, "opendata.html", {"files": files, "stats": queries.stats(),
                                                           "base": str(request.base_url).rstrip("/")})


@app.get("/opendata/{name}", include_in_schema=False)
def opendata_file(name: str):
    p = store.DATA / ("sources.json" if name == "sources.json" else f"opendata/{name}")
    if "/" in name or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/opendata/text/{name}", include_in_schema=False)
def text_file(name: str):
    p = store.DATA / "text" / name
    if "/" in name or not name.endswith(".txt") or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="text/plain; charset=utf-8")


@app.get("/opendata-texts.txt", response_class=PlainTextResponse, include_in_schema=False)
def texts_index():
    return "\n".join(sorted(p.name for p in (store.DATA / "text").glob("*.txt")))


@app.get("/opendata/extracted/{name}", include_in_schema=False)
def extracted_file(name: str):
    """Raw parse/enrich results per meeting (the snapshot workflow mirrors them into git)."""
    p = store.DATA / "extracted" / name
    if "/" in name or not name.endswith(".json") or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/opendata-extracted.txt", response_class=PlainTextResponse, include_in_schema=False)
def extracted_index():
    return "\n".join(sorted(p.name for p in (store.DATA / "extracted").glob("*.json")))


@app.get("/pdf/{mid}.pdf", include_in_schema=False)
def pdf(mid: str):
    p = store.DATA / "pdf" / f"{mid}.pdf"
    if "/" in mid or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")


@app.get("/healthz", include_in_schema=False)
def healthz():
    with db.pool().connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


# --- REST API -----------------------------------------------------------------------------

@app.get("/api/v1/resolutions", tags=["usnesení"])
def api_search(q: str = "", mode: str = Query("hybrid", pattern="^(hybrid|fulltext|semantic)$"),
               body: str | None = Query(None, pattern="^(zmo|rmo)$"), year: int | None = None,
               topic: str | None = None, kind: str | None = None,
               status: str | None = Query(None, pattern="^(prijato|neprijato|castecne|neovereno)$"),
               member: str | None = None,
               member_choice: str | None = Query(None, pattern="^(pro|proti|zdrzel|nehlasoval)$"),
               limit: int = Query(20, le=100), offset: int = 0):
    """Hledání v usneseních. `status` je výsledek hlasování – číslo usnesení ≠ přijato."""
    f = search.Filters(body=body, year=year, topic=topic, kind=kind, status=status,
                       member=queries.find_member(member) if member else None,
                       member_choice=member_choice)
    hits, info = search.search(q, mode, f, limit=limit, offset=offset)
    return {"info": info, "results": [{**h.row, "score": h.score} for h in hits]}


@app.get("/api/v1/resolutions/{uid}", tags=["usnesení"])
def api_resolution(uid: str):
    r = queries.resolution(uid)
    if not r:
        raise HTTPException(404)
    return r


@app.get("/api/v1/meetings", tags=["jednání"])
def api_meetings(body: str | None = None, year: int | None = None):
    return queries.meetings(body, year)


@app.get("/api/v1/meetings/{mid}", tags=["jednání"])
def api_meeting(mid: str):
    m = queries.meeting(mid)
    if not m:
        raise HTTPException(404)
    return m


@app.get("/api/v1/members", tags=["členové"])
def api_members(term: str | None = None):
    return queries.members(term)


@app.get("/api/v1/members/{mid}/votes", tags=["členové"])
def api_member_votes(mid: str, dissent_only: bool = False, choice: str | None = None,
                     limit: int = Query(50, le=500), offset: int = 0):
    m = queries.member(mid)
    if not m:
        raise HTTPException(404)
    return {"member": m, "votes": queries.member_votes(mid, dissent_only=dissent_only,
                                                       choice=choice, limit=limit, offset=offset)}


@app.get("/api/v1/stats", tags=["přehled"])
def api_stats():
    return queries.stats()
