"""Ankety as a section of the portal (see petka.section): indicative polls for the city app,
API only, so not listed on the portal's pages."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.api]


SECTION = Section(
    "ankety", "Ankety", "Ankety", "Co si o tom myslíte?", "live", listed=False,
    routers=_routers,
)
