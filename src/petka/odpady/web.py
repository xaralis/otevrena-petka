"""Odpady: the page at /verejny-prostor/odpady (the obvod's přistavení of the velkoobjemové
kontejnery on a map with their list, ?kde=mesto for the whole town; the separační dvory under it
with their hours and whether they are open now) and the API for the app:
/api/v1/odpady/kontejnery and /api/v1/odpady/dvory (the whole town, `?obvod=`).
"""

import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..obvody import ObvodParam
from ..web.render import tpl
from . import data

pages = APIRouter(prefix="/verejny-prostor/odpady", include_in_schema=False)
api = APIRouter(prefix="/api/v1/odpady", tags=["odpady"])
TZ = ZoneInfo("Europe/Prague")
NB = " "
SOURCE = "https://smp-pce.cz/odpady/velkoobjemove-kontejnery"
YARDS_SOURCE = "https://smp-pce.cz/odpady/separacni-dvory"


def _now() -> dt.datetime:
    return dt.datetime.now(TZ)


def _until(d: dt.date, today: dt.date) -> str:
    n = (d - today).days
    if n == 0:
        return "dnes"
    if n == 1:
        return "zítra"
    if n < 7:
        return f"za {n} dny" if n < 5 else f"za {n} dní"
    w = round(n / 7)
    return "za týden" if w == 1 else (f"za {w} týdny" if w < 5 else f"za {w} týdnů")


def upcoming(today: dt.date) -> list[data.Drop]:
    return [d for d in data.drops(today.year) + data.drops(today.year + 1) if d.date >= today]


def _row(d: data.Drop, today: dt.date) -> dict:
    wd = data.DAYS[d.date.weekday()]
    sub = ", ".join(x for x in (f"dovezen {d.time}" if d.time and "–" in d.time else d.time, d.note) if x)
    return {"key": d.key, "date": f"{wd} {d.date.day}.{NB}{d.date.month}.", "place": d.place, "sub": sub,
            "until": _until(d.date, today), "mapped": d.point is not None}


def _yard(y: dict, at: dt.datetime) -> dict:
    is_open, word = data.status(y, at)
    extra = []
    if y["only_here"]:
        extra.append("Jen tady: " + "; ".join(y["only_here"]) + ".")
    if y["takes_not"]:
        extra.append("Nebere: " + "; ".join(y["takes_not"]) + ".")
    return {"key": y["key"], "name": y["name"], "address": y["address"], "hours": data.hours_text(y),
            "open": is_open, "status": word, "extra": " ".join(extra), "mapped": y["point"] is not None}


def _features(drops: list[data.Drop], ys: list[dict], today: dt.date) -> dict:
    by = {}
    for d in drops:
        by.setdefault(d.key, []).append(d)
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": ds[0].point},
              "properties": {"key": k, "kind": "kontejner", "place": ds[0].place, "approx": ds[0].approx,
                             "next": ds[0].date.isoformat(), "when": _row(ds[0], today)["date"]}}
             for k, ds in by.items() if ds[0].point]
    feats += [{"type": "Feature", "geometry": {"type": "Point", "coordinates": y["point"]},
               "properties": {"key": y["key"], "kind": "dvur", "place": y["name"], "approx": y["approx"]}}
              for y in ys if y["point"]]
    return {"type": "FeatureCollection", "features": feats}


@pages.get("", response_class=HTMLResponse)
def overview(request: Request, kde: str = ""):
    at = _now()
    today = at.date()
    obvod = request.state.obvod
    every = upcoming(today)
    year = [d for d in every if d.date.year == today.year]
    mine = [d for d in year if d.obvod == obvod.id]
    town = kde == "mesto"
    shown = year if town else mine
    yd = data.yards()
    ys = yd["yards"]
    nxt = next((d for d in every if d.obvod == obvod.id), None) if not mine and not town else None
    return tpl.TemplateResponse(request, "odpady/prehled.html", {
        "obvod": obvod, "town": town, "n_mine": len(mine), "n_town": len(year),
        "rows": [_row(d, today) for d in shown], "next": _row(nxt, today) if nxt else None,
        "yards": [_yard(y, at) for y in ys], "fc": _features(shown, ys, today),
        "source": SOURCE, "yards_source": YARDS_SOURCE, "checked": dt.date.fromisoformat(yd["checked"])})


@api.get("/kontejnery")
def containers(obvod: ObvodParam):
    """Přistavení velkoobjemových kontejnerů na objemný odpad (Služby města Pardubic) od dneška do
    konce harmonogramu, nejbližší první. Celé město, jen některé obvody s `?obvod=mo5`.

    `time`: kdy bude kontejner dovezen (ne jak dlouho stojí; odváží se po naplnění). `obvod`: blok
    tabulky SmP, ve kterém stanoviště je. `point` [lon, lat] je odvozený z popisu (`approx`: jen
    přibližně), u nenalezeného místa chybí; platí text `place`. Harmonogram je přepsaný ze skenu PDF."""
    today = _now().date()
    out = [{"key": d.key, "place": d.place, "date": d.date.isoformat(), "time": d.time, "note": d.note,
            "obvody": [d.obvod], "point": d.point, "approx": d.approx}
           for d in upcoming(today) if obvod.matches([d.obvod])]
    return JSONResponse({"source": SOURCE, "items": out}, headers={"Cache-Control": "public, max-age=3600"})


@api.get("/dvory")
def yards(obvod: ObvodParam):
    """Separační (sběrné) dvory města s otevírací dobou (`hours`: dny po–ne, od, do) a s tím, co
    nebere (`takes_not`) nebo bere jen on (`only_here`). Podle seznamu Služeb města Pardubic.
    Odpad z domácnosti zdarma s dokladem o poplatku nebo občankou s trvalým bydlištěm v Pardubicích."""
    yd = data.yards()
    out = [{k: y[k] for k in ("key", "name", "address", "hours", "takes_not", "only_here", "point", "approx")}
           for y in yd["yards"]]
    return JSONResponse({"source": YARDS_SOURCE, "file": yd["file"], "checked": yd["checked"], "items": out},
                        headers={"Cache-Control": "public, max-age=3600"})
