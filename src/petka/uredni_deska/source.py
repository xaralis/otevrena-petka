"""The official boards as machine-readable data: the open formal norm (OFN) "Úřední deska",
JSON-LD, https://ofn.gov.cz/úřední-desky/2021-07-20/.

Statutární město Pardubice publishes one export endpoint for all its boards:

    https://pardubice.eu/export/official-board-json                 board of the Magistrát
                                                                    (registered in NKOD)
    https://pardubice.eu/export/official-board-json?district_id=5   board of ÚMO Pardubice V
                                                                    (district_id 1–8 = MO I–VIII)

The district board is the úřední deska of MO Pardubice V itself: everything the district
office posts, plus decisions of the Magistrát or other offices it posts because they concern
its territory (traffic orders, deliveries to residents). The Magistrát board carries the rest
of the city. Both send `Cache-Control: no-store` and no ETag or Last-Modified; we still send
the conditional headers in case that changes.

The feed is a snapshot of what is posted right now: a notice that disappears from it was
taken down (sejmuto). History is kept by the job, not by the source.
"""

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

from ..usneseni.text import fold

FEED = "https://pardubice.eu/export/official-board-json"


@dataclass(frozen=True)
class Board:
    id: str
    name: str
    url: str        # the JSON feed
    page: str       # the board for people
    mo5: bool       # everything on it concerns MO Pardubice V


BOARDS = [
    Board("mo5", "Úřední deska MO Pardubice V", f"{FEED}?district_id=5",
          "https://pardubice.eu/uredni-deska/obvody?district=mo5", True),
    Board("mmp", "Úřední deska Magistrátu města Pardubic", FEED,
          "https://pardubice.eu/uredni-deska", False),
]
BY_ID = {b.id: b for b in BOARDS}
NKOD = "https://data.gov.cz/datov%C3%A1-sada?iri=https%3A%2F%2Fdata.gov.cz%2Fzdroj%2Fdatov%C3%A9-sady%2F00274046%2F996543981"
OFN = "https://ofn.gov.cz/úřední-desky/2021-07-20/"

TIMEOUT = httpx.Timeout(30, connect=10)
HEADERS = {"User-Agent": "otevrena-petka (+https://otevrenapetka.cz)",
           "Accept": "application/ld+json, application/json"}


@dataclass
class Fetched:
    status: int                  # 200, or 304 when the conditional request says unchanged
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def fetch(board: Board, etag: str | None = None, last_modified: str | None = None,
          client: httpx.Client | None = None) -> Fetched:
    """Download one board; raises on network errors and non-2xx answers."""
    headers = dict(HEADERS)
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    try:
        r = client.get(board.url, headers=headers)
        if r.status_code == 304:
            return Fetched(304, etag=etag, last_modified=last_modified)
        r.raise_for_status()
        return Fetched(r.status_code, r.content, r.headers.get("etag"), r.headers.get("last-modified"))
    finally:
        if own:
            client.close()


# --- parsing --------------------------------------------------------------------------------

def _text(v) -> str | None:
    """OFN multilingual text {"cs": …} (or a plain string some publishers send)."""
    if isinstance(v, dict):
        v = v.get("cs") or next((x for x in v.values() if isinstance(x, str)), None)
    if not isinstance(v, str):
        return None
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def _date(v) -> dt.date | None:
    """OFN time instant {"datum": "2026-10-22"} or {"datum_a_čas": "2026-10-22T08:00:00+02:00"};
    {"nespecifikovaný": true} (no end date) gives None."""
    if not isinstance(v, dict):
        return None
    s = v.get("datum") or v.get("datum_a_čas")
    if not isinstance(s, str):
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def notice_id(board: str, url: str) -> str:
    """Stable id from the notice's URL: `mo5-15531` for …/obvody?id=15531."""
    q = parse_qs(urlparse(url).query).get("id")
    if q and q[0].isdigit():
        return f"{board}-{q[0]}"
    return f"{board}-{hashlib.sha1(url.encode()).hexdigest()[:12]}"


# MO V named explicitly: "MO Pardubice V", "ÚMO 5", "ZMO Pardubice V", "OE UMO5/…" and
# "městský obvod / obvodu Pardubice V". Roman V must stand alone ("Pardubice VII" is not V),
# and "Pardubice v …" with the preposition needs the MO/obvod in front to count.
MO5 = re.compile(r"\b[uzr]?mo\s*(pardubice\s*)?(v|5)\b|\bobvod\w*\s+pardubice\s+v\b")


def mentions_mo5(*texts: str | None) -> bool:
    return bool(MO5.search(fold(" ".join(t for t in texts if t))))


# What kind of notice it is, from its title (our label, not the city's). First match wins,
# so the specific kinds go before the broad ones ("Veřejná vyhláška – oznámení o uložení
# písemnosti" is a delivery, not a regulation).
KINDS = [
    ("doruceni", "Doručení písemnosti", r"pisemnost|vyzvednuti silnicniho vozidla"),
    ("jednani", "Zasedání a jednání", r"pozvank|zasedani|ustavujic|jednani zastupitelstva"),
    ("volby", "Volby", r"\bvol(b|eb|ic)"),
    ("doprava", "Doprava a uzavírky", r"uprav\w* provozu|uzavirk|objizd|dopravni"),
    ("energie", "Přerušení dodávek energií", r"preruseni dodav|odstavk\w* (elektr|plyn|vod)"),
    ("dotace", "Dotace", r"dotac|grant"),
    ("rozpocet", "Rozpočet a hospodaření", r"rozpoc(e)?t|zaverecn\w* uc(e)?t|hospodareni"),
    ("poplatky", "Místní poplatky", r"poplat|predpisn\w* seznam"),
    ("drazby", "Dražby a aukce", r"drazb|drazebni|aukc"),
    ("zakazky", "Zakázky", r"vyberov\w* rizeni|zakazk"),
    ("majetek", "Majetek a pronájmy",
     r"zamer\w* (o |na )?(prod|pronaj|smen|propacht|pacht|vypujc|darov|bezuplat)|prodej|pronaj|pacht|vypujck|nebytov|^zverejneni c"),
    ("prostredi", "Životní prostředí", r"nakladani s vodami|odpadni\w* vod|\blesu\b|lesni|stromov|kacen|drevin|odchyt|ochran\w* prirody"),
    ("stavby", "Stavby a řízení", r"stavb|stavebn|rizeni|uzemn|kolaudac|podklad\w* rozhodnuti|cyklostezk|chodnik"),
    ("predpisy", "Vyhlášky a předpisy", r"obecne zavazn|pravni\w* predpis|narizeni|smernic"),
    ("informace", "Poskytnuté informace", r"106/1999|zadost|odpoved|sdeleni"),
]
KIND_LABEL = {k: label for k, label, _ in KINDS} | {"ostatni": "Ostatní"}


def kind(title: str, published: dt.date | None = None, valid_until: dt.date | None = None) -> str:
    t = fold(title)
    k = next((k for k, _, rx in KINDS if re.search(rx, t)), "ostatni")
    # answers to requests under the Act 106/1999 stay posted for ten years and their titles
    # are just the subject ("Průměrné platy")
    if k == "ostatni" and published and valid_until and (valid_until - published).days > 9 * 365:
        k = "informace"
    return k


def parse(doc: dict, board: Board) -> list[dict]:
    """Rows for the `notices` table from one board's OFN document. Items without a URL or a
    title are skipped (the OFN requires both)."""
    out, seen = [], set()
    for item in doc.get("informace") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("iri")
        title = _text(item.get("název"))
        if not url or not title:
            continue
        nid = notice_id(board.id, url)
        if nid in seen:
            continue
        seen.add(nid)
        department = _text(item.get("odbor")) or _text((item.get("zveřejnil") or {}).get("název")
                                                       if isinstance(item.get("zveřejnil"), dict) else None)
        reference = _text(item.get("číslo_jednací"))
        if reference and re.fullmatch(r"[xX]+", reference):   # the city's placeholder "xxx"
            reference = None
        agenda = [a for a in (_text(x.get("název")) if isinstance(x, dict) else _text(x)
                              for x in (item.get("agenda") or [])) if a]
        attachments = [{"title": _text(d.get("název")) or "Dokument", "url": d["url"]}
                       for d in item.get("dokument") or [] if isinstance(d, dict) and d.get("url")]
        published, valid_until = _date(item.get("vyvěšení")), _date(item.get("relevantní_do"))
        out.append({
            "id": nid, "board": board.id, "url": url, "title": title,
            "published": published, "valid_until": valid_until,
            "agenda": agenda, "kind": kind(title, published, valid_until), "reference": reference,
            "file_mark": _text(item.get("spisová_značka")), "department": department,
            "attachments": attachments,
            "is_mo5": board.mo5 or mentions_mo5(title, department, reference, *agenda),
        })
    return out
