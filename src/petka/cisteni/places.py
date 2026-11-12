"""A Místo of the harmonogram as text: its key, which side of the road, what kind of place it
is, and a short wording for lists.

The key is the normalised text (folded, dashes unified, abbreviation dots spaced): the same
place written with other spacing or case is one place; a place written differently is another
(left and right side are different places, cleaned on different days).
"""

import re
import unicodedata


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def key(s: str) -> str:
    """Folded, dashes unified, a space after every abbreviation dot, single spaces."""
    s = fold(s.replace("\xa0", " "))
    s = re.sub(r"[–—−‐]", "-", s)
    s = re.sub(r"\.(?=[^\s.,])", ". ", s)
    return re.sub(r"\s+", " ", s).strip()


def place_key(text: str) -> str:
    k = key(text)
    k = re.sub(r"c\. ?p\. ?", "c. p. ", k)
    k = re.sub(r"\bul\. ?", "ul. ", k)
    return re.sub(r"\s+", " ", k).strip(" ,-")


# the side of the road at the end of a key ("- obě strany komunikace", "pravá strana")
SIDE = re.compile(r"[-,]?\s*(obe|obou|prava|leva) (strany|strana|stran|cast)[^,]*$"
                  r"|[-,]?\s*obe strany komunikace.*$")


def side(k: str) -> tuple[str | None, str]:
    """(obe|prava|leva|None, the key without the side suffix)."""
    m = SIDE.search(k)
    if not m:
        return None, k
    s = m[0]
    return ("prava" if "prav" in s else "leva" if "lev" in s else "obe"), k[:m.start()].strip(" ,-")


# what a place is, from its key; the first match wins
PATTERNS = [
    ("vnitroblok", r"vnitroblo"),
    ("mezi ulicemi", r"\bmezi (ul\.|ulic)"),
    ("usek od-k", r"\bod\b.*\b(k|po|ke|do)\b"),
    ("jen od", r"\bod\b"),
    ("plocha u c. p.", r"(parkovist|plocha|komunikace).*\b(pred|za|u|podel|mezi)\b.*c\. p\."),
    ("u c. p.", r"c\. p\. \d"),
    ("plocha", r"parkovist|tocn|plocha"),
    ("pojmenovane misto", r"\b(nam\.|namesti|nabrezi|sidliste|areal|park|most)\b"),
    ("cela ulice", r"^[^\d]*$"),
]


def pattern(k: str) -> str:
    for name, rx in PATTERNS:
        if re.search(rx, k):
            return name
    return "jine"


SIDE_TEXT = {"obe": "obě strany", "prava": "pravá strana", "leva": "levá strana"}


def short(text: str, street: str | None) -> str:
    """The Místo shortened for lists, after the street's name: 'Milheimova od ul. V Ráji k ul.
    Pražská - pravá strana komunikace' -> 'od V Ráji k Pražská, pravá strana'. Names stay in
    the case the harmonogram uses; the street page shows the original wording."""
    s = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    if street:
        # the name as written may differ in spaces, dots and hyphens ("Boženy Vikové Kunětické");
        # fold() keeps the length of Czech text, so a match on it cuts the original
        words = re.findall(r"\w+", fold(street))
        m = re.match(r"[\s.\-]*".join(map(re.escape, words)) + r"\b", fold(s))
        if m:
            s = s[m.end():]
    # "od ul. Lexova" -> "od Lexova"; "v ul. Wolkerova" keeps it
    s = re.sub(r"(?i)\b(od|k|ke|po|do|mezi|a|z|ze|s|se)\s+(?:ul\.?|ulice|ulic)(?=\s|\w)\s*", r"\1 ", s)
    s = re.sub(r"č\. ?p\. ?(?=\d)", "č. p. ", s)
    s = re.sub(r"(?<=\w)\.(?=[^\W\d_])", ". ", s)       # "Čs.armády"
    s = re.sub(r"(?i)\s*[-–,]?\s*(obě|obou) stran[ay]?(?: komunikace)?", ", obě strany", s)
    s = re.sub(r"(?i)\s*[-–,]?\s*(pravá|levá) strana(?: komunikace)?", lambda m: f", {m[1].lower()} strana", s)
    s = re.sub(r"\bk (?=[KkGg])", "ke ", s)                # "k K Blahobytu" -> "ke K Blahobytu"
    s = re.sub(r"\bvč\.\s*", "včetně ", s)
    s = re.sub(r"\s+[-–]\s+", ", ", s)
    s = re.sub(r"\s*,\s*,?", ", ", s)
    s = s.strip(" ,-–")
    if not s or s.lower() in ("obě strany", "pravá strana", "levá strana"):
        s = "v celé délce" + (", " + s if s else "")
    return s
