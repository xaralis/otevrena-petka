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
    sub = ", ".join(x for x in (f"dovezen {d.time}" if d.time and "–" in d.time else d.time, d.note,
                                "na mapě není" if d.point is None else "") if x)
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


def _features(drops: list[data.Drop], ys: list[dict], today: dt.date, at: dt.datetime) -> dict:
    """The map's markers and what their cards say: a stanoviště its dates (the next three), a yard
    whether it is open now and its hours."""
    by = {}
    for d in drops:
        by.setdefault(d.key, []).append(d)
    def when(ds):
        first = _row(ds[0], today)
        rest = [_row(d, today)["date"] for d in ds[1:3]]
        return first["date"] + (f", {first['sub']}" if first["sub"] else "") + (f"; pak {', '.join(rest)}" if rest else "")
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": ds[0].point},
              "properties": {"key": k, "kind": "kontejner", "place": ds[0].place, "approx": ds[0].approx,
                             "what": "Kontejner na objemný odpad" + (", poloha přibližná" if ds[0].approx else ""),
                             "when": when(ds)}}
             for k, ds in by.items() if ds[0].point]
    feats += [{"type": "Feature", "geometry": {"type": "Point", "coordinates": y["point"]},
               "properties": {"key": y["key"], "kind": "dvur", "place": f"Sběrný dvůr {y['name']}", "approx": y["approx"],
                              "what": data.status(y, at)[1], "when": data.hours_text(y)}}
              for y in ys if y["point"]]
    return {"type": "FeatureCollection", "features": feats}


# Kontejnery na tříděný odpad: OpenStreetMap through the Místa export (petka.mista), the kinds in
# the order and colours people know them by
SORTS = (("plast", "Plast", "#e8b400"), ("papir", "Papír", "#1f5fbf"), ("sklo", "Sklo", "#2e8b46"),
         ("kov", "Kov", "#7d838b"), ("bio", "Bio", "#8a5a2b"), ("textil", "Textil", "#8e3f8f"),
         ("elektro", "Elektro", "#b00716"), ("olej", "Olej", "#191c1f"))


def _svoz_rows(obvod_id: str | None) -> list[dict]:
    """The page's svoz list: a street (or a whole part of the town) and its days in words, by name;
    the obvod's streets, or the town's."""
    from ..ulice import streets as st
    names = None
    if obvod_id:
        try:
            names = {s.name: s.slug for s in st.streets(obvod_id).values()}
        except Exception:
            names = {}
    out: dict[str, dict] = {}
    for r in data.svoz_rows():
        name = r.get("street") or (r["name"].title() if r.get("town_part") else None)
        if not name or (names is not None and r.get("street") not in names):
            continue
        out.setdefault(name, {"name": name, "slug": (names or {}).get(name), "text": data.svoz_text(r["street"]) if r.get("street")
                              else data._days_text(r["days"])})
    from ..ulice.streets import fold
    return sorted(out.values(), key=lambda x: fold(x["name"]))


def _bins(obvod_id: str | None) -> list[dict]:
    """The kontejner stanoviště of the obvod (None: the whole town) from the Místa export; [] when
    it is not there (a database without it)."""
    from .. import db
    try:
        with db.pool().connection() as conn:
            return conn.execute("""SELECT id, name, address, lon, lat, odpad, obvody FROM mista_places
                                   WHERE kind = 'kontejner' AND (%s::text IS NULL OR %s = ANY(obvody))""",
                                (obvod_id, obvod_id)).fetchall()
    except Exception:
        return []


def _bins_fc(bins: list[dict]) -> dict:
    names = dict((k, label) for k, label, _ in SORTS)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [b["lon"], b["lat"]]},
         "properties": {"id": b["id"], "odpad": [o for o, _, _ in SORTS if o in (b["odpad"] or [])],
                        "what": ", ".join(names[o] for o, _, _ in SORTS if o in (b["odpad"] or [])),
                        "place": b["address"] or b["name"] or "Kontejnery"}} for b in bins]}


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
    bins = _bins(None if town else obvod.id)
    svoz = _svoz_rows(None if town else obvod.id)
    sorts = [{"key": k, "label": label, "color": c, "n": sum(1 for b in bins if k in (b["odpad"] or []))} for k, label, c in SORTS]
    return tpl.TemplateResponse(request, "odpady/prehled.html", {
        "bins": _bins_fc(bins), "sorts": [x for x in sorts if x["n"]], "n_bins": len(bins), "street_names": [r["name"] for r in svoz if r.get("slug")],
        "obvod": obvod, "town": town, "n_mine": len(mine), "n_town": len(year),
        "rows": [_row(d, today) for d in shown], "next": _row(nxt, today) if nxt else None,
        "yards": [_yard(y, at) for y in ys], "fc": _features(shown, ys, today, at),
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


def _street_obvody() -> dict[str, list[str]]:
    """{street name: [obvod ids]} for the town (a street on a border belongs to both)."""
    from ..obvody import TOWN_BY_ID
    from ..ulice import streets as st
    out: dict[str, list[str]] = {}
    for o in TOWN_BY_ID:
        try:
            for s in st.streets(o).values():
                out.setdefault(s.name, []).append(o)
        except Exception:
            pass
    return out


@api.get("/svoz")
def collection(obvod: ObvodParam, ulice: str = ""):
    """Svoz směsného komunálního odpadu podle ulic: tabulka Služeb města Pardubic „Harmonogram
    svozu TKO ulice“ (2022, SmP ji stále odkazuje). Jeden řádek = ulice (nebo část obce bez ulic)
    a dny svozu (`days`: po–ne). Některé ulice tabulka dělí na `popelnice` (nádoby u domů) a
    `kontejnery` (1100 l na sídlištích, `who`) nebo na části (`part`). `text` je znění tabulky.

    ulice: názvy ulic oddělené čárkou (přesně podle RÚIAN, např. `Češkova,Wolkerova`). `obvody`
    podle RÚIAN; řádek části obce bez ulic (`town_part`, např. Žižín) obvody nemá, vrací se jen bez `?obvod=`. Nádoby
    přistavte ve svozový den od 5.30."""
    by = _street_obvody()
    want = {x.strip() for x in ulice.split(",") if x.strip()}
    out = []
    for r in data.svoz_rows():
        obv = sorted(by.get(r.get("street") or "", []))
        if want and r.get("street") not in want:
            continue
        if not obvod.matches(obv) and not (obvod.whole_town and r.get("town_part")):
            continue
        out.append({"street": r.get("street"), "town_part": r["name"] if r.get("town_part") else None,
                    "who": r["bins"] or None, "part": r["part"] or None, "days": r["days"], "text": r["text"],
                    "obvody": obv})
    return JSONResponse({"source": "https://smp-pce.cz/odpady/svoz-komunalniho-odpadu", "file": "harmonogram-svozu-tko-ulice-1665467792.xls",
                         "date": "2022-10-11", "items": out}, headers={"Cache-Control": "public, max-age=86400"})
