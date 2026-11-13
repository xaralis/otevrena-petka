"""The front page and the street pages. The obvod is the request's (petka.obvody).

    /                    a street search, „Aktuálně“ (this week's cleanings and the board's notices
                         on one map), the areas
    /verejny-prostor/ulice?q=<name>   the search: one street goes straight to its page, more are listed
    /verejny-prostor/ulice/<slug>     one street: next cleaning, decisions, reports, map, everything dated
"""

import datetime as dt
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import nav
from ..cisteni import queries as cq
from ..podnety import queries as pq, stats as ps
from ..usneseni import queries as uq
from ..uredni_deska import queries as dq
from ..web.render import tpl
from . import queries as q, streets as st

pages = APIRouter(include_in_schema=False)
TZ = ZoneInfo("Europe/Prague")


def _now() -> dt.datetime:
    """Local time without a zone, as podněty are stored."""
    return dt.datetime.now(TZ).replace(tzinfo=None)


def _today() -> dt.date:
    return _now().date()


def _names(obvod: str) -> dict[str, str]:
    return {s.slug: s.name for s in st.streets(obvod).values()}


# --- the front page ---------------------------------------------------------------------------

def home(request: Request):
    today = _today()
    obvod = request.state.obvod.id
    every = st.streets(obvod)
    names = {s.slug: s.name for s in every.values()}
    its = cq.items(obvod, cq.year_start(today))
    week = q.week_cleanings(its, cq.geometries(obvod), today)
    marks = q.board_marks(q.place_notices(), every, today, [f["geometry"] for f in week["lines"]["features"]])
    traffic = sorted((m for m in marks if m["traffic"]), key=lambda m: m["order"])

    per = ps.period("12m", today)
    s = ps.summary(pq.period_rows(obvod, per.start, per.end), per, _now())
    ustats, dstats = uq.stats(), dq.stats()
    # the right side of each link row: one number and what it counts, the same shape everywhere
    info = {
        "/verejny-prostor/ulice": (q.thousands(len(names)), "ulic obvodu"),
        "/radnice/usneseni": (q.thousands(ustats["resolutions"]), "usnesení"),
        "/radnice/zastupitele": ("15", "zastupitelů"),
        "/radnice/uredni-deska": (q.thousands(dstats["posted_mo5"]), "oznámení visí"),
        "/verejny-prostor/blokove-cisteni": (q.thousands(len(its)), "termínů letos"),
        "/verejny-prostor/zavady": (q.thousands(s["n"]), "hlášení za rok"),
    }
    g = {x.label: x for x in nav.GROUPS}
    areas = [("Radnice", g["Radnice"].items), ("Veřejný prostor", g["Veřejný prostor"].items),
             ("Finance a ankety", g["Finance"].items + g["Zapojte se"].items)]
    data = {"lines": week["lines"], "anchors": week["anchors"],
            "days": [{"keys": d["keys"], "sids": d["sids"]} for d in week["rows"]],
            "marks": [{k: m[k] for k in ("id", "nid", "kind", "traffic", "street", "what", "when", "label", "lng", "lat")}
                      for m in marks]}
    return tpl.TemplateResponse(request, "ulice/home.html", {
        "today": today, "names": names, "miss": request.query_params.get("ulice", "").strip()[:80],
        "areas": areas, "info": info, "ustats": ustats,
        "days": week["rows"], "traffic": traffic, "has_other": any(not m["traffic"] for m in marks),
        "akt": data,
    })


# --- streets ----------------------------------------------------------------------------------

@pages.get("/verejny-prostor/ulice", response_class=HTMLResponse)
def search(request: Request, q: str = "", z: str = ""):
    """The Ulice page: the search and every street of the obvod. A search from the front page
    (z=uvod) that finds nothing goes back there with the hint under its field."""
    names = _names(request.state.obvod.id)
    query = q.strip()
    found = st.find(query, names) if query else []
    if len(found) == 1:
        return RedirectResponse(f"/verejny-prostor/ulice/{found[0]}", status_code=303)
    if query and not found and z == "uvod":
        return RedirectResponse(f"/?ulice={quote_plus(query)}#hledat", status_code=303)
    every = sorted(names.items(), key=lambda kv: st.fold(kv[1]))
    return tpl.TemplateResponse(request, "ulice/hledat.html", {
        "query": query, "found": [(s, names[s]) for s in found], "names": names, "every": every,
        "miss": query if query and not found else ""})


@pages.get("/verejny-prostor/ulice/{slug}", response_class=HTMLResponse)
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
                      "href": f"/verejny-prostor/blokove-cisteni/ulice/{slug}"})
    items += [{"date": i["date"], "source": "Blokové čištění", "text": i["short"] or i["text"],
               "href": f"/verejny-prostor/blokove-cisteni/ulice/{slug}"} for i in cl.past[:3]]
    items += [q.resolution_item(r) for r in res]
    items += [q.report_item(r, "/verejny-prostor/zavady") | {"text": r["category"]} for r in reps[:4]]

    geoms = cq.geometries(obvod)
    # the map shows the street itself and, on it, the stretches still to be cleaned (the next ink,
    # later dashed); places filed under the street that lie elsewhere and past cleanings stay off,
    # like on the cleaning page of the street
    feats = [{"type": "Feature", "geometry": s.geometry, "properties": {"kind": "street"}}]
    for i in sorted((i for i in its if i["date"] >= today), key=lambda i: i["date"] == cl.next):
        g = geoms.get(i["key"])
        if g and g["type"] in ("LineString", "MultiLineString") and cq.on_street(g, s.geometry):
            when = "next" if i["date"] == cl.next else "later"
            feats.append({"type": "Feature", "geometry": g,
                          "properties": {"kind": "cleaning", "when": when, "text": i["text"], "date": i["date"].isoformat()}})
    cells = ps.grid(reps)["features"]
    for c in cells:
        c["properties"] = {"kind": "reports", "n": c["properties"]["n"], "waiting": c["properties"]["waiting"]}
    whens = {f["properties"].get("when") for f in feats}

    return tpl.TemplateResponse(request, "ulice/ulice.html", {
        "today": today, "s": s, "names": names, "cl": cl, "rep": q.reports(reps), "n_res": n_res,
        "last_res": res[0]["date"] if res else None, "n_notices": q.notices_posted(s.name),
        "q_url": "/radnice/usneseni?q=" + quote_plus(s.name) + "&rezim=fulltext",
        "deska_url": "/radnice/uredni-deska?q=" + quote_plus(s.name), "in_harm": bool(its),
        "feed": q.feed(items, q.FEED_STREET), "around": st.around(slug, every),
        "geojson": {"type": "FeatureCollection", "features": feats + cells},
        "has_next": "next" in whens, "has_later": "later" in whens,
        "has_reports": bool(cells), "since_word": q.since_word,
    })
