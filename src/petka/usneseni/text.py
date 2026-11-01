"""Text helpers shared by the parser, name matching and search."""

import re
import unicodedata

# Academic titles that appear before or after names in the minutes ("Ing. Filip Vařecha",
# "Jiří Rejda, DiS.", "Mgr. Miloš Adamů, MBA."). Matching ignores them.
TITLES = {
    "bc", "bca", "ing", "ing. arch", "mgr", "mga", "judr", "mudr", "mvdr", "phdr", "rndr",
    "paeddr", "pharmdr", "thdr", "doc", "prof", "dis", "mba", "phd", "ph.d", "csc", "drsc",
    "lic", "llm", "ll.m", "msc", "dr", "arch", "dipl", "th.d", "ba", "mpa", "dba", "lic",
}


def fold(s: str) -> str:
    """Lowercase without diacritics; the key for accent-insensitive matching."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")


def ws(s: str) -> str:
    """Collapse all whitespace to single spaces (for substring checks against PDF text)."""
    return re.sub(r"\s+", " ", s).strip()


def strip_titles(name: str) -> list[str]:
    """'Ing. Lic. Jaroslav Kňava' -> ['Jaroslav', 'Kňava']; 'Ing. F. Vařecha' -> ['F.', 'Vařecha']."""
    parts = re.split(r"[\s,]+", name.strip())
    out = []
    for p in parts:
        if not p:
            continue
        key = fold(p).rstrip(".")
        if key in TITLES or fold(p) in TITLES:
            continue
        out.append(p)
    return out


PAGE_FOOTER = re.compile(r"^Stránka\s+\d+\s+z\s+\d+$")


def clean_block(lines: list[str]) -> str:
    """Turn a slice of `pdftotext -layout` lines into readable text.

    Layout mode keeps centring and hanging indents; we drop the indentation, keep line
    breaks before list items (1., a), -, •) and unwrap everything else into paragraphs.
    """
    out: list[str] = []
    for raw in lines:
        line = raw.strip()
        if PAGE_FOOTER.match(line):
            continue
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        starts_item = bool(re.match(r"^([0-9]+\.|[a-z]\)|[IVX]+\.|[-–•\uf0b7])\s", line))
        if out and out[-1] != "" and not starts_item:
            prev = out[-1]
            if prev.endswith("-") and not prev.endswith(" -"):
                out[-1] = prev + line  # "Pardubice-" + "Polabiny": keep the hyphen
            else:
                out[-1] = prev + " " + line
        else:
            out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out).replace("\uf0b7", "•")
