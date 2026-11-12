"""What the úřední deska templates need beyond the shared helpers: the quality semafor, card
clusters and thumbnails, the spending donut, the shown headline and the kind icons."""

import math
import re
from pathlib import Path

ICON_SPRITE = Path(__file__).parent.parent / "web" / "static" / "deska-ikony.svg"

# Spending by chapter: the 5 largest + the rest (a donut reads up to ~6 parts). Categorical hues in a
# fixed order (validated: CVD and normal-vision separation pass on white; three are under 3:1 contrast,
# so the legend carries every value as text), grey for the rest.
DONUT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
DONUT_REST = "#a8a7a1"


def donut(items: list[dict], top: int = 5, r: float = 90, w: float = 34) -> list[dict]:
    """Slices with SVG paths (centre 100,100) for spending items {label, amount}; largest first."""
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


_ADDRESSEE = re.compile(r"adresátem je\s+(.+?)\s*$", re.I)
_SALUTATION = re.compile(r"^(?:(?:pan|paní|pí|p\.)\s+)+", re.I)


def headline(d: dict, n: dict) -> str:
    """The card's headline as shown. A delivery names its addressee like the office's title does, but
    only while it hangs: the title of a taken-down delivery is redacted, and the generic headline is back.
    Page titles and share images keep the stored headline (they get cached outside our reach)."""
    m = _ADDRESSEE.search(n.get("title") or "") if d.get("cluster") == "doruceni" and not n.get("redacted") else None
    if not m:
        return d["headline"]
    name = _SALUTATION.sub("", m[1]).strip()
    return f"Úřad doručuje písemnost: {name.title() if name.isupper() else name}"


def template_globals() -> dict:
    from .digest import CLUSTERS, card_thumb
    from .score import LEADS, LEVELS, breakdown
    return {"QUALITY_LEVELS": LEVELS, "QUALITY_LEADS": LEADS, "quality_breakdown": breakdown,
            "donut": donut, "headline": headline, "CLUSTERS": CLUSTERS, "card_thumb": card_thumb,
            "ICONS": set(re.findall(r'<symbol id="([a-z]+)"', ICON_SPRITE.read_text()))}
