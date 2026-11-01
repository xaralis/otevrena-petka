"""Úřední deska section: page under /uredni-deska, data files under /uredni-deska/data,
API under /api/v1/uredni-deska."""

import csv
import io
import json
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..web.render import tpl
from . import queries, source

pages = APIRouter(prefix="/uredni-deska", include_in_schema=False)
api = APIRouter(prefix="/api/v1/uredni-deska", tags=["úřední deska"])

PER_PAGE = 20


@pages.get("", response_class=HTMLResponse)
def home(request: Request, q: str = "", kde: str = "", sejmute: str = "", druh: str = "", strana: str = "1"):
    mo5 = kde != "mesto"            # default: only what concerns MO Pardubice V
    active = sejmute != "1"
    druh = druh if druh in queries.KIND_LABEL else ""
    strana = max(1, int(strana)) if strana.strip().isdigit() else 1
    rows, total = queries.search(q, mo5, active, druh or None, limit=PER_PAGE, offset=(strana - 1) * PER_PAGE)
    state = {"q": q.strip(), "kde": "" if mo5 else "mesto", "sejmute": "" if active else "1", "druh": druh}

    def url(**change) -> str:
        """This page with some parameters changed; empty ones dropped, back to page 1."""
        params = {k: v for k, v in {**state, **change}.items() if v}
        return "/uredni-deska" + ("?" + urlencode(params) if params else "")

    return tpl.TemplateResponse(request, "uredni_deska/home.html", {
        **state, "mo5": mo5, "active": active, "url": url,
        "rows": rows, "total": total, "strana": strana, "pages": -(-total // PER_PAGE),
        "kinds": queries.kinds(mo5, active), "stats": queries.stats(), "boards": source.BOARDS,
    })


# --- open data: generated from the database on request (a few hundred rows) -----------------

def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _csv(k, v):
    if k == "attachments":
        return json.dumps(v, ensure_ascii=False)
    if k == "agenda":
        return "; ".join(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return _iso(v)


@pages.get("/data/notices.json")
def data_json():
    rows = [{k: _iso(v) for k, v in r.items()} for r in queries.export_rows()]
    return JSONResponse(rows, headers={"Content-Disposition": 'inline; filename="notices.json"'})


@pages.get("/data/notices.csv")
def data_csv():
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=queries.EXPORT_FIELDS)
    w.writeheader()
    for r in queries.export_rows():
        w.writerow({k: _csv(k, v) for k, v in r.items()})
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="notices.csv"'})


# --- REST API -------------------------------------------------------------------------------

@api.get("/notices")
def api_notices(q: str = "", mo5: bool = True, active: bool = True, kind: str | None = None,
                limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    """Oznámení z úřední desky, nejnovější první. `mo5=true` (výchozí) = jen to, co se týká
    MO Pardubice V (vše z desky obvodu + oznámení magistrátu, která obvod výslovně jmenují);
    `mo5=false` = i celá deska magistrátu. `active=false` = sejmutá oznámení (archiv).
    `q` hledá v názvu, čísle jednacím a odboru (bez diakritiky, předpony slov)."""
    rows, total = queries.search(q, mo5, active, kind, limit=limit, offset=offset)
    return {"total": total, "results": rows}


@api.get("/notices/{nid}")
def api_notice(nid: str):
    r = queries.notice(nid)
    if not r:
        raise HTTPException(404)
    return r


@api.get("/boards")
def api_boards():
    """Zdrojové desky (OFN JSON na pardubice.eu), kdy jsme je naposledy stáhli a počty."""
    return queries.stats()


@api.get("/kinds")
def api_kinds():
    """Druhy oznámení (odvozené z názvu, ne údaj města)."""
    return queries.KIND_LABEL
