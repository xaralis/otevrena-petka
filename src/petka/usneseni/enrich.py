"""Derived descriptions of resolutions: short title, summary, keywords, topics, entities.

These are ours, not the city's: they are stored apart from the resolution text, shown as
"odvozeno" on the web and in the API, and never used to decide whether something passed.
Money amounts are copied as written (for search), never added up.
"""

import json
from functools import cache

import yaml

from . import llm
from .members import CONFIG

PROMPT_VERSION = "enrich-v1"


@cache
def vocab() -> dict:
    return yaml.safe_load((CONFIG / "topics.yaml").read_text())


def system() -> str:
    v = vocab()
    topics = "\n".join(f"- {k}: {d}" for k, d in v["topics"].items())
    kinds = "\n".join(f"- {k}: {d}" for k, d in v["kinds"].items())
    return f"""\
Popisuješ usnesení Zastupitelstva (ZMO) a Rady (RMO) městského obvodu Pardubice V pro
veřejnou vyhledávací databázi. Píšeš věcně, česky, bez hodnocení a bez domýšlení. Co
v textu není, neuváděj. Česká typografie: pomlčka –, uvozovky „ “, datum 13. 10. 2026.

Pro každé usnesení vrať:
- title: krátký výstižný název (do 90 znaků), co se rozhodlo, bez „ZMO schvaluje“.
- summary: 1–3 věty, co usnesení dělá a čeho/koho se týká (místo, předmět, žadatel –
  právnické osoby jménem, fyzické osoby nikdy). Výsledek hlasování nepiš, ten je zvlášť.
- keywords: 3–10 klíčových slov / frází v 1. pádě, která by člověk hledal (místa, ulice,
  předmět, typ rozhodnutí, synonyma běžné řeči: „parkování“, „kácení stromů“).
- topics: 1–3 id z tohoto seznamu:
{topics}
- kind: jedno id:
{kinds}
- places: ulice, lokality, budovy, katastrální území zmíněná v textu.
- parcels: čísla pozemků ve tvaru z textu („p. p. č. 2568/7, k. ú. Pardubice“).
- organizations: právnické osoby, spolky, organizace, úřady (ne fyzické osoby).
- amounts: částky, jak jsou v textu („351.129,90 Kč vč. DPH“). Nic nesčítej.

Pro každý bod programu s rozpravou vrať discussion: 1–3 věty, kdo se na co ptal nebo co
navrhl (jen členové zastupitelstva/rady jménem, občané a úředníci obecně). Bod bez
rozpravy vynech.
"""


def _schema() -> dict:
    v = vocab()
    s = {"type": "array", "items": {"type": "string"}}

    def obj(p):
        return {"type": "object", "properties": p, "required": list(p),
                "additionalProperties": False}

    return obj({
        "resolutions": {"type": "array", "items": obj({
            "number": {"type": "string"}, "title": {"type": "string"},
            "summary": {"type": "string"}, "keywords": s,
            "topics": {"type": "array", "items": {"type": "string", "enum": list(v["topics"])}},
            "kind": {"type": "string", "enum": list(v["kinds"])},
            "places": s, "parcels": s, "organizations": s, "amounts": s,
        })},
        "agenda": {"type": "array", "items": obj({
            "no": {"type": "string"}, "discussion": {"type": "string"},
        })},
    })


SCHEMA = _schema()


def payload(meeting, text_lines: list[str]) -> str:
    """User message: the resolutions to describe plus the discussion parts of the minutes."""
    items = []
    agenda = sorted(meeting.agenda_items, key=lambda a: a["line"])
    for i, a in enumerate(agenda):
        end = agenda[i + 1]["line"] - 1 if i + 1 < len(agenda) else len(text_lines)
        items.append({"no": a["no"], "title": a["title"],
                      "minutes": "\n".join(l.strip() for l in text_lines[a["line"] - 1:end] if l.strip())})
    res = [{"number": r["number"], "agenda": r["agenda_title"], "text": r["text"]}
           for r in meeting.resolutions]
    body = "Zastupitelstvo" if meeting.body == "zmo" else "Rada"
    return (f"{body} MO Pardubice V, {meeting.number}. jednání dne {meeting.date:%-d. %-m. %Y}.\n\n"
            f"USNESENÍ:\n{json.dumps(res, ensure_ascii=False, indent=1)}\n\n"
            f"BODY PROGRAMU (zápis):\n{json.dumps(items, ensure_ascii=False, indent=1)}")


def enrich(meeting, text_lines: list[str]) -> dict:
    return llm.structured(system(), payload(meeting, text_lines), SCHEMA, effort="medium")


def check(meeting, enriched: dict) -> list[str]:
    problems = []
    got = [r["number"] for r in enriched["resolutions"]]
    want = [r["number"] for r in meeting.resolutions]
    if sorted(got) != sorted(want):
        problems.append(f"resolution numbers differ: missing {sorted(set(want) - set(got))}, "
                        f"extra {sorted(set(got) - set(want))}")
    v = vocab()
    for r in enriched["resolutions"]:
        if not r["topics"] or any(t not in v["topics"] for t in r["topics"]):
            problems.append(f"{r['number']}: bad topics {r['topics']}")
        if r["kind"] not in v["kinds"]:
            problems.append(f"{r['number']}: bad kind {r['kind']}")
        if len(r["title"]) > 120:
            problems.append(f"{r['number']}: title too long")
    return problems
