"""The obvod a request is for comes from its host; today every host is MO V (ADR 0001). Data
sources take the whole town or `?obvod=` (ADR 0002): parsing, matching, SQL and the dependency."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from petka import obvody
from petka.uredni_deska import source
from petka.web.app import app


def test_from_host():
    assert obvody.from_host("otevrenapetka.cz") is obvody.MO5
    assert obvody.from_host("www.otevrenapetka.cz:443") is obvody.MO5
    assert obvody.from_host("127.0.0.1:8080") is obvody.MO5
    assert obvody.from_host("neznamy.example") is obvody.DEFAULT
    assert obvody.from_host(None) is obvody.DEFAULT and obvody.from_host("[::1]:80") is obvody.DEFAULT


def test_mo5_record_matches_what_the_sections_used():
    o = obvody.MO5
    assert (o.id, o.gordic, o.district_id, o.momc) == ("mo5", "05274046", 5, 557072)
    b = source.BY_ID["mo5"]
    assert (b.name, b.url, b.page) == ("Úřední deska MO Pardubice V",
                                       "https://pardubice.eu/export/official-board-json?district_id=5",
                                       "https://pardubice.eu/uredni-deska/obvody?district=mo5")
    from petka.rozpocet import queries, source as rsource
    assert queries.UNIT == o.id and rsource.UNITS[o.id] == o.gordic


def test_request_knows_its_obvod():
    r = TestClient(app).get("/site.webmanifest", headers={"host": "otevrenapetka.cz"})
    assert r.json()["name"] == "Otevřená Pětka"


# --- the town and the filter of data sources ------------------------------------------------

def test_town_registry():
    assert [o.id for o in obvody.TOWN] == [f"mo{i}" for i in range(1, 9)]
    assert obvody.TOWN_BY_ID["mo4"].abbr == "MO Pardubice IV" and obvody.TOWN_BY_ID["mo8"].name == "Městský obvod Pardubice VIII"
    assert len({o.momc for o in obvody.TOWN}) == 8
    for o in obvody.OBVODY:                       # every served obvod is one of the town's
        t = obvody.TOWN_BY_ID[o.id]
        assert (t.name, t.abbr, t.momc) == (o.name, o.abbr, o.momc)


def test_parse():
    F = obvody.ObvodFilter
    assert obvody.parse(None) == obvody.parse("") == obvody.parse(" , ") == F() and F().whole_town
    assert obvody.parse("mo5") == F(("mo5",))
    assert obvody.parse(" MO5 , mo1,mo5") == F(("mo1", "mo5"))     # the town's order, once each
    with pytest.raises(ValueError, match="Neznámý obvod: mo9, x. Platné jsou mo1, mo2, mo3"):
        obvody.parse("mo1,x,mo9")
    assert F.only("mo5") == F(("mo5",)) and F.only() == F()


def test_matches():
    F = obvody.ObvodFilter
    assert F().matches([]) and F().matches(["mo2"])                # the whole town takes everything
    assert F(("mo4", "mo5")).matches(["mo5", "mo6"]) and not F(("mo4",)).matches(["mo5"])
    assert not F(("mo5",)).matches([])


def test_sql():
    assert obvody.ObvodFilter().sql("p.obvody", 0.05) == ("TRUE", [])
    cond, params = obvody.ObvodFilter(("mo1", "mo5")).sql("p.obvody", 0.05)
    assert "jsonb_each_text(p.obvody)" in cond and cond.count("%s") == 2 and params == [["mo1", "mo5"], 0.05]


def test_sql_of_a_column_with_one_obvod():
    assert obvody.ObvodFilter().sql_one("obvod") == ("TRUE", [])
    assert obvody.ObvodFilter(("mo1", "mo5")).sql_one("obvod") == ("obvod = ANY(%s)", [["mo1", "mo5"]])


def test_share_ids():
    assert obvody.share_ids({"mo5": 0.9, "mo4": 0.07, "mo6": 0.03}, 0.05) == ["mo4", "mo5"]
    assert obvody.share_ids(None, 0.05) == [] and obvody.share_ids({}, 0.05) == []


def test_dependency():
    app_ = FastAPI()

    @app_.get("/x")
    def x(obvod: obvody.ObvodParam):
        return {"ids": list(obvod.ids)}

    c = TestClient(app_)
    assert c.get("/x").json() == {"ids": []}
    assert c.get("/x", params={"obvod": "mo5, MO4"}).json() == {"ids": ["mo4", "mo5"]}
    r = c.get("/x", params={"obvod": "mo9"})
    assert r.status_code == 422 and "Platné jsou mo1" in r.json()["detail"]
    p = c.get("/openapi.json").json()["paths"]["/x"]["get"]["parameters"][0]
    assert p["name"] == "obvod" and p["in"] == "query" and not p.get("required")
    assert p["description"] == obvody.OBVOD_DOC
