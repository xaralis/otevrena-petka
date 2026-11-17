"""Parkování as a section of the portal (see petka.section): the page /verejny-prostor/parkovani
and the API /api/v1/parkovani… (petka.parkovani.web); the jobs `parkovani-update` (daily) and
`parkovani-obsazenost` (every 60 s). Not listed on /prehled; in Data a API (/data#parkovani)."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.pages, web.api]


def _commands():
    from .cli import COMMANDS
    return COMMANDS


def _catalog() -> dict:
    from . import data, queries
    try:
        b = queries.last_build()
        st = queries.state()
    except Exception:
        b = st = None
    return {"pk_cat": {"lots": len(b["lots"]) if b else None,
                       "built_at": b["built_at"] if b else None,
                       "fetched_at": st["fetched_at"] if st else None,
                       "checked": {k: data.meta(k).get("checked") for k in data.FILES}}}


SECTION = Section(
    "parkovani", "Parkování", "Parkování",
    "Kde je volno a kdy bývá plno?", "live", listed=False,
    sources=[("ChytřejšíParking (DPMP)", "https://pardubice.chytrejsiparking.cz/"),
             ("Parkování podle nařízení města", "https://pardubice.eu/parkovani")],
    routers=_routers, commands=_commands, catalog=_catalog,
)
