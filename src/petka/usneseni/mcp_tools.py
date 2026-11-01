"""MCP tools of the usnesení section (registered on the portal's server in petka.mcp_server).

Public data, so no auth; the ingress rate-limits. Every answer carries the caveats that
matter for not misleading anyone: a number doesn't mean passed, ballots may be inferred,
summaries are ours, and "nothing found" is not proof that something never happened.
"""

import os
from typing import Literal

from .. import db
from . import embed, queries, search
from .text import fold

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://opendata.mov.varecha.work").rstrip("/")

INSTRUCTIONS = f"""\
Sekce Usnesení: databáze usnesení Zastupitelstva (ZMO, 15 členů) a Rady (RMO, 5 členů) městského obvodu
Pardubice V od roku 2018, vytěžená z PDF zápisů na pardubice.eu.

Při odpovědích:
- Číslo neznamená, že jde o usnesení. Záznam se `stav: neprijato` je jen hlasování o návrhu,
  který nezískal většinu – podle zákona to usnesení není, i když mu zápis přidělil číslo.
  Nazývej ho „nepřijatý návrh“, ne „usnesení“. `castecne` = prošly jen některé části.
- Hlasy jednotlivých členů mají `provenance`: `named` = jmenovitě v zápisu, `inferred` =
  odvozeno z prezence a jmenovitě uvedených menšinových hlasů, `attendance` = nepřítomen /
  omluven. Odvozené hlasy tak označ.
- `title`, `summary`, `keywords` jsou odvozené popisy, ne text města; cituj `text`.
- Usnesení mohou být později zrušena (revokována) nebo změněna jiným usnesením – viz
  `zruseno_nebo_zmeneno` (jen `ucinne: true` platí; zrušení, které neprošlo, nic nemění).
- Prázdný výsledek neznamená, že se o věci nikdy nejednalo – zkus jiná slova nebo režim.
- Odkazuj na usnesení číslem a URL {PUBLIC_URL}/usneseni/<uid>, zdroj je `source_url`.
"""


NOT_FOUND = ("Nic nenalezeno. To neznamená, že se o věci nejednalo – zkuste jiná slova, "
             "režim 'semantic' nebo méně filtrů.")


def _member_id(name_or_id: str | None) -> str | None:
    if not name_or_id:
        return None
    return queries.find_member(name_or_id)


def _url(uid: str) -> str:
    return f"{PUBLIC_URL}/usneseni/{uid}"


def hledej_usneseni(
    dotaz: str = "",
    rezim: Literal["hybrid", "fulltext", "semantic"] = "hybrid",
    organ: Literal["zmo", "rmo"] | None = None,
    rok: int | None = None,
    od: str | None = None,
    do: str | None = None,
    tema: str | None = None,
    druh: str | None = None,
    stav: Literal["prijato", "neprijato", "castecne", "neovereno"] | None = None,
    clen: str | None = None,
    clen_hlasoval: Literal["pro", "proti", "zdrzel", "nehlasoval"] | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict:
    """Vyhledá usnesení ZMO/RMO Pardubice V.

    dotaz: přirozený jazyk nebo klíčová slova (prázdný = nejnovější podle filtrů).
    rezim: hybrid (výchozí) spojuje fulltext a sémantické hledání; semantic najde i jinak
      formulované věci; fulltext hledá slova (předpony, bez diakritiky).
    od/do: datum YYYY-MM-DD. tema: id tématu (viz statistika). stav: prijato/neprijato/…
      (číslo usnesení ≠ přijato). clen + clen_hlasoval: jen usnesení, kde daný člen
      (jméno nebo id) hlasoval danou volbou.
    """
    f = search.Filters(body=organ, year=rok, date_from=od, date_to=do, topic=tema, kind=druh,
                       status=stav, member=_member_id(clen), member_choice=clen_hlasoval)
    if clen and not f.member:
        return {"chyba": f"Člena '{clen}' nenacházím. Použijte nástroj clenove."}
    hits, info = search.search(dotaz, rezim, f, limit=min(limit, 50), offset=offset)
    out = {
        "rezim": info["mode"], "celkem": info.get("total"),
        "vysledky": [{
            "uid": h.uid, "cislo": h.row["number"], "datum": str(h.row["date"]),
            "organ": h.row["body"], "stav": h.row["status"], "nazev": h.row["title"],
            "shrnuti": h.row["summary"], "bod_programu": h.row["agenda_title"],
            "temata": h.row["topics"], "zruseno": h.row["revoked_by"], "url": _url(h.uid),
        } for h in hits],
    }
    if info["mode"] != rezim and rezim != "fulltext":
        out["poznamka"] = "Sémantické hledání teď není k dispozici, použit fulltext."
    if not hits:
        out["poznamka"] = NOT_FOUND
    return out


def usneseni_detail(usneseni: str) -> dict:
    """Plné znění usnesení, výsledek a hlasování po členech. usneseni: uid ('154-2025-z')
    nebo číslo ('154/2025 Z')."""
    uid = fold(usneseni).replace("/", "-").replace(" ", "-").strip("-")
    r = queries.resolution(uid)
    if not r:
        return {"chyba": f"Usnesení {usneseni} nenalezeno."}
    return {
        "uid": r["uid"], "cislo": r["number"], "organ": r["body"], "datum": str(r["date"]),
        "jednani": r["meeting_id"], "bod_programu": r["agenda_title"], "stav": r["status"],
        "text": r["text"], "zodpovida": r["responsible"], "termin": r["deadline"],
        "odvozeno": {"nazev": r["title"], "shrnuti": r["summary"], "klicova_slova": r["keywords"],
                     "temata": r["topics"], "druh": r["kind"], "mista": r["places"],
                     "pozemky": r["parcels"], "organizace": r["organizations"],
                     "castky": r["amounts"]},
        "hlasovani": [_vote(v) for v in r["votes"]],
        "zruseno_nebo_zmeneno": [{"usnesenim": x["number"], "datum": str(x["date"]), "typ": x["type"],
                                  "rozsah": x["scope"], "cast": x["detail"], "ucinne": x["effective"]}
                                 for x in r["revoked_by"]],
        "rusi_nebo_meni": [{"usneseni": x["target_number"], "typ": x["type"], "rozsah": x["scope"],
                            "cast": x["detail"], "ucinne": x["effective"]} for x in r["revokes"]],
        "na_mape": [{"druh": g["kind"], "misto": g["label"], "lat": round(g["lat"], 6), "lon": round(g["lon"], 6)}
                    for g in r["geo"]],
        "url": _url(r["uid"]), "zdroj": r["source_url"],
    }


def usneseni_k_mistu(misto: str, jen_platna: bool = True, limit: int = 30) -> dict:
    """Usnesení týkající se konkrétního místa v MO Pardubice V: ulice ('Jiránkova'), adresy
    ('Jana Palacha 324') nebo parcely ('2515/14'). Hledá v místech převedených na souřadnice
    podle RÚIAN; obecná místa (Dukla, sídliště) tu nejsou – na ta použijte hledej_usneseni.
    Výsledek je od nejnovějších."""
    q = fold(misto).strip()
    if not q:
        return {"chyba": "Zadejte místo."}
    with db.pool().connection() as conn:
        rows = conn.execute(
            """SELECT p.kind, p.label, r.uid, r.number, r.title, r.date, r.status
               FROM resolution_places p JOIN resolutions r ON r.uid = p.uid
               WHERE (NOT %s OR r.status <> 'neprijato') ORDER BY r.date DESC, r.seq DESC""",
            (jen_platna,)).fetchall()
    hits: dict[str, dict] = {}
    for x in rows:
        if q in fold(x["label"]):
            h = hits.setdefault(x["uid"], {"cislo": x["number"], "nazev": x["title"], "datum": str(x["date"]),
                                           "stav": x["status"], "mista": [], "url": _url(x["uid"])})
            if x["label"] not in h["mista"]:
                h["mista"].append(x["label"])
    out = list(hits.values())
    return {"misto": misto, "pocet": len(out), "usneseni": out[:limit],
            "mapa": f"{PUBLIC_URL}/usneseni/mapa",
            "poznamka": "Jen místa, která šlo podle zápisu jednoznačně umístit; nenalezeno ≠ nikdy neřešeno."}


def _vote(v: dict) -> dict:
    return {
        "cast": v["part"], "pro": v["n_pro"], "proti": v["n_proti"], "zdrzel": v["n_zdrzel"],
        "nehlasoval": v["n_nehlasoval"], "pritomno": v["n_present"], "kvorum": v["quorum"],
        "vysledek": v["outcome"], "zapis": v["raw"], "hlasy_clenu": v["ballots_status"],
        "clenove": [{"clen": b["name"], "id": b["member_id"], "kandidatka": b["list"],
                     "volba": b["choice"], "zdroj": b["provenance"]} for b in v["ballots"]],
    }


def jednani(id: str | None = None, organ: Literal["zmo", "rmo"] | None = None,
            rok: int | None = None) -> dict:
    """Bez id: seznam jednání (filtr organ/rok). S id ('zmo-2025-12-17-20'): prezence,
    body programu se shrnutím rozpravy, usnesení a hlasování mimo usnesení (program,
    nepřijaté návrhy, protinávrhy)."""
    if not id:
        return {"jednani": [{**m, "date": str(m["date"])} for m in queries.meetings(organ, rok)]}
    m = queries.meeting(id)
    if not m:
        return {"chyba": f"Jednání {id} nenalezeno."}
    n = m["names"]
    return {
        "id": m["id"], "organ": m["body"], "cislo": m["number"], "druh": m["kind"],
        "datum": str(m["date"]), "misto": m["place"], "zdroj": m["source_url"],
        "pritomni": [n.get(x, x) for x in m["present"]],
        "omluveni": [n.get(x, x) for x in m["excused"]],
        "nepritomni": [n.get(x, x) for x in m["absent"]],
        "body": [{"cislo": a["no"], "nazev": a["title"], "rozprava": a["discussion"]}
                 for a in m["agenda"]],
        "usneseni": [{"uid": r["uid"], "cislo": r["number"], "stav": r["status"],
                      "nazev": r["title"]} for r in m["resolutions"]],
        "ostatni_hlasovani": [{**_vote(v), "predmet": v["subject"], "navrhl": v["proposer"],
                               "zneni_navrhu": v["motion_text"]} for v in m["other_votes"]],
    }


def clenove(obdobi: str | None = None) -> dict:
    """Členové ZMO/RMO po volebních obdobích ('2018-2022', '2022-2026', '2026-2030'):
    id, jméno, kandidátka, zda byl zvolen (jinak náhradník), zda byl v radě."""
    return {"clenove": queries.members(obdobi)}


def hlasovani_clena(clen: str, jen_odlisne: bool = False,
                    volba: Literal["pro", "proti", "zdrzel", "nehlasoval"] | None = None,
                    limit: int = 30, offset: int = 0) -> dict:
    """Jak hlasoval člen (jméno nebo id). jen_odlisne: jen hlasování, kde hlasoval jinak,
    než jak hlasování dopadlo. Hlasy mají zdroj named/inferred."""
    mid = _member_id(clen)
    if not mid:
        return {"chyba": f"Člena '{clen}' nenacházím."}
    m = queries.member(mid)
    rows = queries.member_votes(mid, dissent_only=jen_odlisne, choice=volba,
                                limit=min(limit, 100), offset=offset)
    return {
        "clen": m["name"], "id": mid,
        "obdobi": [{"obdobi": t["term"], "kandidatka": t["list"], "rada": t["in_rada"]}
                   for t in m["terms"]],
        "dochazka": m["attendance"], "souhrn": m["stats"],
        "hlasovani": [{**r, "date": str(r["date"]),
                       "url": _url(r["uid"]) if r["uid"] else None} for r in rows],
        **({"poznamka": NOT_FOUND} if not rows else {}),
    }


def statistika() -> dict:
    """Rozsah databáze (období, počty, poslední aktualizace) a seznam témat a druhů."""
    from .enrich import vocab

    s = queries.stats()
    v = vocab()
    return {**{k: str(x) if hasattr(x, "isoformat") else x for k, x in s.items()},
            "semanticke_hledani": embed.enabled(), "temata": v["topics"], "druhy": v["kinds"],
            "otevrena_data": f"{PUBLIC_URL}/data/usneseni"}


TOOLS = [hledej_usneseni, usneseni_detail, usneseni_k_mistu, jednani, clenove, hlasovani_clena, statistika]


def register(mcp) -> None:
    for fn in TOOLS:
        mcp.tool()(fn)
