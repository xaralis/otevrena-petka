"""MCP tools of the čištění section (registered on the portal's server in petka.mcp_server)."""

import datetime as dt

from .. import obvody
from . import queries, source, words

INSTRUCTIONS = f"""\
Sekce Čištění ulic: harmonogram blokového čištění Služeb města Pardubic ({source.PAGE})
v obvodu – kdy se která ulice nebo její úsek čistí a od kolika hodin.

Při odpovědích:
- V den čištění platí v úseku zákaz stání podle dopravních značek; auto je potřeba přeparkovat
  nejpozději večer předem.
- Platí text harmonogramu (`misto`), polohu na mapě jsme odvodili sami (`poloha`: auto,
  approx = přibližně, manual = neurčená nebo ručně zakreslená).
- Kalendář ulice k odběru: https://otevrenapetka.cz/blokove-cisteni/ulice/<slug>.ics
"""


def cisteni(ulice: str | None = None, od: str | None = None, limit: int = 50,
            obvod: str = obvody.DEFAULT.id) -> dict:
    """Termíny blokového čištění v obvodu, od nejbližšího.

    ulice: název ulice (stačí část, bez diakritiky, např. „wolkerova“); bez ní celý obvod.
    od: jen termíny od toho dne YYYY-MM-DD (výchozí dnešek).
    """
    if obvod not in obvody.BY_ID:
        return {"chyba": f"Neznámý obvod, použij: {', '.join(obvody.BY_ID)}"}
    today = dt.date.today()
    try:
        since = dt.date.fromisoformat(od) if od else today
    except ValueError:
        return {"chyba": "od: datum YYYY-MM-DD"}
    its = queries.items(obvod, min(since, queries.year_start(today)))
    names = queries.streets(its)
    slugs = None
    if ulice:
        slugs = queries.find(ulice, names)
        if not slugs:
            return {"chyba": f"Ulici '{ulice}' v harmonogramu obvodu nemáme.",
                    "ulice": list(names.values())}
    rows = [i for i in its if i["date"] >= since and (slugs is None or i["slug"] in slugs)]
    checked = queries.checked()
    out = {
        "stav_k": str(checked.date()) if checked else None,
        "terminy": [{"datum": i["date"].isoformat(), "den": words.WEEKDAY[i["date"].weekday()],
                     "cas": words.clock(i) or None, "ulice": i["street"], "misto": i["text"],
                     "poloha": i["status"] if i["located"] else "neurcena",
                     **({"kalendar": f"https://otevrenapetka.cz/blokove-cisteni/ulice/{i['slug']}.ics"} if i["slug"] else {})}
                    for i in rows[:max(1, min(limit, 300))]],
        "zdroj": source.PAGE,
    }
    if not rows:
        out["poznamka"] = "Od toho dne letos žádný termín."
    return out


TOOLS = [cisteni]
