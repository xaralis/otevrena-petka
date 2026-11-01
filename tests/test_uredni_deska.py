"""Úřední deska: parsing the city's OFN JSON (fixtures cut from the real boards on
2026-11-01, private persons' names replaced), the MO V rule, kinds and the fetch."""

import datetime as dt
import json
from pathlib import Path

import httpx

from petka.uredni_deska import source
from petka.uredni_deska.queries import tsquery

FIX = Path(__file__).parent / "fixtures" / "uredni_deska"
MO5, MMP = source.BY_ID["mo5"], source.BY_ID["mmp"]


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def test_parse_district_board():
    rows = source.parse(load("mo5"), MO5)
    assert [r["id"] for r in rows] == ["mo5-15531", "mo5-15512", "mo5-15416", "mo5-12520"]
    first = rows[0]
    assert first["url"] == "https://pardubice.eu/uredni-deska/obvody?id=15531"
    assert first["title"].startswith("Veřejná vyhláška - oznámení o uložení")
    assert "  " not in first["title"]              # whitespace collapsed
    assert first["published"] == dt.date(2026, 10, 22)
    assert first["valid_until"] == dt.date(2026, 12, 15)
    assert first["reference"] == "9164/2026/OE UMO5/Lu"
    assert first["attachments"] == [{"title": "VVVzorovy", "url": first["attachments"][0]["url"]}]
    assert first["attachments"][0]["url"].endswith(".pdf")
    assert "popis" not in first and "description" not in first   # dates of birth are not kept
    # everything on the district's own board concerns MO V, Magistrát decisions included
    assert all(r["is_mo5"] and r["board"] == "mo5" for r in rows)
    assert [r["kind"] for r in rows] == ["doruceni", "doprava", "volby", "rozpocet"]


def test_parse_city_board_flags_only_explicit_mo5():
    rows = {r["title"]: r for r in source.parse(load("mmp"), MMP)}
    mo5 = [t for t, r in rows.items() if r["is_mo5"]]
    assert mo5 == [next(t for t in rows if "MO Pardubice V - Nové Jesenčany" in t)]
    rosice = next(r for t, r in rows.items() if "Pardubice VII" in t)
    assert not rosice["is_mo5"] and rosice["department"] == "Kancelář tajemníka"
    assert rosice["reference"] is None              # "xxx" in the source
    moa = next(r for t, r in rows.items() if "SO MOA" in t)
    assert len(moa["attachments"]) > 3 and all(a["url"].startswith("https://pardubice.eu/") for a in moa["attachments"])
    old = next(r for r in rows.values() if r["valid_until"] and r["valid_until"].year == 2222)
    assert old["kind"] == "informace"
    assert next(r for t, r in rows.items() if t.startswith("Pozvánka"))["kind"] == "jednani"
    assert next(r for t, r in rows.items() if "Vzorová" in t)["kind"] == "doruceni"


def test_mentions_mo5():
    yes = ["Přerušení dodávky, MO Pardubice V - Nové Jesenčany", "č. j. 9164/2026/OE UMO5/Lu",
           "Usnesení ZMO Pardubice V", "ÚMO 5", "pozemek v městském obvodu Pardubice V",
           "Schválený rozpočet MO Pardubice V na r. 2026"]
    no = ["MO Pardubice VII - Rosice", "MO Pardubice I - Bílé Předměstí", "Pardubice v roce 2026",
          "zařizovací obvod Pardubice-Chlumec", "chodník v obvodu v Pardubicích", "MmP 205861/2026"]
    assert all(source.mentions_mo5(t) for t in yes), [t for t in yes if not source.mentions_mo5(t)]
    assert not any(source.mentions_mo5(t) for t in no), [t for t in no if source.mentions_mo5(t)]


def test_ofn_variants():
    doc = {"informace": [
        {"iri": "https://example.org/deska/abc", "název": "Plain string title",
         "vyvěšení": {"datum_a_čas": "2026-10-01T08:00:00+02:00"},
         "relevantní_do": {"nespecifikovaný": True},
         "agenda": [{"název": {"cs": "Stavební řízení"}}], "spisová_značka": "SZ 1/2026",
         "zveřejnil": {"název": {"cs": "Odbor dopravy"}}, "dokument": [{"název": {"cs": "bez url"}}]},
        {"url": "https://example.org/no-title"},                 # no title: skipped
        {"url": "https://pardubice.eu/uredni-deska?id=1", "název": {"cs": "A"}},
        {"url": "https://pardubice.eu/uredni-deska?id=1", "název": {"cs": "A again"}},  # duplicate
    ]}
    rows = source.parse(doc, MMP)
    assert len(rows) == 2
    r = rows[0]
    assert r["id"].startswith("mmp-") and len(r["id"]) == 4 + 12
    assert r["title"] == "Plain string title"
    assert r["published"] == dt.date(2026, 10, 1) and r["valid_until"] is None
    assert r["agenda"] == ["Stavební řízení"] and r["file_mark"] == "SZ 1/2026"
    assert r["department"] == "Odbor dopravy" and r["attachments"] == []
    assert rows[1]["id"] == "mmp-1"


def test_kind():
    assert source.kind("Stanovení přechodné úpravy provozu v ulici Jana Palacha") == "doprava"
    assert source.kind("Dražební vyhláška - elektronická dražba") == "drazby"
    assert source.kind("Oznámení č. 28 - nebytové prostory") == "majetek"
    assert source.kind("Vyrozumění o zahájení řízení - Chodník Čechovo nábřeží") == "stavby"
    assert source.kind("Informace o konání ustavujícího zasedání ZMO") == "jednani"
    assert source.kind("Upozornění - odchyt volně žijících koček") == "prostredi"
    assert source.kind("Oznámení o přerušení dodávky elektrické energie, MO Pardubice V") == "energie"
    assert source.kind("Schválený závěrečný účet MO Pardubice V za r. 2025") == "rozpocet"
    assert source.kind("Zápis o výsledku voleb do Zastupitelstva MO Pardubice V") == "volby"
    assert source.kind("Zveřejňování pro ÚSC na úřední desce") == "ostatni"
    # a 106/1999 answer: just a subject, posted for ten years
    assert source.kind("Průměrné platy", dt.date(2019, 12, 2), dt.date(2029, 12, 2)) == "informace"


def test_tsquery():
    assert tsquery("Jesničánky") == "jesnican:*"            # accents off, ending off, prefix
    assert tsquery("rozpočet 2026", "|") == "rozpoc:* | 2026:*"
    assert tsquery("a v na") is None


def test_fetch_conditional_and_304():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(request.headers)
        if request.headers.get("if-none-match") == '"abc"':
            return httpx.Response(304)
        return httpx.Response(200, content=b'{"informace": []}', headers={"ETag": '"abc"'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    f = source.fetch(MO5, client=client)
    assert f.status == 200 and f.etag == '"abc"' and f.body.startswith(b"{")
    f = source.fetch(MO5, etag='"abc"', last_modified="Sun, 01 Nov 2026 10:00:00 GMT", client=client)
    assert f.status == 304 and f.etag == '"abc"'
    assert seen["if-modified-since"] == "Sun, 01 Nov 2026 10:00:00 GMT"
