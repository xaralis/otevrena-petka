"""MCP tools of the podněty section (registered on the portal's server in petka.mcp_server)."""

import datetime as dt

from .. import obvody
from . import queries, source

INSTRUCTIONS = f"""\
Sekce Podněty: hlášení občanů z městské aplikace Dej Tip ({source.HOME}) v obvodu – co lidé
nahlásili (kategorie), kde (souřadnice a ulice bez čísla domu), kdy a v jakém je stavu.

Při odpovědích:
- Podněty jsou hlášení lidí, ne zjištění úřadu; počet podnětů neříká, jak velký problém je.
- Stav je to, co v Dej Tipu nastavil úřad. `zmena_stavu` = kdy jsme změnu zaznamenali my
  (denní kontrola), ne kdy ji úřad provedl.
- Popis od občana, fotky a poznámky úřadu nepřebíráme; pro ně odkaž na mapu Dej Tipu.
- Chybné, spamové a smazané podněty vynecháváme.
"""


def _date(v: str | None) -> dt.date | None:
    return dt.date.fromisoformat(v) if v else None


def podnety(lat: float | None = None, lng: float | None = None, okruh: int = 500,
            kategorie: str | None = None, stav: str | None = None, od: str | None = None,
            do: str | None = None, limit: int = 20, obvod: str = obvody.DEFAULT.id) -> dict:
    """Podněty z aplikace Dej Tip v obvodu: přehled a seznam (nejnovější první, s lat/lng nejbližší).

    lat, lng + okruh (metry, nejvýš 5000): jen podněty v okolí bodu.
    kategorie: název nebo jeho začátek (např. „chodník“, „zeleň“, „odpadky“).
    stav: Evidováno, V řešení, Vyřešeno, Nelze vyřídit, Nepřísluší, Předáno, Zařazeno do plánu.
    od/do: den nahlášení YYYY-MM-DD.
    """
    if obvod not in obvody.BY_ID:
        return {"chyba": f"Neznámý obvod, použij: {', '.join(obvody.BY_ID)}"}
    prehled = queries.summary(obvod)
    cats = tuple(c["category_id"] for c in prehled["categories"]
                 if kategorie and kategorie.strip().lower() in c["category"].lower())
    stats = tuple(k for k, v in source.STATUSES.items() if stav and stav.strip().lower() == v.lower())
    if kategorie and not cats:
        return {"chyba": f"Kategorii '{kategorie}' neznám, jsou: "
                         + ", ".join(c["category"] for c in prehled["categories"])}
    if stav and not stats:
        return {"chyba": f"Stav '{stav}' neznám, jsou: " + ", ".join(source.STATUSES.values())}
    point = (lat, lng) if lat is not None and lng is not None else None
    f = queries.Filters(obvod, cats, stats, _date(od), _date(do), point, max(1, min(okruh, 5000)))
    rows = queries.search(f, min(limit, 100))
    out = {
        "prehled": {"celkem": prehled["total"],
                    "od": str(prehled["first"].date()) if prehled["first"] else None,
                    "aktualizovano": str(prehled["checked"]) if prehled["checked"] else None,
                    "podle_kategorie": {c["category"]: c["n"] for c in prehled["categories"]},
                    "podle_stavu": {s["name"]: s["n"] for s in prehled["statuses"]}},
        "vysledky": [{
            "id": r["id"], "kategorie": r["category"], "stav": source.STATUSES.get(r["status"]),
            "nahlaseno": r["reported_at"].isoformat(timespec="minutes"), "ulice": r["street"],
            "lat": r["lat"], "lng": r["lng"],
            "zmena_stavu": str(r["status_changed_at"]) if r["status_changed_at"] else None,
            **({"vzdalenost_m": r["distance"]} if "distance" in r else {}),
        } for r in rows],
        "zdroj": source.HOME,
    }
    if not rows:
        out["poznamka"] = "Nic nenalezeno. Zkuste větší okruh, jinou kategorii nebo bez filtru stavu."
    return out


TOOLS = [podnety]
