"""Uzavírky: the NDIC snapshot parsed (official samples of cz-ndic_d2-common-v1.1, tests/data/ndic)
and placed in a town (a fake one, no database)."""

from pathlib import Path

import pytest

from petka.cisteni.geocode import to_m
from petka.uzavirky import geo, jobs, source

DATA = Path(__file__).parent / "data" / "ndic"


def test_parse_a_closure():
    published, recs = source.parse((DATA / "restriction-bkom.xml").read_bytes())
    assert published is not None and len(recs) == 1
    r = recs[0]
    assert (r.kind, r.details, r.version) == ("RoadOrCarriagewayOrLaneManagement", ["roadClosed"], 2)
    assert r.comment.startswith("silnice I/41 (ulice Dornych), Brno-jih") and "\n" not in r.comment
    assert r.ends_at is not None and r.starts_at is not None and r.ends_at > r.starts_at
    assert len(r.points) == 2 and all(16.5 < lon < 16.7 and 49.1 < lat < 49.3 for lon, lat in r.points)   # Brno


def test_parse_an_accident():
    _, recs = source.parse((DATA / "accident.xml").read_bytes())
    assert {r.kind for r in recs} == {"Accident", "AuthorityOperation", "VehicleObstruction"}
    acc = next(r for r in recs if r.kind == "Accident")
    assert "accidentInvolvingHeavyLorries" in acc.details
    assert {r.source for r in recs} == {"", "Policie České republiky"}          # not every record names it
    assert len({r.situation for r in recs}) == 1          # one situation, three records


def test_parse_refuses_a_doctype():
    with pytest.raises(ValueError):
        source.parse(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "a">]><x/>')


def _town() -> geo.Town:
    street = {"type": "LineString", "coordinates": [[15.760, 50.034], [15.770, 50.034]]}
    west = {"type": "Polygon", "coordinates": [[[15.755, 50.030], [15.765, 50.030], [15.765, 50.038], [15.755, 50.038], [15.755, 50.030]]]}
    east = {"type": "Polygon", "coordinates": [[[15.765, 50.030], [15.775, 50.030], [15.775, 50.038], [15.765, 50.038], [15.765, 50.030]]]}
    return geo.Town({"mo5": to_m(west), "mo4": to_m(east)}, [("Wolkerova", to_m(street))])


def test_place_on_the_street_and_shares():
    town = _town()
    g, method, name = geo.place([(15.761, 50.0341), (15.764, 50.0339)], town)
    assert (method, name, g["type"]) == ("street", "Wolkerova", "LineString")
    assert all(abs(lat - 50.034) < 1e-5 for _, lat in g["coordinates"])     # on the street, not between the ends
    assert geo.shares(g, town) == {"mo5": 1.0}
    g, _, _ = geo.place([(15.762, 50.034), (15.768, 50.034)], town)          # across the border
    s = geo.shares(g, town)
    assert set(s) == {"mo5", "mo4"} and abs(s["mo5"] - 0.5) < 0.05


def test_place_on_a_street_split_at_crossings():
    parts = {"type": "MultiLineString", "coordinates": [[[15.760, 50.034], [15.763, 50.034]], [[15.763, 50.034], [15.768, 50.034]]]}
    town = geo.Town(_town().obvody, [("Wolkerova", to_m(parts))])
    g, method, _ = geo.place([(15.761, 50.034), (15.766, 50.034)], town)   # the ends on two pieces of RÚIAN
    assert method == "street" and len(g["coordinates"]) == 3                 # through the crossing


def test_place_an_end_in_the_crossing_beyond_the_line():
    town = _town()                                   # the street ends at 15.770; 0.0004° lon ≈ 29 m further
    g, method, _ = geo.place([(15.762, 50.034), (15.7704, 50.034)], town)
    assert method == "street"
    g, method, _ = geo.place([(15.762, 50.0343), (15.7704, 50.0343)], town)   # both 33 m off: not on it
    assert method == "straight"


def test_place_off_the_street_and_outside():
    town = _town()
    g, method, _ = geo.place([(15.761, 50.0365), (15.763, 50.0366)], town)  # 280 m north of the street
    assert method == "straight" and g["coordinates"] == [[15.761, 50.0365], [15.763, 50.0366]]
    assert geo.place([(15.761, 50.034)], town)[1] == "point"
    assert geo.place([], town) == (None, "none", None)
    g, _, _ = geo.place([(16.60, 49.19), (16.61, 49.19)], town)            # Brno
    assert geo.shares(g, town) == {}


def test_update_waits_for_settings(monkeypatch):
    for k in ("NDIC_URL", "NDIC_USER", "NDIC_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert jobs.update() == {"skipped": "no NDIC settings", "failures": []}


# --- the page and the API (petka.uzavirky.queries, web) -------------------------------------

import datetime as dt

from fastapi.testclient import TestClient

from petka.uzavirky import queries as uq
from petka.web.app import app

UTC = dt.timezone.utc
AT = dt.datetime(2026, 11, 16, 12, tzinfo=UTC)
WOLK = "ulice Wolkerova, Pardubice V, uzavřeno, oprava povrchu vozovky, Od 30.09.2026 16:00 Do 30.11.2026 16:00, Úplná uzavírka provozu"
LINE = {"type": "LineString", "coordinates": [[15.7585, 50.026], [15.7547, 50.0263]]}


def rec(id, situation, kind, details, starts, ends, comment=WOLK, method="street", obvody=None, geometry=LINE):
    return {"id": id, "situation": situation, "kind": kind, "details": details, "starts_at": starts, "ends_at": ends,
            "comment": comment, "geometry": geometry, "method": method, "obvody": obvody or {"mo5": 1.0}}


ROWS = [rec("a1", "A", "RoadOrCarriagewayOrLaneManagement", ["roadClosed"], dt.datetime(2026, 9, 30, 14, tzinfo=UTC),
            dt.datetime(2026, 11, 30, 15, tzinfo=UTC)),
        rec("a2", "A", "MaintenanceWorks", ["resurfacingWork"], dt.datetime(2026, 9, 30, 14, tzinfo=UTC),
            dt.datetime(2026, 11, 30, 15, tzinfo=UTC), method="straight"),
        rec("b1", "B", "RoadOrCarriagewayOrLaneManagement", ["laneClosures"], dt.datetime(2026, 11, 23, tzinfo=UTC),
            dt.datetime(2026, 12, 4, tzinfo=UTC), comment="silnice II/355 (ulice Dašická), Pardubice III, stavební práce",
            obvody={"mo3": 0.95, "mo5": 0.05})]


def test_closures_one_per_situation():
    cs = uq.closures(ROWS, AT)
    assert [c.id for c in cs] == ["A", "B"]                     # going on first, then to come
    a, b = cs
    assert (a.place, a.what, a.closed, a.method, a.records) == ("Wolkerova", "Uzavřeno, oprava povrchu", True, "street", ["a1", "a2"])
    assert a.now(AT) and not b.now(AT)
    assert (b.place, b.what, b.obvody) == ("Silnice II/355 (ulice Dašická)", "Uzavřený jízdní pruh", ["mo3"])


@pytest.fixture
def fake(monkeypatch):
    from petka.uzavirky import web
    monkeypatch.setattr(uq, "rows", lambda where, now: [r for r in ROWS if where.matches(uq.obvody.share_ids(r["obvody"], uq.MIN_SHARE))])
    monkeypatch.setattr(uq, "checked", lambda: AT)
    monkeypatch.setattr(web, "_now", lambda: AT)


def test_page(fake):
    h = TestClient(app).get("/verejny-prostor/uzavirky").text
    assert "Kde se teď nedá projet?" in h and "<b>Wolkerova</b>" in h and "do 30. 11." in h
    assert WOLK in h and uq.ATTRIBUTION in h                     # NDIC's text unchanged, with its source
    assert "Dašická" not in h                                    # MO III's
    assert "Chystá se <b>0</b>" in h


def test_api(fake):
    r = TestClient(app).get("/api/v1/uzavirky", params={"obvod": "mo3"})
    d = r.json()
    assert r.headers["content-type"].startswith("application/geo+json")
    assert d["attribution"] == uq.ATTRIBUTION and d["terms"] and "ŘSD" in d["note"]
    assert [f["properties"]["place"] for f in d["features"]] == ["Silnice II/355 (ulice Dašická)"]
    assert d["features"][0]["properties"]["now"] is False
    assert len(TestClient(app).get("/api/v1/uzavirky").json()["features"]) == 2
