"""Street-level photos for cards: the nearest Panoramax 360° picture (CC BY-SA), turned into
an ordinary camera view, and the same view "after the change" – signs that go struck out, new
ones put in with their official pictures. Where things stand comes from Claude looking at the
views next to the office's drawing; when it can't tell, there is no "after" picture.
"""

import io
import math
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import source

API = "https://api.panoramax.xyz/api"
SIGNS_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "znacky"
FONT = next((p for p in ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if Path(p).exists()), None)
MAX_BYTES, MAX_PIXELS = 40_000_000, 16384 * 8192      # a full 360° picture is ~ 30 MP
RED, GREEN, INK = (222, 9, 28, 235), (6, 115, 82, 235), (25, 28, 31, 220)


def _bearing(a, b) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _dist(a, b) -> float:
    dx = (a[0] - b[0]) * 111320 * math.cos(math.radians(a[1]))
    return math.hypot(dx, (a[1] - b[1]) * 110540)


def nearest(lon: float, lat: float, radius: int = 40) -> dict | None:
    """The closest 360° picture within `radius` m, newest first among equals."""
    r = httpx.get(f"{API}/search", timeout=30, headers=source.HEADERS,
                  params={"place_position": f"{lon},{lat}", "place_distance": f"0-{radius}", "limit": 10})
    r.raise_for_status()
    feats = [f for f in r.json().get("features", [])
             if f["properties"].get("pers:interior_orientation", {}).get("field_of_view", 360) == 360
             or f["properties"].get("pers:interior_orientation") is None]
    if not feats:
        return None
    feats.sort(key=lambda f: (round(_dist(f["geometry"]["coordinates"], (lon, lat)) / 5),
                              -(int(f["properties"].get("datetime", "0")[:4] or 0))))
    return feats[0]


def view(pano: np.ndarray, center: float, yaw: float, pitch: float = -3, fov: float = 75,
         size=(1200, 760)) -> Image.Image:
    """Rectilinear view from an equirectangular panorama whose middle points to `center`°."""
    W, H = size
    ph, pw = pano.shape[:2]
    f = (W / 2) / np.tan(np.radians(fov) / 2)
    x, y = np.meshgrid(np.arange(W) - W / 2, np.arange(H) - H / 2)
    d = np.stack([x, -y, np.full_like(x, f, dtype=float)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    p = np.radians(pitch)
    d = d @ np.array([[1, 0, 0], [0, np.cos(p), np.sin(p)], [0, -np.sin(p), np.cos(p)]]).T
    lon = np.degrees(np.arctan2(d[..., 0], d[..., 2])) + (yaw - center)
    lat = np.degrees(np.arcsin(np.clip(d[..., 1], -1, 1)))
    u = ((lon + 180) % 360) / 360 * pw
    v = (90 - lat) / 180 * ph
    return Image.fromarray(pano[np.clip(v.astype(int), 0, ph - 1), np.clip(u.astype(int), 0, pw - 1)])


def candidates(feature: dict, target: tuple[float, float], out: Path) -> dict:
    """Download the picture and save three views around the direction of the target."""
    href = (feature["assets"].get("hd") or feature["assets"]["sd"])["href"]
    host = urlparse(href).hostname or ""
    if not (host == "panoramax.xyz" or host.endswith(".panoramax.xyz") or host.endswith(".openstreetmap.fr")
            or host.endswith(".ign.fr")):
        raise ValueError(f"picture from an unexpected host: {host}")
    buf = io.BytesIO()
    with httpx.stream("GET", href, timeout=120, headers=source.HEADERS) as r:   # no redirects elsewhere
        r.raise_for_status()
        for chunk in r.iter_bytes():
            buf.write(chunk)
            if buf.tell() > MAX_BYTES:
                raise ValueError("picture too large")
    im = Image.open(buf)
    if im.width * im.height > MAX_PIXELS:
        raise ValueError(f"picture too large: {im.width}x{im.height}")
    pano = np.asarray(im.convert("RGB"))
    cam = feature["geometry"]["coordinates"]
    center = float(feature["properties"].get("view:azimuth") or 0)
    toward = _bearing(cam, target)
    yaws = [(toward + off) % 360 for off in (-55, 0, 55)]
    files = []
    for i, yaw in enumerate(yaws):
        p = out / f"pohled-{i}.jpg"
        view(pano, center, yaw).save(p, quality=88)
        files.append(p)
    props = feature["properties"]
    return {"files": files, "yaws": yaws, "center": center, "pano": pano,
            "id": feature["id"], "distance": round(_dist(cam, target)),
            "author": props.get("geovisio:producer") or props.get("geovisio:producer_name") or "Panoramax",
            "licence": (props.get("license") or "CC-BY-SA-4.0").replace("-", " ").replace("CC BY SA", "CC BY-SA"),
            "date": (props.get("datetime") or "")[:10],
            "url": f"https://api.panoramax.xyz/#focus=pic&pic={feature['id']}"}


def _font(size: int):
    return ImageFont.truetype(FONT, size) if FONT else ImageFont.load_default()


def _label(d: ImageDraw.ImageDraw, text: str, xy, bg, size=17):
    f = _font(size)
    x, y = xy
    tw = d.textlength(text, font=f)
    d.rectangle([x - 7, y - 5, x + tw + 7, y + size + 5], fill=bg)
    d.text((x, y), text, font=f, fill=(255, 255, 255, 255))


def _sign_picture(code: str) -> Image.Image | None:
    if not re.fullmatch(r"[A-ZČ]{1,2}\d{1,2}[a-z]?", code):    # a code comes from the model: no paths
        return None
    for ext in (".png", ".jpg", ".jpeg"):
        p = SIGNS_DIR / f"{code}{ext}"
        if p.is_file() and p.resolve().is_relative_to(SIGNS_DIR.resolve()):
            return Image.open(p).convert("RGBA")
    return None


def _plate(d: ImageDraw.ImageDraw, text: str, x: int, y: int, w: int) -> int:
    f = _font(13)
    words, lines, cur = text.split(), [], ""
    for wd in words:                                     # wrap to the plate's width
        t = f"{cur} {wd}".strip()
        if d.textlength(t, font=f) > w - 8 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = t
    lines.append(cur)
    h = len(lines) * 16 + 8
    d.rectangle([x, y, x + w, y + h], fill=(255, 255, 255, 255), outline=(20, 20, 20, 255), width=2)
    for i, line in enumerate(lines):
        d.text((x + (w - d.textlength(line, font=f)) / 2, y + 4 + i * 16), line, font=f, fill=(20, 20, 20, 255))
    return h


def _groups(marks: list[dict], tol: float = .07) -> list[list[dict]]:
    """New signs on one post (close together in the picture) form one group, in the given order."""
    out: list[list[dict]] = []
    for m in marks:
        g = next((g for g in out if abs(g[0]["x"] - m["x"]) < tol and abs(g[0]["y"] - m["y"]) < tol * 2), None)
        (g.append(m) if g else out.append([m]))
    return out


def _panel(img: Image.Image, d: ImageDraw.ImageDraw, group: list[dict], sh: int) -> None:
    """A white panel with the new signs of one post, next to the post, with a pointer to it."""
    W, H = img.size
    pw = int(sh * 1.9)
    items, h = [], 10
    for m in group:
        pic = None if (m["code"].startswith("E") and m.get("text")) else _sign_picture(m["code"])
        if pic:
            pic = pic.resize((max(1, round(pic.width * sh / pic.height)), sh))
            items.append(("pic", pic, m))
            h += sh + 6
        if m.get("text"):
            f = _font(13)
            lines = max(1, int(d.textlength(m["text"], font=f) // (pw - 16)) + 1)
            items.append(("plate", m["text"], m))
            h += lines * 16 + 14
    h += 4
    cx, cy = int(group[0]["x"] * W), int(group[0]["y"] * H)
    x = cx + sh if cx + sh + pw < W - 8 else cx - sh - pw            # beside the post, inside the picture
    x = min(max(8, x), W - pw - 8)
    y = min(max(48, cy - h // 2), H - h - 30)
    d.line([(cx, cy), (x if x > cx else x + pw, y + h // 2)], fill=GREEN, width=4)
    d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=GREEN)
    d.rectangle([x, y, x + pw, y + h], fill=(255, 255, 255, 240), outline=GREEN, width=4)
    yy = y + 8
    for kind, val, m in items:
        if kind == "pic":
            img.paste(val, (x + (pw - val.width) // 2, yy), val)
            yy += sh + 6
        else:
            yy += _plate(d, val, x + 8, yy, pw - 16) + 6


def render(base: Path, marks: list[dict], out_before: Path, out_after: Path, credit: str) -> None:
    """'Dnes' and 'po změně' versions of one view. Marks: {action: odstranit|nova, code, text,
    x, y} with x, y as fractions of the image (the sign's centre). Signs that go are struck out
    where they stand; new ones sit in a panel pointing at their post (the exact spot is the
    drawing's, the photo only shows roughly where)."""
    img = Image.open(base).convert("RGB")
    W, H = img.size
    before, after = img.copy(), img.copy()
    db, da = ImageDraw.Draw(before, "RGBA"), ImageDraw.Draw(after, "RGBA")
    sh = max(44, H // 13)                                 # sign height in the picture
    for m in (m for m in marks if m["action"] == "odstranit"):
        cx, cy = int(m["x"] * W), int(m["y"] * H)
        box = [cx - sh // 2, cy - sh // 2, cx + sh // 2, cy + sh // 2]
        da.rectangle(box, outline=RED, width=5)
        da.line([(box[0], box[1]), (box[2], box[3])], fill=RED, width=6)
        da.line([(box[0], box[3]), (box[2], box[1])], fill=RED, width=6)
    for g in _groups([m for m in marks if m["action"] == "nova"]):
        _panel(after, da, g, sh)
    _label(db, "Dnes", (18, 16), INK)
    _label(da, "Po změně – nové značky zeleně, rušené červeně; poloha podle výkresu přibližná", (18, 16), INK, size=15)
    for d in (db, da):
        f = _font(13)
        d.text((10, H - 22), credit, font=f, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
    before.save(out_before, quality=86)
    after.save(out_after, quality=86)


PLACEMENT_SYSTEM = """Jsi redaktor portálu Otevřená Pětka. Máš tři pohledy z 360° fotky ulice (pohled-0,
pohled-1, pohled-2) a podklady k úpravě dopravního značení: seznam značek a případně oficiální výkres.
Úkol: vybrat pohled, na kterém je místo změny opravdu vidět, a určit, kde v něm stojí značky, které se
odstraní, a kam patří nové.

Pravidla – raději nic než nepravda:
- Vyber pohled jen tehdy, když místo na fotce spolehlivě odpovídá výkresu a popisu (budovy, parkoviště,
  stávající značky). Jinak `view` = null.
- `odstranit`: jen značky, které na fotce skutečně vidíš a které oznámení ruší; x, y = střed značky.
- `nova`: nové značky podle výkresu; když výkres jejich polohu neukazuje, umísti je na sloup rušené
  značky, kterou nahrazují, nebo je vynech. Dodatkovou tabulku E13 uveď jako samostatnou značku s textem.
- x a y jsou zlomky šířky a výšky obrázku (0 = vlevo/nahoře).
- `confidence`: jak jistě sedí fotka na místo z výkresu (vysoká / střední / nízká) a v `reason` proč."""

PLACEMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["view", "marks", "confidence", "reason"],
    "properties": {
        "view": {"type": ["integer", "null"], "enum": [0, 1, 2, None]},
        "marks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["action", "code", "text", "x", "y"],
            "properties": {"action": {"type": "string", "enum": ["odstranit", "nova"]},
                           "code": {"type": "string"}, "text": {"type": ["string", "null"]},
                           "x": {"type": "number"}, "y": {"type": "number"}}}},
        "confidence": {"type": "string", "enum": ["vysoka", "stredni", "nizka"]},
        "reason": {"type": "string"},
    },
}


ANNOTATE_SYSTEM = """Jsi redaktor portálu Otevřená Pětka. Dostaneš oficiální výkres k úpravě dopravního
značení a stručný popis změny. Označ na výkresu nejvýš 6 míst, která běžnému čtenáři vysvětlí, co se
mění: nové nebo rušené značení (přechod, šikmé čáry, stání, sloupky, značky), případně názvy ulic pro
orientaci. Jen věci, které na výkresu opravdu jsou nakreslené; nic nedomýšlej.
- x, y = místo na výkresu jako zlomky šířky a výšky (0 = vlevo/nahoře), přesně na tom prvku.
- text: krátce a lidsky, nejvýš 70 znaků („nový přechod pro chodce“, „šikmé čáry: tady se nesmí stát,
  aby byly děti vidět“), bez kódů značek.
- kind: nove (přibývá), zrusene (mizí), stavajici (zůstává, jen pro orientaci), misto (ulice, budova).
- legend: co znamenají barvy na výkresu, jen pokud to z výkresu nebo textu jasně plyne; jinak prázdné."""

ANNOTATE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["marks", "legend"],
    "properties": {
        "marks": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "additionalProperties": False, "required": ["x", "y", "text", "kind"],
            "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "text": {"type": "string"},
                           "kind": {"type": "string", "enum": ["nove", "zrusene", "stavajici", "misto"]}}}},
        "legend": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["color", "meaning"],
            "properties": {"color": {"type": "string"}, "meaning": {"type": "string"}}}},
    },
}
MARK_COLOUR = {"nove": GREEN, "zrusene": RED, "stavajici": INK, "misto": (95, 99, 104, 235)}


def annotate(src: Path, marks: list[dict], out: Path) -> list[dict]:
    """Numbered markers on the drawing; the texts go into the caption, numbered the same."""
    img = Image.open(src).convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img, "RGBA")
    r = max(13, min(W, H) // 34)
    f = _font(int(r * 1.15))
    kept = []
    for m in marks:
        if not (0 <= m["x"] <= 1 and 0 <= m["y"] <= 1):
            continue
        kept.append(m)
        n = str(len(kept))
        cx, cy = int(m["x"] * W), int(m["y"] * H)
        d.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], fill=(255, 255, 255, 255))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MARK_COLOUR.get(m["kind"], INK))
        d.text((cx - d.textlength(n, font=f) / 2, cy - r * .62), n, font=f, fill=(255, 255, 255, 255))
    img.save(out)
    return kept
