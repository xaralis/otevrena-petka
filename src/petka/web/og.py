"""Share images (Open Graph, 1200×630) per page: the brand image with the page's own title.

The base is static/icons/og.png (logo, vote squares and tagline stay as drawn); its headline is painted
over and replaced by the section name and the page title, wrapped and sized to fit. Bricolage Grotesque
comes as a full TTF here (fonts/, OFL): the web fonts are woff2 subsets split by script.
"""

import io
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
BASE = HERE / "static" / "icons" / "og.png"
FONT = HERE / "fonts" / "BricolageGrotesque.ttf"
RED = (222, 9, 28)
WHITE = (255, 255, 255)
SOFT = (255, 214, 214)                 # kicker: white on red, toned down

LEFT, RIGHT = 80, 1120                 # text column, as in the base image
HEADLINE = (60, 175, 1150, 470)        # the base's headline, painted over
KICKER_Y = 190
TITLE_TOP, TITLE_BOTTOM = 246, 462     # title block; the vote squares start at 486
TITLE_TOP_ALONE = 200                  # no kicker: where the base headline starts
SIZES = range(84, 47, -4)              # the base headline is ~82 px; smaller is unreadable in a chat preview


@lru_cache(maxsize=32)
def _font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_axes([min(96, max(12, size)), weight, 100])     # optical size, weight, width
    return f


@lru_cache(maxsize=1)
def _base() -> Image.Image:
    im = Image.open(BASE).convert("RGB")
    ImageDraw.Draw(im).rectangle(HEADLINE, fill=RED)
    return im


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Greedy wrap; a one-letter word (v, s, k, a, …) stays with the next one, as Czech typesetting wants."""
    text = re.sub(r"(?<!\S)(\w) ", "\\1\u00a0", text)
    lines, line = [], ""
    for word in text.split(" "):
        trial = f"{line} {word}".strip()
        if font.getlength(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


def _fit(title: str, top: int) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """Largest size whose wrapped lines fit the title block; at the smallest, the last line gets an ellipsis."""
    height = TITLE_BOTTOM - top
    font, lines, step = _font(SIZES[-1], 800), [], 1
    for size in SIZES:
        font, step = _font(size, 800), round(size * 1.05)
        lines = _wrap(title, font, RIGHT - LEFT)
        if len(lines) * step <= height and all(font.getlength(line) <= RIGHT - LEFT for line in lines):
            return font, lines, step
    keep = max(1, height // step)
    lines = lines[:keep]
    while lines[-1] and font.getlength(lines[-1] + " …") > RIGHT - LEFT:
        lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
    lines[-1] += " …"
    return font, lines, step


def render(title: str, kicker: str = "") -> bytes:
    im = _base().copy()
    d = ImageDraw.Draw(im)
    title = " ".join(title.split())
    if kicker and title.casefold().startswith(kicker.casefold()):
        kicker = ""                    # the title says it already
    if kicker:
        d.text((LEFT, KICKER_Y), kicker, font=_font(34, 500), fill=SOFT)
    top = TITLE_TOP if kicker else TITLE_TOP_ALONE
    font, lines, step = _fit(title, top)
    y = top
    for line in lines:
        d.text((LEFT, y), line, font=font, fill=WHITE)
        y += step
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
