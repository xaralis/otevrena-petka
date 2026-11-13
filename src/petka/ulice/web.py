"""The front page and the street pages. The obvod is the request's (petka.obvody).

    /                    a street search, what is going on in the whole obvod, the areas
    /ulice?q=<name>      the search: one street goes straight to its page, more are listed
    /ulice/<slug>        one street: next cleaning, decisions, reports, map, everything dated
"""

import datetime as dt
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import nav
from ..cisteni import queries as cq
from ..podnety import queries as pq, stats as ps
from ..usneseni import queries as uq, search as us
from ..usneseni.text import slug as to_slug
from ..uredni_deska import queries as dq
from ..web.render import tpl
from . import queries as q, streets as st

pages = APIRouter(include_in_schema=False)
TZ = ZoneInfo("Europe/Prague")
SOON = 14       # days: the front page's map shows cleanings this close


def _now() -> dt.datetime:
    """Local time without a zone, as podněty are stored."""
    return dt.datetime.now(TZ).replace(tzinfo=None)


def _today() -> dt.date:
    return _now().date()


def _names(obvod: str) -> dict[str, str]:
    return {s.slug: s.name for s in st.streets(obvod).values()}


def _report_href(r: dict, names: dict[str, str]) -> str:
    s = to_slug(r["street"]) if r.get("street") else None
    return f"/ulice/{s}" if s in names else "/podnety"


# --- the front page ---------------------------------------------------------------------------

def overview_map(its: list[dict], geoms: dict, waiting: list[dict], today: dt.date) -> dict:
    """Cleanings in the next SOON days (`when`: week, two) and the cells with waiting reports
    (grouped like on /podnety, never a report's own position)."""
    nxt: dict[str, dict] = {}
    for i in its:
        if today <= i["date"] <= today + dt.timedelta(days=SOON) and i["key"] in geoms and i["key"] not in nxt:
            nxt[i["key"]] = i
    feats = [{"type": "Feature", "geometry": geoms[k],
              "properties": {"kind": "cleaning", "when": "week" if (i["date"] - today).days <= 7 else "two",
                             "street": i["street"], "slug": i["slug"], "text": i["text"], "date": i["date"].isoformat()}}
             for k, i in nxt.items()]
    feats.sort(key=lambda f: f["properties"]["when"] == "week")       # the nearest on top
    cells = ps.grid(waiting)["features"]
    for c in cells:
        c["properties"] = {"kind": "reports", "n": c["properties"]["n"], "waiting": c["properties"]["waiting"]}
    return {"type": "FeatureCollection", "features": feats + cells}


def home(request: Request):
    today = _today()
    obvod = request.state.obvod.id
    names = _names(obvod)
    its = cq.items(obvod, cq.year_start(today))
    future = [i for i in its if i["date"] >= today]
    nd = cq.next_date(future, today)
    items = []
    if nd:
        text, href = q.next_cleaning_line([i for i in future if i["date"] == nd])
        items.append({"date": nd, "source": "Blokové čištění", "text": text, "href": href, "next": True})

    now = _now()
    per = ps.period("12m", today)
    rows = pq.period_rows(obvod, per.start, per.end)
    s = ps.summary(rows, per, now)
    items += [q.report_item(r, _report_href(r, names)) for r in s["newest"][:3]]
    items += [q.notice_item(n) for n in q.latest_notices(2)]
    hits, _ = us.search("", filters=us.Filters(status="usneseni"), limit=2)
    items += [q.resolution_item(h.row) for h in hits]

    ustats, dstats = uq.stats(), dq.stats()
    info = {
        "/usneseni": f"{q.thousands(ustats['resolutions'])} usnesení ze {ustats['meetings']} jednání od roku {ustats['first_date'].year}",
        "/usneseni/clenove": "15 zastupitelů a jak kdo hlasuje",
        "/uredni-deska": f"{dstats['posted_mo5']} oznámení k obvodu, {dstats['posted'] - dstats['posted_mo5']} magistrátu",
        "/blokove-cisteni": f"{len(its)} termínů na {len({i['key'] for i in its})} místech letos",
        "/podnety": f"{s['n']} hlášení za rok, {s['done_pct']} % vyřešeno",
    }
    g = {x.label: x for x in nav.GROUPS}
    areas = [("Radnice", g["Radnice"].items), ("Veřejný prostor", g["Veřejný prostor"].items),
             ("Finance a ankety", g["Finance"].items + g["Zapojte se"].items)]
    waiting = [r for r in rows if ps.outcome(r) == "ceka"]
    return tpl.TemplateResponse(request, "ulice/home.html", {
        "today": today, "names": names, "miss": request.query_params.get("ulice", "").strip()[:80],
        "feed": q.feed(items, q.FEED_HOME), "areas": areas, "info": info,
        "ustats": ustats, "geojson": overview_map(its, cq.geometries(obvod), waiting, today),
        "has_week": any(i["date"] <= today + dt.timedelta(days=7) for i in future),
        "has_two": any(7 < (i["date"] - today).days <= SOON for i in future), "has_waiting": bool(waiting),
    })


# --- streets ----------------------------------------------------------------------------------

@pages.get("/ulice", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    names = _names(request.state.obvod.id)
    query = q.strip()
    found = st.find(query, names) if query else []
    if len(found) == 1:
        return RedirectResponse(f"/ulice/{found[0]}", status_code=303)
    if query and not found:    # back to the search on the front page, with the hint under the field
        return RedirectResponse(f"/?ulice={quote_plus(query)}#hledat", status_code=303)
    return tpl.TemplateResponse(request, "ulice/hledat.html", {
        "query": query, "found": [(s, names[s]) for s in found], "names": names})


@pages.get("/ulice/{slug}", response_class=HTMLResponse)
def street(request: Request, slug: str):
    today = _today()
    obvod = request.state.obvod.id
    every = st.streets(obvod)
    s = every.get(slug)
    if not s:
        raise HTTPException(404)
    names = {x.slug: x.name for x in every.values()}
    its = [i for i in cq.items(obvod, cq.year_start(today)) if i["slug"] == slug]
    cl = q.cleaning(its, today)
    reps = q.street_reports(obvod, s.name)
    res, n_res = q.resolutions(s.name)

    items = []
    if cl.next:
        items.append({"date": cl.next, "source": "Blokové čištění", "next": True, "text": q.cleaning_text(cl),
                      "href": f"/blokove-cisteni/ulice/{slug}"})
    items += [{"date": i["date"], "source": "Blokové čištění", "text": i["short"] or i["text"],
               "href": f"/blokove-cisteni/ulice/{slug}"} for i in cl.past[:3]]
    items += [q.resolution_item(r) for r in res]
    items += [q.report_item(r, "/podnety") | {"text": r["category"]} for r in reps[:4]]

    geoms = cq.geometries(obvod)
    feats = [{"type": "Feature", "geometry": s.geometry, "properties": {"kind": "street"}}]
    order = {"past": 0, "later": 1, "next": 2}
    for i in sorted(its, key=lambda i: order["next" if i["date"] == cl.next else "past" if i["date"] < today else "later"]):
        if i["key"] in geoms:
            when = "next" if i["date"] == cl.next else "past" if i["date"] < today else "later"
            feats.append({"type": "Feature", "geometry": geoms[i["key"]],
                          "properties": {"kind": "cleaning", "when": when, "text": i["text"], "date": i["date"].isoformat()}})
    cells = ps.grid(reps)["features"]
    for c in cells:
        c["properties"] = {"kind": "reports", "n": c["properties"]["n"], "waiting": c["properties"]["waiting"]}
    whens = {f["properties"].get("when") for f in feats}

    return tpl.TemplateResponse(request, "ulice/ulice.html", {
        "today": today, "s": s, "names": names, "cl": cl, "rep": q.reports(reps), "n_res": n_res,
        "last_res": res[0]["date"] if res else None, "n_notices": q.notices_posted(s.name),
        "q_url": "/usneseni?q=" + quote_plus(s.name) + "&rezim=fulltext",
        "deska_url": "/uredni-deska?q=" + quote_plus(s.name), "in_harm": bool(its),
        "feed": q.feed(items, q.FEED_STREET), "around": st.around(slug, every),
        "geojson": {"type": "FeatureCollection", "features": feats + cells},
        "has_next": "next" in whens, "has_later": "later" in whens, "has_past": "past" in whens,
        "has_reports": bool(cells), "since_word": q.since_word,
    })
