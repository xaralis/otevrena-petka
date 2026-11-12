"""Structure of one "Usnesení (a zápis)" PDF: header, attendance, agenda, resolutions, votes.

Claude reads the line-numbered text and returns *pointers* (line numbers) plus the parts
that need reading comprehension (who voted how by name, arrivals/departures, which vote
belongs to which resolution or sub-point). The resolution text itself is always cut from
the PDF text by those line numbers, never written by the model, so it stays verbatim.
Vote counts the model returns are re-checked against the raw vote line in `validate`.
"""

import re

from .. import llm

PROMPT_VERSION = "parse-v1"

SYSTEM = """\
Jsi pečlivý zapisovatel. Dostaneš text PDF „Usnesení“ nebo „Usnesení a zápis“ z jednání
Zastupitelstva (ZMO) nebo Rady (RMO) městského obvodu Pardubice V. Každý řádek začíná
číslem řádku a svislítkem („0042| …“). Vrať strukturu dokumentu podle schématu.

Pravidla:
- Řádky uváděj čísly z levého sloupce. Nic nepřepisuj ani neopravuj; jména piš tak, jak
  jsou v textu (s tituly), jen v 1. pádě.
- attendance: jména ze seznamů Přítomni / Omluven(a, i) / Nepřítomen (Neomluven). Hosté,
  zapisovatelé a úředníci tam nepatří.
- presence_events: každý příchod a odchod člena během jednání („odešel“, „přišel“,
  „dostavil se“, „vrátil se“, „opustil jednání“) s číslem řádku, kde je zmínka. Pokud text
  říká „při hlasování o bodu X nebyl přítomen“, zapiš odchod před a příchod po.
- votes: KAŽDÉ hlasování v dokumentu, tj. každý řádek s počty hlasů („Pro 12, proti 0,
  zdržel se 1 …“, „pro 5, zdržel se 0, proti 0“) – i procedurální (program, ověřovatelé,
  pořadí bodů), i nepřijaté návrhy a protinávrhy bez čísla usnesení, i hlasování o
  jednotlivých osobách nebo dílčích bodech uvnitř jednoho usnesení.
  - line / last_line: řádky, na kterých je hlasovací zápis (počty a jména), nic víc.
  - resolution: číslo usnesení ve tvaru „17/2019 Z“ nebo „250/2025 R“, ke kterému hlasování
    patří; null, pokud hlasování k žádnému číslovanému usnesení nepatří.
  - part: pokud se hlasovalo jen o části usnesení (bod „4.“, „1. a)“, jedna osoba při
    volbě členů komise), krátké označení té části („bod 4“, „Ing. Jiří Janoš – člen
    komise pro školství“); null, pokud se hlasovalo o celém usnesení.
  - subject: u hlasování bez čísla usnesení krátce, o čem se hlasovalo („schválení
    programu“, „protinávrh Ing. Vařechy: …“); jinak null.
  - proposer: kdo návrh podal, pokud to text u nepřijatého návrhu / protinávrhu uvádí.
  - motion_first_line / motion_last_line: u hlasování bez čísla usnesení řádky se zněním
    hlasovaného návrhu, pokud je v textu; jinak null.
  - pro / proti / zdrzel / nehlasoval: počty přesně podle textu; nehlasoval null, pokud
    text tuto možnost vůbec neuvádí.
  - names: jména jmenovitě uvedená u jednotlivých možností (v závorce za počtem). Prázdný
    seznam, pokud jména uvedena nejsou. Nic nedomýšlej.
  - stated_outcome: „prijato“ / „neprijato“ jen pokud to text u toho hlasování výslovně
    říká („usnesení bylo přijato“, „nebylo přijato“, „nebyl schválen“); jinak null.
    Výsledek NIKDY neodvozuj z toho, že návrh má číslo usnesení.
- resolutions: každé číslo usnesení „(usnesení č. N/RRRR Z|R)“ právě jednou. first_line a
  last_line ohraničují znění usnesení (od „Zastupitelstvo/Rada městského obvodu … schvaluje“
  po poslední řádek znění), bez řádku s číslem a bez řádků Z: (zodpovídá) a T: (termín).
  Hlasovací řádky uvnitř (u dílčích hlasování) do rozsahu patří, odstraní se později.
  responsible / deadline: text za „Z:“ a „T:“, pokud jsou.
- agenda_items: body programu, jak jsou v dokumentu projednány (číslo a název bodu, řádek
  nadpisu bodu), včetně Různé/Diskuse. speakers: členové ZMO/RMO, kteří v bodu vystoupili
  v diskusi (jen pokud to zápis uvádí).
- notes: nesrovnalosti, které vidíš (počty nesedí na přítomné, chybí výsledek, číslo
  usnesení se opakuje…). Jinak prázdný seznam.
"""

_names = {"type": "array", "items": {"type": "string"}}
_nullable_int = {"type": ["integer", "null"]}
_nullable_str = {"type": ["string", "null"]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


SCHEMA = _obj({
    "header": _obj({
        "body": {"type": "string", "enum": ["zmo", "rmo"]},
        "number": {"type": "integer"},
        "kind": {"type": "string", "enum": ["radne", "mimoradne", "ustavujici"]},
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "place": _nullable_str,
    }),
    "attendance": _obj({"present": _names, "excused": _names, "absent": _names}),
    "presence_events": {"type": "array", "items": _obj({
        "line": {"type": "integer"}, "name": {"type": "string"},
        "event": {"type": "string", "enum": ["arrive", "leave"]},
    })},
    "agenda_items": {"type": "array", "items": _obj({
        "no": {"type": "string"}, "title": {"type": "string"}, "line": {"type": "integer"},
        "speakers": _names,
    })},
    "resolutions": {"type": "array", "items": _obj({
        "number": {"type": "string"}, "agenda_no": _nullable_str,
        "first_line": {"type": "integer"}, "last_line": {"type": "integer"},
        "responsible": _nullable_str, "deadline": _nullable_str,
    })},
    "votes": {"type": "array", "items": _obj({
        "line": {"type": "integer"}, "last_line": {"type": "integer"},
        "resolution": _nullable_str, "part": _nullable_str, "subject": _nullable_str,
        "proposer": _nullable_str,
        "motion_first_line": _nullable_int, "motion_last_line": _nullable_int,
        "procedural": {"type": "boolean"},
        "pro": {"type": "integer"}, "proti": {"type": "integer"},
        "zdrzel": {"type": "integer"}, "nehlasoval": _nullable_int,
        "names": _obj({"pro": _names, "proti": _names, "zdrzel": _names,
                       "nehlasoval": _names}),
        "stated_outcome": {"type": ["string", "null"], "enum": ["prijato", "neprijato", None]},
    })},
    "notes": _names,
})


def number_lines(text: str) -> tuple[list[str], str]:
    lines = [l.rstrip() for l in text.splitlines()]
    width = max(4, len(str(len(lines))))
    return lines, "\n".join(f"{i:0{width}d}| {l}" for i, l in enumerate(lines, 1))


def parse(text: str) -> dict:
    _, numbered = number_lines(text)
    return llm.default().structured(SYSTEM, numbered, SCHEMA, effort="high")


# --- deterministic helpers used by validation ------------------------------------------

RESOLUTION_REF = re.compile(r"usnesení\s+č\.\s*(\d+)\s*/\s*(\d{4})\s*([ZR])?", re.I)


def resolution_numbers_in_text(text: str) -> set[str]:
    """Every '(usnesení č. N/YYYY Z)' marker – the parse must account for all of them."""
    out = set()
    for line in text.splitlines():
        s = line.strip()
        # markers sit on their own line, in parentheses; references inside resolution
        # texts ("revokuje usnesení č. 12/2019 Z") are not markers
        m = re.fullmatch(r"\(?\s*" + RESOLUTION_REF.pattern + r"\s*\)?", s, re.I)
        if m:
            out.add(f"{int(m[1])}/{m[2]} {(m[3] or '').upper()}".strip())
    return out


def normalize_number(n: str, body: str) -> str:
    m = re.search(r"(\d+)\s*/\s*(\d{4})\s*([ZRzr])?", n)
    if not m:
        return n.strip()
    suffix = (m[3] or ("Z" if body == "zmo" else "R")).upper()
    return f"{int(m[1])}/{m[2]} {suffix}"


_COUNT = {
    "pro": r"\bpro\s*:?\s*(\d+)",
    "proti": r"\bproti\s*:?\s*(\d+)",
    "zdrzel": r"zdržel\w*\s+se\s*:?\s*(\d+)",
    "nehlasoval": r"nehlasoval\w*\s*:?\s*(\d+)",
}


def counts_in_raw(raw: str) -> dict[str, int | None]:
    """Counts read straight from the vote line, as an independent check of the model."""
    # drop parenthesised name lists ("(Ing. Vařecha, Ing. Hájek)") but keep parenthesised
    # counts ("(pro 5, zdržel se 0, proti 0)") – names never contain digits
    flat = re.sub(r"\([^)0-9]*\)", " ", raw)
    out: dict[str, int | None] = {}
    for k, pat in _COUNT.items():
        m = re.search(pat, flat, re.I)
        out[k] = int(m[1]) if m else None
    return out
