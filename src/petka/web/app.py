"""Otevřená Pětka: the open-data portal of MO Pardubice V.

Portal pages (home, data catalog, planned sections), the sections' routers, REST API
(OpenAPI at /api/docs) and one MCP server for the whole portal at /mcp.
"""

import asyncio
import contextlib
import html
import os
import re
from collections import OrderedDict
from urllib.parse import parse_qs

from xml.sax.saxutils import escape

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from .. import db
from ..ankety import web as ankety_web
from ..mcp_server import mcp
from ..rozpocet import web as rozpocet_web
from ..sections import BY_SLUG, SECTIONS
from ..uredni_deska import queries as deska_queries, source as deska_source, web as deska_web
from ..usneseni import queries, search as usneseni_search, web as usneseni_web
from . import og
from .render import HERE, asset_version, tpl

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://otevrenapetka.cz").rstrip("/")

if os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    sentry_sdk.init(os.environ["SENTRY_DSN"], traces_sample_rate=0, send_default_pii=False,
                    environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
                    release=os.environ.get("APP_VERSION") or None)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Otevřená Pětka – otevřená data MO Pardubice V", lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
class _Static(StaticFiles):
    """A URL carrying the file's own hash (?v=<asset_version>) never changes, so it may be
    cached for a year. Any other version – e.g. a new page asking an old pod during a rolling
    update – must not be: the browser would keep the old file under the new URL for good."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code in (200, 206):
            v = parse_qs(scope.get("query_string", b"").decode()).get("v", [""])[0]
            resp.headers["Cache-Control"] = ("public, max-age=31536000, immutable" if v == asset_version(path)
                                             else "no-cache" if v else "public, max-age=604800")
        return resp


app.mount("/static", _Static(directory=HERE / "static"), name="static")
app.router.routes.extend(mcp.streamable_http_app().routes)  # POST /mcp
app.include_router(usneseni_web.pages)
app.include_router(usneseni_web.api)
app.include_router(deska_web.pages)   # before the planned-section catch-all /{slug}
app.include_router(deska_web.api)
app.include_router(ankety_web.api)
app.include_router(rozpocet_web.pages)  # preview behind a secret token; /rozpocet itself stays planned


class _Head:
    """FastAPI GET routes answer HEAD with 405; monitors and link checkers send HEAD.
    Run HEAD as GET on a copy of the scope; uvicorn still sees HEAD and drops the body."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "HEAD":
            scope = dict(scope, method="GET")
        await self.app(scope, receive, send)


class _Gzip:
    """Compress pages and data files, but leave the MCP endpoint's responses alone."""
    def __init__(self, app):
        self.app, self.gzip = app, GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope, receive, send):
        # MCP streams; PMTiles is read with Range requests, which compression would break
        if scope["type"] == "http" and not scope["path"].startswith("/mcp") and not scope["path"].endswith(".pmtiles"):
            return await self.gzip(scope, receive, send)
        await self.app(scope, receive, send)


app.add_middleware(_Gzip)
app.add_middleware(_Head)


# --- error pages: the portal's look for people, JSON for the API ------------------------

_ERRORS = {
    404: ("Tahle stránka tu není", "Odkaz je možná starý nebo v něm je překlep. Zkuste to, co hledáte, najít vyhledáváním."),
    500: ("Něco se pokazilo u nás", "Chybu jsme zaznamenali a podíváme se na ni. Zkuste stránku za chvíli načíst znovu."),
}


def _error_response(request: Request, status: int, detail=None):
    if request.url.path.startswith(("/api/", "/mcp")):
        return JSONResponse({"detail": detail or _ERRORS.get(status, ("Chyba",))[0]}, status_code=status)
    title, text = _ERRORS.get(status, ("Chyba", "Požadavek se nepodařilo zpracovat."))
    return tpl.TemplateResponse(request, "error.html", {"title": title, "text": text, "error_page": True},
                                status_code=status)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code in _ERRORS or request.url.path.startswith(("/api/", "/mcp")):
        return _error_response(request, exc.status_code, exc.detail)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    # Starlette re-raises after this, so Sentry/GlitchTip still records the exception
    return _error_response(request, 500)


# --- portal pages -------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def front(request: Request, q: str = "", kde: str = "", sejmute: str = "", druh: str = "", zneni: str = "",
          strana: str = "1"):
    """The front page is the úřední deska pro lidi (its own address stays canonical)."""
    return deska_web.home(request, q=q, kde=kde, sejmute=sejmute, druh=druh, zneni=zneni, strana=strana)


@app.get("/prehled", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request):
    hits, _ = usneseni_search.search("", filters=usneseni_search.Filters(status="usneseni"), limit=3)
    # the newest notices of MO V, leaving out deliveries to named people (not news, and personal)
    notices = [n for n in deska_queries.search(limit=12)[0] if n["kind"] != "doruceni"][:3]
    return tpl.TemplateResponse(request, "home.html", {
        "stats": queries.stats(), "latest": [h.row for h in hits],
        "deska": deska_queries.stats(), "notices": notices,
    })


@app.get("/data", response_class=HTMLResponse, include_in_schema=False)
def catalog(request: Request):
    return tpl.TemplateResponse(request, "data.html", {
        "stats": queries.stats(), "base": PUBLIC_URL,
        "tables": queries.opendata_tables(), "updated": usneseni_web.opendata_updated(),
        "deska": deska_queries.stats(), "deska_source": deska_source,
    })


@app.get("/data/usneseni", include_in_schema=False)
def dataset_usneseni_moved():
    return RedirectResponse("/data#usneseni", status_code=301)


# --- files crawlers, browsers and feed readers ask for at fixed paths ---------------------

ICONS = HERE / "static" / "icons"


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(ICONS / "favicon.ico", headers={"Cache-Control": "public, max-age=604800"})


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(ICONS / "apple-touch-icon.png", headers={"Cache-Control": "public, max-age=604800"})


@app.get("/site.webmanifest", include_in_schema=False)
def manifest():
    return JSONResponse({
        "name": "Otevřená Pětka", "short_name": "Pětka", "lang": "cs", "start_url": "/",
        "display": "browser", "background_color": "#ffffff", "theme_color": "#de091c",
        "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, media_type="application/manifest+json")


@app.get("/robots.txt", include_in_schema=False)
def robots():
    # The API and MCP are for programs; the bulk files are linked from /data
    return PlainTextResponse(f"User-agent: *\nDisallow: /api/\nDisallow: /mcp\n\nSitemap: {PUBLIC_URL}/sitemap.xml\n")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    pages = ["/prehled", "/data", "/soukromi", "/pristupnost", "/usneseni", "/usneseni/mapa", "/usneseni/jednani",
             "/usneseni/clenove", "/usneseni/clenove/ucast", "/usneseni/metodika", "/uredni-deska"]
    pages += [f"/{s.slug}" for s in SECTIONS if s.status == "planned"]
    urls = [(u, None) for u in pages]
    with db.pool().connection() as conn:
        urls += [(f"/usneseni/jednani/{r['id']}", r["date"]) for r in conn.execute(
            "SELECT id, date FROM meetings ORDER BY date DESC")]
        urls += [(f"/usneseni/{r['uid']}", r["date"]) for r in conn.execute(
            "SELECT uid, date FROM resolutions ORDER BY date DESC, seq DESC")]
        urls += [(f"/usneseni/clenove/{r['id']}", None) for r in conn.execute("SELECT id FROM members ORDER BY id")]
    body = "".join(f"<url><loc>{escape(PUBLIC_URL + u)}</loc>{f'<lastmod>{d.isoformat()}</lastmod>' if d else ''}</url>"
                   for u, d in urls)
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + body + "</urlset>", media_type="application/xml")


@app.get("/.well-known/security.txt", include_in_schema=False)
def security_txt():
    return PlainTextResponse("Contact: mailto:filip.varecha@pirati.cz\nExpires: 2027-11-01T00:00:00Z\n"
                             f"Preferred-Languages: cs, en\nCanonical: {PUBLIC_URL}/.well-known/security.txt\n")


@app.get("/soukromi", response_class=HTMLResponse, include_in_schema=False)
def privacy(request: Request):
    return tpl.TemplateResponse(request, "privacy.html", {})


@app.get("/pristupnost", response_class=HTMLResponse, include_in_schema=False)
def accessibility(request: Request):
    return tpl.TemplateResponse(request, "accessibility.html", {})


@app.get("/healthz", include_in_schema=False)
def healthz():
    with db.pool().connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


# --- share images ---------------------------------------------------------------------------

_OG_TITLE = re.compile(r'<meta property="og:title" content="([^"]*)"')
_og_cache: OrderedDict[tuple[str, str, str], bytes] = OrderedDict()


_OG_PATH = re.compile(r"(?:[a-z0-9_-]+(?:\.[a-z0-9_-]+)*/)*[a-z0-9_-]+\.png")   # no "..", "//", "%", "?"


@app.get("/og/{path:path}", include_in_schema=False)
async def og_image(request: Request, path: str):
    """The share image of page /<path> (og:image is /og/<path>.png, the front page /og/index.png).
    The title comes from the page itself, rendered in-process, so only text the page shows gets drawn."""
    if request.headers.get("x-petka-og") or not _OG_PATH.fullmatch(path) or path.startswith("og/"):
        raise HTTPException(404)        # the header marks our own request: never render recursively
    page = "/" if path == "index.png" else "/" + path[:-4]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                 base_url=PUBLIC_URL) as client:
        r = await client.get(page, headers={"accept": "text/html", "x-petka-og": "1"})
    m = _OG_TITLE.search(r.text) if r.status_code == 200 and r.headers.get("content-type", "").startswith("text/html") else None
    if not m:
        raise HTTPException(404)
    section = BY_SLUG.get(page.strip("/").split("/")[0])
    key = (page, html.unescape(m[1]), section.title if section else "")
    if key not in _og_cache:
        _og_cache[key] = await asyncio.to_thread(og.render, key[1], key[2])
        while len(_og_cache) > 300:
            _og_cache.popitem(last=False)
    return Response(_og_cache[key], media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


# catch-all for planned sections – keep it last
@app.get("/{slug}", response_class=HTMLResponse, include_in_schema=False)
def planned_section(request: Request, slug: str):
    s = BY_SLUG.get(slug)
    if not s or s.status != "planned":
        raise HTTPException(404)
    return tpl.TemplateResponse(request, "planned.html", {"s": s})


__all__ = ["app", "SECTIONS"]
