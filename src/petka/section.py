"""What a section of the portal is: the interface every section implements.

A section is named by the question it answers; `title` is the short name used everywhere
else, `nav` the label in the header. A live section has its own code; a planned one is only
metadata (a page saying what it will answer, where to look meanwhile and where the data will
come from).

The portal (web app, MCP server, command line, templates) knows sections only through this
record: it loops over the registry in petka.sections and calls the hooks a section supplies.
Hooks import the section's code lazily, so reading the registry stays cheap and free of cycles.
"""

import argparse
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Command:
    """One command of `petka <name>`: `args` adds its arguments to the subparser, `run` gets the
    parsed namespace and returns the exit code (None = 0)."""
    name: str
    help: str
    run: Callable[[argparse.Namespace], int | None]
    args: Callable[[argparse.ArgumentParser], None] = lambda p: None


@dataclass(frozen=True)
class Section:
    slug: str
    nav: str
    title: str
    question: str               # h1 of the section and the line on the home page
    status: str                 # live | planned
    examples: list = field(default_factory=list)   # questions the section answers
    bridges: list = field(default_factory=list)    # (label, url) already answerable elsewhere here
    sources: list = field(default_factory=list)    # (label, url) where the data comes from
    listed: bool = True         # in the header, on the home page and in the catalog (an API-only section isn't)

    # --- hooks (all optional) ---------------------------------------------------------------
    routers: Callable[[], list] | None = None            # FastAPI routers to mount
    front: Callable[[], Callable] | None = None          # endpoint for "/" if this section is the front page
    mcp: Callable[[], tuple[str, list[Callable]]] | None = None   # (instructions, tool functions)
    commands: Callable[[], list[Command]] | None = None  # CLI commands
    template: Callable[[], tuple[dict, dict]] | None = None       # (Jinja globals, Jinja filters)
    sitemap: Callable[[object], list[tuple[str, object]]] | None = None  # conn -> [(path, lastmod)]
    home: Callable[[], dict] | None = None               # context for the overview page /prehled
    catalog: Callable[[], dict] | None = None            # context for the data catalog /data
    bootstrap: Callable[[], None] | None = None          # run by `petka bootstrap` (init container)
