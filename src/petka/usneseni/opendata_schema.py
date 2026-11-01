"""Open-data tables: field definitions (Frictionless Table Schema) shared by export and docs.

One place describes every published column: the CSV/JSON export writes `datapackage.json`
from it and `docs/otevrena-data.md` documents the same names.
"""

BODY = ["zmo", "rmo"]
STATUS = ["prijato", "neprijato", "castecne", "neovereno"]
CHOICE = ["pro", "proti", "zdrzel", "nehlasoval", "omluven", "nepritomen"]


def f(name, type_, desc, *, enum=None, required=False, fmt=None):
    d = {"name": name, "type": type_, "description": desc}
    if fmt:
        d["format"] = fmt
    c = {}
    if enum:
        c["enum"] = enum
    if required:
        c["required"] = True
    if c:
        d["constraints"] = c
    return d


TABLES = {
    "meetings": {
        "title": "Jednání",
        "description": "Jedno jednání zastupitelstva (ZMO) nebo rady (RMO).",
        "primaryKey": ["id"],
        "fields": [
            f("id", "string", "Identifikátor jednání: <orgán>-<datum>-<číslo jednání>, např. zmo-2025-12-17-20.", required=True),
            f("body", "string", "Orgán: zmo = zastupitelstvo, rmo = rada.", enum=BODY, required=True),
            f("term", "string", "Volební období, např. 2022-2026.", required=True),
            f("number", "integer", "Pořadové číslo jednání v rámci období.", required=True),
            f("kind", "string", "Druh jednání.", enum=["radne", "mimoradne", "ustavujici"], required=True),
            f("date", "date", "Datum jednání.", required=True),
            f("place", "string", "Místo konání."),
            f("status", "string", "ok = zpracování prošlo kontrolami; needs_review = čeká na ruční kontrolu.", enum=["ok", "needs_review"]),
            f("source_url", "string", "URL zdrojového PDF na pardubice.eu.", fmt="uri", required=True),
            f("present", "string", "Přítomní zastupitelé (id oddělená středníkem)."),
            f("excused", "string", "Omluvení zastupitelé (id oddělená středníkem)."),
            f("absent", "string", "Neomluveně nepřítomní zastupitelé (id oddělená středníkem)."),
        ],
    },
    "resolutions": {
        "title": "Usnesení a nepřijaté návrhy",
        "description": "Číslované záznamy ze zápisu. Stav „neprijato“ znamená nepřijatý návrh: nezískal většinu, takže nejde o usnesení, i když mu zápis přidělil číslo.",
        "primaryKey": ["uid"],
        "foreignKeys": [{"fields": ["meeting_id"], "reference": {"resource": "meetings", "fields": ["id"]}}],
        "fields": [
            f("uid", "string", "Identifikátor odvozený z čísla: 154-2025-z.", required=True),
            f("number", "string", "Číslo usnesení, jak ho uvádí zápis: 154/2025 Z (Z = zastupitelstvo, R = rada).", required=True),
            f("meeting_id", "string", "Jednání (meetings.id).", required=True),
            f("body", "string", "Orgán.", enum=BODY, required=True),
            f("date", "date", "Datum jednání.", required=True),
            f("agenda_no", "string", "Číslo bodu programu."),
            f("agenda_title", "string", "Název bodu programu."),
            f("status", "string", "Výsledek: prijato; neprijato (nepřijatý návrh – není usnesením, i když má číslo ze zápisu); castecne (část bodů prošla); neovereno (nelze určit ze zápisu).", enum=STATUS, required=True),
            f("text", "string", "Doslovné znění usnesení ze zápisu.", required=True),
            f("responsible", "string", "Zodpovídá (řádek Z:)."),
            f("deadline", "string", "Termín (řádek T:)."),
            f("verbs", "string", "Rozhodovací slovesa ve znění (schvaluje; bere na vědomí; …), oddělená středníkem."),
            f("title", "string", "ODVOZENÉ: krátký název."),
            f("summary", "string", "ODVOZENÉ: shrnutí v 1–3 větách."),
            f("keywords", "string", "ODVOZENÉ: klíčová slova oddělená středníkem."),
            f("topics", "string", "ODVOZENÉ: témata (id z číselníku témat) oddělená středníkem."),
            f("kind", "string", "ODVOZENÉ: druh rozhodnutí (id z číselníku druhů)."),
            f("places", "string", "ODVOZENÉ: místa a ulice zmíněná ve znění."),
            f("parcels", "string", "ODVOZENÉ: pozemky ve tvaru ze znění."),
            f("organizations", "string", "ODVOZENÉ: právnické osoby a organizace."),
            f("amounts", "string", "ODVOZENÉ: částky, jak jsou ve znění (nesčítat)."),
        ],
    },
    "votes": {
        "title": "Hlasování",
        "description": "Každé hlasování v zápisu: o usnesení, o jeho části, procedurální i o nepřijatých návrzích bez čísla.",
        "primaryKey": ["id"],
        "foreignKeys": [{"fields": ["meeting_id"], "reference": {"resource": "meetings", "fields": ["id"]}},
                        {"fields": ["resolution_uid"], "reference": {"resource": "resolutions", "fields": ["uid"]}}],
        "fields": [
            f("id", "string", "Identifikátor: <meeting_id>-<pořadí>.", required=True),
            f("meeting_id", "string", "Jednání.", required=True),
            f("seq", "integer", "Pořadí hlasování v zápisu.", required=True),
            f("resolution_uid", "string", "Usnesení, ke kterému hlasování patří; prázdné u procedurálních a nepřijatých návrhů bez čísla."),
            f("part", "string", "Část usnesení, o které se hlasovalo zvlášť (bod 4, jedna osoba při volbě); prázdné = celé usnesení."),
            f("subject", "string", "Předmět hlasování bez čísla usnesení (program, protinávrh …)."),
            f("proposer", "string", "Navrhovatel u protinávrhů a nepřijatých návrhů, pokud ho zápis uvádí."),
            f("procedural", "boolean", "Procedurální hlasování (program, ověřovatelé …).", required=True),
            f("n_pro", "integer", "Počet hlasů pro.", required=True),
            f("n_proti", "integer", "Počet hlasů proti.", required=True),
            f("n_zdrzel", "integer", "Počet zdržení.", required=True),
            f("n_nehlasoval", "integer", "Počet nehlasujících; prázdné, pokud ho zápis neuvádí."),
            f("n_present", "integer", "Zastupitelů přítomných v okamžiku hlasování (podle prezence a příchodů/odchodů).", required=True),
            f("quorum", "integer", "Potřebný počet hlasů pro: nadpoloviční většina všech členů orgánu (§ 87 a § 101 zákona o obcích).", required=True),
            f("passed", "boolean", "n_pro >= quorum.", required=True),
            f("outcome", "string", "Výsledek; prázdný, pokud zápis výslovně tvrdí opak toho, co vychází z počtů.", enum=["prijato", "neprijato"]),
            f("stated_outcome", "string", "Výsledek, pokud ho zápis výslovně uvádí.", enum=["prijato", "neprijato"]),
            f("ballots_status", "string", "Hlasy jednotlivých zastupitelů: complete = všechny známé; partial = jen jmenovaní; tallies_only = jen součty.", enum=["complete", "partial", "tallies_only"], required=True),
            f("raw", "string", "Hlasovací řádek doslova ze zápisu.", required=True),
        ],
    },
    "ballots": {
        "title": "Hlasy zastupitelů",
        "description": "Jak hlasoval jednotlivý zastupitel. Zápisy MO V jmenují jen menšinu; ostatní hlasy jsou odvozené.",
        "primaryKey": ["vote_id", "member_id"],
        "foreignKeys": [{"fields": ["vote_id"], "reference": {"resource": "votes", "fields": ["id"]}}],
        "fields": [
            f("vote_id", "string", "Hlasování (votes.id).", required=True),
            f("member_id", "string", "Zastupitel (members.id).", required=True),
            f("choice", "string", "Volba, nebo omluven/nepritomen.", enum=CHOICE, required=True),
            f("provenance", "string", "named = jmenovitě v zápisu; inferred = odvozeno (přítomní minus jmenovaní, sedí-li součet); attendance = podle prezence.", enum=["named", "inferred", "attendance"], required=True),
        ],
    },
    "members": {
        "title": "Zastupitelé",
        "description": "Zastupitelé MO Pardubice V po volebních obdobích, včetně členství v radě, s kandidátní listinou podle volby.cz.",
        "fields": [
            f("id", "string", "Identifikátor: jmeno-prijmeni bez diakritiky.", required=True),
            f("name", "string", "Jméno s tituly.", required=True),
            f("term", "string", "Volební období."),
            f("list", "string", "Kandidátní listina, za kterou byl zvolen."),
            f("elected", "boolean", "Zvolen ve volbách (jinak nastoupil jako náhradník)."),
            f("in_rada", "boolean", "Byl v daném období členem rady."),
        ],
    },
    "places": {
        "title": "Místa usnesení",
        "description": "Pozemky, adresy a ulice, kterých se usnesení týká, s geometrií z RÚIAN (ČÚZK). Obecná místa (Dukla, sídliště) nejsou zahrnuta; parcely jsou v dnešní podobě. Stejná data jako GeoJSON: places.geojson.",
        "fields": [
            f("uid", "string", "Usnesení.", required=True),
            f("number", "string", "Číslo usnesení."),
            f("kind", "string", "parcel = pozemek (polygon), address = adresní místo (bod), street = ulice (linie).", enum=["parcel", "address", "street"], required=True),
            f("label", "string", "Úřední název podle RÚIAN.", required=True),
            f("source_text", "string", "Místo, jak ho uvádí zápis (strojově vytěžené)."),
            f("lon", "number", "Zeměpisná délka těžiště (WGS84)."),
            f("lat", "number", "Zeměpisná šířka těžiště (WGS84)."),
            f("geometry", "string", "Geometrie jako GeoJSON (WGS84).", required=True),
        ],
        "foreignKeys": [{"fields": "uid", "reference": {"resource": "resolutions", "fields": "uid"}}],
    },
    "relations": {
        "title": "Zrušení a změny usnesení",
        "description": "Usnesení, které ruší (revokuje) nebo mění dřívější usnesení. Účinné jen, pokud rušící usnesení prošlo.",
        "fields": [
            f("source_uid", "string", "Rušící / měnící usnesení.", required=True),
            f("source_number", "string", "Jeho číslo."),
            f("type", "string", "rusi = ruší/revokuje; meni = mění/doplňuje.", enum=["rusi", "meni"], required=True),
            f("target_number", "string", "Číslo rušeného usnesení.", required=True),
            f("target_uid", "string", "Rušené usnesení, je-li v databázi (starší než 2018 nejsou)."),
            f("scope", "string", "cele / cast.", enum=["cele", "cast"], required=True),
            f("detail", "string", "Která část (body, části), jak ji uvádí znění."),
            f("effective", "boolean", "Rušící usnesení bylo přijato.", required=True),
        ],
    },
}
