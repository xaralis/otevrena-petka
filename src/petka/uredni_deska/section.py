"""Úřední deska as a section of the portal: metadata and hooks (see petka.section)."""

from ..section import Section


def _routers() -> list:
    from . import web
    return [web.pages, web.api]


def _front():
    from . import web
    return web.home


def _mcp():
    from . import mcp_tools
    return mcp_tools.INSTRUCTIONS, mcp_tools.TOOLS


def _commands():
    from .cli import COMMANDS
    return COMMANDS


def _template():
    from .render import template_globals
    return template_globals(), {}


def _sitemap(conn) -> list:
    return [("/uredni-deska", None)]


def _home() -> dict:
    from . import queries
    # the newest notices of MO V, leaving out deliveries to named people (not news, and personal)
    notices = [n for n in queries.search(limit=12)[0] if n["kind"] != "doruceni"][:3]
    return {"deska": queries.stats(), "notices": notices}


def _catalog() -> dict:
    from . import queries, source
    return {"deska": queries.stats(), "deska_source": source}


def _bootstrap() -> None:
    from .cli import bootstrap
    bootstrap()


SECTION = Section(
    "uredni-deska", "Úřední deska pro lidi", "Úřední deska pro lidi",
    "Co úřad právě vyvěsil?", "live",
    sources=[("Úřední deska MO Pardubice V na pardubice.eu", "https://pardubice.eu/uredni-deska/obvody?district=mo5"),
             ("Úřední deska Magistrátu města Pardubic", "https://pardubice.eu/uredni-deska")],
    routers=_routers, front=_front, mcp=_mcp, commands=_commands, template=_template,
    sitemap=_sitemap, home=_home, catalog=_catalog, bootstrap=_bootstrap,
)
