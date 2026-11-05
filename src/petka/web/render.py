"""Shared Jinja environment for the portal and its sections."""

import datetime as dt
import functools
import hashlib
import os
import re
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


def _card_thumb(d: dict) -> dict:
    from ..uredni_deska.digest import card_thumb
    return card_thumb(d)


def _clusters() -> dict:
    from ..uredni_deska.digest import CLUSTERS
    return CLUSTERS


# Spending by chapter: the 5 largest + the rest (a donut reads up to ~6 parts). Categorical hues in a
# fixed order (validated: CVD and normal-vision separation pass on white; three are under 3:1 contrast,
# so the legend carries every value as text), grey for the rest.
DONUT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
DONUT_REST = "#a8a7a1"


def _donut(items: list[dict], top: int = 5, r: float = 90, w: float = 34) -> list[dict]:
    """Slices with SVG paths (centre 100,100) for spending items {label, amount}; largest first."""
    import math
    items = sorted((i for i in items if (i.get("amount") or 0) > 0), key=lambda i: -i["amount"])
    if len(items) > top:      # never a cycled hue: everything past the 5th is grey
        rest = items[top:]
        items = items[:top] + [{"label": "Ostatní" if len(rest) > 1 else rest[0]["label"],
                                "amount": sum(i["amount"] for i in rest), "rest": True}]
    total = sum(i["amount"] for i in items) or 1
    out, a0 = [], -math.pi / 2
    for k, i in enumerate(items):
        frac = i["amount"] / total
        a1 = a0 + 2 * math.pi * frac
        big = 1 if a1 - a0 > math.pi else 0
        ri = r - w
        pt = lambda rad, ang: f"{100 + rad * math.cos(ang):.2f},{100 + rad * math.sin(ang):.2f}"
        if frac >= 0.9999:      # a single slice: two half arcs
            d = (f"M{pt(r, a0)}A{r},{r} 0 1 1 {pt(r, a0 + math.pi)}A{r},{r} 0 1 1 {pt(r, a0)}"
                 f"M{pt(ri, a0)}A{ri},{ri} 0 1 0 {pt(ri, a0 + math.pi)}A{ri},{ri} 0 1 0 {pt(ri, a0)}Z")
        else:
            d = (f"M{pt(r, a0)}A{r},{r} 0 {big} 1 {pt(r, a1)}L{pt(ri, a1)}"
                 f"A{ri},{ri} 0 {big} 0 {pt(ri, a0)}Z")
        out.append({"label": i["label"], "amount": i["amount"], "pct": 100 * frac, "d": d,
                    "color": DONUT_REST if i.get("rest") else DONUT_COLORS[k]})
        a0 = a1
    return out


def asset(path: str) -> str:
    return f"/static/{path}?v={asset_version(path)}"
SITE_NAME = "Otevřená Pětka"

tpl = Jinja2Templates(directory=HERE / "templates")
tpl.env.globals.update(asset=asset, donut=_donut, CLUSTERS=_clusters(), card_thumb=_card_thumb, ICONS=set(re.findall(r'<symbol id="([a-z]+)"', (HERE / 'static' / 'deska-ikony.svg').read_text())), CONTACT="filip.varecha@pirati.cz", PUBLIC_URL=os.environ.get("PUBLIC_URL", "https://opendata.mov.varecha.work").rstrip("/"), STATUS=queries.STATUS_LABEL, BODY=queries.BODY_LABEL,
                       CHOICE=queries.CHOICE_LABEL, SECTIONS=SECTIONS, SECTION=BY_SLUG, SITE_NAME=SITE_NAME)


def _date(d) -> str:
    """'1. 2. 2018' from a date or an ISO string (digests keep dates as text)."""
    if isinstance(d, str):
        try:
            d = dt.date.fromisoformat(d[:10])
        except ValueError:
            return d
    return f"{d.day}. {d.month}. {d.year}" if d else ""


def _initials(name: str) -> str:
    """'Ing. Lic. Jaroslav Kňava' -> 'JK', 'Jiří Rejda, DiS.' -> 'JR' (tile labels)."""
    t = strip_titles(name)
    return (t[0][0] + t[-1][0]) if len(t) > 1 else (t[0][:2] if t else "?")


tpl.env.filters["d"] = _date
tpl.env.filters["initials"] = _initials
