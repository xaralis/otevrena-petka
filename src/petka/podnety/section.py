"""Podněty as a section of the portal (see petka.section): citizens' reports from the city's
Dej Tip app. The page at /verejny-prostor/zavady ("Závady" under Veřejný prostor in the header, petka.nav), with
the API and MCP; not listed on /prehled."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.pages, web.api]


def _mcp():
    from . import mcp_tools
    return mcp_tools.INSTRUCTIONS, mcp_tools.TOOLS


def _commands():
    from .cli import COMMANDS
    return COMMANDS


SECTION = Section(
    "podnety", "Podněty", "Podněty občanů",
    "Co lidé hlásí a jak se to řeší?", "live", listed=False,
    examples=["Co lidé nahlásili v mé ulici?",
              "Kolik podnětů k zeleni úřad vyřešil?",
              "Jak dlouho trvá vyřízení podnětu?"],
    sources=[("Dej Tip – mapa podnětů v Pardubicích", "https://amg.dejtip.eu/pardubice/")],
    routers=_routers, mcp=_mcp, commands=_commands,
)
