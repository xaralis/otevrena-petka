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


def test_prompt_carries_today():
    import datetime as dt
    p = digest.prompt([{"title": "VV - OOP Doubravice", "published": "2026-11-04", "valid_until": "2026-11-21",
                        "board": "mo5", "kind": "doprava"}], dt.date(2026, 11, 5))
    assert p.startswith("Dnes je 5. 11. 2026.")


def test_sign_ranges_are_one_item_with_a_name():
    out = digest.signs([{"code": "C4a-c", "text": None, "change": "nova"},
                        {"code": "B24a-b", "text": None, "change": "nova"}])
    assert out[0]["code"] == "C4a–c" and out[0]["name"] == "Přikázaný směr objíždění" and out[0]["image"]
    assert out[1]["name"] == "Zákaz odbočování"


def test_sign_with_a_value_in_brackets():
    out = digest.signs([{"code": "B20a(30)", "text": None, "change": "nova"}])
    assert out[0]["code"] == "B20a" and out[0]["text"] == "30" and out[0]["image"]


def test_card_thumb_prefers_main_sign_then_photo_then_icon():
    d = {"cluster": "doprava", "visual": {"thumb": "nahled.jpg", "signs": [
        {"code": "E13", "image": "E13.jpg", "change": "nova", "name": "Text"},
        {"code": "Z2", "image": "Z2.png", "change": "nova", "name": "Zábrana"},
        {"code": "B28", "image": "B28.png", "change": "nova", "name": "Zákaz zastavení"}]}}
    assert digest.card_thumb(d)["alt"] == "Zákaz zastavení"
    assert digest.card_thumb({"cluster": "stavby", "visual": {"thumb": "nahled.jpg"}})["kind"] == "photo"
    assert digest.card_thumb({"cluster": "poplatky", "visual": {"thumb": "nahled.jpg"}})["kind"] == "icon"
    assert digest.card_thumb({"cluster": "doruceni", "visual": {}}) == {"kind": "icon", "id": "doruceni"}


# --- drafting end to end, with a fake writer ---------------------------------------------------

def _pdf(text: str) -> bytes:
    """A one-page PDF with a text layer (enough for pdftotext)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


NOTICE = {"id": "mo5-7", "kind": "ostatni", "title": "Uzavírka Jana Palacha", "published": "2026-11-10",
          "valid_until": "2026-11-25", "board": "mo5", "department": "OD", "url": "https://deska/7", "is_mo5": True,
          "attachments": [{"url": "https://deska/7/priloha.pdf"}]}

ANSWER = {"cluster": "doprava", "headline": "Uzavírka ulice", "summary": "Ulice bude zavřená.", "where": "Jana Palacha",
          "period": {"from": "2026-11-24", "to": None, "text": "od 24. 11. 2026"}, "action": None, "affects": None,
          "facts": [], "signs": [{"code": "B 1", "text": None, "change": "nova"}], "places": [], "parcels": [],
          "spending": [], "budget": [], "drawing": None, "parking": None, "visual_plan": "Značka.", "reviewer_notes": ""}


def test_draft_runs_end_to_end_with_a_fake_writer(tmp_path, monkeypatch):
    from petka import llm
    monkeypatch.setattr(digest, "DRAFTS", tmp_path / "drafts")
    monkeypatch.setattr(digest, "WORK", tmp_path / "work")
    (tmp_path / "work" / "mo5-7").mkdir(parents=True)
    (tmp_path / "work" / "mo5-7" / "mo5-7-1.pdf").write_bytes(_pdf("Uzavirka od 24. 11. 2026"))  # already downloaded
    seen = []

    class Writer(llm.LLM):
        model_id = "fake:writer"

        def structured_files(self, system, user, files, schema, **kw):
            seen.append({"user": user, "files": [p.name for p in files]})
            return json.loads(json.dumps(ANSWER))

    out = digest.draft([NOTICE], llm=Writer())
    d = json.loads((out / "digest.json").read_text())
    assert seen == [{"user": seen[0]["user"], "files": ["mo5-7-1.pdf"]}] and "Uzavírka Jana Palacha" in seen[0]["user"]
    assert d["status"] == "draft" and d["model"] == "fake:writer" and d["notice_id"] == "mo5-7"
    assert d["problems"] == []                          # the date is in the document
    assert [s["code"] for s in d["visual"]["signs"]] == ["B1"] and d["visual"]["photo"] is None
    assert d["source"]["url"] == "https://deska/7"
