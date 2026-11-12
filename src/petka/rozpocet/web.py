"""Rozpočet section, preview: pages under /rozpocet/nahled/<token> for review before launch.

The public /rozpocet stays the planned-section page. The preview is reachable only with the
token from ROZPOCET_NAHLED_TOKEN (a secret in the cluster); a wrong or missing token is a 404,
and every page says noindex. No link on the site leads here.
"""

import datetime as dt
import hmac
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..web.render import tpl
from . import names, queries as q

pages = APIRouter(prefix="/rozpocet/nahled/{token}", include_in_schema=False)

NO_INDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
PER_PAGE = 20

# Money the city sends the district (rozpočet města Pardubic 2026, s. 126, "Finanční toky do
# rozpočtů městských obvodů"), tis. Kč. Only this year is known; other years show no block.
FROM_CITY = {2026: {"dane": 25276.5, "zp": 23503.5, "doprava": 12432.8, "zpet": 8026.0,
                    "zdroj": "rozpočet města Pardubic na rok 2026, s. 126"}}

# Periods marked in the charts: (from, to, label). Covid: the first state of emergency
# (12. 3. 2020) to shops and restaurants reopening at the end of May 2021.
MARKS = [(dt.date(2020, 3, 12), dt.date(2021, 5, 31), "covid 3/2020–5/2021")]


def _marks(years: list[int]) -> list[dict]:
    """Bands behind year columns: a and b are positions in columns (index + fraction of the
    year), fa and fb the fractions, which the template needs to step over the gaps."""
    out = []
    for start, end, label in MARKS:
        if start.year not in years or end.year not in years:
            continue
        frac = lambda d: (d - dt.date(d.year, 1, 1)).days / (dt.date(d.year + 1, 1, 1) - dt.date(d.year, 1, 1)).days
        fa, fb = frac(start), frac(end)
        a, b = years.index(start.year) + fa, years.index(end.year) + fb
        out.append({"a": round(a, 3), "b": round(b, 3), "fa": round(fa, 3), "fb": round(fb, 3),
                    "n": len(years), "label": label})
    return out


# Changes of the 2026 budget (usnesení RMO/ZMO in the Usnesení section)
CHANGES = {2026: [
    ("17. 12. 2025", "Zastupitelstvo schválilo rozpočet", "159/2025 Z", "159-2025-z"),
    ("28. 1. 2026", "Rada: dar na Masopust", "267/2026 R", "267-2026-r"),
    ("11. 3. 2026", "Zastupitelstvo: 1. změna rozpočtu", "172/2026 Z", "172-2026-z"),
    ("1. 4. 2026", "Rada: dotace na parlamentní volby", "281/2026 R", "281-2026-r"),
    ("3. 6. 2026", "Zastupitelstvo: 2. změna rozpočtu", "179/2026 Z", "179-2026-z"),
    ("24. 6. 2026", "Zastupitelstvo: 3. změna rozpočtu", "182/2026 Z", "182-2026-z"),
    ("2. 9. 2026", "Zastupitelstvo: 4. změna rozpočtu", "190/2026 Z", "190-2026-z"),
]}


def _check(token: str) -> str:
    want = os.environ.get("ROZPOCET_NAHLED_TOKEN", "")
    if len(want) < 16 or not hmac.compare_digest(token, want):
        raise HTTPException(404)
    return f"/rozpocet/nahled/{token}"


def _year(rok: str, ys: list[int]) -> int:
    return int(rok) if rok.isdigit() and int(rok) in ys else ys[-1]


def _ctx(request: Request, base: str, tab: str, **kw) -> dict:
    ys = [y["year"] for y in q.years()]
    as_of = {y["year"]: y["as_of"] for y in q.years()}
    year = kw.get("year")
    running = bool(year and year == ys[-1] and as_of[year] and as_of[year].year == year)
    return {"base": base, "tab": tab, "years": ys, "as_of": as_of, "today": dt.date.today(),
            "mil": q.mil, "tis": q.tis, "marks": _marks([s["year"] for s in kw.get("series") or []]), "running": running,
            "zatim": " zatím" if running else "", **kw}


def _render(request: Request, name: str, ctx: dict):
    return tpl.TemplateResponse(request, f"rozpocet/{name}", ctx, headers=NO_INDEX)


@pages.get("", response_class=HTMLResponse)
def overview(request: Request, token: str, rok: str = ""):
    base = _check(token)
    ys = [y["year"] for y in q.years()]
    if not ys:
        raise HTTPException(503, "Rozpočet zatím není stažený.")
    year = _year(rok, ys)
    tot = q.totals()
    series = [{"year": y, "r": tot[y]["vydaje"]["revised"], "a": tot[y]["vydaje"]["actual"]} for y in ys if y in tot]
    top = max(s["r"] for s in series) if series else 1
    step = 40000 if top > 100000 else 20000
    top = -(-top // step) * step
    for s in series:
        s.update(r_h=round(s["r"] / top * 280), a_h=round(s["a"] / top * 280), label=q.mil(s["a"]))
    ticks = [{"pos": round(v / top * 280), "label": int(v / 1000)} for v in range(0, int(top) + 1, step)]
    groups, _ = q.group(q.by_paragraph(year), q.by_paragraph(year - 1), "plan")
    t = tot.get(year, {})
    last_closed = max((y for y in ys if y < year), default=None)
    closed_pct = (q.pct(tot[last_closed]["vydaje"]["actual"], tot[last_closed]["vydaje"]["revised"])
                  if last_closed in tot else None)
    return _render(request, "prehled.html", _ctx(
        request, base, "prehled", year=year, t=t, series=series, ticks=ticks, groups=groups,
        from_city=FROM_CITY.get(year), last_closed=last_closed, closed_pct=closed_pct,
        first=series[0] if series else None, peak=max(series, key=lambda s: s["a"]) if series else None))


@pages.get("/oblasti", response_class=HTMLResponse)
def areas(request: Request, token: str, rok: str = "", pohled: str = ""):
    base = _check(token)
    ys = [y["year"] for y in q.years()]
    year = _year(rok, ys)
    view = "zmena" if pohled == "zmena" and (year - 1) in ys else "plan"
    groups, axis = q.group(q.by_paragraph(year), q.by_paragraph(year - 1), view)
    total = sum(g["plan"] for g in groups)
    return _render(request, "oblasti.html", _ctx(request, base, "oblasti", year=year, view=view,
                                                  groups=groups, axis=axis, total=total))


@pages.get("/oblasti/{par}", response_class=HTMLResponse)
def area(request: Request, token: str, par: str, rok: str = ""):
    base = _check(token)
    if not par.isdigit():
        raise HTTPException(404)
    ys = [y["year"] for y in q.years()]
    year = _year(rok, ys)
    series = q.paragraph_series(par)
    if not series:
        raise HTTPException(404)
    top = max(max(s["r"], s["a"]) for s in series)
    step = 10000 if top > 20000 else 5000 if top > 8000 else 2000 if top > 3000 else 500
    top = -(-top // step) * step
    for s in series:
        s.update(r_h=round(s["r"] / top * 220), a_h=round(s["a"] / top * 220), label=q.mil(s["a"]))
    ticks = [{"pos": round(v / top * 220), "label": q.mil(v) if v else "0"} for v in range(0, int(top) + 1, step)]
    items = q.paragraph_items(par, year)
    shown, rest = items[:7], items[7:]
    inv, n, s = q.invoices(year, par=par, limit=12)
    cur = q.by_paragraph(year)
    official = cur.get(par, (0, 0, ""))[2] or q.by_paragraph(series[-1]["year"]).get(par, (0, 0, ""))[2]
    total = sum(x[0] for x in cur.values())
    k = names.key(par)
    return _render(request, "oblast.html", _ctx(
        request, base, "oblasti", year=year, par=par, label=names.PARAGRAF.get(par, official or par),
        official=official, oddil=names.oddil(k), oddil_code=k, series=series, ticks=ticks,
        items=shown, rest_n=len(rest), rest_sum=sum(i["r"] for i in rest), invoices=inv, inv_n=n, inv_sum=s,
        now=cur.get(par, (0, 0, "")), share=q.pct(cur.get(par, (0,))[0], total), describe=q.describe,
        kinds=names.ITEM_KIND, about=names.ABOUT.get(par)))


@pages.get("/faktury", response_class=HTMLResponse)
def invoice_list(request: Request, token: str, rok: str = "", oblast: str = "", razeni: str = "",
                 hledat: str = "", strana: str = "1"):
    base = _check(token)
    ys = [y["year"] for y in q.years()]
    year = _year(rok, ys)
    oblast = oblast if oblast.isdigit() and len(oblast) == 2 else ""
    page = max(1, int(strana)) if strana.isdigit() else 1
    rows, n, s = q.invoices(year, hledat, oblast, sort=razeni, limit=PER_PAGE, offset=(page - 1) * PER_PAGE)
    _, all_n, all_s = q.invoices(year, limit=0)
    spent = q.totals().get(year, {}).get("vydaje", {}).get("actual") or 0
    present = sorted({str(p)[:2] for p in q.by_paragraph(year) if p.isdigit()})
    return _render(request, "faktury.html", _ctx(
        request, base, "faktury", year=year, rows=rows, n=n, s=s, all_n=all_n, all_s=all_s,
        share=q.pct(all_s, spent), top=q.invoice_top(year), oblasti=[(k, names.oddil(k)[0]) for k in present],
        oblast=oblast, razeni="oblast" if razeni == "oblast" else "castka", hledat=hledat.strip(), page=page,
        pages=max(1, -(-n // PER_PAGE)), describe=q.describe, kinds=names.ITEM_KIND, label=names.PARAGRAF))


@pages.get("/jak-vznika", response_class=HTMLResponse)
def process(request: Request, token: str):
    base = _check(token)
    ys = [y["year"] for y in q.years()]
    tot = q.totals()
    year = 2026 if 2026 in tot else ys[-1]
    v = tot.get(year, {}).get("vydaje", {})
    return _render(request, "jak.html", _ctx(request, base, "jak", year=year, v=v, changes=CHANGES.get(year, [])))
