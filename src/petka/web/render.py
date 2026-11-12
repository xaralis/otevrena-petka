"""Shared Jinja environment for the portal and its sections. Section-specific globals and
filters come from each section's `template` hook (petka.section)."""

import datetime as dt
import functools
import hashlib
import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

from .. import obvody
from ..sections import BY_SLUG, REGISTRY, SECTIONS

HERE = Path(__file__).parent


@functools.cache
def asset_version(path: str) -> str:
    """Short hash of a static file; it goes into the URL so a changed file gets a new URL."""
    f = HERE / "static" / path
    return hashlib.sha256(f.read_bytes()).hexdigest()[:10] if f.is_file() else "0"


def asset(path: str) -> str:
    return f"/static/{path}?v={asset_version(path)}"


def _date(d) -> str:
    """'1. 2. 2018' from a date or an ISO string (digests keep dates as text)."""
    if isinstance(d, str):
        try:
            d = dt.date.fromisoformat(d[:10])
        except ValueError:
            return d
    return f"{d.day}. {d.month}. {d.year}" if d else ""


SITE_NAME = obvody.DEFAULT.brand     # outside a request (tests, macros); a page gets its obvod's


def _obvod(request) -> dict:
    """Every page knows its obvod (set by the app from the host, petka.web.app)."""
    o = getattr(request.state, "obvod", None) or obvody.DEFAULT
    return {"obvod": o, "SITE_NAME": o.brand}


tpl = Jinja2Templates(directory=HERE / "templates", context_processors=[_obvod])
tpl.env.globals.update(asset=asset, CONTACT="filip.varecha@pirati.cz",
                       PUBLIC_URL=os.environ.get("PUBLIC_URL", "https://otevrenapetka.cz").rstrip("/"),
                       SECTIONS=SECTIONS, SECTION=BY_SLUG, SITE_NAME=SITE_NAME,
                       obvod=obvody.DEFAULT)
tpl.env.filters["d"] = _date

for _s in REGISTRY:
    if _s.template:
        _globals, _filters = _s.template()
        tpl.env.globals.update(_globals)
        tpl.env.filters.update(_filters)
