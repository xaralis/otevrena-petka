"""Otevřená Pětka: the open-data portal of MO Pardubice V.

Portal pages (home, data catalog, planned sections), the sections' routers, REST API
(OpenAPI at /api/docs) and one MCP server for the whole portal at /mcp. Requests for the
old single-section host are redirected to the matching portal path.
"""

import contextlib
import os
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import db
from ..mcp_server import mcp
from ..sections import BY_SLUG, SECTIONS
from ..usneseni import queries, web as usneseni_web
from .render import HERE, tpl

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://opendata.mov.varecha.work").rstrip("/")
LEGACY_HOSTS = {h.strip() for h in os.environ.get("LEGACY_HOSTS", "usneseni.dev.varecha.work").split(",") if h.strip()}

if os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    sentry_sdk.init(os.environ["SENTRY_DSN"], traces_sample_rate=0)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Otevřená Pětka – otevřená data MO Pardubice V", lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.router.routes.extend(mcp.streamable_http_app().routes)  # POST /mcp
app.include_router(usneseni_web.pages)
app.include_router(usneseni_web.api)


# --- the old usneseni.dev.varecha.work: same paths, one level down -----------------------

_LEGACY = [
    (re.compile(r"^/$"), "/usneseni"),
    (re.compile(r"^/(jednani|clenove)(/.*)?$"), r"/usneseni/\1\2"),
    (re.compile(r"^/otevrena-data$"), "/data/usneseni"),
    (re.compile(r"^/opendata/(.*)$"), r"/usneseni/data/\1"),
    (re.compile(r"^/opendata-texts\.txt$"), "/usneseni/data/texts.txt"),
    (re.compile(r"^/opendata-extracted\.txt$"), "/usneseni/data/extracted.txt"),
    (re.compile(r"^/pdf/(.*)$"), r"/usneseni/pdf/\1"),
    (re.compile(r"^/api/v1/(resolutions|meetings|members|stats)(.*)$"), r"/api/v1/usneseni/\1\2"),
]


@app.middleware("http")
async def legacy_redirect(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    path = request.url.path
    if host in LEGACY_HOSTS and path not in ("/mcp", "/healthz"):  # MCP clients don't follow redirects
        for pat, repl in _LEGACY:
            if pat.match(path):
                path = pat.sub(repl, path)
                break
        q = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(PUBLIC_URL + path + q, status_code=301)
    return await call_next(request)


# --- portal pages -------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request):
    return tpl.TemplateResponse(request, "home.html", {
        "stats": queries.stats(), "latest": queries.latest_meetings(4),
    })


@app.get("/data", response_class=HTMLResponse, include_in_schema=False)
def catalog(request: Request):
    return tpl.TemplateResponse(request, "data.html", {
        "stats": queries.stats(), "base": PUBLIC_URL,
        "usneseni_files": usneseni_web.opendata_files(),
    })


@app.get("/data/usneseni", response_class=HTMLResponse, include_in_schema=False)
def dataset_usneseni(request: Request):
    return tpl.TemplateResponse(request, "usneseni/dataset.html", {
        "files": usneseni_web.opendata_files(), "stats": queries.stats(), "base": PUBLIC_URL,
    })


@app.get("/healthz", include_in_schema=False)
def healthz():
    with db.pool().connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


# catch-all for planned sections – keep it last
@app.get("/{slug}", response_class=HTMLResponse, include_in_schema=False)
def planned_section(request: Request, slug: str):
    s = BY_SLUG.get(slug)
    if not s or s.status != "planned":
        raise HTTPException(404)
    return tpl.TemplateResponse(request, "planned.html", {"s": s})


__all__ = ["app", "SECTIONS"]
