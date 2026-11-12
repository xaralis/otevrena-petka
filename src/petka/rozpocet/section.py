"""Rozpočet as a section of the portal (see petka.section). The public /rozpocet is still the
planned-section page; the preview under /rozpocet/nahled/<token> is mounted for review."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.pages]


def _commands():
    from .cli import COMMANDS
    return COMMANDS


SECTION = Section(
    "rozpocet", "Rozpočet", "Rozpočet a hospodaření",
    "Kolik stojí obvod a kam jdou peníze?", "planned",
    examples=["Kolik obvod letos utratí za údržbu zeleně?",
              "Jak se rozpočet změnil během roku?",
              "Kolik šlo na dotace spolkům?"],
    bridges=[("rozpočtová opatření a změny rozpočtu", "/usneseni?q=rozpo%C4%8Dtov%C3%A9+opat%C5%99en%C3%AD"),
             ("schválení rozpočtu a závěrečného účtu", "/usneseni?q=z%C3%A1v%C4%9Bre%C4%8Dn%C3%BD+%C3%BA%C4%8Det"),
             ("dotace z rozpočtu obvodu", "/usneseni?tema=dotace")],
    sources=[("Monitor státní pokladny – rozpočty obcí a jejich částí", "https://monitor.statnipokladna.gov.cz/"),
             ("Rozpočet a závěrečný účet na webu obvodu", "https://pardubice.eu/obvod5")],
    routers=_routers, commands=_commands,
)
