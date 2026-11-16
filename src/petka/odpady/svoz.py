"""Svoz směsného komunálního odpadu by street: Služby města Pardubic's table „Harmonogram svozu
TKO ulice“ (harmonogram-svozu-tko-ulice-1665467792.xls, 11. 10. 2022; SmP still links it, so we
take it as valid). A row is a street and one or two weekdays; some rows split a street into
popelnice (the houses' bins) and kontejnery (1100 l on the housing estates), or into its parts
(„Na Drážce (od hlavních semaforů po ulici Na Okrouhlíku) – popelnice“). `parse` keeps those apart;
`match` puts each row on a street of the town by its name, abbreviations allowed („Dem. mládeže“).
"""

import re

FILE = "https://smp-pce.cz/data/files/harmonogram-svozu-tko-ulice-1665467792.xls"
DAYS = {"pondělí": "po", "úterý": "út", "středa": "st", "čtvrtek": "čt", "pátek": "pá", "sobota": "so", "neděle": "ne"}


def parse(rows: list[list]) -> list[dict]:
    """[{name, bins: popelnice|kontejnery|"", part: "", days: ["po", …], text}] of the table's rows."""
    out = []
    for r in rows:
        text = " ".join(str(r[0]).split())
        days = [DAYS[str(c).strip().lower()] for c in r[1:] if str(c).strip().lower() in DAYS]
        if not text or not days or text.lower() in ("název ulice",):
            continue
        name, part, bins = text, "", ""
        m = re.search(r"\s*[-–]?\s*(popelnice|kontejnery)\b.*$", name, re.I)
        if m:
            bins = m.group(1).lower()
            name = name[:m.start()]
        m = re.search(r"\s*\((.*)\)\s*$", name) or re.search(r"\s*\((.*)", name)
        if m:
            part, name = m.group(1).strip(" )"), name[:m.start()]
        m = re.match(r"(.*?)\s+-\s+(.*)$", name)          # „Gebauerova - část ul. se jezdí v úterý …“
        if m:
            name, part = m.group(1), (m.group(2) + (" " + part if part else "")).strip()
        out.append({"name": name.strip(" ,-"), "bins": bins, "part": part, "days": days, "text": text})
    return out


def _words(s: str) -> list[str]:
    from ..ulice.streets import fold
    return [w for w in re.split(r"[\s.]+", fold(s)) if w]


ALIASES = {"Lidimily Malé": "Lidmily Malé", "Palackého": "Palackého třída"}   # the table's spelling
# rows that are a whole part of the town (its village, no street names): the days hold for all of it
PARTS = {"DOUBRAVICE", "DRAŽKOVICE", "DROZDICE", "Hostovice", "LÁNY NA DULKU", "OPOČíNEK", "SEMTÍN", "Staročernsko", "ŽIŽÍN"}


def match(row_name: str, streets: list[str]) -> str | None:
    """The town's street a row names: the same words, a word ending in „.“ in the table a prefix
    („Dem. mládeže“ → Demokratické mládeže, „kpt. Nálepky“, „J.K.Tyla“ → Josefa Kajetána Tyla);
    words after a street's name (a part of the town: „Bělehradská Polabiny II.“) are ignored."""
    if row_name in ALIASES:
        return ALIASES[row_name]
    rw = _words(row_name)
    best = None
    for s in streets:
        sw = _words(s)
        if len(sw) > len(rw):
            continue
        if all(a == b or (len(a) <= 4 and b.startswith(a)) for a, b in zip(rw, sw)):
            if best is None or len(sw) > len(_words(best)):
                best = s
    return best
