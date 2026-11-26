"""Supplements of Místa: All The Places, schema.org on the places' webs, the town's list, and
how the export uses them (petka.mista.doplnky, petka.mista.export)."""

import json

import pytest

from petka.mista import doplnky as d
from petka.mista import export


def ld(data) -> str:
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head></html>'


@pytest.mark.parametrize("data, hours", [
    ({"@type": "Dentist", "openingHoursSpecification": [
        {"dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday"], "opens": "07:00", "closes": "15:30"},
        {"dayOfWeek": "https://schema.org/Friday", "opens": "7:00:00", "closes": "12:00"}]},
     "Mo-Th 07:00-15:30; Fr 07:00-12:00"),
    ({"@graph": [{"@type": "WebSite"}, {"@type": "Store", "openingHoursSpecification": {
        "dayOfWeek": ["Saturday", "Monday"], "opens": "09:00", "closes": "12:00"}}]},
     "Mo 09:00-12:00; Sa 09:00-12:00"),
    ({"openingHoursSpecification": [
        {"dayOfWeek": "Monday", "opens": "08:00", "closes": "12:00"},
        {"dayOfWeek": "Monday", "opens": "13:00", "closes": "17:00"},
        {"dayOfWeek": "Tuesday", "opens": "08:00", "closes": "12:00", "validFrom": "2026-12-24", "validThrough": "2026-12-24"}]},
     "Mo 08:00-12:00,13:00-17:00"),
    ({"openingHours": ["Mo-Fr 08:00-17:00", "Sa 09:00-12:00"]}, "Mo-Fr 08:00-17:00; Sa 09:00-12:00"),
    ({"openingHours": "Mo-Su 10:00-22:00"}, "Mo-Su 10:00-22:00"),
    ({"openingHours": "Po-Pá 8-17"}, None),                  # not OSM's syntax: not guessed
    ({"@type": "Organization", "name": "x"}, None),
])
def test_hours_from_schema(data, hours):
    assert d.hours_from_html(ld(data)) == hours


def test_broken_json_does_not_stop_the_next_block():
    html = '<script type="application/ld+json">{nope</script>' + ld({"openingHours": "Mo-Fr 08:00-16:00"})
    assert d.hours_from_html(html) == "Mo-Fr 08:00-16:00"
    assert d.hours_from_html("<p>Po–Pá 8–16</p>") is None


def test_web_hours_reads_only_own_html_pages():
    class R:
        def __init__(self, status=200, ctype="text/html; charset=utf-8", text=ld({"openingHours": "Mo-Fr 08:00-16:00"})):
            self.status_code, self.headers, self.text, self.content = status, {"content-type": ctype}, text, text.encode()

    class C:
        def __init__(self, r):
            self.r, self.urls = r, []

        def get(self, url, **kw):
            self.urls.append(url)
            return self.r

    c = C(R())
    assert d.web_hours(c, "https://zubar.cz") == "Mo-Fr 08:00-16:00"
    assert d.web_hours(c, "https://www.facebook.com/zubar") is None and c.urls == ["https://zubar.cz"]
    assert d.web_hours(C(R(status=404)), "https://zubar.cz") is None
    assert d.web_hours(C(R(ctype="application/pdf")), "https://zubar.cz/x.pdf") is None


PLACES = [
    {"id": "n1", "kind": "potraviny", "name": "Albert", "at": [15.77, 50.03]},
    {"id": "n2", "kind": "potraviny", "name": "Albert", "at": [15.80, 50.03]},
    {"id": "n3", "kind": "posta", "name": "Pošta Pardubice 2", "at": [15.78, 50.03]},
    {"id": "n4", "kind": "lekarna", "name": "Lékárna U Anděla", "at": [15.7701, 50.03]},
]


def test_atp_feature_goes_to_the_nearest_place_of_its_brand():
    f = lambda spider, brand, name, lon, **kw: {"spider": spider, "brand": brand, "name": name, "at": [lon, 50.0301], **kw}  # noqa: E731
    rows = d.match_atp(PLACES, [
        f("albert_cz", "Albert", "Albert Supermarket", 15.7705, hours="Mo-Su 07:00-21:00"),
        f("czech_post_cz", "Česká pošta", "Pardubice 2", 15.7801, hours="Mo-Fr 08:00-18:00", phone="+420 954 530 002"),
        f("dr_max", "Dr.Max", "Dr.Max Pardubice", 15.7702, hours="Mo-Fr 08:00-18:00"),    # no Dr.Max place near
        f("albert_cz", "Albert", "Albert", 15.79, hours="Mo-Su 06:00-22:00"),                 # 700 m from both
    ])
    assert rows == {"n1": {"hours": "Mo-Su 07:00-21:00", "url": None},
                    "n3": {"hours": "Mo-Fr 08:00-18:00", "phone": "+420 954 530 002", "url": None}}


def test_town_list(tmp_path):
    p = tmp_path / "hodiny.json"
    entry = {"id": "w1", "name": "Magistrát", "hours": "Mo,We 08:00-17:00; Tu,Th 08:00-14:00; Fr 08:00-12:00",
             "url": "https://pardubice.eu/uredni-hodiny", "checked": "2026-11-26", "phone": "+420 466 859 111"}
    p.write_text(json.dumps({"places": [entry]}))
    assert d.town_list(p) == {"w1": {"hours": entry["hours"], "url": entry["url"], "phone": "+420 466 859 111"}}
    p.write_text(json.dumps({"places": [{**entry, "hours": "Po-Pá 8-17"}]}))
    with pytest.raises(ValueError, match="w1 Magistrát"):
        d.town_list(p)
    assert isinstance(d.town_list(), dict)       # the list in the repository reads


ROW = {"id": "n1", "kind": "misto", "name": "MUDr. Nová", "what": "Zubař", "address": None, "lon": 15.77, "lat": 50.03,
       "hours": None, "obvody": ["mo1"], "odpad": None, "capacity": None, "phone": None, "web": "https://zubar.cz", "email": None}


def test_export_takes_a_supplement_only_where_osm_has_none():
    sup = {"d_source": "web", "d_hours": "Mo-Fr 07:00-13:00", "d_phone": "+420 466 000 000", "d_web": None, "d_url": "https://zubar.cz"}
    p = export.place({**ROW, **sup})
    assert (p["hours"], p["hours_from"], p["hours_url"], p["phone"], p["web"]) == (
        "Mo-Fr 07:00-13:00", "web", "https://zubar.cz", "+420 466 000 000", "https://zubar.cz")
    osm = export.place({**ROW, **sup, "hours": "Mo-Fr 08:00-12:00"})
    assert osm["hours"] == "Mo-Fr 08:00-12:00" and "hours_from" not in osm and "hours_url" not in osm
    plain = export.place(ROW)
    assert "hours_from" not in plain and plain["hours"] is None
