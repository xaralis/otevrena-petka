"""Separační (sběrné) dvory of the town from Služby města Pardubic: the Word file „Seznam
separačních dvorů a otevírací doby“ linked from https://smp-pce.cz/odpady/separacni-dvory (its
name carries a stamp that changes with each version).

The file is Word 97 (.doc), so its text is read from the piece table (`doc_text`, no external
tool). Its table rows are cells ending in BEL (\\x07); a yard's row is „place | days | from | to“,
where one cell may hold two lines (two rules: „po, út, čt, pá\\rst“ with „6.30\\r6.30“ and
„15.00\\r17.00“). Below it, what each yard takes („všechny SD mimo Polabiny“) is turned into each
yard's exceptions.
"""

import io
import re
import struct
from dataclasses import asdict, dataclass, field

PAGE = "https://smp-pce.cz/odpady/separacni-dvory"
LINK = re.compile(r'href="(/data/files/seznam-separacnich-dvoru[^"?]*\.doc)')
DAYS = ("po", "út", "st", "čt", "pá", "so", "ne")


def doc_text(data: bytes) -> str:
    """The text of a Word 97–2003 file: its pieces (CLX in the table stream), 8-bit or UTF-16."""
    import olefile
    ole = olefile.OleFileIO(io.BytesIO(data))
    wd = ole.openstream("WordDocument").read()
    flags = struct.unpack_from("<H", wd, 0x0A)[0]
    table = ole.openstream("1Table" if flags & 0x0200 else "0Table").read()
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    while clx[i] == 0x01:                       # Prc (formatting): skipped
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if clx[i] != 0x02:
        raise ValueError("no piece table")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    out = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        length = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            off = (fc & 0x3FFFFFFF) // 2
            out.append(wd[off:off + length].decode("cp1252", "replace"))
        else:
            out.append(wd[fc:fc + 2 * length].decode("utf-16-le", "replace"))
    return "".join(out)


@dataclass
class Yard:
    key: str                        # dvur-<slug of the place's first word>
    name: str                       # „Dražkovice“, „Na Staré poště“
    address: str                    # what follows: „areál překladiště odpadu“, „č.p. 2903“
    place: str                      # the file's whole text of the place
    hours: list[dict] = field(default_factory=list)     # [{days: ["po", …], from: "6:30", to: "15:00"}]
    takes_not: list[str] = field(default_factory=list)  # kinds of waste it does not take
    only_here: list[str] = field(default_factory=list)  # kinds only this yard takes


def _time(t: str) -> str:
    h, m = (t.strip().replace(",", ".").split(".") + ["00"])[:2]
    return f"{int(h)}:{m.zfill(2)[:2]}"


def _days(s: str) -> list[str]:
    out = []
    for part in re.split(r"[,\s]+", s.strip().lower()):
        m = re.fullmatch(r"(po|út|st|čt|pá|so|ne)\s*[–-]\s*(po|út|st|čt|pá|so|ne)", part)
        if m:
            a, b = DAYS.index(m.group(1)), DAYS.index(m.group(2))
            out += list(DAYS[a:b + 1])
        elif part in DAYS:
            out.append(part)
    return out


def _slug(s: str) -> str:
    from ..ulice.streets import fold
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")


def _split(place: str) -> tuple[str, str]:
    """„Dražkovice, areál překladiště odpadu“ → („Dražkovice“, „areál překladiště odpadu“)."""
    name, _, rest = place.partition(",")
    return name.strip(), rest.strip()


def parse(text: str) -> list[Yard]:
    """The yards and their hours from the file's text; what they take from its table above."""
    cells = [c.strip() for c in text.replace("\r\x07", "\x07").split("\x07")]
    try:
        start = next(i for i, c in enumerate(cells) if "Umístění separačních dvorů" in c)
    except StopIteration:
        raise ValueError("no table of the yards") from None
    yards, i = [], start
    while i < len(cells) - 3:
        place, days, fr, to = cells[i:i + 4]
        lines = [x.strip() for x in days.split("\r") if x.strip()]
        froms = [x.strip() for x in fr.split("\r") if x.strip()]
        tos = [x.strip() for x in to.split("\r") if x.strip()]
        if place and lines and len(lines) == len(froms) == len(tos) and all(re.match(r"\d", x) for x in froms + tos):
            name, address = _split(place)
            yards.append(Yard(f"dvur-{_slug(name)}", name, address, place,
                              [{"days": _days(d), "from": _time(a), "to": _time(b)} for d, a, b in zip(lines, froms, tos)]))
            i += 4
        else:
            i += 1
    if not yards:
        raise ValueError("no yard found")
    _takes(cells, yards)
    return yards


def _takes(cells: list[str], yards: list[Yard]) -> None:
    """„pneumatiky … | všechny SD mimo Polabiny a Pardubičky“, „eternit … | pouze SD Dražkovice“."""
    for what, where in zip(cells, cells[1:]):
        w = where.lower()
        what = re.sub(r"\s*\(.*?\)\s*", " ", what).strip(" ,")
        if w.startswith("všechny sd mimo"):
            for y in yards:
                if any(y.name.split(",")[0].split()[0].lower() in part for part in re.split(r",| a ", w[len("všechny sd mimo"):])):
                    y.takes_not.append(what)
        elif w.startswith("pouze sd"):
            for y in yards:
                if y.name.split()[0].lower() in w:
                    y.only_here.append(what)


def as_json(yards: list[Yard]) -> list[dict]:
    return [asdict(y) for y in yards]
