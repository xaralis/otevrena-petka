"""The front page and the street pages. The obvod is the request's (petka.obvody).

    /                    a street search, „Aktuálně“ (this week's cleanings and the board's notices
                         on one map), the areas
    /verejny-prostor/ulice?q=<name>   the search: one street goes straight to its page, more are listed
    /verejny-prostor/ulice/<slug>     one street: next cleaning, decisions, reports, map, everything dated,
                                      and the street's cleaning (#cisteni, it was a page of its own)
"""

import datetime as dt
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import nav
from ..cisteni import queries as cq, source as csource, words as cw
from ..cisteni.web import subscribe
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
        "/verejny-prostor/podnety": (q.thousands(s["n"]), "hlášení za rok"),
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


DETAILS = ("cisteni", "podnety", "usneseni", "zadny")     # the tiles' panels; zadny: all closed


@pages.get("/verejny-prostor/ulice/{slug}", response_class=HTMLResponse)
def street(request: Request, slug: str, radky: str = "", detail: str = "cisteni"):
    """One street: three tiles (the next cleaning, the reports, the decisions) over one panel
    as on the Podněty page (?detail= the open one, without JS), „Aktuálně“ (the map of the
    street and what is current on it, the list beside it; ?radky=vse everything), its cleaning
    (#cisteni) and links to the rest."""
    now = _now()
    today = now.date()
    obvod = request.state.obvod.id
    every = st.streets(obvod)
    s = every.get(slug)
    its = [i for i in cq.items(obvod, cq.year_start(today)) if i["slug"] == slug]
    if not s and not its:
        raise HTTPException(404)
    cl = q.cleaning(its, today)
    checked = _safe(cq.checked)
    cleaning_ctx = {
        "cl_rows": [i for i in its if i["date"] >= today] + sorted((i for i in its if i["date"] < today),
                                                                  key=lambda i: i["date"], reverse=True),
        "gen": cw.genitive(its[0]["street"] if its else s.name), **subscribe([slug]),
        "ics": f"/verejny-prostor/blokove-cisteni/ulice/{slug}.ics",
        "cl_source": csource.PAGE, "cl_checked": checked.date() if checked else None,
    }
    if not s:
        # a street of the harmonogram that isn't one of the obvod's streets (RÚIAN): only its
        # cleaning, the page the cleaning had of its own before it became a section of this one
        return tpl.TemplateResponse(request, "ulice/jen_cisteni.html", {
            "today": today, "name": its[0]["street"], "in_harm": True, **cleaning_ctx,
            "panel": cw.next_panel(cl.on_next, today) if cl.on_next else None,
            "last": cw.nbdm(cl.past[0]["date"]) if cl.past else None})
    names = {x.slug: x.name for x in every.values()}
    reps = q.street_reports(obvod, s.name)
    res, n_res = q.resolutions(s.name)
    geoms = cq.geometries(obvod)
    cl_href = "#cisteni" if its else "/verejny-prostor/blokove-cisteni"

    # the map: the street, its cleaned places (a line on the street's own line, an area filed
    # under it; places filed under the street that lie elsewhere stay off, like on the
    # cleaning page), its reports and the notices that name it
    def on_map(g: dict | None) -> bool:
        return bool(g) and (cq.is_area(g) or (g["type"] in ("LineString", "MultiLineString") and cq.on_street(g, s.geometry)))

    cl_rows = q.cleaning_rows(its, today, cl_href)
    cleaning, anchors = [], []
    for r in cl_rows:
        gs = [(k, geoms[k]) for k in r["keys"] if on_map(geoms.get(k))]
        r["keys"] = [k for k, _ in gs]
        for k, g in gs:
            cleaning.append({"type": "Feature", "geometry": g,
                             "properties": {"key": k, "row": r["key"], "past": r["past"], "area": cq.is_area(g)}})
        if gs:
            lng, lat = q.point_on(gs[0][1])
            anchors.append({"row": r["key"], "lng": lng, "lat": lat, "title": f"Blokové čištění {r['label']}",
                            "text": r["sub"], "when": r["status"][0], "label": f"Blokové čištění {r['label']}, {r['sub']}"})
    ahead = [f["geometry"] for f in cleaning if not f["properties"]["past"]]
    marks = q.board_marks(q.place_notices(), {slug: s}, today, ahead)
    rep_rows = q.report_rows(reps, now, slug)
    rows = q.rows(rep_rows, cl_rows, [q.resolution_row(r, today) for r in res], [q.notice_row(m, today) for m in marks])
    shown = rows if radky == "vse" else q.current(rows, today)[:q.ROWS]
    # the map shows what the rows show, nothing more
    keys = {r["key"] for r in shown}
    row_of = {i: r["key"] for r in rep_rows for i in r["ids"]}
    points = ps.points(reps, now)["features"]
    for f in points:
        f["properties"]["row"] = row_of.get(f["properties"]["id"])
    points = [f for f in points if f["properties"]["row"] in keys]
    cleaning = [f for f in cleaning if f["properties"]["row"] in keys]
    anchors = [a for a in anchors if a["row"] in keys]
    marks = [m for m in marks if f"d{m['id']}" in keys]
    # rows with something on the map get a control that shows it there
    mapped = ({f["properties"]["row"] for f in points} | {f["properties"]["row"] for f in cleaning}
              | {f"d{m['id']}" for m in marks})
    for r in rows:
        r["on_map"] = r["key"] in mapped
    data = {"street": s.geometry, "reports": {"type": "FeatureCollection", "features": points},
            "cleaning": {"type": "FeatureCollection", "features": cleaning}, "anchors": anchors,
            "marks": [{k: m[k] for k in ("id", "nid", "kind", "traffic", "what", "when", "label", "lng", "lat")}
                      | {"row": f"d{m['id']}"} for m in marks]}

    rep = q.reports(reps)
    since = ps.period("12m", today).start          # the panel's chart and kinds: the Podněty page's 12 months
    kinds, kinds_rest = q.report_kinds([r for r in reps if r["reported_at"].date() >= since])
    pd_checked = _safe(pq.checked, obvod)
    pd_url = f"/verejny-prostor/podnety?ulice={slug}" + ("" if rep["ceka"] else "&stav=vse") + "#kde"
    return tpl.TemplateResponse(request, "ulice/ulice.html", {
        "today": today, "s": s, "names": names, "cl": cl, "cl_href": cl_href, "in_harm": bool(its),
        "panel": cw.next_panel(cl.on_next, today) if cl.on_next else None,
        "last": cw.nbdm(cl.past[0]["date"]) if cl.past else None,
        "rep": rep, "rep_months": q.report_months(reps, today), "kinds": kinds, "kinds_rest": kinds_rest,
        "pd_url": pd_url, "pd_kind": f"/verejny-prostor/podnety?ulice={slug}&stav=vse&druh=",
        "n_res": n_res, "res_years": q.resolution_years(res, today), "res_last": [q.resolution_row(r, today) for r in res[:3]],
        "detail": detail if detail in DETAILS else "cisteni",
        "next_date": cl.on_next[0]["date"] if cl.on_next else None,
        "q_url": "/radnice/usneseni?q=" + quote_plus(s.name) + "&rezim=fulltext",
        "deska_url": "/radnice/uredni-deska?q=" + quote_plus(s.name), "n_notices": _safe(q.notices_posted, s.name),
        "rows": shown, "data": data,
        "views": [{"label": "Aktuální", "n": len(q.current(rows, today)[:q.ROWS]), "href": f"/verejny-prostor/ulice/{slug}#aktualne", "on": radky != "vse"},
                  {"label": "Vše", "n": len(rows), "href": f"/verejny-prostor/ulice/{slug}?radky=vse#aktualne", "on": radky == "vse"}],
        "has": {"next": any(not f["properties"]["past"] and not f["properties"]["area"] for f in cleaning),
                "area": any(not f["properties"]["past"] and f["properties"]["area"] for f in cleaning),
                "reports": bool(points), "waiting": bool(rep["ceka"]), "cluster": len(points) > 1,
                "traffic": any(m["traffic"] for m in marks), "other": any(not m["traffic"] for m in marks)},
        "around": st.around(slug, every), "short_title": q.short_title,
        "loc": cw.locative(s.name), "acc": cw.accusative(s.name), **cleaning_ctx,
        "pd_checked": pd_checked.date() if pd_checked else None,
    })


def _safe(f, *args):
    """When a source was last fetched, for „Odkud to víme“; None when it can't be told."""
    try:
        return f(*args)
    except Exception:
        return None
