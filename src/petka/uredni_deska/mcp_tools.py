"""MCP tools of the úřední deska section (registered on the portal's server in petka.mcp_server)."""

import os

from . import queries, source

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://opendata.mov.varecha.work").rstrip("/")

INSTRUCTIONS = """\
Sekce Úřední deska: oznámení z oficiálních úředních desek, stažená z otevřených dat města
(OFN Úřední deska na pardubice.eu) – deska městského obvodu Pardubice V a deska Magistrátu
města Pardubic.

Při odpovědích:
- Závazný je dokument na pardubice.eu (`url`, `prilohy`); my jen přebíráme název a data.
- `vyveseno` = den vyvěšení, `relevantni_do` = do kdy má oznámení na desce viset.
  `sejmuto` = kdy jsme zjistili, že z desky zmizelo (nejpozději tehdy bylo sejmuto).
- `druh` odvozujeme z názvu, není to údaj města.
- Výchozí výběr (`jen_mo5`) = vše z desky obvodu a oznámení magistrátu, která obvod
  výslovně jmenují. Pro celé město nastav `jen_mo5: false`.
"""


def uredni_deska_hledej(dotaz: str = "", jen_mo5: bool = True, sejmute: bool = False,
                        druh: str | None = None, limit: int = 10, offset: int = 0) -> dict:
    """Oznámení z úřední desky MO Pardubice V a magistrátu, nejnovější první.

    dotaz: slova z názvu, čísla jednacího nebo odboru (bez diakritiky, stačí začátek slova);
      prázdný = všechna podle filtrů. jen_mo5: jen to, co se týká obvodu Pardubice V (výchozí).
    sejmute: místo právě vyvěšených ukáže sejmutá (archiv od doby, kdy desku sledujeme).
    druh (odvozený z názvu): doruceni, jednani, volby, doprava, energie, dotace, rozpocet,
      poplatky, drazby, zakazky, majetek, prostredi, stavby, predpisy, informace (odpovědi
      podle zákona 106/1999), ostatni.
    """
    rows, total = queries.search(dotaz, jen_mo5, not sejmute, druh, limit=min(limit, 50), offset=offset)
    out = {
        "celkem": total,
        "vysledky": [{
            "id": r["id"], "nazev": r["title"], "druh": r["kind_label"],
            "vyveseno": str(r["published"]) if r["published"] else None,
            "relevantni_do": str(r["valid_until"]) if r["valid_until"] else None,
            "sejmuto": str(r["removed_on"]) if r["removed_on"] else None,
            "cislo_jednaci": r["reference"], "odbor": r["department"], "deska": r["board_name"],
            "tyka_se_mo5": r["is_mo5"], "url": r["url"],
            "prilohy": [{"nazev": a["title"], "url": a["url"]} for a in r["attachments"]],
        } for r in rows],
        "zdroj": [b.page for b in source.BOARDS],
        "web": f"{PUBLIC_URL}/uredni-deska",
    }
    if not rows:
        out["poznamka"] = ("Nic nenalezeno. Zkuste jiná nebo kratší slova, jen_mo5: false (celé město) "
                           "nebo sejmute: true (archiv).")
    return out


TOOLS = [uredni_deska_hledej]


def register(mcp) -> None:
    for fn in TOOLS:
        mcp.tool()(fn)
