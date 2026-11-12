"""Čištění ulic as a section of the portal (see petka.section): when the town's blokové čištění
comes to a street, from the harmonogram of Služby města Pardubic. The pages work at /blokove-cisteni,
but the section is not listed yet (launched later)."""

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


def _template():
    from . import words
    return words.TEMPLATE_GLOBALS, words.TEMPLATE_FILTERS


SECTION = Section(
    "blokove-cisteni", "Čištění ulic", "Čištění ulic",
    "Kdy proběhne čištění mojí ulice?", "live", listed=False,
    examples=["Kdy se čistí Wolkerova?",
              "Kde se čistí příští týden?",
              "Jak dostanu termíny čištění do kalendáře?"],
    sources=[("Služby města Pardubic – čištění komunikací", "https://smp-pce.cz/udrzba-komunikaci/cisteni-komunikaci")],
    routers=_routers, mcp=_mcp, commands=_commands, template=_template,
)
