import json

from petka.uredni_deska import digest, score


def marks(p=5, u=5, s=5, o=5):
    def m(v):
        return {"score": v, "reason": "x"}
    return {"presnost": m(p), "uplnost": m(u), "srozumitelnost": m(s), "obrazky": m(o)}


def res(**kw):
    return {"marks": marks(), "blockers": [], "dates": [], "summary": "Sedí.", "fixes": [], **kw}


CARD = {"action": None, "problems": []}


def test_nothing_to_warn_about_is_green():
    q = score.evaluate(res(), CARD)
    assert q["level"] == "spolehlive" and q["passed"] and q["issues"] == []


def test_minor_inaccuracy_stays_green_but_is_said():
    q = score.evaluate(res(marks=marks(p=4)), CARD)
    assert q["level"] == "spolehlive" and q["issues"] == ["x"]


def test_a_picture_that_merely_helps_little_is_no_warning():
    assert score.evaluate(res(marks=marks(o=3)), CARD)["level"] == "spolehlive"
    assert score.evaluate(res(marks=marks(o=None)), CARD)["level"] == "spolehlive"


def test_missing_or_unclear_goes_out_with_a_warning():
    q = score.evaluate(res(marks=marks(u=3)), CARD)
    assert q["level"] == "pozor" and q["passed"] and q["issues"] == ["Úplnost: x"]
    assert score.evaluate(res(marks=marks(s=2)), CARD)["level"] == "pozor"
    assert score.evaluate(res(marks=marks(o=2)), CARD)["level"] == "pozor"


def test_inaccurate_card_waits_for_a_person_however_good_the_rest():
    q = score.evaluate(res(marks=marks(p=3)), CARD)
    assert q["level"] == "spatne" and not q["passed"]


def test_very_poor_dimension_waits_for_a_person():
    assert not score.evaluate(res(marks=marks(u=1)), CARD)["passed"]
    assert not score.evaluate(res(marks=marks(o=1)), CARD)["passed"]


def test_blockers_stop_a_perfect_card():
    q = score.evaluate(res(blockers=[{"kind": "obrazek_osobni_udaje", "what": "na fotce"}]), CARD)
    assert q["level"] == "spatne" and "na fotce" in q["issues"][0]


def test_personal_data_found_by_the_check_stops_it_a_literal_date_warning_doesnt():
    assert not score.evaluate(res(), {"action": None, "problems": ["vypadá to na SPZ"]})["passed"]
    assert score.evaluate(res(), {"action": None, "problems": ["datum do 2026-12-18 v dokumentu není doslova"]})["passed"]


def test_deadline_must_be_verified():
    card = {"action": {"what": "Připomínky", "deadline": "2026-11-26", "how": ""}, "problems": []}
    assert not score.evaluate(res(), card)["passed"]
    ok = {"field": "lhuta", "value": "2026-11-26", "verdict": "spocitano_spravne", "evidence": "12. 10. + 15 + 30"}
    assert score.evaluate(res(dates=[ok]), card)["passed"]
    assert not score.evaluate(res(dates=[{**ok, "verdict": "nelze_overit"}]), card)["passed"]
    assert not score.evaluate(res(dates=[{**ok, "verdict": "spatne"}]), card)["passed"]


def test_rewrite_only_when_it_can_help():
    bad = score.evaluate(res(marks=marks(p=2), fixes=["Oprav datum"]), CARD)
    assert score.retryable(bad)
    assert not score.retryable(score.evaluate(res(), CARD))
    assert not score.retryable(score.evaluate(res(marks=marks(p=2)), CARD))     # nothing to fix by
    outside = score.evaluate(res(blockers=[{"kind": "mimo_obvod", "what": "x"}], fixes=["y"]), CARD)
    assert not score.retryable(outside)


# --- the pipeline, without the models --------------------------------------------------------

def setup(tmp_path, monkeypatch, reviews, kind="ostatni"):
    monkeypatch.setattr(digest, "DRAFTS", tmp_path / "drafts")
    monkeypatch.setattr(digest, "DIGESTS", tmp_path / "digests")
    monkeypatch.setattr(digest, "WORK", tmp_path / "work")
    group = [{"id": "mo5-1", "kind": kind, "title": "T", "members": []}]
    calls = {"drafts": [], "reviews": 0}

    def fake_draft(g, fixes=None):
        calls["drafts"].append(fixes)
        out = digest.DRAFTS / "mo5-1"
        out.mkdir(parents=True, exist_ok=True)
        (out / "digest.json").write_text(json.dumps({
            "notice_id": "mo5-1", "members": [], "status": "draft", "cluster": "doruceni" if kind == "doruceni" else "ostatni",
            "headline": "H", "summary": "S", "action": None, "problems": [], "source": {"title": "T", "url": "u", "mo5": True}}))
        return out

    def fake_review(card, files, images):
        calls["reviews"] += 1
        return score.evaluate(reviews[calls["reviews"] - 1], card)

    monkeypatch.setattr(digest, "draft", fake_draft)
    monkeypatch.setattr(digest.score, "review", fake_review)
    monkeypatch.setattr(digest, "download", lambda g: [])
    (tmp_path / "work" / "mo5-1").mkdir(parents=True)
    return group, calls


def test_good_card_goes_out_marked_as_checked_by_the_model(tmp_path, monkeypatch):
    group, calls = setup(tmp_path, monkeypatch, [res()])
    row = digest._settle(group)
    d = json.loads((digest.DIGESTS / "mo5-1" / "digest.json").read_text())
    assert row["state"] == "vydano" and row["level"] == "spolehlive"
    assert d["status"] == "published" and d["reviewed_by"] == "model" and d["quality"]["attempts"] == 1
    assert calls["drafts"] == [None]


def test_poor_card_gets_one_rewrite_with_the_findings(tmp_path, monkeypatch):
    group, calls = setup(tmp_path, monkeypatch, [res(marks=marks(p=2), fixes=["Oprav datum"]), res()])
    assert digest._settle(group)["state"] == "vydano"
    assert calls["drafts"] == [None, ["Oprav datum"]]


def test_card_that_stays_poor_waits_for_a_person_with_the_reason(tmp_path, monkeypatch):
    poor = res(marks=marks(p=2), fixes=["Oprav datum"])
    group, calls = setup(tmp_path, monkeypatch, [poor, poor])
    row = digest._settle(group)
    assert row["state"] == "ceka" and any("Přesnost" in w for w in row["why"])
    assert calls["reviews"] == 2 and not (digest.DIGESTS / "mo5-1").exists()
    assert json.loads((digest.DRAFTS / "mo5-1" / "digest.json").read_text())["status"] == "draft"


def test_delivery_uses_no_model_and_shows_no_score(tmp_path, monkeypatch):
    group, calls = setup(tmp_path, monkeypatch, [], kind="doruceni")
    row = digest._settle(group)
    d = json.loads((digest.DIGESTS / "mo5-1" / "digest.json").read_text())
    assert row["state"] == "vydano" and calls["reviews"] == 0
    assert d["quality"]["method"] == "sablona" and "level" not in d["quality"]


def test_card_outside_mo5_is_not_published_even_with_a_good_score(tmp_path, monkeypatch):
    group, _ = setup(tmp_path, monkeypatch, [res()])
    real = digest.draft

    def outside(g, fixes=None):
        out = real(g, fixes)
        d = json.loads((out / "digest.json").read_text())
        d["source"]["mo5"] = False
        (out / "digest.json").write_text(json.dumps(d))
        return out
    monkeypatch.setattr(digest, "draft", outside)
    assert digest._settle(group)["state"] == "ceka"
    assert not (digest.DIGESTS / "mo5-1").exists()


def test_caution_card_is_rewritten_once_then_waits_for_a_person(tmp_path, monkeypatch):
    caution = res(marks=marks(u=3), fixes=["Doplň místo"])
    group, calls = setup(tmp_path, monkeypatch, [caution, caution])
    row = digest._settle(group)
    assert row["state"] == "ceka" and row["level"] == "pozor" and calls["reviews"] == 2
    assert not (digest.DIGESTS / "mo5-1").exists()


def test_caution_card_that_turns_green_goes_out(tmp_path, monkeypatch):
    group, _ = setup(tmp_path, monkeypatch, [res(marks=marks(u=3), fixes=["Doplň místo"]), res()])
    assert digest._settle(group)["state"] == "vydano"


def test_personal_data_in_the_reviewers_sentences_never_reaches_the_page(tmp_path, monkeypatch):
    group, _ = setup(tmp_path, monkeypatch, [res(summary="Místo pro SPZ 7E3 5810.")])
    assert digest._settle(group)["state"] == "ceka"
    q = json.loads((digest.DRAFTS / "mo5-1" / "digest.json").read_text())["quality"]
    assert q["summary"] == "" and not q["passed"]


def test_unscored_draft_is_picked_up_again(tmp_path, monkeypatch):
    group, calls = setup(tmp_path, monkeypatch, [res()])
    digest.draft(group)
    assert list(digest._waiting()) == ["mo5-1"]
    calls["drafts"].clear()
    assert digest._settle(group)["state"] == "vydano"
    assert calls["drafts"] == []        # the existing draft, no new writing


def test_person_approving_a_held_card_turns_it_green(tmp_path, monkeypatch):
    poor = res(marks=marks(p=2), fixes=["Oprav datum"])
    group, _ = setup(tmp_path, monkeypatch, [poor, poor])
    digest._settle(group)
    assert digest.publish(["mo5-1"]) == ["mo5-1"]
    d = json.loads((digest.DIGESTS / "mo5-1" / "digest.json").read_text())
    assert d["reviewed_by"] == "clovek" and d["quality"]["level"] == "spolehlive"


def test_breakdown_gives_each_dimension_a_state_and_keeps_other_problems_apart():
    q = score.evaluate(res(marks=marks(p=4, u=3, s=5, o=None),
                           blockers=[{"kind": "spatny_termin", "what": "jiný rok"}]), CARD)
    b = score.breakdown(q)
    assert b["main"] == ["Špatné datum nebo lhůta: jiný rok"]
    assert {r["label"]: r["state"] for r in b["rows"]} == {"Přesnost": "minor", "Úplnost": "caution", "Srozumitelnost": "ok"}
    assert score.breakdown(score.evaluate(res(marks=marks(p=2)), CARD))["rows"][0]["state"] == "wrong"
    assert score.breakdown(score.evaluate(res(marks=marks(u=3)), CARD))["main"] == []


def test_popover_explains_ai_and_what_was_found():
    from petka.web.render import tpl
    mod = tpl.env.get_template("uredni_deska/_macros.html").module
    html = mod.quality_light({"quality": score.evaluate(res(marks=marks(u=3)), CARD)})
    assert "q-pozor" in html and "Buďte obezřetní" in html and 'tabindex="0"' in html
    assert "umělá inteligence" in html and "Závazné je vždy úřední oznámení" in html
    assert "Je tam všechno důležité?" in html and ">pozor<" in html
    assert "Sedí údaje s originálem?" in html and "v pořádku" in html
    assert "problém" in mod.quality_light({"quality": score.evaluate(res(marks=marks(p=2)), CARD)})
    person = mod.quality_light({"quality": {"level": "spolehlive", "approved_by_person": True, "issues": []}})
    assert "schválil" in person and "q-row" not in person
    assert mod.quality_light({"quality": score.template()}).strip() == ""
    assert mod.quality_light({}).strip() == ""


def test_red_shows_to_reviewers_but_not_on_a_published_card():
    from petka.web.render import tpl
    mod = tpl.env.get_template("uredni_deska/_macros.html").module
    q = score.evaluate(res(marks=marks(p=2)), CARD)
    assert "q-spatne" in mod.quality_light({"quality": q, "status": "draft"})
    assert mod.quality_light({"quality": q, "status": "published"}).strip() == ""
