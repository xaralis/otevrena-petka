"""The streets of the obvod as a part of the portal (see petka.section): the front page (a street
search and what is going on in the whole obvod) and one page per street that puts together what
the other sections know about it: cleaning, decisions, reports, notices."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.pages]


def _front():
    from . import web
    return web.home


def _commands():
    from .cli import COMMANDS
    return COMMANDS


def _template():
    from . import queries
    return {}, {"ul_thousands": queries.thousands, "ul_since": queries.since_word,
                "ul_dm": queries.dm, "ul_dmy": queries.dmy}


SECTION = Section(
    "ulice", "Ulice", "Ulice", "Co se děje v mé ulici?", "live", listed=False,
    routers=_routers, front=_front, commands=_commands, template=_template,
)
