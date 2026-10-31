"""Index of published resolution PDFs on pardubice.eu for ZMO and RMO Pardubice V.

The landing pages link one page per year; year slugs are irregular (`/zmo5-2026`,
`/2019-548`, `/2023-3185`), so they are always read from the landing page. Each year page
lists `a.document-Card` links whose title carries the meeting number, kind and date:
"Usnesení z 20. řádného jednání ZMO Pardubice V ze dne 17.12.2025".
"""

import hashlib
import html
import datetime as dt
import re
from dataclasses import dataclass

import httpx

BASE = "https://pardubice.eu"
LANDING = {"zmo": "/zapisy-z-jednani-zmo5", "rmo": "/zapisy-z-jednani-rmo5"}
UA = "usneseni-mo5 (+https://github.com/xaralis/usneseni-mo5)"

_YEAR_LINK = re.compile(
    r'<a href="(/[^"]+)"\s+class="LinkCell-inner[^"]*">\s*'
    r'<span class="LinkCell-title">(\d{4})[^<]*</span>')
_CARD = re.compile(r'<a([^>]*class="document-Card[^"]*"[^>]*)>(.*?)</a>', re.S)
_TITLE = re.compile(r'document-Card-title">(.*?)</span>', re.S)
_MEETING = re.compile(
    r"(?P<num>\d+)\.\s*(?:(?P<kind>řádné|mimořádné|ustavující)\w*\s+)?(?:jednání|zasedání)"
    r".*?ze dne\s+(?P<d>\d{1,2})\.\s*(?P<m>\d{1,2})\.\s*(?P<y>\d{4})", re.I | re.S)


@dataclass
class Document:
    body: str          # zmo | rmo
    year: int          # year page it was listed on
    url: str
    title: str
    number: int | None = None
    kind: str | None = None   # radne | mimoradne | ustavujici
    date: dt.date | None = None
    is_attachment: bool = False

    @property
    def meeting_id(self) -> str | None:
        if self.number is None or self.date is None:
            return None
        return f"{self.body}-{self.date:%Y-%m-%d}-{self.number}"


def parse_title(title: str) -> dict:
    out: dict = {"is_attachment": bool(re.match(r"\s*Příloh", title, re.I))}
    m = _MEETING.search(title)
    if m:
        kind = (m["kind"] or "").lower()
        out.update(number=int(m["num"]),
                   kind={"řádné": "radne", "mimořádné": "mimoradne",
                         "ustavující": "ustavujici"}.get(kind),
                   date=dt.date(int(m["y"]), int(m["m"]), int(m["d"])))
    return out


def client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True)


def index(http: httpx.Client) -> list[Document]:
    docs: list[Document] = []
    for body, landing in LANDING.items():
        page = http.get(BASE + landing).text
        years = _YEAR_LINK.findall(page)
        if not years:
            raise RuntimeError(f"no year links on {landing} – page layout changed?")
        for href, year in years:
            ypage = http.get(BASE + href).text
            for attrs, inner in _CARD.findall(ypage):
                h = re.search(r'href="([^"]+)"', attrs)
                t = _TITLE.search(inner)
                if not h or not t:
                    continue
                url = h.group(1)
                url = BASE + url if url.startswith("/") else url
                title = html.unescape(re.sub(r"\s+", " ", t.group(1))).strip()
                docs.append(Document(body=body, year=int(year), url=url, title=title,
                                     **parse_title(title)))
    return docs


def download(http: httpx.Client, url: str) -> tuple[bytes, str]:
    r = http.get(url)
    r.raise_for_status()
    return r.content, hashlib.sha256(r.content).hexdigest()
