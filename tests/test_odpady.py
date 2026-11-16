"""Odpady: the yards read from SmP's Word file, their hours, the kontejner dates from the
transcribed harmonogram, the page and the API (files only, no database)."""

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from petka.odpady import data, dvory, web
from petka.web.app import app

TZ = ZoneInfo("Europe/Prague")
AT = dt.datetime(2026, 11, 16, 13, 40, tzinfo=TZ)        # Monday


def text(rows: list[list[str]]) -> str:
    """The shape of the Word file's text: cells end in BEL, a row in an extra BEL."""
    return "intro\r" + "".join("\x07".join(r) + "\x07\x07" for r in rows)


SAMPLE = text([["komodita", "Příjem SD:"], ["pneumatiky (osobní, bez disků)", "všechny SD mimo Polabiny a Pardubičky"],
               ["eternit, lepenka", "pouze SD Dražkovice **"],
               ["Umístění separačních dvorů", "Provozní doba", "", ""], ["", "den", "od", "do"],
               ["Dražkovice, areál překladiště odpadu", "po, út, čt, pá\rst", "6.30\r6.30", "15.00\r17.00"],
               ["Polabiny, Lonkova ul. – mezi výměníky", "po, so\rút, čt", "8.00\r14.00", "12.00\r18.00"],
               ["Pardubičky, ul. Průmyslová", "út, čt\rso", "12.00\r8.00", "17.00\r12.00"]])


def test_parse_yards():
    ys = {y.name: y for y in dvory.parse(SAMPLE)}
    assert list(ys) == ["Dražkovice", "Polabiny", "Pardubičky"]
    d = ys["Dražkovice"]
    assert d.key == "dvur-drazkovice" and d.address == "areál překladiště odpadu"
    assert d.hours == [{"days": ["po", "út", "čt", "pá"], "from": "6:30", "to": "15:00"}, {"days": ["st"], "from": "6:30", "to": "17:00"}]
    assert d.only_here == ["eternit, lepenka"]
    assert ys["Polabiny"].takes_not == ["pneumatiky"] and ys["Pardubičky"].takes_not == ["pneumatiky"]
    with pytest.raises(ValueError):
        dvory.parse("nic\x07")


def test_status_and_hours():
    y = {"hours": [{"days": ["po", "so"], "from": "8:00", "to": "12:00"}, {"days": ["út", "čt"], "from": "14:00", "to": "18:00"}]}
    assert data.status(y, AT) == (False, "otevře zítra ve 14.00")
    assert data.status(y, AT.replace(hour=9)) == (True, "otevřeno do 12.00")
    assert data.status(y, AT.replace(hour=7)) == (False, "otevře dnes v 8.00")
    assert data.hours_text(y) == "po, so 8.00–12.00, út, čt 14.00–18.00"


def test_drops_from_the_harmonogram():
    ds = [d for d in data.drops(2026) if d.obvod == "mo5" and d.date >= AT.date()]
    assert [(d.date, d.place) for d in ds] == [(dt.date(2026, 12, 14), "Pod Břízkami – Dražkovická"),
                                              (dt.date(2026, 12, 14), "Češkova – Kašparova u školy"),
                                              (dt.date(2026, 12, 16), "Dražkovice – u pošty")]
    assert ds[0].time == "14.00–15.30" and ds[0].point and ds[2].point is None
    assert len(data.places()) >= 59 and all(len(v["point"]) == 2 for v in data.places().values() if v["point"])


def test_the_files_yards_have_places():
    ys = data.yards()["yards"]
    assert len(ys) == 9 and all(y["point"] for y in ys)


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr(web, "_now", lambda: AT)


def test_page(now):
    h = TestClient(app).get("/verejny-prostor/odpady").text
    assert "<h1>Odpady</h1>" in h and "Češkova – Kašparova u školy" in h and "za 4 týdny" in h
    assert "Pardubice V <b>3</b>" in h and "Celé město <b>34</b>" in h
    assert "Sběrné dvory" in h and "otevřeno do 15.00" in h and "Jen tady: eternit" in h
    assert "Polabiny 1 Družstevní" in TestClient(app).get("/verejny-prostor/odpady?kde=mesto").text


def test_api(now):
    c = TestClient(app)
    k = c.get("/api/v1/odpady/kontejnery", params={"obvod": "mo5"}).json()["items"]
    assert [x["date"] for x in k] == ["2026-12-14", "2026-12-14", "2026-12-16"] and k[0]["obvody"] == ["mo5"]
    assert len(c.get("/api/v1/odpady/kontejnery").json()["items"]) == 34
    d = c.get("/api/v1/odpady/dvory").json()
    assert len(d["items"]) == 9 and d["items"][0]["hours"][0]["days"] == ["po", "út", "čt", "pá"]


def test_sorted_waste_map(now, monkeypatch):
    bins = [{"id": "n1", "name": None, "address": "Češkova 12", "lon": 15.77, "lat": 50.02, "odpad": ["papir", "plast"], "obvody": ["mo5"]},
            {"id": "n2", "name": None, "address": None, "lon": 15.78, "lat": 50.03, "odpad": ["sklo"], "obvody": ["mo5"]}]
    monkeypatch.setattr(web, "_bins", lambda obvod: bins)
    h = TestClient(app).get("/verejny-prostor/odpady").text
    assert "Kontejnery na tříděný odpad" in h and 'data-sort="plast">Plast <b>1</b>' in h and "Vše <b>2</b>" in h
    fc = web._bins_fc(bins)
    assert fc["features"][0]["properties"]["what"] == "Plast, Papír" and fc["features"][1]["properties"]["place"] == "Kontejnery"
    monkeypatch.setattr(web, "_bins", lambda obvod: [])
    assert "Kontejnery na tříděný odpad" not in TestClient(app).get("/verejny-prostor/odpady").text


def test_api_svoz():
    c = TestClient(app)
    d = c.get("/api/v1/odpady/svoz", params={"ulice": "Češkova"}).json()
    assert d["date"] == "2022-10-11"
    assert {(x["who"], tuple(x["days"])) for x in d["items"]} == {("popelnice", ("čt",)), ("kontejnery", ("po", "čt"))}
    assert len(c.get("/api/v1/odpady/svoz").json()["items"]) == 479


def test_svoz_section(now, monkeypatch):
    monkeypatch.setattr(web, "_svoz_rows", lambda obvod: [{"name": "Češkova", "slug": "ceskova", "text": "popelnice čtvrtek"}])
    h = TestClient(app).get("/verejny-prostor/odpady").text
    assert "Svoz směsného odpadu" in h and '<a href="/verejny-prostor/ulice/ceskova">Češkova</a><span>popelnice čtvrtek</span>' in h
    from petka.odpady import data
    assert data.svoz_text("Pražská") == "čtvrtek"                  # two parts, the same day
