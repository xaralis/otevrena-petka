"""Podněty as a section of the portal (see petka.section): citizens' reports from the city's
Dej Tip app. API and MCP only for now (the city app and the portal's map will read it), so not
listed; /podnety is the planned-section page."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.api]


def _mcp():
    from . import mcp_tools
    return mcp_tools.INSTRUCTIONS, mcp_tools.TOOLS


def _commands():
    from .cli import COMMANDS
    return COMMANDS


SECTION = Section(
    "podnety", "Podněty", "Podněty občanů",
    "Co lidé v obvodu hlásí a jak se to řeší?", "planned", listed=False,
    examples=["Co lidé nahlásili v mé ulici?",
              "Kolik podnětů k zeleni úřad vyřešil?",
              "Jak dlouho trvá vyřízení podnětu?"],
    sources=[("Dej Tip – mapa podnětů v Pardubicích", "https://amg.dejtip.eu/pardubice/")],
    routers=_routers, mcp=_mcp, commands=_commands,
)
