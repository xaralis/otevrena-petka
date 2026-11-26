"""The API of Místa (docs/mista.md); no pages, the section is listed only in Data a API.

    /api/v1/mista            the file version 2 (JSON), what the app Pardubice do kapsy downloads
    /api/v1/mista.geojson    the same places as a GeoJSON FeatureCollection

Both cover the whole town and take `?obvod=` (ADR 0002) and `?druh=`. The answer carries a
weak ETag of the build and the filter; If-None-Match with it gives 304. The portal gzips it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from ..obvody import ObvodParam
from ..web import etag
from . import export
from . import queries as q

api = APIRouter(prefix="/api/v1", tags=["místa"])

CACHE = "public, max-age=3600"
DRUH_DOC = ("Jen tyto druhy, oddělené čárkou: potraviny, bankomat, lekarna, jidlo, pamatky, wc, posta, "
            "stojan, kontejner, dvur (městské sběrné dvory), vykupna (soukromá recyklační centra, výkup kovů), "
            "misto (ostatní pojmenovaná místa: firmy, úřady, lékaři, školy, obchody, sportoviště, budovy). "
            "Bez parametru všechny.")


def _kinds(druh: str | None = Query(None, description=DRUH_DOC, examples=["stojan", "kontejner,dvur"])):
    try:
        return export.parse_kinds(druh)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def _answer(request: Request, what: str, obvod, kinds, shape, media_type: str) -> Response:
    built = q.built()
    if built is None:
        raise HTTPException(503, "Místa ještě nejsou sestavená, zkuste to později.")
    tag = export.etag(built, what, obvod, kinds)
    headers = {"ETag": tag, "Cache-Control": CACHE}
    if etag.fresh(request, tag):
        return etag.not_modified(headers)
    places = export.chosen(q.places(built), obvod, kinds)
    return JSONResponse(shape(built, places), media_type=media_type, headers=headers)


KindsParam = Annotated[tuple[str, ...], Depends(_kinds)]


@api.get("/mista")
def mista(request: Request, obvod: ObvodParam, druh: KindsParam):
    """Místa v Pardubicích z OpenStreetMap: obchody s potravinami, bankomaty, lékárny, kde se
    najíst, památky, veřejná WC, pošty, stojany na kola, kontejnery na tříděný odpad a sběrné
    dvory. Soubor verze 2 (docs/mista.md), obnovuje se jednou denně. `at` = [lon, lat],
    `obvody` = obvod, ve kterém místo leží. `odpad` jen u kontejneru a dvora, `capacity` jen
    u stojanu. Licence ODbL 1.0, © přispěvatelé OpenStreetMap."""
    return _answer(request, "v2", obvod, druh, export.file_v2, "application/json")


@api.get("/mista.geojson")
def mista_geojson(request: Request, obvod: ObvodParam, druh: KindsParam):
    """Stejná místa jako GeoJSON FeatureCollection (body; vlastnosti = pole souboru bez `at`).
    Licence ODbL 1.0, © přispěvatelé OpenStreetMap."""
    return _answer(request, "geojson", obvod, druh, export.geojson, "application/geo+json")
