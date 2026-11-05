import json
from petka.uredni_deska import digest


def n(id, title, board="mo5", published="2026-10-20"):
    return {"id": id, "title": title, "board": board, "published": published}


def test_annexes_group_with_their_notice():
    items = [n("mo5-1", "Schválená 4. změna rozpočtu MO Pardubice V na r. 2026 a schválená rozpočtová opatření"),
             n("mo5-2", "Schválená 4. změna rozpočtu MO Pardubice V na r. 2026 a schválená RO - Příloha č. 1"),
             n("mo5-3", "Příloha č. 2 směrnice č. 28/2025 – Smlouva o poskytnutí dotace"),
             n("mo5-4", "Schválená směrnice č. 28/2025: Zásady a program pro poskytování dotací"),
             n("mo5-5", "VV - OOP stanovení přechodné úpravy provozu - Češkova")]
    gs = {g[0]["id"]: [x["id"] for x in g] for g in digest.groups(items)}
    assert gs["mo5-1"] == ["mo5-1", "mo5-2"]
    assert gs["mo5-4"] == ["mo5-4", "mo5-3"]          # the directive leads, its annex follows
    assert gs["mo5-5"] == ["mo5-5"]


def _draft(**kw):
    d = {"headline": "Nové vyhrazené místo", "summary": "", "where": None, "affects": None, "facts": [],
         "action": None, "signs": [], "period": {"from": None, "to": None, "text": None}}
    d.update(kw)
    return d


TEXT = """Žadatel: Petr Novák, Češkova 1761, 53002 Pardubice – fyzická osoba
IP12 se symbolem č. 225 a textem „7E35810“
Platnost úpravy: 24. 10. 2026 – 23. 10. 2031"""


def test_check_catches_personal_data():
    assert digest.check(_draft(summary="Místo pro pana Nováka"), TEXT)   # inflected forms too
    probs = digest.check(_draft(summary="Žádal Petr Novák, SPZ 7E3 5810"), TEXT)
    assert any("jméno" in p for p in probs) and any("SPZ" in p for p in probs)
    assert digest.check(_draft(facts=[{"label": "Kdo", "value": "nar. 1. 1. 1950"}]), TEXT)


def test_check_dates_must_be_in_the_document():
    ok = _draft(period={"from": "2026-10-24", "to": "2031-10-23", "text": None})
    assert digest.check(ok, TEXT) == []
    bad = _draft(action={"what": "Připomínky", "deadline": "2026-12-04", "how": ""})
    assert digest.check(bad, TEXT) == ["datum lhůta 2026-12-04 v dokumentu není doslova"]


def test_delivery_card_names_nobody():
    d = digest.delivery([{"id": "mo5-9", "title": "… jejímž adresátem je pan Jan Novák", "valid_until": "2026-12-18"}])
    assert "Novák" not in str(d) and d["cluster"] == "doruceni"


def test_sign_codes_normalised():
    s = digest.signs([{"code": "IP 12", "text": None, "change": "nova"}, {"code": "V-10E", "text": None, "change": "odstranit"}])
    assert [x["code"] for x in s] == ["IP12", "V10e"]


def test_same_sign_removed_and_added_is_one_change():
    s = digest.signs([{"code": "IP12", "text": None, "change": "zustava"},
                      {"code": "E13", "text": None, "change": "odstranit"},
                      {"code": "E 13", "text": None, "change": "nova"}])
    assert [(x["code"], x["change"]) for x in s] == [("IP12", "zustava"), ("E13", "vymena")]


def test_change_pairs_one_to_one():
    s = digest.signs([{"code": "E13", "text": "NÁSTUPNÍ PLOCHA", "change": "odstranit"},
                      {"code": "E13", "text": "NÁSTUPNÍ PLOCHA PRO POŽÁRNÍ TECHNIKU", "change": "nova"},
                      {"code": "E13", "text": "MAX. 30 min", "change": "nova"},
                      {"code": "IP12", "text": None, "change": "odstranit"}])
    assert [(x["text"], x["change"]) for x in s] == [("NÁSTUPNÍ PLOCHA PRO POŽÁRNÍ TECHNIKU", "vymena"),
                                                     ("MAX. 30 min", "nova"), (None, "odstranit")]


def test_delivery_source_keeps_no_title_or_link():
    n = {"title": "Oznámení o uložení písemnosti, adresát pan Jan Novák", "url": "https://x/?id=1",
         "board": "mo5", "is_mo5": True}
    s = digest._source(n, "doruceni")
    assert "Novák" not in json.dumps(s, ensure_ascii=False) and s["url"] == ""
    assert digest._source(n, "doprava")["title"] == n["title"]


def _card(root, nid, mo5, status="draft"):
    (root / nid).mkdir(parents=True)
    (root / nid / "digest.json").write_text(json.dumps(
        {"notice_id": nid, "status": status, "cluster": "doprava",
         "source": {"title": "t", "url": "u", "board": "mmp", "mo5": mo5}}))


def test_publish_refuses_cards_outside_mo5_and_reject_takes_cards_down(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DRAFTS", tmp_path / "drafts")
    monkeypatch.setattr(digest, "DIGESTS", tmp_path / "digests")
    _card(tmp_path / "drafts", "mmp-1", False)
    _card(tmp_path / "drafts", "mo5-2", True)
    report = digest.publish(["mmp-1", "mo5-2"])
    assert report[0]["error"] and report[1] == "mo5-2"
    assert not (tmp_path / "digests" / "mmp-1").exists()
    assert digest.reject(["mo5-2"]) == ["mo5-2"]
    assert not (tmp_path / "digests" / "mo5-2").exists()
    assert json.loads((tmp_path / "drafts" / "mo5-2" / "digest.json").read_text())["status"] == "rejected"


def test_only_current_notices_get_cards():
    import datetime as dt
    today = dt.date(2026, 11, 5)
    assert digest.recent([{"published": "2026-10-20"}], today)
    assert not digest.recent([{"published": "2022-03-21"}], today)
    assert digest.over({"period": {"to": "2026-10-11"}, "action": None}, today)
    assert not digest.over({"period": {"to": "2026-10-11"}, "action": {"deadline": "2026-11-30"}}, today)
    assert not digest.over({"period": {"to": "2026-11-13"}, "action": None}, today)
    assert not digest.over({"period": {"to": None}, "action": None}, today)
