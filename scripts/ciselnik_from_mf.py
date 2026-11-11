"""Generate data/rozpocet/ciselnik.json: the rozpočtová skladba codelists (paragraf, položka)
from the Ministry of Finance's state treasury open data. GORDIC reports some levels by name
only, often shortened ("Sběr a svoz ost. odpadů jiných než nebez. a komun."); the job maps
the names back to codes with these lists.

    uv run python scripts/ciselnik_from_mf.py > data/rozpocet/ciselnik.json

Only entries valid in 2018 or later are kept (the GORDIC reports start in 2018).
"""

import json
import sys
import xml.etree.ElementTree as ET

import httpx

URL = "https://monitor.statnipokladna.gov.cz/data/xml/{}.xml"
SINCE = "2018-01-01"


def codelist(name: str) -> list[list]:
    r = httpx.get(URL.format(name), timeout=120, follow_redirects=True)
    r.raise_for_status()
    out = []
    for row in ET.fromstring(r.content):
        d = {c.tag: (c.text or "").strip() for c in row}
        if d["end_date"] >= SINCE and d[name].isdigit() and int(d[name]):
            out.append([int(d[name]), d["nazev"], d["start_date"], d["end_date"]])
    return sorted(out)


if __name__ == "__main__":
    json.dump({"source": "Ministerstvo financí, Monitor státní pokladny – číselníky",
               "url": URL.format("<paragraf|polozka>"),
               "paragraf": codelist("paragraf"), "polozka": codelist("polozka")},
              sys.stdout, ensure_ascii=False, indent=0)
    sys.stdout.write("\n")
