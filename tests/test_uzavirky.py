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
