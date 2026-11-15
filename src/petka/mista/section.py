"""Místa as a section of the portal (see petka.section): places of the whole town from
OpenStreetMap as one daily export for the app Pardubice do kapsy and anyone else. Data only:
no pages, not in the header; listed in Data a API (/data#mista)."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.api]


def _commands():
    from .cli import COMMANDS
    return COMMANDS


def _catalog() -> dict:
    from . import queries
    return {"mi_cat": queries.counts()}


SECTION = Section(
    "mista", "Místa", "Místa",
    "Kde je nejbližší stojan na kola, kontejner nebo lékárna?", "live", listed=False,
    sources=[("OpenStreetMap (ODbL 1.0)", "https://www.openstreetmap.org/copyright")],
    routers=_routers, commands=_commands, catalog=_catalog,
)
