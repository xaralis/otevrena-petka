"""Shared Jinja environment for the portal and its sections."""

import functools
import hashlib
import os
from pathlib import Path

from fastapi.templating import Jinja2Templates

from ..sections import BY_SLUG, SECTIONS
from ..usneseni import queries
from ..usneseni.text import strip_titles

HERE = Path(__file__).parent


@functools.cache
def asset_version(path: str) -> str:
    """Short hash of a static file; it goes into the URL so a changed file gets a new URL."""
    f = HERE / "static" / path
    return hashlib.sha256(f.read_bytes()).hexdigest()[:10] if f.is_file() else "0"


def asset(path: str) -> str:
    return f"/static/{path}?v={asset_version(path)}"
SITE_NAME = "Otevřená Pětka"

tpl = Jinja2Templates(directory=HERE / "templates")
tpl.env.globals.update(asset=asset, CONTACT="filip.varecha@pirati.cz", PUBLIC_URL=os.environ.get("PUBLIC_URL", "https://opendata.mov.varecha.work").rstrip("/"), STATUS=queries.STATUS_LABEL, BODY=queries.BODY_LABEL,
                       CHOICE=queries.CHOICE_LABEL, SECTIONS=SECTIONS, SECTION=BY_SLUG, SITE_NAME=SITE_NAME)


def _date(d) -> str:
    return f"{d.day}. {d.month}. {d.year}" if d else ""


def _initials(name: str) -> str:
    """'Ing. Lic. Jaroslav Kňava' -> 'JK', 'Jiří Rejda, DiS.' -> 'JR' (tile labels)."""
    t = strip_titles(name)
    return (t[0][0] + t[-1][0]) if len(t) > 1 else (t[0][:2] if t else "?")


tpl.env.filters["d"] = _date
tpl.env.filters["initials"] = _initials
