"""Invariants on stored meetings plus golden cases checked by hand against the PDFs."""

import datetime as dt

import pytest

from petka.usneseni import members, pipeline, scrape, store
from petka.usneseni.parse import counts_in_raw, normalize_number, resolution_numbers_in_text
from petka.usneseni.text import clean_block, ws

PARSED = [mid for mid in pipeline.meeting_ids() if store.text_path(mid).exists()
          and store.extracted(mid, "parse")]


def test_title_parsing():
    t = scrape.parse_title("Usnesení z 48.mimořádného jednání RMO Pardubice V ze dne 25.6.2025")
    assert (t["number"], t["kind"], t["date"]) == (48, "mimoradne", dt.date(2025, 6, 25))
    t = scrape.parse_title("Usnesení z 3. jednání ZMO Pardubice V ze dne 22.2.2023")
    assert (t["number"], t["kind"]) == (3, None)
    assert scrape.parse_title("Příloha k usnesení ZMO Pardubice V ze dne 8.11.2023")["is_attachment"]


def test_counts_in_raw():
    assert counts_in_raw("Pro 12, Proti 0, Zdržel se: 1 (Ing. Jakub Kutílek)") == \
        {"pro": 12, "proti": 0, "zdrzel": 1, "nehlasoval": None}
    assert counts_in_raw("Ing. Jiří Janoš, (pro 0, zdržel se 0, proti 5 – nebyl schválen).")["proti"] == 5
    assert counts_in_raw("Pro 4 (Ing. Kutílek, Ing. Jeřábek) Proti 4 (…), Zdržel se: 3 (…) Nehlasoval: 1 (Jiří Rejda, DiS.)") == \
        {"pro": 4, "proti": 4, "zdrzel": 3, "nehlasoval": 1}
    assert counts_in_raw("Pro 14, zdrželo se 0, proti 0")["zdrzel"] == 0


def test_resolution_markers_ignore_references():
    text = "   (usnesení č. 17/2019 Z)\nrevokuje usnesení č. 12/2018 Z\n(usnesení č.18/2019 Z)\n"
    assert resolution_numbers_in_text(text) == {"17/2019 Z", "18/2019 Z"}
    assert normalize_number("usnesení č. 5/2022", "rmo") == "5/2022 R"


def test_clean_block_drops_footer_and_keeps_items():
    out = clean_block(["Rada souhlasí:", "1. s nájmem pozemku", "   na dobu neurčitou,",
                       "Stránka 4 z 7", "2. s výpůjčkou"])
    assert out == "Rada souhlasí:\n1. s nájmem pozemku na dobu neurčitou,\n2. s výpůjčkou"


def test_member_matching():
    term = members.term_for(dt.date(2019, 3, 13))
    pool = list(term.lists)
    assert members.match("Ing. F. Vařecha", pool) == "filip-varecha"
    assert members.match("J. Rejda, DiS.", pool) == "jiri-rejda"
    assert members.match("Ing. Lic. Jaroslav Kňava", pool) == "jaroslav-knava"


def test_numbered_resolution_that_failed():
    """18/2019 Z got a number but only 1 vote for – it must not show as passed."""
    m = pipeline.meeting("zmo-2019-03-13-3")
    r = {r["number"]: r for r in m.resolutions}
    assert r["18/2019 Z"]["status"] == "neprijato"
    v = next(v for v in m.votes if v["resolution"] == "18/2019 Z")
    assert (v["pro"], v["proti"], v["zdrzel"], v["ballots_status"]) == (1, 6, 7, "complete")
    by = {b["member"]: (b["choice"], b["provenance"]) for b in v["ballots"]}
    assert by["filip-varecha"] == ("pro", "named")
    assert by["aneta-jelinkova"] == ("omluven", "attendance")


def test_partial_votes_inside_resolution():
    m = pipeline.meeting("rmo-2022-11-02-1")
    parts = [v for v in m.votes if v["resolution"] == "2/2022 R" and v["part"]]
    assert len(parts) == 14
    assert sum(v["outcome"] == "neprijato" for v in parts) == 2
    assert {r["number"]: r["status"] for r in m.resolutions}["2/2022 R"] == "prijato"


@pytest.mark.parametrize("mid", PARSED)
def test_invariants(mid):
    m = pipeline.meeting(mid)
    assert m.status == "ok", pipeline.summarize(m)
    full = ws(store.text(mid))
    for r in m.resolutions:
        # verbatim: every line of the stored text occurs in the PDF text
        for line in r["text"].split("\n"):
            if line and not line.startswith("•"):
                assert ws(line)[:60] in full or len(ws(line)) < 8, (r["number"], line)
    for v in m.votes:
        assert v["passed"] == (v["pro"] >= v["quorum"])
        if v["ballots_status"] == "complete":
            voted = [b for b in v["ballots"] if b["provenance"] != "attendance"]
            assert len(voted) == v["pro"] + v["proti"] + v["zdrzel"] + (v["nehlasoval"] or 0)
        if v["stated_outcome"]:
            assert v["outcome"] == v["stated_outcome"]


def test_revocation_links():
    from petka.usneseni.relations import links
    assert links("Rada: 1. revokuje usnesení č. 39/2023 R, bod 6, 16 a 17 ze dne 15. 3. 2023", "rmo") == \
        [{"type": "rusi", "target": "39/2023 R", "scope": "cast", "detail": "bod 6, 16 a 17"}]
    assert links("Rada ruší své usnesení č. 229/2021 ze dne 25.11.2021", "rmo")[0]["target"] == "229/2021 R"
    assert links("kterou se k datu 31. 12. 2018 ruší směrnice č. 7-1/2015", "rmo") == []


def test_double_surname_across_terms():
    term = members.term_for(dt.date(2021, 3, 10))
    assert members.resolve_attendee("Anna Gudrun Vavrečková", term) == "anna-gudrun-vavreckova"


def test_embedding_pack_roundtrip():
    from petka.usneseni.jobs import _pack, _unpack
    v = [0.5, -1.25, 3.0, 1e-3]
    assert [round(x, 6) for x in _unpack(_pack(v))] == [round(x, 6) for x in v]
