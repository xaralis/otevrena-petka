"""Odpady as a section of the portal (see petka.section): the velkoobjemové kontejnery and the
separační dvory of Služby města Pardubic. The page /verejny-prostor/odpady and the API for the
app (petka.odpady.web); the job `odpady-update` reads the yards' file. Not listed on /prehled."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.pages, web.api]


def _commands():
    from .cli import COMMANDS
    return COMMANDS


SECTION = Section(
    "odpady", "Odpady", "Odpady",
    "Kdy přistaví kontejner a kdy má otevřeno sběrný dvůr?", "live", listed=False,
    sources=[("Služby města Pardubic – odpady", "https://smp-pce.cz/odpady")],
    routers=_routers, commands=_commands,
)
