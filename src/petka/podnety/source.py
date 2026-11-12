"""Dej Tip, the city's app for reporting problems (podněty), as its public map reads it:

    https://amg.dejtip.eu/pardubice/

The map asks one endpoint for every report of the city in a date range; there is no filter by
obvod, so we take the whole city and keep the obvod's reports by CS_MUNICODE (the RÚIAN code
of the městský obvod, obvody.Obvod.momc). Rows are positional arrays. The map's own config
(model.db.conversionArray) names 21 columns, but the answer has 23 and NOTE_DATE has no
column of its own: NOTE carries "date¦official's e-mail¦text". Positions below were checked on
the real answer on 12. 11. 2026 (3 602 rows from 2025 on), see docs/dejtip.md.

Most of a row is not ours to publish: the reporter's comment, the office's notes with an
official's e-mail, photo and admin URLs, the device and an official's login. `sanitize` keeps
only what the public map shows anyway, minus the house number, and nothing else ever leaves
this module.
"""

import datetime as dt
import json
import re

import httpx

URL = "https://amg.dejtip.eu/DbConn/handler.aspx/Database"
HOME = "https://amg.dejtip.eu/pardubice/"       # the public map; no link to one report is known
CITY = "pardubice"
TIMEOUT = httpx.Timeout(120, connect=15)       # two years of the city is ~1.3 MB, built slowly
HEADERS = {"User-Agent": "otevrena-petka (+https://otevrenapetka.cz)",
           "Content-Type": "application/json; charset=utf-8"}

# positions in a row (checked 12. 11. 2026); everything not named here is never read
ID, CATEGORY, ADDRESS, LAT, LNG, CATEGORY_ID, STATUS, DATE, MOMC = 0, 5, 6, 8, 9, 13, 17, 18, 19
WIDTH = 23

# c_status.csv on amg.dejtip.eu/upload/data/; the categories come with each row (KAT_TYPE)
STATUSES = {1: "Evidováno", 2: "V řešení", 3: "Vyřešeno", 4: "Nelze vyřídit", 5: "Chybné/nepravdivé",
            6: "Nepřísluší", 7: "Spam", 8: "Předáno", 9: "Zařazeno do plánu", 99: "Smazané"}
SKIP = {5, 7, 99}       # chybné, spam, smazané: not shown, and dropped if we had them


def request(date_from: dt.date, date_to: dt.date) -> dict:
    """The body the map sends: JSON whose `json` member is itself JSON, as a string."""
    q = {"db": {"app": "dejtip", "sql": "sql", "ins": False, "upd": False, "city": CITY,
                "monthsBack": "", "yearsBack": "", "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat()}}
    return {"json": json.dumps(q)}


def fetch(date_from: dt.date, date_to: dt.date, client: httpx.Client | None = None) -> list[list]:
    """Every report of the city filed in the range, as the raw positional rows."""
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers=HEADERS)
    try:
        r = client.post(URL, json=request(date_from, date_to), headers=HEADERS)
        r.raise_for_status()
        return parse(r.json())
    finally:
        if own:
            client.close()


def parse(answer: dict) -> list[list]:
    """{"d": "<JSON array of rows>"} -> the rows, checked for the shape `sanitize` relies on.
    A source that moved its columns must stop the job, not put a comment where a street goes."""
    rows = json.loads(answer["d"] or "[]")
    for r in rows:
        if not isinstance(r, list) or len(r) != WIDTH:
            raise ValueError(f"dejtip: a row has {len(r) if isinstance(r, list) else type(r).__name__} "
                             f"fields, expected {WIDTH}")
        if not (isinstance(r[ID], int) and isinstance(r[CATEGORY_ID], int) and isinstance(r[STATUS], int)
                and isinstance(r[MOMC], int) and isinstance(r[LAT], (int, float))
                and isinstance(r[LNG], (int, float)) and isinstance(r[DATE], str)
                and re.fullmatch(r"\d\d\.\d\d\.\d{4} \d\d:\d\d", r[DATE])):
            raise ValueError(f"dejtip: row {r[ID]!r} doesn't have the expected columns")
    return rows


# "Pardubice, Na Záboří 223, Pardubice, 53002, Nové Jesenčany": town, street + number, post
# town, PSČ, part of town. Without a street the second part is only a number ("Pardubice,  99, …").
_ADDRESS = re.compile(r"^[^,]+, ([^,]*), [^,]+, \d{5}, [^,]+$")
_NUMBER = re.compile(r"\s+\d+[a-zA-Z]?(?:/\d+[a-zA-Z]?)?$")


def street(address: str | None) -> str | None:
    """The street of a Dej Tip address, without the house number; None when the address
    isn't a street address or isn't in the shape above (then we know nothing safe about it)."""
    m = _ADDRESS.match((address or "").strip())
    if not m:
        return None
    name = _NUMBER.sub("", m[1]).strip()
    return name if re.search(r"[^\W\d_]", name) else None


def sanitize(row: list) -> dict:
    """The only fields of a row we keep: id, category, status, date, position, street and
    the obvod's code."""
    return {"id": row[ID], "category_id": row[CATEGORY_ID], "category": (row[CATEGORY] or "").strip(),
            "status": row[STATUS], "reported_at": dt.datetime.strptime(row[DATE], "%d.%m.%Y %H:%M"),
            "lat": float(row[LAT]), "lng": float(row[LNG]), "street": street(row[ADDRESS]),
            "momc": row[MOMC]}


def reports(rows: list[list], momc: int) -> tuple[list[dict], list[int]]:
    """The obvod's reports to keep, sanitized, and the ids of its reports to drop (SKIP)."""
    keep, drop = [], []
    for r in rows:
        if r[MOMC] != momc:
            continue
        if r[STATUS] in SKIP:
            drop.append(r[ID])
        else:
            keep.append(sanitize(r))
    return keep, drop
