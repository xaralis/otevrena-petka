"""The harmonogram of blokové čištění from Služby města Pardubic (SmP), as their page links it:

    https://smp-pce.cz/udrzba-komunikaci/cisteni-komunikaci

The page links one Excel for the whole city whose file name carries a timestamp
("harmonogram-blokoveho-cisteni-a-strojniho-cisteni-s-dz-1775820984.xlsx"), so we find it by
pattern. The first sheet has a header row and then one row per cleaning:
Typ čištění (BLK), Datum čištění, Čas čištění ("Blokové čištění od 7:00 hod."), Den and Týden
(formulas), Místo (free text). Checked on 12. 11. 2026: 711 rows of 2026.

What the sheet gets wrong, and how `clean` mends it:
- a long Místo spills into the next row, which then has no date: appended to the row above;
- a row without date that is not right below one ("Blokové čištění vybraných lokalit …") is a
  heading, dropped;
- a date with a year that doesn't fit its neighbours (2025 inside 2026) takes their year;
- times come as "od 7:00 hod.", "od 6:00hod", "od 6:00 hod.ou", "před 6 hod.".
"""

import datetime as dt
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

PAGE = "https://smp-pce.cz/udrzba-komunikaci/cisteni-komunikaci"
HOME = PAGE
TIMEOUT = httpx.Timeout(60, connect=15)
HEADERS = {"User-Agent": "otevrena-petka (+https://otevrenapetka.cz)"}
LINK = re.compile(r'href="([^"]*harmonogram-blokoveho-cisteni[^"]*\.xlsx[^"]*)"', re.I)
TIME = re.compile(r"(před|od)\s*(\d{1,2})(?::(\d\d))?\s*h", re.I)


@dataclass
class Row:
    row: int                    # row number in the sheet (the first data row is 2)
    date: dt.date | None
    when: str                   # "Čas čištění" as written
    place: str                  # Místo, whitespace normalised
    time: dt.time | None = None
    before: bool = False        # "před 6 hod.": done before that time, not from it
    merged: list[int] = field(default_factory=list)   # continuation rows appended to this one
    year_fixed: bool = False


def excel_url(html: str, base: str = PAGE) -> str:
    """The harmonogram's Excel linked from the page (the first link that looks like it)."""
    m = LINK.search(html)
    if not m:
        raise ValueError("smp-pce.cz: no harmonogram Excel linked on the page")
    return urljoin(base, m[1].replace("&amp;", "&"))


def fetch(client: httpx.Client) -> tuple[str, bytes]:
    """(url, bytes) of the current Excel."""
    r = client.get(PAGE)
    r.raise_for_status()
    url = excel_url(r.text, str(r.url))
    x = client.get(url)
    x.raise_for_status()
    return url, x.content


def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("\xa0", " ")).strip()


def _date(v) -> dt.date | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)):         # a bare Excel serial
        return (dt.datetime(1899, 12, 30) + dt.timedelta(days=v)).date()
    return None


def parse(xlsx: bytes) -> list[Row]:
    """The sheet's rows as written (not cleaned). Refuses a sheet whose header moved: a Místo
    must not end up where a date goes."""
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    head = [norm(h).lower() for h in next(rows, ())[:6]]
    if len(head) < 6 or not (head[1].startswith("datum") and head[2].startswith("čas") and head[5] == "místo"):
        raise ValueError(f"smp-pce.cz: unexpected header {head!r}")
    out = []
    for i, r in enumerate(rows, start=2):
        r = tuple(r) + (None,) * (6 - len(r))
        typ, d, when, _, _, place = r[:6]
        if not any((typ, d, when, place)):
            continue
        out.append(Row(i, _date(d), norm(when), norm(place)))
    return out


def parse_time(when: str) -> tuple[dt.time | None, bool]:
    """'Blokové čištění od 7:00 hod.' -> (7:00, False); 'před 6 hod.' -> (6:00, True)."""
    m = TIME.search(when or "")
    if not m:
        return None, False
    return dt.time(int(m[2]), int(m[3] or 0)), m[1].lower() == "před"


def clean(rows: list[Row]) -> tuple[list[Row], list[tuple]]:
    """Rows with a date, continuation rows merged, years mended, times parsed; and the issues
    found ((kind, row, detail), for the job's report)."""
    out, issues = [], []
    for r in rows:
        if r.date is None:
            prev = out[-1] if out else None
            if prev and (prev.merged or [prev.row])[-1] == r.row - 1 and r.place \
                    and not r.place.lower().startswith("blokové čištění"):
                prev.place = (prev.place.rstrip(" ,") + " " + r.place).strip()
                prev.merged.append(r.row)
                issues.append(("continuation", r.row, r.place))
            else:
                issues.append(("dropped", r.row, r.place or r.when))
            continue
        if not r.place:
            issues.append(("dropped", r.row, "no place"))
            continue
        out.append(Row(r.row, r.date, r.when, r.place))
    # the year most rows have; a stray year (2025 inside 2026) takes it
    year = Counter(r.date.year for r in out).most_common(1)[0][0] if out else None
    for r in out:
        if r.date.year != year:
            try:
                fixed = r.date.replace(year=year)
            except ValueError:          # 29. 2. into a year without it
                fixed = r.date.replace(year=year, day=28)
            issues.append(("year", r.row, f"{r.date.isoformat()} -> {fixed.isoformat()}"))
            r.date, r.year_fixed = fixed, True
        r.time, r.before = parse_time(r.when)
    return out, issues
