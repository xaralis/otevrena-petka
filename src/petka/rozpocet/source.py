"""The city's rozklikávací rozpočet (GORDIC, SQL Server Reporting Services over GINIS):

    https://rozpocet.pardubice.eu/gordic/Rozpocet/

It covers the Magistrát and every district, years 2018 on, current to the day ("Stav ke
dni"). A district is chosen by a pseudo-IČO derived from the city's: MO V = 05274046. Each
report is addressable directly and exports to Excel with the whole tree expanded (the web page
only shows the top level until rows are clicked, which is why people "can't get past the
overview"). CSV and XML export are switched off (404).

Getting the Excel takes a ReportViewer session:
  1. GET default.aspx?report=…  (session cookie, ASP.NET form fields, ExportUrlBase)
  2. POST the form back as the async load the viewer's JavaScript would send (renders it)
  3. GET ExportUrlBase + "EXCELOPENXML" with the same cookies

Amounts in every report are thousands of Kč with two decimals; we keep them as they are.

Reports used (all for one unit and year):
  RROZROZK0023     rekapitulace: příjmy, výdaje, financování × schváleno/upraveno/skutečnost
  RROZROZK0001_Va  výdaje podle odvětví (the overview on the site)
  RROZROZK0018     faktury podle položky – only to tell položky from paragrafy in 0019
  RROZROZK0019     faktury podle skupin a paragrafů: skupina → paragraf → položka → faktura
  RROZROZK0032     výdaje dle odborů: odbor → paragraf → položka × schváleno/upraveno/skutečnost
                   (the menu calls it "Kapitoly rozpočtu"; names only, no codes)
Others (0002 paragrafy v odvětví, 0005–0010, 0020–0022, 0025) are listed in
docs/rozpocet-reserse.md.
"""

import datetime as dt
import functools
import io
import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import httpx
import openpyxl

from ..usneseni.text import fold

BASE = "https://rozpocet.pardubice.eu/gordic/Rozpocet/"
REPORT = BASE + "default.aspx?report=/Gordic/S00B/UCR/ROZ/"
SITE = "https://rozpocet.pardubice.eu"
FIRST_YEAR = 2018

# unit -> GORDIC pseudo-IČO; the Magistrát has the city's real one
UNITS = {"mmp": "00274046", **{f"mo{i}": f"0{i}274046" for i in range(1, 9)}}
NAMES = {"mmp": "Magistrát města Pardubic",
         **{f"mo{i}": f"Městský obvod Pardubice {r}" for i, r in
            enumerate(["I", "II", "III", "IV", "V", "VI", "VII", "VIII"], 1)}}

REPORTS = {
    "rekapitulace": ("RROZROZK0023", ""),
    "odvetvi": ("RROZROZK0001_Va", "&Odpa=(1=1)"),
    "polozky": ("RROZROZK0018", ""),
    "faktury": ("RROZROZK0019", ""),
    "odbory": ("RROZROZK0032", ""),
}

TIMEOUT = httpx.Timeout(120, connect=15)       # the server renders reports slowly
HEADERS = {"User-Agent": "otevrena-petka (+https://otevrenapetka.cz)"}
PAUSE = 2.0                                     # seconds between reports; it's the city's server
XLSX = b"PK\x03\x04"
CISELNIK = Path(__file__).resolve().parents[3] / "data" / "rozpocet" / "ciselnik.json"


def page_url(unit: str) -> str:
    """The unit's budget for people (the overview the site opens with)."""
    return f"{BASE}index_MC.html?Ico={UNITS[unit]}"


def report_url(report: str, unit: str, year: int) -> str:
    code, extra = REPORTS[report]
    return f"{REPORT}{code}&Ico={UNITS[unit]}&Rok={year}&nazO={NAMES[unit]}&nazU={extra}"


class _Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name") and a.get("type") not in ("submit", "image", "button"):
            self.fields[a["name"]] = a.get("value") or ""


def fetch(report: str, unit: str, year: int, client: httpx.Client | None = None) -> bytes:
    """The report as an .xlsx; raises when the server answers with anything else."""
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS)
    try:
        client.cookies.clear()                  # one ReportViewer session per report
        r = client.get(report_url(report, unit, year))
        r.raise_for_status()
        m = re.search(r'"ExportUrlBase":"([^"]+)"', r.text)
        if not m:
            raise RuntimeError(f"{report} {unit} {year}: no ExportUrlBase in the viewer page")
        form = _Form()
        form.feed(r.text)
        target = "ReportViewer1$ctl09$Reserved_AsyncLoadTarget"
        data = {**form.fields, "ScriptManager1": f"ScriptManager1|{target}",
                "__EVENTTARGET": target, "__EVENTARGUMENT": "", "__ASYNCPOST": "true"}
        client.post(str(r.url), data=data,
                    headers={"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest"}
                    ).raise_for_status()
        x = client.get(SITE + m.group(1).replace("\\u0026", "&") + "EXCELOPENXML")
        x.raise_for_status()
        if not x.content.startswith(XLSX):
            raise RuntimeError(f"{report} {unit} {year}: export is not an xlsx "
                               f"({x.headers.get('content-type')}, {len(x.content)} B)")
        return x.content
    finally:
        if own:
            client.close()


def fetch_all(unit: str, year: int, client: httpx.Client | None = None) -> dict[str, bytes]:
    out = {}
    for i, report in enumerate(REPORTS):
        if i:
            time.sleep(PAUSE)
        out[report] = fetch(report, unit, year, client)
    return out


# --- parsing --------------------------------------------------------------------------------

@dataclass
class Cell:
    col: int
    value: object
    bold: bool


def rows(xlsx: bytes) -> list[list[Cell]]:
    """Non-empty cells of the first sheet, row by row. SSRS lays the report out on a grid of
    merged cells, so a column letter means "indent level", not a field."""
    ws = openpyxl.load_workbook(io.BytesIO(xlsx)).active
    out = []
    for r in ws.iter_rows():
        cells = [Cell(c.column, c.value.strip() if isinstance(c.value, str) else c.value,
                      bool(c.font and c.font.b))
                 for c in r if c.value is not None and c.value != ""]
        if cells:
            out.append(cells)
    return out


def as_of(rs: list[list[Cell]]) -> dt.date:
    for r in rs[:5]:
        for c in r:
            m = re.match(r"Stav ke dni (\d{1,2})\.(\d{1,2})\.(\d{4})", str(c.value))
            if m:
                return dt.date(int(m[3]), int(m[2]), int(m[1]))
    raise ValueError("no 'Stav ke dni' in the report header")


def _nums(r: list[Cell]) -> list[float]:
    return [float(c.value) for c in r if isinstance(c.value, (int, float)) and not isinstance(c.value, bool)]


def _after(rs: list[list[Cell]], header: str) -> list[list[Cell]]:
    for i, r in enumerate(rs):
        if isinstance(r[0].value, str) and r[0].value.startswith(header):
            return rs[i + 1:]
    raise ValueError(f"no '{header}' header in the report")


def parse_rekapitulace(xlsx: bytes) -> list[dict]:
    """[{kind: prijmy|vydaje|financovani, approved, revised, actual}]"""
    kinds = {"Příjmy": "prijmy", "Výdaje": "vydaje", "Financování": "financovani"}
    out = []
    for r in rows(xlsx):
        if isinstance(r[0].value, str) and r[0].value in kinds:
            n = _nums(r)
            out.append({"kind": kinds[r[0].value], "approved": n[0], "revised": n[1], "actual": n[2]})
    if len(out) != 3:
        raise ValueError(f"rekapitulace: expected 3 rows, got {len(out)}")
    return out


def parse_odvetvi(xlsx: bytes) -> list[dict]:
    """[{sector, approved, revised, actual}]; checked against the CELKEM row."""
    out, total = [], None
    for r in _after(rows(xlsx), "ODVĚTVÍ"):
        if not isinstance(r[0].value, str):
            continue
        n = _nums(r)
        if r[0].value == "CELKEM":
            total = n
            break
        out.append({"sector": r[0].value, "approved": n[0], "revised": n[1], "actual": n[2]})
    if total is None:
        raise ValueError("odvětví: no CELKEM row")
    for i, k in enumerate(("approved", "revised", "actual")):
        s = sum(x[k] for x in out)
        if abs(s - total[i]) > 0.01 * len(out) + 0.01:
            raise ValueError(f"odvětví: {k} rows sum to {s:.2f}, CELKEM says {total[i]:.2f}")
    return out


CODE = re.compile(r"^(\d{1,4}) - (.+)$")


def item_codes(xlsx: bytes) -> set[tuple[int, str]]:
    """(code, name) of every položka in RROZROZK0018 (faktury podle položky)."""
    out = set()
    for r in _after(rows(xlsx), "POLOŽKA"):
        m = CODE.match(str(r[0].value))
        if m and len(m[1]) == 4:
            out.add((int(m[1]), m[2].strip()))
    return out


def parse_faktury(xlsx: bytes, items: set[tuple[int, str]]) -> list[dict]:
    """RROZROZK0019 flattened: one row per invoice with its skupina, paragraf and položka.

    Paragraf and položka rows look the same (four digits, a name, same column, not bold), so
    `items` (from RROZROZK0018 of the same year) tells them apart: a code row that is one of
    the year's položky is a položka, anything else a paragraf. Right after a paragraf there
    must be a položka – a check that the two reports agree. Invoices are summed per skupina
    and compared with the skupina's total."""
    out: list[dict] = []
    group = para = item = None
    totals: dict[int, float] = {}
    last = None                                   # kind of the previous row
    for r in _after(rows(xlsx), "SKUPINA / PARAGRAF / POLOŽKA"):
        text = r[0].value if isinstance(r[0].value, str) else None
        m = CODE.match(text) if text else None
        if m and len(m[1]) == 1 and r[0].bold:
            group = (int(m[1]), m[2].strip())
            totals[group[0]] = _nums(r)[0]
            para = item = None
            last = "group"
        elif m and len(m[1]) == 4 and not _nums(r):
            code = (int(m[1]), m[2].strip())
            if code in items:
                if para is None:
                    raise ValueError(f"faktury: položka {code} outside a paragraf")
                item, last = code, "item"
            else:
                if last == "para":
                    raise ValueError(f"faktury: paragraf {para} followed by {code}, not a položka")
                para, item, last = code, None, "para"
        elif _nums(r):                            # an invoice; a few have no description
            if group is None or para is None or item is None:
                raise ValueError(f"faktury: invoice {text!r} outside a položka")
            out.append({"group": group[0], "group_name": group[1], "paragraph": para[0],
                        "paragraph_name": para[1], "item": item[0], "item_name": item[1],
                        "description": re.sub(r"\s+", " ", text or ""), "amount": _nums(r)[0]})
            last = "invoice"
    for g, total in totals.items():
        s = sum(x["amount"] for x in out if x["group"] == g)
        if abs(s - total) > 0.015:
            raise ValueError(f"faktury: skupina {g} invoices sum to {s:.2f}, report says {total:.2f}")
    return out


def parse_odbory(xlsx: bytes) -> list[dict]:
    """RROZROZK0032 flattened: one row per položka with its odbor and paragraf, each with
    schváleno / upraveno / skutečnost.

    Odbor rows are bold (the first one has no name in the export). Paragraf and položka rows
    look the same and carry names only, so the tree is rebuilt from the sums: the first row
    under an odbor is a paragraf, the rows after it are its položky until they add up to it
    in all three columns, then the next row is a paragraf again. Each odbor is checked against
    the sum of its paragrafy."""
    keys = ("approved", "revised", "actual")
    out: list[dict] = []
    dept = para = None
    acc = [0.0, 0.0, 0.0]
    done = True                                   # the current paragraf has all its položky

    def close_dept():
        if dept is None:
            return
        for i, k in enumerate(keys):
            s = sum(p[k] for p in dept["paras"])
            if abs(s - dept["vals"][i]) > 0.005 * len(dept["paras"]) + 0.01:
                raise ValueError(f"odbory: {dept['name']!r} {k} paragrafy sum to {s:.2f}, "
                                 f"odbor says {dept['vals'][i]:.2f}")

    for r in _after(rows(xlsx), "ODBOR \\ ODPA \\ POL"):
        name = r[0].value if isinstance(r[0].value, str) else None
        n = _nums(r)
        if len(n) < 3:
            continue
        vals = n[:3]
        if r[0].bold:
            if not done:
                raise ValueError(f"odbory: paragraf {para['name']!r} položky don't add up")
            close_dept()
            dept = {"name": name, "vals": vals, "paras": []}
            done = True
            continue
        if dept is None:
            raise ValueError(f"odbory: {name!r} before the first odbor")
        if done:
            para = {"name": name, **dict(zip(keys, vals))}
            dept["paras"].append(para)
            acc, done = [0.0, 0.0, 0.0], False
            continue
        acc = [a + v for a, v in zip(acc, vals)]
        out.append({"department": dept["name"], "paragraph_name": para["name"], "item_name": name,
                    **dict(zip(keys, vals))})
        done = all(abs(a - p) < 0.005 for a, p in zip(acc, (para[k] for k in keys)))
    if not done:
        raise ValueError(f"odbory: paragraf {para['name']!r} položky don't add up")
    close_dept()
    return out


# --- names back to codes --------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", fold(text))


@functools.cache
def _codelist(kind: str) -> list[tuple[int, list[str], str, str]]:
    data = json.loads(CISELNIK.read_text())
    return [(code, _tokens(name), start, end) for code, name, start, end in data[kind]]


def code_for(name: str | None, kind: str, year: int) -> int | None:
    """The paragraf (kind="paragraf") or výdajová položka (kind="polozka") a GORDIC name stands
    for in `year`, or None when it isn't one exactly. GORDIC cuts names at 50 characters and
    abbreviates words ("ost. odpadů jiných než nebez."), so the tiers are: same words, the
    official name starts with these words, every word is a prefix of the official one. The
    first tier with a single answer wins."""
    if not name:
        return None
    n = _tokens(name)
    first, last = f"{year}-12-31", f"{year}-01-01"
    cands = [(c, t) for c, t, start, end in _codelist(kind)
             if start <= first and end >= last and (kind != "polozka" or c >= 5000)]
    for test in (lambda t: t == n,
                 lambda t: t[:len(n)] == n,
                 lambda t: len(t) >= len(n) and all(a.startswith(b) for a, b in zip(t, n))):
        hits = {c for c, t in cands if test(t)}
        if len(hits) == 1:
            return hits.pop()
        if hits:
            return None
    return None


@functools.cache
def _names(kind: str) -> dict[int, str]:
    """Code -> official name from the MF codelist (the latest valid entry)."""
    data = json.loads(CISELNIK.read_text())
    out: dict[int, str] = {}
    for code, name, start, end in sorted(data[kind], key=lambda r: r[2]):
        out[code] = name
    return out


def official(kind: str, code) -> str | None:
    """The full official name of a paragraf / položka (GORDIC shortens and truncates them)."""
    try:
        return _names(kind).get(int(code))
    except (TypeError, ValueError):
        return None
