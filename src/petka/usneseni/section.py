"""Usnesení as a section of the portal: metadata and hooks (see petka.section)."""

from ..section import Section

PAGES = ["/usneseni", "/usneseni/mapa", "/usneseni/jednani", "/usneseni/clenove", "/usneseni/clenove/ucast",
         "/usneseni/metodika"]


def _routers() -> list:
    from . import web
    return [web.pages, web.api]


def _mcp():
    from . import mcp_tools
    return mcp_tools.INSTRUCTIONS, mcp_tools.TOOLS


def _commands():
    from .cli import COMMANDS
    return COMMANDS


def _initials(name: str) -> str:
    """'Ing. Lic. Jaroslav Kňava' -> 'JK', 'Jiří Rejda, DiS.' -> 'JR' (tile labels)."""
    from .text import strip_titles
    t = strip_titles(name)
    return (t[0][0] + t[-1][0]) if len(t) > 1 else (t[0][:2] if t else "?")


def _template():
    from . import queries
    return ({"STATUS": queries.STATUS_LABEL, "BODY": queries.BODY_LABEL, "CHOICE": queries.CHOICE_LABEL},
            {"initials": _initials})


def _sitemap(conn) -> list:
    urls = [(u, None) for u in PAGES]
    urls += [(f"/usneseni/jednani/{r['id']}", r["date"]) for r in conn.execute(
        "SELECT id, date FROM meetings ORDER BY date DESC")]
    urls += [(f"/usneseni/{r['uid']}", r["date"]) for r in conn.execute(
        "SELECT uid, date FROM resolutions ORDER BY date DESC, seq DESC")]
    urls += [(f"/usneseni/clenove/{r['id']}", None) for r in conn.execute("SELECT id FROM members ORDER BY id")]
    return urls


def _home() -> dict:
    from . import queries, search
    hits, _ = search.search("", filters=search.Filters(status="usneseni"), limit=3)
    return {"stats": queries.stats(), "latest": [h.row for h in hits]}


def _catalog() -> dict:
    from . import queries, web
    return {"stats": queries.stats(), "tables": queries.opendata_tables(), "updated": web.opendata_updated()}


def _bootstrap() -> None:
    from . import jobs
    jobs.bootstrap()


SECTION = Section(
    "usneseni", "Usnesení", "Usnesení a hlasování",
    "Co se rozhodlo a kdo jak hlasoval?", "live",
    sources=[("Zápisy z jednání ZMO a RMO na pardubice.eu", "https://pardubice.eu/zapisy-z-jednani-zmo5")],
    routers=_routers, mcp=_mcp, commands=_commands, template=_template, sitemap=_sitemap,
    home=_home, catalog=_catalog, bootstrap=_bootstrap,
)
