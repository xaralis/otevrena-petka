"""The obvod a request is for comes from its host; today every host is MO V (ADR 0001)."""

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
    assert (o.id, o.gordic, o.district_id) == ("mo5", "05274046", 5)
    b = source.BY_ID["mo5"]
    assert (b.name, b.url, b.page) == ("Úřední deska MO Pardubice V",
                                       "https://pardubice.eu/export/official-board-json?district_id=5",
                                       "https://pardubice.eu/uredni-deska/obvody?district=mo5")
    from petka.rozpocet import queries, source as rsource
    assert queries.UNIT == o.id and rsource.UNITS[o.id] == o.gordic


def test_request_knows_its_obvod():
    r = TestClient(app).get("/site.webmanifest", headers={"host": "otevrenapetka.cz"})
    assert r.json()["name"] == "Otevřená Pětka"
