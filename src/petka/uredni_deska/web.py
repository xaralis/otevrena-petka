"""Úřední deska section: page under /uredni-deska, data files under /uredni-deska/data,
API under /api/v1/uredni-deska."""

import csv
import io
import json
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from ..web.render import tpl
from . import digest as digests, queries, source

pages = APIRouter(prefix="/uredni-deska", include_in_schema=False)
api = APIRouter(prefix="/api/v1/uredni-deska", tags=["úřední deska"])

PER_PAGE = 20


@pages.get("", response_class=HTMLResponse)
def home(request: Request, q: str = "", kde: str = "", sejmute: str = "", druh: str = "", zneni: str = "",
         strana: str = "1"):
    mo5 = kde != "mesto"            # default: only what concerns MO Pardubice V
    active = sejmute != "1"
    druh = druh if druh in queries.KIND_LABEL else ""
    official = zneni == "uredni"   # default: our plain-language card where there is one
    strana = max(1, int(strana)) if strana.strip().isdigit() else 1
    rows, total = queries.search(q, mo5, active, druh or None, limit=PER_PAGE, offset=(strana - 1) * PER_PAGE)
    state = {"q": q.strip(), "kde": "" if mo5 else "mesto", "sejmute": "" if active else "1", "druh": druh,
             "zneni": "uredni" if official else ""}

    def url(**change) -> str:
        """This page with some parameters changed; empty ones dropped, back to page 1."""
        params = {k: v for k, v in {**state, **change}.items() if v}
        return "/uredni-deska" + ("?" + urlencode(params) if params else "")

    return tpl.TemplateResponse(request, "uredni_deska/home.html", {
        **state, "mo5": mo5, "active": active, "official": official, "url": url,
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


@pages.get("/rss.xml")
def rss(zneni: str = ""):
    """RSS 2.0 of what is posted for MO V now, newest first. Our plain-language card where there
    is one (`?zneni=uredni`: the office's titles only). A delivery never carries the addressee's
    name: readers keep items for good, and we drop the name once the notice is taken down."""
    import os
    from email.utils import format_datetime
    from datetime import datetime, time, timezone
    from xml.sax.saxutils import escape
    base = os.environ.get("PUBLIC_URL", "https://opendata.mov.varecha.work").rstrip("/")
    official = zneni == "uredni"
    rows, _ = queries.search("", True, True, None, limit=50)
    items = []
    for n in rows:
        d = None if official else n["digest"]
        link = f"{base}/uredni-deska/{n['id']}"
        if n["kind"] == "doruceni":
            title, text = "Doručení písemnosti veřejnou vyhláškou", "Úřad doručuje písemnost vyvěšením na úřední desce."
        elif d:
            title, text = d["headline"], d["summary"] + f"\n\nÚředně: {n['title']}"
        else:
            title, text = n["title"], f"{n['kind_label']} – vyvěsil {'MO Pardubice V' if n['board'] == 'mo5' else 'Magistrát města Pardubic'}"
        if n["reference"] and n["kind"] != "doruceni":
            text += f" (č. j. {n['reference']})"
        when = format_datetime(datetime.combine(n["published"], time(8), timezone.utc)) if n["published"] else ""
        items.append(f"""<item><title>{escape(title)}</title><link>{link}</link><guid isPermaLink="true">{link}</guid>
<description>{escape(text)}</description><category>{escape(n['kind_label'])}</category>{f'<pubDate>{when}</pubDate>' if when else ''}</item>""")
    name = "Úřední deska MO Pardubice V (úřední znění)" if official else "Úřední deska pro lidi – MO Pardubice V"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>
<title>{name}</title><link>{base}/uredni-deska</link>
<atom:link href="{base}/uredni-deska/rss.xml{'?zneni=uredni' if official else ''}" rel="self" type="application/rss+xml"/>
<description>Co právě visí na úřední desce a týká se městského obvodu Pardubice V. Závazné jsou dokumenty na pardubice.eu.</description>
<language>cs</language>
{chr(10).join(items)}
</channel></rss>"""
    return Response(xml, media_type="application/rss+xml; charset=utf-8")


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


# --- "pro lidi": the reviewers' preview, card images, one notice (keep /{nid} last) --------

def _reviewer(request: Request) -> None:
    """The preview has its own ingress with basic auth, which passes the signed-in user on as
    X-Auth-User; the public ingress strips that header. Without it the page doesn't exist –
    whatever path spelling got the request here."""
    if not request.headers.get("x-auth-user", "").strip():
        raise HTTPException(404)


@pages.get("/navrhy", response_class=HTMLResponse)
def drafts_page(request: Request):
    """Proposed cards for a person to review (behind basic auth at the ingress, not indexed)."""
    _reviewer(request)
    return tpl.TemplateResponse(request, "uredni_deska/navrhy.html", {"rows": queries.drafts()},
                                headers=NO_INDEX)


NO_INDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"}


@pages.get("/navrhy/obrazky/{nid}/{name}")
def draft_image(request: Request, nid: str, name: str):
    _reviewer(request)
    p = digests.asset_path(nid, name, draft=True)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@pages.get("/navrhy/{nid}", response_class=HTMLResponse)
def draft_page(request: Request, nid: str):
    """One proposed card exactly as people would see it, with a slim reviewers' bar."""
    _reviewer(request)
    r = queries.draft(nid)
    if not r:
        raise HTTPException(404)
    d = r["draft"]
    order = [x["id"] for x in queries.drafts()]
    return tpl.TemplateResponse(request, "uredni_deska/notice.html", {
        "n": r, "d": d, "member_rows": queries.members(d.get("members", [])), "preview": True,
        "position": order.index(nid) + 1 if nid in order else None, "total": len(order),
        "prev_id": order[order.index(nid) - 1] if nid in order and order.index(nid) > 0 else None,
        "next_id": order[order.index(nid) + 1] if nid in order and order.index(nid) + 1 < len(order) else None,
    }, headers=NO_INDEX)


@pages.get("/obrazky/{nid}/{name}")
def card_image(nid: str, name: str):
    p = digests.asset_path(nid, name)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


@pages.get("/{nid}", response_class=HTMLResponse)
def notice_page(request: Request, nid: str):
    n = queries.notice(nid)
    if not n:
        raise HTTPException(404)
    d = n.get("digest")
    return tpl.TemplateResponse(request, "uredni_deska/notice.html", {
        "n": n, "d": d, "member_rows": queries.members(d.get("members", [])) if d else [],
        "clusters": digests.CLUSTERS})
