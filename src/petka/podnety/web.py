"""Podněty: API under /api/v1/podnety for the portal's map and the city app. The obvod is the
request's (petka.obvody); everything else comes as query parameters."""

import datetime as dt

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import queries

api = APIRouter(prefix="/api/v1/podnety", tags=["podněty"])


def _ints(v: str, name: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split(",") if x.strip())
    except ValueError:
        raise HTTPException(422, f"{name}: čísla oddělená čárkou")


def _date(v: str, name: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(v) if v.strip() else None
    except ValueError:
        raise HTTPException(422, f"{name}: datum RRRR-MM-DD")


def _point(v: str) -> tuple[float, float] | None:
    if not v.strip():
        return None
    try:
        lat, lng = (float(x) for x in v.split(","))
    except ValueError:
        raise HTTPException(422, "near: lat,lng")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(422, "near: lat,lng mimo rozsah")
    return lat, lng


@api.get("")
def reports(request: Request, kategorie: str = "", stav: str = "", od: str = "", do: str = "",
            near: str = "", r: int = 500, limit: int = 500):
    """Podněty z aplikace Dej Tip v obvodu jako GeoJSON, nejnovější první (s `near` nejbližší).

    kategorie, stav: id z číselníků Dej Tip, víc oddělených čárkou. od, do: den nahlášení
    RRRR-MM-DD (včetně). near=lat,lng a r (metry, nejvýš 5000): jen podněty v tom okruhu,
    s `distance`. Místo jen jako ulice bez čísla domu, bez popisu od občana i poznámek úřadu."""
    f = queries.Filters(request.state.obvod.id, _ints(kategorie, "kategorie"), _ints(stav, "stav"),
                        _date(od, "od"), _date(do, "do"), _point(near), max(1, min(r, 5000)))
    rows = queries.search(f, max(1, limit))
    return JSONResponse(queries.geojson(rows), media_type="application/geo+json",
                        headers={"Cache-Control": "public, max-age=600"})
