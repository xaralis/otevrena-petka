"""Links between resolutions: one resolution revoking (rušící) or amending an earlier one.

Extracted deterministically from the verbatim text, e.g.
  "ruší své usnesení č. 248/2022 R ze dne 6. 1. 2022"
  "revokuje usnesení č. 39/2023 R, bod 6, 16 a 17 ze dne 15. 3. 2023"
  "ruší části 2. a 3. usnesení č. 31/2023 R"
  "revokuje dnem 21.12.2022 usnesení č. 3/2022 Z, v části volby členů kontrolního výboru …"
A link only takes effect when the revoking resolution itself passed – a numbered resolution
can be voted down, and so can a counter-proposal to revoke something.
"""

import re

from .text import fold

_VERB = r"(?P<verb>revokuj\w*|ruší|zrušuje|mění|doplňuje)"
_LINK = re.compile(
    _VERB + r"\s+(?:dnem\s+[\d.\s]+?\s+)?(?:své\s+)?"
    r"(?:(?P<pre>část\w*|bod\w*)\s+(?P<predetail>[^;]{0,40}?)\s+)?"
    r"usnesení\s+(?:č\.\s*)+(?P<num>\d+)\s*/\s*(?P<year>\d{4})\s*(?P<suffix>[ZR](?![a-zá-ž]))?"
    r"(?P<post>\s*,?\s*(?:v\s+)?(?:bod\w*|část\w*)\s*[^.;]{0,80})?",
    re.I)

TYPES = {"revok": "rusi", "ruší": "rusi", "zrušuje": "rusi", "mění": "meni", "doplňuje": "meni"}


def links(text: str, body: str) -> list[dict]:
    """[{type: rusi|meni, target: '248/2022 R', scope: cele|cast, detail: str|None}]"""
    flat = re.sub(r"\s+", " ", text)
    out, seen = [], set()
    for m in _LINK.finditer(flat):
        verb = fold(m["verb"])
        kind = "rusi" if verb.startswith(("revok", "rusi", "zrus")) else "meni"
        suffix = (m["suffix"] or ("Z" if body == "zmo" else "R")).upper()
        target = f"{int(m['num'])}/{m['year']} {suffix}"
        detail = None
        if m["pre"]:
            detail = f"{m['pre']} {m['predetail']}".strip()
        elif m["post"]:
            detail = re.sub(r"\s+ze dne.*$", "", m["post"].strip(" ,"))
        key = (kind, target)
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": kind, "target": target, "scope": "cast" if detail else "cele",
                    "detail": detail})
    return out
