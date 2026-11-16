"""Uzavírky as a section of the portal (see petka.section): closures, road works and accidents
from NDIC (ŘSD), kept for the whole town. The page at /verejny-prostor/uzavirky and the API
/api/v1/uzavirky (petka.uzavirky.web); not listed on /prehled."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.pages, web.api]


def _commands():
    from .cli import COMMANDS
    return COMMANDS


SECTION = Section(
    "uzavirky", "Uzavírky", "Uzavírky",
    "Kde se teď nedá projet?", "live", listed=False,
    sources=[("Dopravní informace NDIC (ŘSD)", "https://www.dopravniinfo.cz/")],
    routers=_routers, commands=_commands,
)
