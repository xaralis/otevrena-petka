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
