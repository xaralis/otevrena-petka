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

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import db, nav
from ..cisteni import queries as cq, source as csource, words as cw
from ..cisteni.web import subscribe
from ..podnety import photos as pphotos, queries as pq, source as psource, stats as ps
from ..usneseni import queries as uq
from ..uredni_deska import queries as dq
from ..web.render import tpl
from . import feed, push, queries as q, streets as st

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

def _drops(today: dt.date) -> list:
    """This year's přistavení of the velkoobjemové kontejnery still to come (petka.odpady)."""
    from ..odpady import data as od
    return [d for d in od.drops(today.year) if d.date >= today]


def every_name(request: Request, slug: str) -> str:
    return _names(request.state.obvod.id).get(slug, "")


def _waste_and_closures(obvod: str, name: str, now) -> dict:
    """The street page's rows for odpady (the svoz days, the nearest kontejner on objemný odpad)
    and for uzavírky (closures naming the street now)."""
    from ..odpady import data as od
    from ..ulice.feed import _near_containers
    today = now.date() if hasattr(now, "date") else now
    try:
        near = [d for d in _near_containers(obvod)(name) if d.date >= today]
    except Exception:
        near = []
    try:
        from ..obvody import ObvodFilter
        from ..uzavirky import queries as uzq
        at = dt.datetime.now(TZ)
        closures = [c for c in uzq.closures(uzq.rows(ObvodFilter.only(obvod), at), at) if c.now(at) and uzq.names(c, name)]
    except Exception:
        closures = []
    return {"svoz": od.svoz_text(name), "vok": near[0] if near else None, "n_closures": len(closures)}


def _closures(obvod: str, today: dt.date) -> list[dict]:
    """The obvod's closures from NDIC (petka.uzavirky) as the front page's traffic marks: those
    going on and those starting within a week, each on the middle of its stretch, linked to its
    place on the Uzavírky page. A database without them (a test, a new obvod) is no closures."""
    from shapely.geometry import shape
    from ..obvody import ObvodFilter
    from ..uzavirky import queries as uzq
    try:
        now = dt.datetime.now(TZ)
        cs = uzq.closures(uzq.rows(ObvodFilter.only(obvod), now), now)
    except Exception:
        return []
    out = []
    for c in cs:
        if not c.geometry or (c.starts and c.starts.astimezone(TZ).date() > today + dt.timedelta(days=q.WEEK)):
            continue
        g = shape(c.geometry)
        p = g.interpolate(0.5, normalized=True) if g.geom_type in ("LineString", "MultiLineString") else g.representative_point()
        a = c.starts.astimezone(TZ).date() if c.starts else None
        b = c.ends.astimezone(TZ).date() if c.ends else None
        when = q.period(a, b) if a or b else ""
        out.append({"id": f"uz{len(out)}", "nid": None, "href": f"/verejny-prostor/uzavirky#uz-{c.id}", "kind": "doprava",
                    "traffic": True, "street": c.place, "what": c.what, "when": when,
                    "label": f"{'Uzavírka' if c.closed else 'Dopravní omezení'}: {c.place}, {c.what}" + (f", {when}" if when else ""),
                    "box": q.short_until(a, b, today) if b else "", "lng": round(p.x, 6), "lat": round(p.y, 6), "date": a,
                    "order": (bool(a and a > today), a if a and a > today else (b or dt.date.max))})
    return out


def home(request: Request):
    today = _today()
    obvod = request.state.obvod.id
    every = st.streets(obvod)
    names = {s.slug: s.name for s in every.values()}
    its = cq.items(obvod, cq.year_start(today))
    week = q.week_cleanings(its, cq.geometries(obvod), today)
    marks = q.board_marks(q.place_notices(), every, today, [f["geometry"] for f in week["lines"]["features"]])
    closures = _closures(obvod, today)
    marks += closures
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
        "/verejny-prostor/odpady": (str(sum(1 for d in _drops(today) if d.obvod == obvod)), "přistavení letos"),
        "/verejny-prostor/uzavirky": (str(n := sum(1 for m in closures if not m["order"][0])),
                                      cw.plural(n, "uzavírka platí", "uzavírky platí", "uzavírek platí")),
    }
    g = {x.label: x for x in nav.GROUPS}
    areas = [("Radnice", g["Radnice"].items), ("Veřejný prostor", g["Veřejný prostor"].items),
             ("Finance a ankety", g["Finance"].items + g["Zapojte se"].items)]
    data = {"lines": week["lines"], "anchors": week["anchors"],
            "days": [{"keys": d["keys"], "sids": d["sids"]} for d in week["rows"]],
            "marks": [{k: m.get(k) for k in ("id", "nid", "href", "kind", "traffic", "street", "what", "when", "label", "lng", "lat")}
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
    radky = radky if radky in {k for k, _, _ in q.VIEWS} else ""
    shown = q.view(rows, radky, today)
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
        **_waste_and_closures(request.state.obvod.id, every_name(request, slug), now),
        "today": today, "s": s, "names": names, "cl": cl, "cl_href": cl_href, "in_harm": bool(its),
        "panel": cw.next_panel(cl.on_next, today) if cl.on_next else None,
        "last": cw.nbdm(cl.past[0]["date"]) if cl.past else None,
        "rep": rep, "rep_months": q.report_months(reps, today), "kinds": kinds, "kinds_rest": kinds_rest,
        "pd_url": pd_url, "pd_kind": f"/verejny-prostor/podnety?ulice={slug}&stav=vse&druh=",
        "n_res": n_res, "res_years": q.resolution_years(res, today), "res_last": [q.resolution_row(r, today) for r in res[:3]],
        "detail": detail if detail in DETAILS else "cisteni",
        "waiting": [{"key": f"r{r['id']}", "category": r["category"], "since": r["reported_at"].date(),
                     "days": (today - r["reported_at"].date()).days, "status": ps.status_word(r),
                     "text": (r.get("description") or "").strip(), "photo": pphotos.href(r["id"], r.get("photo_version")),
                     "href": psource.detail(r["id"])}
                    for r in sorted(reps, key=lambda r: r["reported_at"]) if ps.outcome(r) == "ceka"],   # longest waiting first
        "next_date": cl.on_next[0]["date"] if cl.on_next else None,
        "q_url": "/radnice/usneseni?q=" + quote_plus(s.name) + "&rezim=fulltext",
        "deska_url": "/radnice/uredni-deska?q=" + quote_plus(s.name), "n_notices": _safe(q.notices_posted, s.name),
        "rows": shown, "data": data,
        "views": [{"label": label, "hint": hint, "n": q.count(q.view(rows, k, today)), "on": k == radky,
                   "href": f"/verejny-prostor/ulice/{slug}" + (f"?radky={k}" if k else "") + "#aktualne"}
                  for k, label, hint in q.VIEWS if k in ("", "vse") or q.view(rows, k, today)],
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


# --- Upozornění: what is new in the streets one follows (RSS now, web push later) --------------

def _sources(obvod: str) -> "feed.Sources":
    return feed.sources(obvod)


def _picked(request: Request, ulice: list[str], co: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    names = _names(request.state.obvod.id)
    slugs = [s for s in dict.fromkeys(x for v in ulice for x in v.split(",")) if s in names]
    valid = [k for k, _, _ in feed.KINDS]
    kinds = [k for k in dict.fromkeys(x for v in co for x in v.split(",")) if k in valid] or [k for k in valid if k not in feed.OPT_IN]
    return [(names[s], s) for s in slugs], kinds


def _feed_url(streets: list[tuple[str, str]], kinds: list[str]) -> str:
    every = set(kinds) == {k for k, _, _ in feed.KINDS} - feed.OPT_IN
    return (_origin() + "/muj-prehled/rss.xml?ulice=" + ",".join(s for _, s in streets)
            + ("" if every else "&co=" + ",".join(kinds)))


def _origin() -> str:
    import os
    return os.environ.get("PUBLIC_URL", "https://otevrenapetka.cz").rstrip("/")


def _preview(obvod: str, streets: list[tuple[str, str]], kinds: list[str]) -> dict:
    """The page's preview (the chosen kinds' events of the last PREVIEW days, all of them: the box
    scrolls) and how many events of each kind the streets had in the same days."""
    if not streets:
        return {"rows": [], "counts": {}}
    now = dt.datetime.now(feed.TZ)
    every = feed.events(streets, _sources(obvod), now)
    counts = {k: sum(1 for e in every if feed.GROUP[e.kind] == k and e.at >= now - dt.timedelta(days=feed.PREVIEW))
              for k, _, _ in feed.KINDS}
    since = now - dt.timedelta(days=feed.PREVIEW)
    rows = [{"date": q.dm(e.at.date()), "head": e.head, "sub": e.sub, "status": e.status[0], "cls": e.status[1],
             "href": e.path} for e in every if feed.GROUP[e.kind] in kinds and e.at >= since]
    return {"rows": rows, "counts": counts}


@pages.get("/muj-prehled", response_class=HTMLResponse)
def follow(request: Request, ulice: list[str] = Query(default=[]), co: list[str] = Query(default=[]),
           pridat: str = "", odebrat: str = ""):
    """Upozornění: pick streets and what to hear about; the preview of the feed, and three ways
    to get it (browser notifications with JS, the calendar of cleanings, the RSS address). Without
    JS the form comes back here (pridat= adds a street, odebrat= drops one)."""
    obvod = request.state.obvod.id
    names = _names(obvod)
    streets, kinds = _picked(request, ulice, co)
    streets = [x for x in streets if x[1] != odebrat]
    missing = None
    if pridat.strip():
        hits = st.find(pridat, names)
        if len(hits) == 1 and hits[0] not in {s for _, s in streets}:
            streets.append((names[hits[0]], hits[0]))
        elif not hits:
            missing = pridat.strip()
    slugs = [s for _, s in streets]
    return tpl.TemplateResponse(request, "ulice/upozorneni.html", {
        "names": names, "streets": streets, "kinds": kinds, "KINDS": feed.KINDS, "OPT_IN": feed.OPT_IN, "missing": missing,
        "preview": _preview(obvod, streets, kinds), "vapid": push.public_key(),
        "feed_url": _feed_url(streets, kinds) if streets else None,
        **(subscribe(slugs) if slugs else {})})


@pages.get("/muj-prehled/nahled.json", include_in_schema=False)
def follow_preview(request: Request, ulice: list[str] = Query(default=[]), co: list[str] = Query(default=[])):
    """The preview and the counts for the page's script, when the choice changes."""
    streets, kinds = _picked(request, ulice, co)
    out = _preview(request.state.obvod.id, streets, kinds)
    slugs = [s for _, s in streets]
    return JSONResponse({**out, "feed": _feed_url(streets, kinds) if streets else None,
                         **(subscribe(slugs) if slugs else {})})


def _subscription(body: dict) -> dict:
    sub = body.get("subscription") or {}
    keys = sub.get("keys") or {}
    ok = (isinstance(sub.get("endpoint"), str) and push.allowed(sub["endpoint"])
          and all(isinstance(keys.get(k), str) and 0 < len(keys[k]) < 200 for k in ("p256dh", "auth")))
    if not ok:
        raise HTTPException(400, "Neplatný odběr.")
    return sub


@pages.post("/muj-prehled/odber", include_in_schema=False)
def follow_push(request: Request, body: dict = Body(...)):
    """Turn the browser's notifications on, or change what it follows: {subscription, ulice, co}."""
    sub = _subscription(body)
    streets, kinds = _picked(request, [",".join(body.get("ulice") or [])], [",".join(body.get("co") or [])])
    if not streets:
        raise HTTPException(400, "Vyberte aspoň jednu ulici.")
    obvod = request.state.obvod.id
    with db.pool().connection() as conn:
        push.save(conn, sub, obvod, streets, kinds, _sources(obvod), dt.datetime.now(feed.TZ))
    return {"ok": True}


@pages.post("/muj-prehled/odber/obnovit", include_in_schema=False)
def renew_push(body: dict = Body(...)):
    """The service worker's renewed subscription: {old, old_auth, subscription}."""
    sub = _subscription(body)
    with db.pool().connection() as conn:
        push.renew(conn, str(body.get("old") or ""), str(body.get("old_auth") or ""), sub)
    return {"ok": True}


@pages.post("/muj-prehled/odber/zrusit", include_in_schema=False)
def unfollow_push(body: dict = Body(...)):
    """Turn them off: {endpoint, auth}."""
    with db.pool().connection() as conn:
        push.drop(conn, str(body.get("endpoint") or ""), str(body.get("auth") or ""))
    return {"ok": True}


@pages.get("/muj-prehled/rss.xml")
def follow_rss(request: Request, ulice: list[str] = Query(default=[]), co: list[str] = Query(default=[])):
    """RSS of the chosen streets (?ulice=wolkerova,lexova) and kinds (?co=podnety,deska; all by default)."""
    streets, kinds = _picked(request, ulice, co)
    if not streets:
        raise HTTPException(404, "Vyberte aspoň jednu ulici: ?ulice=wolkerova")
    now = dt.datetime.now(feed.TZ)
    evs = feed.events(streets, _sources(request.state.obvod.id), now, set(kinds))
    xml = feed.rss(evs, [n for n, _ in streets], _origin(), _feed_url(streets, kinds))
    return Response(xml, media_type="application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=900"})

