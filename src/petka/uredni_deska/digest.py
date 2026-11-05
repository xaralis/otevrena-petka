"""Úřední deska "pro lidi": each notice retold in plain Czech, with a picture where one helps.

A digest is a directory `<root>/<notice id>/` with `digest.json` and its images:

    data/uredni_deska/drafts/<id>/    proposals waiting for a person (not in git)
    data/uredni_deska/digests/<id>/   approved and published (in git, seeded into the cluster)

Pilot workflow (docs/deska-pilot.md): `deska-drafts` proposes digests for new notices that
concern MO V, a person reviews them at /uredni-deska/navrhy, `deska-publish` approves.
Text comes from Claude (usneseni/llm.py, `api` or `claude-cli`); everything visual is
deterministic: places via RÚIAN (usneseni/geo.py), an orthophoto crop from ČÚZK with the
place drawn on it, a crop of the office's own drawing from the PDF, sign pictures by code.
Personal data from the notices (applicants, number plates, birth dates) never goes in.
"""

import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import httpx
import yaml

from ..usneseni import geo, llm
from ..usneseni.store import ROOT
from . import parking, photo, source
from .jobs import REDACTED_TITLE

log = logging.getLogger(__name__)

PROMPT_VERSION = "deska-v3"
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data")) / "uredni_deska"
SEED = ROOT / "data" / "uredni_deska"
DRAFTS, DIGESTS = DATA / "drafts", DATA / "digests"
WORK = Path(os.environ.get("DESKA_WORK", "/tmp/petka-deska"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://opendata.mov.varecha.work").rstrip("/")
SIGNS = yaml.safe_load((ROOT / "config" / "uredni_deska" / "znacky.yaml").read_text()) \
    if (ROOT / "config" / "uredni_deska" / "znacky.yaml").exists() else {}
ORTHO_WMS = "https://ags.cuzk.gov.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer"

CLUSTERS = {
    "doprava": "Doprava a uzavírky", "energie": "Výpadky elektřiny", "stavby": "Stavby a řízení",
    "majetek": "Majetek města", "rozpocet": "Rozpočet a hospodaření", "predpisy": "Pravidla a vyhlášky",
    "dotace": "Dotace", "informace": "Odpovědi na dotazy", "drazby": "Dražby",
    "doruceni": "Doručení písemnosti", "prostredi": "Životní prostředí", "volby": "Volby",
    "poplatky": "Poplatky", "jednani": "Jednání zastupitelstva", "ostatni": "Ostatní",
}


# --- candidates and grouping ----------------------------------------------------------------

def notices(mo5: bool = True) -> list[dict]:
    """Posted notices from the public API (works anywhere, no database credentials)."""
    out, offset = [], 0
    with httpx.Client(timeout=30, headers=source.HEADERS) as c:
        while True:
            r = c.get(f"{PUBLIC_URL}/api/v1/uredni-deska/notices",
                      params={"mo5": str(mo5).lower(), "active": "true", "limit": 100, "offset": offset})
            r.raise_for_status()
            page = r.json()
            out += page["results"]
            offset += 100
            if offset >= page["total"]:
                return out


_ATTACHMENT = re.compile(r"\s*[-–]\s*příloha\s*(č\.?\s*\d+)?\s*$|^příloha\s*č\.?\s*\d+\s*", re.I)
_KEYS = [re.compile(p, re.I) for p in (r"směrnic\w*\s+č\.\s*\d+/\d{4}",
                                       r"\d+\.\s*změn\w*\s+rozpočtu.*?r\.\s*\d{4}",
                                       r"závěrečn\w*\s+účt\w*.*?\d{4}")]


def group_key(n: dict) -> str:
    """Notices posted as one package (a directive and its annexes, a budget change and its
    tables) share a key; everything else is its own group. Same-titled notices that are not
    annexes are separate decisions when their references differ (the magistrát posts every
    traffic order on a street as „VV - OOP … - Jana Palacha“), so the reference is in the key."""
    t = n["title"]
    for rx in _KEYS:
        m = rx.search(t)
        if m:
            return f"{n['board']}:{re.sub(r'\\s+', ' ', m.group(0).lower())}"
    key = f"{n['board']}:{_ATTACHMENT.sub('', t).strip().lower()}"
    ref = " ".join((n.get("reference") or "").split()).lower()
    return f"{key}|{ref}" if ref and not _ATTACHMENT.search(t) else key


def groups(items: list[dict]) -> list[list[dict]]:
    """Grouped notices, the main one first (not an annex; then the oldest id). Annexes known only
    by their title join the one notice of that title, if there is exactly one."""
    by: dict[str, list[dict]] = {}
    for n in items:
        by.setdefault(group_key(n), []).append(n)
    for key in [k for k in by if "|" not in k]:
        mains = [k for k in by if k.startswith(key + "|")]
        if len(mains) == 1:
            by[mains[0]] += by.pop(key)
    out = []
    for g in by.values():
        g.sort(key=lambda n: (bool(re.search(r"příloha", n["title"], re.I)), n["id"]))
        out.append(g)
    return sorted(out, key=lambda g: g[0]["published"] or "", reverse=True)


def existing() -> set[str]:
    """Notice ids that already have a digest (draft, published or rejected) – leaders and members."""
    ids = set()
    for root in (DRAFTS, DIGESTS):
        for f in root.glob("*/digest.json"):
            d = json.loads(f.read_text())
            ids |= {d["notice_id"], *d.get("members", [])}
    return ids


# --- attachments -------------------------------------------------------------------------------

def download(group: list[dict]) -> list[Path]:
    """The group's attachments (PDFs) into WORK/<leader id>/; returns local paths."""
    d = WORK / group[0]["id"]
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    with httpx.Client(timeout=60, headers=source.HEADERS, follow_redirects=True) as c:
        for n in group:
            for i, a in enumerate(n.get("attachments") or []):
                url = a.get("url") or ""
                ext = Path(url.split("?")[0]).suffix.lower() or ".pdf"
                if ext not in (".pdf", ".png", ".jpg", ".jpeg"):
                    continue
                p = d / f"{n['id']}-{i + 1}{ext}"
                if not p.exists():
                    r = c.get(url)
                    r.raise_for_status()
                    p.write_bytes(r.content)
                paths.append(p)
    return paths


def pdf_text(paths: list[Path]) -> str:
    out = []
    for p in paths:
        if p.suffix.lower() == ".pdf":
            r = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True)
            out.append(r.stdout)
    return "\n".join(out)


# --- the plain-language draft (Claude) ---------------------------------------------------------

SYSTEM = f"""Jsi redaktor portálu Otevřená Pětka (otevřená data městského obvodu Pardubice V).
Převádíš oznámení z úřední desky do češtiny pro běžné lidi: co se děje, kde, kdy, koho se to
týká a co s tím můžou udělat. Píšeš věcně, krátce, bez úředních obratů, paragrafů a zkratek
(místo „OOP o stanovení místní úpravy provozu“ napiš, co se na ulici změní). Nic si nedomýšlej:
každý údaj musí být v oznámení nebo jeho přílohách; když něco nevíš, pole nech prázdné (null).

Pravidla:
- Žádné osobní údaje soukromých osob: jména žadatelů a adresátů, adresy bydliště, SPZ, čísla
  průkazů (ZTP), data narození, čísla účtů. Úřady, firmy a úřední osoby jménem úřadu smíš uvést.
  U vyhrazeného parkování pro osobu se zdravotním postižením napiš jen „vyhrazené místo pro
  osobu se zdravotním postižením“.
- V polích `period.from`, `period.to` a `action.deadline` piš data jako ISO (RRRR-MM-DD); ve všech
  textech (shrnutí, fakta, `period.text`) česky „24. 10. 2026“. Jen data, která v dokumentu stojí;
  dopočtené datum (třeba konec lhůty) uveď a v `reviewer_notes` vysvětli výpočet. Lhůta pro připomínky,
  námitky nebo nabídky je nejdůležitější údaj, pokud existuje – dej ji do `action`.
- Návrhy opatření obecné povahy (místní úprava provozu): „30 dnů ode dne zveřejnění“, kde dnem
  zveřejnění je poslední (15.) den vyvěšení. Počítej od vyvěšení na desce MAGISTRÁTU (ten
  opatření vydává), ne od vyvěšení na desce obvodu: vyvěšeno 12. 10. → zveřejněno 27. 10. →
  lhůta do 26. 11. Datum vyvěšení na desce magistrátu hledej v dokumentu („vyvěšena na úřední
  desku Magistrátu … dne“); když tam není, vezmi datum vyhotovení (`Datum:` v záhlaví) a v
  `reviewer_notes` napiš, že je potřeba ho ověřit.
- U úprav provozu vypiš každou dopravní značku (kód přesně podle dokumentu, např. IP12, E13,
  V10e) a zda je nová, k odstranění, zůstává, nebo se jen mění její text (`vymena` – třeba nová SPZ
  na tabulce; neuváděj ji pak dvakrát jako odstranit + nová). Text dodatkové tabulky (E13) opiš,
  pokud neobsahuje osobní údaje; jinak text null.
- `places`: místa v Pardubicích tak, jak je dokument píše (ulice, ulice + číslo popisné, část
  obce + č. p.); `parcels`: pozemky („p. p. č. 2515/14, k. ú. Pardubice“). Obecná místa (sídliště
  Dukla) do `places` nedávej. Když dokument vyjmenovává domy (výpadek elektřiny, uzavírka), dej
  každou ulici s jejími čísly popisnými („K Dolíčku 4, 16–20, 22“), ne jen název ulice – mapa pak
  ukáže přesně dotčené domy.
- `drawing`: pokud příloha obsahuje situační výkres, mapku nebo fotku místa, urči soubor, stranu
  (od 1) a výřez se samotným obrázkem jako zlomky šířky a výšky strany [x0, y0, x1, y1]
  (0 = levý/horní okraj), bez hlavičky a razítek. Jinak null.
- `budget`: u změn rozpočtu nejvýš 8 největších změn v tisících Kč (+ přidáno, − ubráno),
  popsaných lidsky a krátce, nejvýš 45 znaků („odvoz odpadu“, ne „MP za komunální odpad“; důvod
  jako „vyšlo levněji“ smí být v závorce). Jinak prázdné pole.
- `parking`: jen když výkres nebo fotka v příloze ukazují řadu parkovacích stání a změna se jich týká.
  Popiš jednu řadu zleva doprava tak, jak ji výkres kreslí: úseky stejného druhu s počtem stání
  (`before` dnes, `after` po změně). Počty a pořadí musí jít na výkresu spočítat; co výkres neukazuje,
  nedoplňuj. Do `evidence` napiš, podle čeho na výkresu jsi počty a pořadí určil. Když si nejsi jistý
  (výkres chybí, stání nejsou vidět, nejde je spočítat), dej null – schéma pak nebude.
- `visual_plan`: pro redaktora 1–2 věty, jak oznámení nejlépe ukázat (mapa, výkres, graf…)
  a proč; `reviewer_notes`: co si má člověk před zveřejněním ověřit (nejasnosti, odhady).
- Shluky: {", ".join(f"{k} = {v}" for k, v in CLUSTERS.items())}."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["cluster", "headline", "summary", "where", "period", "action", "affects", "facts",
                 "signs", "places", "parcels", "budget", "drawing", "parking", "visual_plan", "reviewer_notes"],
    "properties": {
        "cluster": {"type": "string", "enum": list(CLUSTERS)},
        "headline": {"type": "string", "description": "Jedna věta, nejvýš 110 znaků: co se děje."},
        "summary": {"type": "string", "description": "2–4 věty pro běžného čtenáře."},
        "where": {"type": ["string", "null"]},
        "period": {"type": "object", "additionalProperties": False, "required": ["from", "to", "text"],
                   "properties": {"from": {"type": ["string", "null"]}, "to": {"type": ["string", "null"]},
                                  "text": {"type": ["string", "null"]}}},
        "action": {"type": ["object", "null"], "additionalProperties": False,
                   "required": ["what", "deadline", "how"],
                   "properties": {"what": {"type": "string"}, "deadline": {"type": ["string", "null"]},
                                  "how": {"type": "string"}}},
        "affects": {"type": ["string", "null"]},
        "facts": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False, "required": ["label", "value"],
            "properties": {"label": {"type": "string"}, "value": {"type": "string"}}}},
        "signs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["code", "text", "change"],
            "properties": {"code": {"type": "string"}, "text": {"type": ["string", "null"]},
                           "change": {"type": "string", "enum": ["nova", "odstranit", "zustava", "vymena"]}}}},
        "places": {"type": "array", "items": {"type": "string"}},
        "parcels": {"type": "array", "items": {"type": "string"}},
        "budget": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False, "required": ["label", "change"],
            "properties": {"label": {"type": "string"}, "change": {"type": "number"}}}},
        "drawing": {"type": ["object", "null"], "additionalProperties": False,
                    "required": ["file", "page", "box", "caption"],
                    "properties": {"file": {"type": "string"}, "page": {"type": "integer"},
                                   "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                                   "caption": {"type": "string"}}},
        "parking": {"type": ["object", "null"], "additionalProperties": False,
                    "required": ["street", "kind", "before", "after", "evidence"],
                    "properties": {"street": {"type": "string"},
                                   "kind": {"type": "string", "enum": ["kolme", "podelne", "sikme"]},
                                   "before": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["type", "n", "label"],
                   "properties": {"type": {"type": "string", "enum": ["bezne", "ztp", "kratkodobe", "doprovod", "rezident", "vyhrazene", "nabijeni", "zakaz"]},
                                  "n": {"type": "integer"}, "label": {"type": ["string", "null"]}}}}, "after": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["type", "n", "label"],
                   "properties": {"type": {"type": "string", "enum": ["bezne", "ztp", "kratkodobe", "doprovod", "rezident", "vyhrazene", "nabijeni", "zakaz"]},
                                  "n": {"type": "integer"}, "label": {"type": ["string", "null"]}}}},
                                   "evidence": {"type": "string"}}},
        "visual_plan": {"type": "string"},
        "reviewer_notes": {"type": "string"},
    },
}


def prompt(group: list[dict]) -> str:
    lines = ["Oznámení z úřední desky (jedno nebo balíček souvisejících):"]
    for n in group:
        lines.append(f"- {n['title']} (vyvěšeno {n['published']}, visí do {n['valid_until']}, "
                     f"deska {'MO Pardubice V' if n['board'] == 'mo5' else 'magistrátu'}, "
                     f"odbor: {n.get('department') or '–'}, druh podle názvu: {n['kind']})")
    lines.append("Názvy souborů příloh začínají id oznámení. Připrav podklad pro kartu „pro lidi“.")
    return "\n".join(lines)


def delivery(group: list[dict]) -> dict:
    """Delivery notices: nothing from them is worth repeating (and the name must not be)."""
    n = group[0]
    return {"cluster": "doruceni", "headline": "Úřad doručuje písemnost veřejnou vyhláškou",
            "summary": ("Úřad se nemohl spojit s adresátem úřední písemnosti, a tak mu ji doručuje "
                        "vyvěšením na úřední desce. Adresát si ji může vyzvednout na úřadu; po uplynutí "
                        "lhůty se považuje za doručenou."),
            "where": None, "period": {"from": None, "to": n.get("valid_until"), "text": None},
            "action": None, "affects": "jen adresáta písemnosti", "facts": [], "signs": [],
            "places": [], "parcels": [], "budget": [], "drawing": None, "parking": None,
            "visual_plan": "Bez vizuálu; jméno adresáta nepřebíráme.", "reviewer_notes": ""}


# --- visuals (deterministic) ------------------------------------------------------------------

def _coords(g: dict):
    c, depth = g["coordinates"], {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2,
                                  "Polygon": 2, "MultiPolygon": 3}[g["type"]]
    stack = [(c, depth)]
    while stack:
        x, d = stack.pop()
        if d == 0:
            yield x
        else:
            stack.extend((y, d - 1) for y in x)


def ortho(features: list[dict], target: Path, width: int = 1200) -> dict | None:
    """Orthophoto crop (ČÚZK WMS, CC BY 4.0) around the places, with the places as SVG paths in
    the image's pixel space. Not for whole streets across town: then the map says more."""
    pts = [p for f in features for p in _coords(f["geometry"])]
    if not pts:
        return None
    w, e = min(p[0] for p in pts), max(p[0] for p in pts)
    s, n = min(p[1] for p in pts), max(p[1] for p in pts)
    if (e - w) > 0.012 or (n - s) > 0.008:       # ~850 x 900 m: too large for a useful photo
        return None
    cx, cy = (w + e) / 2, (s + n) / 2
    half_lat = max((n - s) * 0.8, 0.0009)        # at least ~200 m tall
    half_lon = max((e - w) * 0.8, half_lat * 1.6 / 0.643)  # 16:10, cos(50°) ≈ 0.643
    half_lat = max(half_lat, half_lon * 0.643 / 1.6)
    bbox = [cx - half_lon, cy - half_lat, cx + half_lon, cy + half_lat]
    height = round(width * (half_lat / (half_lon * 0.643)))
    r = httpx.get(ORTHO_WMS, timeout=60, headers=source.HEADERS, params={
        "service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": "0", "styles": "",
        "crs": "EPSG:4326", "bbox": f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}",
        "width": width, "height": height, "format": "image/jpeg"})
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"ČÚZK WMS: {r.text[:200]}")
    target.write_bytes(r.content)

    def xy(p):
        return (round((p[0] - bbox[0]) / (bbox[2] - bbox[0]) * width, 1),
                round((bbox[3] - p[1]) / (bbox[3] - bbox[1]) * height, 1))

    shapes = []
    for f in features:
        g = f["geometry"]
        if g["type"] in ("Point", "MultiPoint"):
            for p in ([g["coordinates"]] if g["type"] == "Point" else g["coordinates"]):
                shapes.append({"kind": "point", "xy": xy(p)})
        elif g["type"] in ("LineString", "MultiLineString"):
            for line in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
                shapes.append({"kind": "line", "d": "M" + " L".join(f"{x},{y}" for x, y in map(xy, line))})
        else:
            for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
                shapes.append({"kind": "area", "d": " ".join(
                    "M" + " L".join(f"{x},{y}" for x, y in map(xy, ring)) + " Z" for ring in poly)})
    return {"file": target.name, "width": width, "height": height, "bbox": bbox, "shapes": shapes,
            "credit": "Ortofoto © ČÚZK, CC BY 4.0, upraveno (vyznačeno místo)"}


def thumbnail(folder: Path, visual: dict, size: int = 192) -> str | None:
    """A small square of the orthophoto around the place, with the dot, for the list."""
    o = visual.get("ortho")
    if not o or not (folder / o["file"]).is_file():
        return None
    from PIL import Image, ImageDraw
    im = Image.open(folder / o["file"]).convert("RGB")
    pts = [sh["xy"] for sh in o["shapes"] if sh["kind"] == "point"]
    cx, cy = pts[0] if pts else (im.width / 2, im.height / 2)
    side = min(im.width, im.height) * 0.6
    left = min(max(cx - side / 2, 0), im.width - side)
    top = min(max(cy - side / 2, 0), im.height - side)
    out = im.crop((round(left), round(top), round(left + side), round(top + side))).resize((size, size), Image.LANCZOS)
    if pts:
        x, y, r = (cx - left) / side * size, (cy - top) / side * size, size * 0.055
        ImageDraw.Draw(out).ellipse((x - r, y - r, x + r, y + r), fill=(222, 9, 28), outline="white", width=max(2, round(r / 3)))
    out.save(folder / "nahled.jpg", quality=82)
    return "nahled.jpg"


# signs that say most about a traffic card, best first: prohibitions, orders, information, zones,
# warnings, markings; supplementary plates (E), barriers (Z) and lights (S) say little alone
_SIGN_RANK = ("B", "C", "IP", "IZ", "IS", "A", "P", "V")


_PLACE_CLUSTERS = {"doprava", "stavby", "majetek", "prostredi", "energie", "drazby", "ostatni"}


def card_thumb(d: dict) -> dict:
    """What the list shows next to a card: its main sign, a crop of its photo, or a kind icon."""
    v = d.get("visual") or {}
    if d.get("cluster") == "doprava":
        signs = [s for s in v.get("signs") or [] if s.get("image")]
        def rank(s):     # within a kind, the order of the document: the main sign comes first
            prefix = next((i for i, p in enumerate(_SIGN_RANK) if s["code"].startswith(p)), len(_SIGN_RANK))
            return (s["change"] not in ("nova", "vymena"), prefix)
        signs = [s for s in signs if s["code"][:1] not in "EZS" or s["code"].startswith("IS")]
        if signs:
            best = min(signs, key=rank)
            return {"kind": "sign", "src": f"/static/znacky/{best['image']}", "alt": best.get("name") or best["code"]}
    if v.get("thumb") and d.get("cluster") in _PLACE_CLUSTERS:   # elsewhere the place is the office
        return {"kind": "photo", "file": v["thumb"], "alt": "Letecký snímek místa"}
    return {"kind": "icon", "id": d.get("cluster") or "ostatni"}


def drawing_crop(spec: dict, files: list[Path], target: Path, dpi: int = 130) -> dict | None:
    """The office's own drawing or photo, cut out of the PDF page Claude pointed at."""
    src = next((p for p in files if p.name == spec["file"]), None)
    if not src or src.suffix.lower() != ".pdf":
        return None
    page = max(1, int(spec["page"]))
    info = subprocess.run(["pdfinfo", "-f", str(page), "-l", str(page), str(src)],
                          capture_output=True, text=True).stdout
    m = re.search(rf"Page\s+{page}\s+size:\s+([\d.]+) x ([\d.]+)", info)
    if not m:
        return None
    pw, ph = float(m.group(1)) / 72 * dpi, float(m.group(2)) / 72 * dpi
    x0, y0, x1, y1 = [min(max(v, 0.0), 1.0) for v in spec["box"]]
    if x1 - x0 < 0.1 or y1 - y0 < 0.1:
        x0, y0, x1, y1 = 0, 0, 1, 1
    stem = target.with_suffix("")
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png", "-singlefile",
                    "-x", str(int(x0 * pw)), "-y", str(int(y0 * ph)),
                    "-W", str(int((x1 - x0) * pw)), "-H", str(int((y1 - y0) * ph)), str(src), str(stem)],
                   check=True)
    return {"file": target.name, "caption": spec.get("caption") or "Příloha oznámení"}


def signs(items: list[dict]) -> list[dict]:
    """Sign list for the card. The same sign both removed and added (a new plate text, a new
    number plate) is one sign whose content changes, not two."""
    items = [dict(i) for i in items]
    norm = lambda i: re.sub(r"[\s-]", "", i["code"]).upper()
    for code in {norm(i) for i in items if i["change"] == "odstranit"}:
        gone = [i for i in items if norm(i) == code and i["change"] == "odstranit"]
        new = [i for i in items if norm(i) == code and i["change"] == "nova"]
        for old, fresh in zip(gone, new):        # one removed + one added = one whose content changes
            fresh["change"] = "vymena"
            old["change"] = "_drop"
    items = [i for i in items if i["change"] != "_drop"]
    out = []
    for s in items:
        span = RANGE.match(re.sub(r"\s", "", s["code"]))
        if span:                                 # "C4a-c": whichever variant fits, one item
            base, first, last = span.group(1).upper(), span.group(2).lower(), span.group(3).lower()
            metas = [SIGNS.get(base + chr(c), {}) for c in range(ord(first), ord(last) + 1)]
            out.append({"code": f"{base}{first}–{last}", "name": _common_name([m.get("name") for m in metas]),
                        "image": metas[0].get("image"), "text": s.get("text"), "change": s["change"]})
            continue
        code, text = re.sub(r"[\s-]", "", s["code"]), s.get("text")
        value = re.match(r"^(.+?)\((.+)\)$", code)       # "B20a(30)": the sign and its number
        if value:
            code, text = value.group(1), text or value.group(2)
        code = code.upper()
        code = re.sub(r"(\d)([A-Z])$", lambda m: m.group(1) + m.group(2).lower(), code)
        meta = SIGNS.get(code, {})
        out.append({"code": code, "name": meta.get("name") or EXTRA_NAMES.get(code), "image": meta.get("image"),
                    "text": text, "change": s["change"]})
    return out


# signs the Wikipedia list (znacky.yaml) lacks; names per vyhláška 294/2015 Sb., no picture
EXTRA_NAMES = {"IP10b": "Návěst před slepou pozemní komunikací", "S7": "Přerušované žluté světlo"}


RANGE = re.compile(r"^([A-Za-z]{1,2}\d{1,2})([a-z])[-–]([a-z])$")


def _common_name(names: list) -> str | None:
    """'Přikázaný směr objíždění vpravo' + '… vlevo' -> 'Přikázaný směr objíždění'."""
    names = [n for n in names if n]
    if not names:
        return None
    words = [n.split() for n in names]
    common = []
    for ws in zip(*words):
        if len(set(ws)) > 1:
            break
        common.append(ws[0])
    return " ".join(common) if len(common) >= 2 else " / ".join(names)


# --- checks ------------------------------------------------------------------------------------

PLATE = re.compile(r"\b\d[A-Z][A-Z0-9]\s?\d{4}\b")
BIRTH = re.compile(r"nar(ozen[aáý]|\.)", re.I)


def _date_forms(iso: str) -> list[str]:
    d = dt.date.fromisoformat(iso)
    return [f"{d.day}. {d.month}. {d.year}", f"{d.day}.{d.month}.{d.year}", f"{d.day:02d}.{d.month:02d}.{d.year}",
            f"{d.day}. {d.month}.{d.year}", f"{d.day:02d}. {d.month:02d}. {d.year}", iso]


def private_names(text: str) -> list[str]:
    """Names of private applicants as the notice states them ("Žadatel: … – fyzická osoba")."""
    out = []
    for m in re.finditer(r"Žadatel\w*:\s*([^,\n]+?),[^\n]*fyzick", text):
        out.append(m.group(1).strip())
    return out


def check(d: dict, text: str) -> list[str]:
    problems = []
    flat = json.dumps({k: d[k] for k in ("headline", "summary", "where", "affects", "facts", "action", "signs")},
                      ensure_ascii=False)
    for name in private_names(text):
        for part in name.split():
            if len(part) > 2 and part in flat:
                problems.append(f"obsahuje jméno žadatele ({part})")
    if PLATE.search(flat):
        problems.append("vypadá to na SPZ")
    if BIRTH.search(flat):
        problems.append("zmínka o datu narození")
    compact = re.sub(r"\s+", " ", text)
    for label, iso in (("od", d["period"]["from"]), ("do", d["period"]["to"]),
                       ("lhůta", (d.get("action") or {}).get("deadline"))):
        if iso:
            try:
                if not any(f in compact for f in _date_forms(iso)):
                    problems.append(f"datum {label} {iso} v dokumentu není doslova")
            except ValueError:
                problems.append(f"datum {label} '{iso}' není ve tvaru RRRR-MM-DD")
    if len(d["headline"]) > 140:
        problems.append("titulek je dlouhý")
    return problems


def annotated_drawing(d: dict, out: Path) -> dict:
    """The office's drawing with numbered markers Claude puts on what changes (only on things
    the drawing shows), the explanations go under it."""
    work = WORK / d.get("_id", out.name) / "vykres"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out / "vykres.png", work / "vykres.png")
    res = llm.structured_files(photo.ANNOTATE_SYSTEM,
                               f"Změna: {d['headline']}\n{d['summary']}\nKde: {d.get('where') or '–'}",
                               [work / "vykres.png"], photo.ANNOTATE_SCHEMA, effort="high")
    kept = photo.annotate(out / "vykres.png", res["marks"], out / "vykres-popis.png")
    return {"annotated": "vykres-popis.png", "marks": kept, "legend": res["legend"]} if kept else {}


def _centre(f: dict) -> tuple[float, float]:
    pts = list(_coords(f["geometry"]))
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def street_photo(notice: dict, d: dict, feats: list[dict], visual: dict, out: Path) -> dict | None:
    """Nearest Panoramax picture of the place, 'dnes' and 'po změně' (signs placed by Claude
    against the drawing). None when there is no picture or Claude can't match it to the drawing."""
    target = _centre(next((f for f in feats if f["kind"] == "address"), feats[0]))
    feature = photo.nearest(*target)
    if not feature:
        return None
    work = WORK / notice["id"] / "foto"
    work.mkdir(parents=True, exist_ok=True)
    c = photo.candidates(feature, target, work)
    inputs = list(c["files"])
    if visual.get("drawing"):
        shutil.copy2(out / visual["drawing"]["file"], work / "vykres.png")
        inputs.append(work / "vykres.png")
    listing = "\n".join(f"- {s['code']} ({s['change']}){': ' + s['text'] if s.get('text') else ''}" for s in visual["signs"])
    placed = llm.structured_files(
        photo.PLACEMENT_SYSTEM,
        f"Oznámení: {d['headline']}\nKde: {d.get('where') or '–'}\nZnačky:\n{listing or '–'}\n"
        f"Fotka je {c['distance']} m od místa. " + ("Výkres je přiložen (vykres.png)." if visual.get("drawing") else "Výkres není."),
        inputs, photo.PLACEMENT_SCHEMA, effort="high")
    if placed["view"] is None or placed["confidence"] == "nizka":
        log.info("%s: photo not used (%s)", notice["id"], placed["reason"][:200])
        return None
    credit = f"Foto: {c['author']}, Panoramax, {c['licence']}" + (f", {c['date']}" if c["date"] else "")
    marks = [m for m in placed["marks"] if 0 <= m["x"] <= 1 and 0 <= m["y"] <= 1]
    photo.render(c["files"][placed["view"]], marks, out / "foto-dnes.jpg", out / "foto-po.jpg",
                 credit + (" · upraveno: značky podle výkresu" if marks else ""))
    return {"before": "foto-dnes.jpg", "after": "foto-po.jpg" if marks else None, "credit": credit,
            "source": c["url"], "distance": c["distance"], "confidence": placed["confidence"],
            "reason": placed["reason"], "marks": marks, "picture": c["id"],
            "yaw": round(c["yaws"][placed["view"]], 1)}


# --- making a draft ----------------------------------------------------------------------------

def draft(group: list[dict]) -> Path:
    """Propose a digest for one notice group; writes DRAFTS/<leader id>/digest.json (+ images)."""
    leader = group[0]
    out = DRAFTS / leader["id"]
    out.mkdir(parents=True, exist_ok=True)
    files = download(group)
    text = pdf_text(files)
    if leader["kind"] == "doruceni":
        d = delivery(group)
    else:
        d = llm.structured_files(SYSTEM, prompt(group), files, SCHEMA, effort="high")
    feats = geo.locate(d["places"], d["parcels"]) if (d["places"] or d["parcels"]) else []
    visual = {"map": feats}
    try:
        # a whole street would make the crop useless: centre on the addresses/parcels if any
        spot = [f for f in feats if f["kind"] != "street"] or feats
        visual["ortho"] = ortho(spot, out / "ortofoto.jpg") if feats else None
    except Exception as e:
        log.warning("%s: ortofoto failed: %s", leader["id"], e)
        visual["ortho"] = None
    visual["drawing"] = drawing_crop(d["drawing"], files, out / "vykres.png") if d.get("drawing") else None
    if visual["drawing"] and d["cluster"] in ("doprava", "stavby"):
        try:
            visual["drawing"].update(annotated_drawing(d, out))
        except Exception as e:
            log.warning("%s: drawing annotation failed: %s", leader["id"], e)
    visual["signs"] = signs(d["signs"])
    problems = check(d, text)
    visual["parking"] = None
    if d.get("parking"):
        if visual["drawing"]:            # never without the drawing it was read from
            (out / "schema.svg").write_text(parking.svg(d["parking"]))
            visual["parking"] = {"file": "schema.svg", "evidence": d["parking"]["evidence"]}
        else:
            problems.append("schéma stání vynecháno: bez výkresu by nebylo čím ho doložit")
    visual["photo"] = None
    if d["cluster"] == "doprava" and feats:
        try:
            visual["photo"] = street_photo(leader, d, feats, visual, out)
        except Exception as e:
            log.warning("%s: street photo failed: %s", leader["id"], e)
    visual["thumb"] = thumbnail(out, visual)
    digest = {
        "notice_id": leader["id"], "members": [n["id"] for n in group[1:]], "status": "draft",
        "prompt_version": PROMPT_VERSION, "model": llm.MODEL if llm.BACKEND == "api" else f"cli:{llm.CLI_MODEL}",
        "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "source": _source(leader, d["cluster"]),
        **d, "visual": visual, "problems": problems,
    }
    (out / "digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=1, default=str) + "\n")
    return out


# The board keeps some notices up for years (where to find the budget, fee rules from 2022).
# Cards are for what is happening now: only notices posted in the last WINDOW_DAYS are drafted,
# and a card whose event is already over (and leaves nothing to do) is dropped right away.
WINDOW_DAYS = 30


def recent(group: list[dict], today: dt.date | None = None) -> bool:
    today = today or dt.date.today()
    published = str(group[0].get("published") or "")[:10]
    return bool(published) and published >= (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()


def over(d: dict, today: dt.date | None = None) -> bool:
    """The card's period has ended and there is no deadline still running."""
    today = (today or dt.date.today()).isoformat()
    end = str((d.get("period") or {}).get("to") or "")[:10]
    deadline = str((d.get("action") or {}).get("deadline") or "")[:10]
    return bool(end) and end < today and not (deadline and deadline >= today)


def drafts(limit: int = 20, ids: list[str] | None = None) -> list[dict]:
    """Draft digests for new MO V notices (or the given ids). Returns a short report per draft."""
    have = set() if ids else existing()
    todo = [g for g in groups(notices(mo5=not ids)) if (g[0]["id"] in ids if ids else
            recent(g) and not ({n["id"] for n in g} & have))][:limit]
    report = []
    for g in todo:
        try:
            p = draft(g)
            d = json.loads((p / "digest.json").read_text())
            if over(d) and not ids:
                reject([g[0]["id"]], note=f"už proběhlo (do {d['period']['to']})")
                d["problems"] = ["zahozeno: už proběhlo"]
            report.append({"id": g[0]["id"], "members": len(g) - 1, "cluster": d["cluster"],
                           "headline": d["headline"], "problems": d["problems"]})
        except Exception as e:
            log.exception("draft %s failed", g[0]["id"])
            report.append({"id": g[0]["id"], "error": str(e)})
    return report


def _source(n: dict, cluster: str) -> dict:
    """Where the card came from. A delivery's title names the addressee and the city takes the
    notice down, so the card (which lives on in git) keeps neither the title nor the link."""
    if cluster == "doruceni":
        return {"title": REDACTED_TITLE, "url": "", "board": n["board"], "mo5": n.get("is_mo5")}
    return {"title": n["title"], "url": n["url"], "board": n["board"], "mo5": n.get("is_mo5")}


def publish(ids: list[str], note: str | None = None) -> list:
    """Approve drafts: move them to DIGESTS with status published (then commit and sync).
    Cards for notices that aren't about MO V (drafted by id, e.g. to try something) are refused."""
    done = []
    for nid in ids:
        src, dst = DRAFTS / nid, DIGESTS / nid
        if not (src / "digest.json").exists():
            continue
        d = json.loads((src / "digest.json").read_text())
        if d.get("source", {}).get("mo5") is False:
            done.append({"id": nid, "error": "oznámení se netýká MO V, kartu nevydávám"})
            continue
        if d["cluster"] == "doruceni":
            d["source"] |= {"title": REDACTED_TITLE, "url": ""}
        d.update(status="published", published_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                 review_note=note)
        (src / "digest.json").write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str) + "\n")
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        done.append(nid)
    return done


def reject(ids: list[str], note: str | None = None) -> list[str]:
    """Keep a rejected draft (so it isn't proposed again) but never show it publicly."""
    done = []
    for nid in ids:
        if (DIGESTS / nid / "digest.json").exists():    # already published: take it back down
            if (DRAFTS / nid).exists():
                shutil.rmtree(DRAFTS / nid)
            shutil.move(str(DIGESTS / nid), str(DRAFTS / nid))
        f = DRAFTS / nid / "digest.json"
        if f.exists():
            d = json.loads(f.read_text())
            d.update(status="rejected", review_note=note)
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str) + "\n")
            done.append(nid)
    return done


# --- database (in the cluster: after seed/sync) -------------------------------------------------

def seed() -> None:
    """Published digests from the image (git) into DATA – they are the reviewed version."""
    if DATA.resolve() == SEED.resolve() or not (SEED / "digests").exists():
        return
    for src in (SEED / "digests").rglob("*"):
        if src.is_file():
            dst = DIGESTS / src.relative_to(SEED / "digests")
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)


def receive(stream) -> dict:
    """Replace the cards in DATA with a tar of `drafts/` and `digests/` (from scripts/deska-sync.sh):
    drafts are swapped wholesale (approved or dropped ones disappear), approved cards are updated
    and those taken back down (`deska-reject` on a published card) are removed."""
    import tarfile
    import tempfile
    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATA, prefix=".incoming-") as tmp:
        with tarfile.open(fileobj=stream, mode="r|") as tar:
            tar.extractall(tmp, filter="data")       # no absolute paths, links or devices
        new = Path(tmp)
        if (new / "drafts").is_dir():
            old = DATA / ".drafts-old"
            if old.exists():
                shutil.rmtree(old)
            if DRAFTS.exists():
                DRAFTS.rename(old)
            (new / "drafts").rename(DRAFTS)
            if old.exists():
                shutil.rmtree(old)
        n = 0
        if (new / "digests").is_dir() and DIGESTS.is_dir():
            # the tar holds every approved card; one missing from it was taken back down
            keep = {d.name for d in (new / "digests").iterdir()}
            for d in DIGESTS.iterdir():
                if d.is_dir() and d.name not in keep:
                    shutil.rmtree(d)
        for src in (new / "digests").glob("*/*") if (new / "digests").is_dir() else []:
            dst = DIGESTS / src.relative_to(new / "digests")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    return {"drafts": len(list(DRAFTS.glob("*/digest.json"))), "published_files": n}


def load(conn) -> int:
    """Bring notice_digests in line with the digest directories (drafts and published)."""
    rows = []
    for root in (DIGESTS, DRAFTS):
        for f in root.glob("*/digest.json"):
            d = json.loads(f.read_text())
            if root == DRAFTS and (DIGESTS / d["notice_id"]).exists():
                continue                    # an approved copy wins over a stale draft
            rows.append(d)
    known = {r["id"] for r in conn.execute("SELECT id FROM notices")}
    conn.execute("DELETE FROM notice_digests")
    n = 0
    for d in rows:
        if d["notice_id"] not in known:
            continue
        conn.execute(
            """INSERT INTO notice_digests (notice_id, members, status, cluster, data, prompt_version,
                 created_at, published_at, review_note)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (d["notice_id"], [m for m in d.get("members", []) if m in known], d["status"], d["cluster"],
             json.dumps(d, ensure_ascii=False, default=str), d.get("prompt_version"), d.get("created_at"),
             d.get("published_at"), d.get("review_note")))
        n += 1
    return n


def asset_path(nid: str, name: str, draft: bool = False) -> Path | None:
    """An image of a card: published ones for everybody, drafts only for the reviewers'
    preview (and never those of a rejected draft)."""
    if not re.fullmatch(r"[a-z0-9]+-\d+", nid) or not re.fullmatch(r"[a-z0-9_-]+\.(png|jpg|jpeg|svg)", name):
        return None
    root = DRAFTS if draft else DIGESTS
    meta, p = root / nid / "digest.json", root / nid / name
    if not (meta.is_file() and p.is_file()):
        return None
    if json.loads(meta.read_text()).get("status") != ("draft" if draft else "published"):
        return None
    return p
