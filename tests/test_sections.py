"""Every section with code is wired into the portal through its own record: its routes are
mounted, its MCP tools registered and its commands on the command line. No database needed."""

import asyncio

import pytest

from petka import cli
from petka.mcp_server import mcp
from petka.sections import BY_SLUG, REGISTRY, SECTIONS
from petka.web.app import app

WITH_CODE = [s for s in REGISTRY if s.routers or s.mcp or s.commands]


def test_registry():
    assert [s.slug for s in SECTIONS] == ["uredni-deska", "usneseni", "rozpocet", "smlouvy"]
    assert "ankety" in BY_SLUG and not BY_SLUG["ankety"].listed
    assert BY_SLUG["rozpocet"].status == "planned" and BY_SLUG["rozpocet"].routers   # preview mounted
    assert "podnety" in BY_SLUG and not BY_SLUG["podnety"].listed
    assert {s.slug for s in WITH_CODE} == {"uredni-deska", "usneseni", "rozpocet", "ankety", "podnety"}


@pytest.mark.parametrize("s", WITH_CODE, ids=lambda s: s.slug)
def test_section_is_wired(s, capsys):
    mounted = [getattr(r, "original_router", None) for r in app.routes]
    for router in s.routers() if s.routers else []:
        assert router.routes and any(m is router for m in mounted), router.prefix

    if s.mcp:
        instructions, tools = s.mcp()
        names = {t.name for t in asyncio.run(mcp.list_tools())}
        assert tools and {fn.__name__ for fn in tools} <= names
        assert instructions in mcp.instructions

    if s.commands:
        with pytest.raises(SystemExit) as e:
            cli.main(["--help"])
        assert e.value.code == 0
        out = capsys.readouterr().out
        for c in s.commands():
            assert c.name in out and c.help.split()[0] in out


def test_rozpocet_preview_is_mounted_and_public_page_stays_planned():
    prefixes = {r.original_router.prefix for r in app.routes if hasattr(r, "original_router")}
    assert "/rozpocet/nahled/{token}" in prefixes and "/rozpocet" not in prefixes
