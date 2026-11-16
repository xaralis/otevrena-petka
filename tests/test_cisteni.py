"""Čištění ulic: the sheet is parsed and mended (continuation rows, a stray year, times), places
are classified and shortened, the geocoder cuts streets and finds obvody on made-up streets
(a local plane in metres around Pardubice), the Czech words, the iCalendar feed, and the pages
and API over fixture items. Tests touching the database skip without one."""

import datetime as dt
import io
import json

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

from petka import db, obvody
from petka.cisteni import geocode, ics, jobs, places, queries, source, web, words
from petka.web.app import app

D = dt.date


# --- the sheet ------------------------------------------------------------------------------

def sheet(rows) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Typ čištění", "Datum čištění", "Čas čištění", "Den", "Týden", "Místo"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_excel_url_is_found_by_pattern():
    html = '<a href="/x.pdf">x</a><a href="/data/files/harmonogram-blokoveho-cisteni-a-strojniho-cisteni-s-dz-1775820984.xlsx?v1">'
    assert source.excel_url(html, "https://smp-pce.cz/udrzba-komunikaci/cisteni-komunikaci") == \
        "https://smp-pce.cz/data/files/harmonogram-blokoveho-cisteni-a-strojniho-cisteni-s-dz-1775820984.xlsx?v1"
    with pytest.raises(ValueError):
        source.excel_url("<p>nic</p>")


def test_parse_and_clean_mend_the_sheet():
    x = sheet([
        ["BLK", dt.datetime(2026, 3, 11), "Blokové čištění od 7:00 hod.", None, None, "Wolkerova\xa0 v celé délce"],
        ["BLK", dt.datetime(2026, 3, 12), "Blokové čištění od 6:00hod", None, None, "Teplého od ul. A"],
        [None, None, None, None, None, "k ul. B - obě strany komunikace"],          # continuation
        [None, None, None, None, None, "a ještě kus"],                              # and another
        ["BLK", dt.datetime(2025, 3, 13), "Blokové čištění před 6 hod.", None, None, "Lexova"],   # stray year
        [None, None, None, None, None, "Blokové čištění vybraných lokalit"],         # heading after a gap? no:
        ["BLK", dt.datetime(2026, 3, 16), "Blokové čištění od 6:00 hod.ou", None, None, "Gorkého"],
        ["BLK", dt.datetime(2026, 3, 17), "Blokové čištění", None, None, "Jiránkova"],
    ])
    raw = source.parse(x)
    assert [r.row for r in raw] == [2, 3, 4, 5, 6, 7, 8, 9]
    rows, issues = source.clean(raw)
    assert [r.place for r in rows] == ["Wolkerova v celé délce", "Teplého od ul. A k ul. B - obě strany komunikace a ještě kus",
                                       "Lexova", "Gorkého", "Jiránkova"]
    assert rows[1].merged == [4, 5]
    assert rows[2].date == D(2026, 3, 13) and rows[2].year_fixed
    assert [(r.time, r.before) for r in rows] == [(dt.time(7), False), (dt.time(6), False), (dt.time(6), True),
                                                  (dt.time(6), False), (None, False)]
    kinds = [i[0] for i in issues]
    assert kinds.count("continuation") == 2 and kinds.count("year") == 1 and kinds.count("dropped") == 1


def test_parse_refuses_a_moved_header():
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["Místo", "Datum", "Čas"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError, match="header"):
        source.parse(buf.getvalue())


@pytest.mark.parametrize("when, want", [
    ("Blokové čištění od 7:00 hod.", (dt.time(7), False)),
    ("Blokové čištění od 8:00hod", (dt.time(8), False)),
    ("Blokové čištění před 6 hod.", (dt.time(6), True)),
    ("Blokové čištění od 6:30 h", (dt.time(6, 30), False)),
    ("Blokové čištění", (None, False)),
])
def test_times(when, want):
    assert source.parse_time(when) == want


# --- places as text -------------------------------------------------------------------------

def test_key_side_and_pattern():
    k = places.place_key("Wolkerova  od ul.Čs. armády k\xa0ul. Lexova – obě strany komunikace")
    assert k == "wolkerova od ul. cs. armady k ul. lexova - obe strany komunikace"
    assert places.side(k) == ("obe", "wolkerova od ul. cs. armady k ul. lexova")
    assert places.side("milheimova od ul. v raji k ul. prazska - prava strana komunikace")[0] == "prava"
    assert places.side("lexova")[0] is None
    assert places.place_key("parkoviště u č.p.2122") == "parkoviste u c. p. 2122"
    assert places.pattern(k) == "usek od-k"
    assert places.pattern("vnitroblok mezi ul. a, b a c") == "vnitroblok"
    assert places.pattern("wolkerova - parkoviste u c. p. 2122-2123") == "plocha u c. p."
    assert places.pattern("konecna - cela od ulice chrudimska") == "jen od"
    assert places.pattern("wolkerova") == "cela ulice"


@pytest.mark.parametrize("text, street, want", [
    ("Milheimova od ul. V Ráji k ul. Pražská - pravá strana komunikace", "Milheimova", "od V Ráji k Pražská, pravá strana"),
    ("Wolkerova v celé délce - obě strany komunikace", "Wolkerova", "v celé délce, obě strany"),
    ("Wolkerova", "Wolkerova", "v celé délce"),
    ("K Barvírně od ul Na Záboří k č. p.1334 - obě strany komunikace", "K Barvírně", "od Na Záboří k č. p. 1334, obě strany"),
    ("Boženy Vikové Kunětické od ul. Pichlova k ul. Na Spravedlnosti", "Boženy Vikové-Kunětické", "od Pichlova k Na Spravedlnosti"),
    ("Rokycanova - od ul.K Višňovce k ul K Blahobytu - obě strany", "Rokycanova", "od K Višňovce ke K Blahobytu, obě strany"),
    ("Vnitrobloková komunikace v ul. Wolkerova vč. parkoviště", "Wolkerova", "Vnitrobloková komunikace v ul. Wolkerova včetně parkoviště"),
])
def test_short(text, street, want):
    assert places.short(text, street) == want


# --- geocoding on made-up streets -----------------------------------------------------------

def wgs(x, y):
    return [geocode.LON0 + x / geocode.KX, geocode.LAT0 + y / geocode.KY]


def line(*pts):
    return {"type": "LineString", "coordinates": [wgs(*p) for p in pts]}


def box(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[wgs(x0, y0), wgs(x1, y0), wgs(x1, y1), wgs(x0, y1), wgs(x0, y0)]]}


class FakeRuian:
    """Hlavní runs east 0–1000 m, drawn in two pieces with a 30 m gap at 400–430; Boční crosses
    it at x = 200, Zadní at x = 700, Horní runs parallel 300 m north. MO V is west of x = 500,
    MO IV east of it. Two houses (čp. 11, 12) stand by Hlavní at x ≈ 300; čp. 13 doesn't exist and
    čp. 14 of Hlavní is 7 km away (a wrong building)."""
    STREETS = [[1, "Hlavní"], [2, "Boční"], [3, "Zadní"], [4, "Horní"], [5, "Krátká"]]
    LINES = {
        1: {"type": "MultiLineString", "coordinates": [line((0, 0), (400, 0))["coordinates"],
                                                       line((430, 0), (1000, 0))["coordinates"]]},
        2: line((200, -200), (200, 400)),
        3: line((700, -200), (700, 400)),
        4: line((0, 300), (1000, 300)),
    }
    ADDR = {11: [(290, 20)], 12: [(320, 20)], 14: [(5000, 5000)]}

    def streets(self):
        return self.STREETS

    def street(self, kod):
        return self.LINES.get(kod)

    def addresses(self, cp):
        return [{"kod": cp * 10 + i, "adresa": f"Hlavní {cp}, Pardubice", "cp": cp, "co": None, "ulice": 1,
                 "point": wgs(*p)} for i, p in enumerate(self.ADDR.get(cp, []))]

    def parts(self):
        return ["Pardubice", "Zelené Předměstí"]

    def obvody(self):
        return {"mo5": box(-100, -300, 500, 500), "mo4": box(500, -300, 1100, 500)}


@pytest.fixture(scope="module")
def geo():
    return geocode.Geo(FakeRuian())


def test_stretch_between_two_streets(geo):
    r = geo.place(places.place_key("Hlavní - jednosměrka mezi ul. Boční a Zadní"))
    assert (r["method"], r["status"], r["main_street"]) == ("segment", "auto", "Hlavní")      # as "od Boční k Zadní"
    xs = [c[0] for c in geocode.to_m(r["geometry"]).coords]
    assert min(xs) == pytest.approx(200, abs=1) and max(xs) == pytest.approx(700, abs=1)
    p = geo.place(places.place_key("Hlavní - parkoviště mezi ul. Boční a Zadní"))
    assert (p["method"], p["status"]) == ("segment", "approx")                                 # a parkoviště along it: approximate


def test_names_in_case_forms(geo):
    assert [f[0] for f in geo.names.find("hlavni od ul. bocni k ul. zadni")] == ["Hlavní", "Boční", "Zadní"]
    assert [f[0] for f in geo.names.find("parkoviste u kratke")] == ["Krátká"]
    assert geo.names.fuzzy("od zadnimu") == "Zadní"


def test_segment_is_cut_between_cross_streets_across_a_gap(geo):
    r = geo.place(places.place_key("Hlavní od ul. Boční k ul. Zadní - obě strany komunikace"))
    assert (r["method"], r["status"], r["side"], r["main_street"]) == ("segment", "auto", "obe", "Hlavní")
    g = geocode.to_m(r["geometry"])
    assert g.length == pytest.approx(500 + 0, abs=35)          # 200 → 700, the 30 m gap bridged
    xs = [c[0] for c in g.coords]
    assert min(xs) == pytest.approx(200, abs=1) and max(xs) == pytest.approx(700, abs=1)
    assert r["obvody"] == {"mo5": pytest.approx(0.6, abs=0.05), "mo4": pytest.approx(0.4, abs=0.05)}


def test_far_cross_street_is_no_endpoint(geo):
    r = geo.place(places.place_key("Hlavní od ul. Horní k ul. Zadní"))
    assert r["geometry"] is None and r["status"] == "manual" and "300 m away" in r["note"]
    assert set(r["obvody"]) == {"mo5", "mo4"}           # from the street, not decided up front


def test_whole_street_across_obvody_is_approximate(geo):
    r = geo.place(places.place_key("Hlavní - obě strany komunikace"))
    assert r["method"] == "whole" and r["status"] == "approx"
    r = geo.place(places.place_key("Boční"))
    assert (r["method"], r["status"], r["obvody"]) == ("whole", "auto", {"mo5": 1.0})


def test_hull_of_addresses_and_a_wrong_building(geo):
    r = geo.place(places.place_key("Hlavní - parkoviště před č. p. 11-12"))
    assert (r["method"], r["status"]) == ("hull", "auto") and r["obvody"] == {"mo5": 1.0}
    r = geo.place(places.place_key("Hlavní - parkoviště před č. p. 11, 13"))
    assert r["status"] == "partial" and "missing [13]" in r["note"]
    r = geo.place(places.place_key("Hlavní - parkoviště před č. p. 11, 14"))
    assert r["geometry"] is None and "apart" in r["note"]


def test_vnitroblok_is_the_block_the_streets_close(geo):
    r = geo.place(places.place_key("vnitroblok mezi ul. Boční, Zadní, Hlavní a Horní"))
    assert (r["method"], r["status"]) == ("block", "approx")
    g = geocode.to_m(r["geometry"])
    c = g.centroid
    assert 400 < c.x < 500 and 100 < c.y < 200 and g.area < 500 * 300


class NamesRuian(FakeRuian):
    """FakeRuian plus Dlouhá třída crossing Hlavní at x = 300, Příčná in two numbered parts (I far
    north, II crossing Hlavní at x = 800), K Hlavní joining Hlavní and Horní at x = 0, and
    Spojovací, Staročernská and nábřeží Závodu míru somewhere."""
    STREETS = FakeRuian.STREETS + [[6, "Dlouhá třída"], [7, "Příčná I"], [8, "Příčná II"], [9, "K Hlavní"],
                                   [10, "Spojovací"], [11, "Staročernská"], [12, "nábřeží Závodu míru"]]
    LINES = {**FakeRuian.LINES, 6: line((300, -200), (300, 400)), 7: line((900, 2000), (900, 3000)),
             8: line((800, -200), (800, 400)), 9: line((0, 0), (0, 300))}


@pytest.fixture(scope="module")
def geo2():
    return geocode.Geo(NamesRuian())


def test_names_without_trida_and_numbered_parts(geo2):
    r = geo2.place(places.place_key("Hlavní od ul. Dlouhá k ul. Příčná - obě strany komunikace"))
    assert (r["method"], r["status"], r["note"]) == ("segment", "auto", "Dlouhá třída → Příčná II")   # the part that crosses
    xs = [c[0] for c in geocode.to_m(r["geometry"]).coords]
    assert min(xs) == pytest.approx(300, abs=1) and max(xs) == pytest.approx(800, abs=1)
    assert geo2.names.find("protihlukova stena i/37") == []       # 'I' of Příčná I is no street
    assert geo2.names.find("spojovaci komunikace k hale") == []   # a connecting road, not Spojovací
    assert [f[0] for f in geo2.names.find("od ul. spojovaci")] == ["Spojovací"]
    assert [f[0] for f in geo2.names.find("po ul. starocenska")] == ["Staročernská"]   # the sheet's misspelling
    assert [f[0] for f in geo2.names.find("zavodu miru - parkoviste")] == ["nábřeží Závodu míru"]


def test_od_a_street_named_k(geo2):
    r = geo2.place(places.place_key("Boční od ul. K Hlavní - obě strany komunikace"))
    assert (r["method"], r["status"]) == ("whole", "auto")            # no end given: the whole street, as "Boční od X"
    r = geo2.place(places.place_key("Boční - celá od ul. K Hlavní"))
    assert (r["method"], r["status"]) == ("whole", "auto")
    r = geo2.place(places.place_key("Boční - od ul. K Hlavní, vč. parkovišť"))
    assert (r["method"], r["status"], r["note"]) == ("whole", "approx", "od X, end not given")


def test_street_with_its_parking_is_the_street(geo2):
    for text in ("Boční, vč. parkoviště", "Boční vč. parkovišť a chodníků - obě strany komunikace",
                 "Boční vč. slepé části"):
        r = geo2.place(places.place_key(text))
        assert (r["method"], r["status"]) == ("whole", "auto"), text
    r = geo2.place(places.place_key("Boční po ul. Hlavní vč. parkovišť"))     # a stretch without its start
    assert r["geometry"] is None


def test_addresses_are_looked_up_in_the_whole_town():
    from petka.cisteni import ruian

    class Offline(dict):
        offline = True
    r = object.__new__(ruian.Ruian)
    lany = {"kod": 1, "adresa": "Lány na Důlku 31, 53002 Pardubice", "cp": 31, "co": None, "ulice": None,
            "point": [15.66, 50.03]}
    r.cache = Offline({"cp:31": [], "cp:31@" + ",".join(map(str, ruian.TOWN_BBOX)): [lany]})
    assert r.addresses(31) == [lany]        # Lány na Důlku lies west of the minutes' box


def test_obvod_ids_and_numbers():
    assert geocode.obvod_id("Pardubice V") == "mo5" and geocode.obvod_id("Pardubice VIII") == "mo8"
    assert geocode.obvod_id("Pardubice") is None
    assert geocode.numbers("č. p. 1895-1893, 1947") == [1893, 1894, 1895, 1947]
    assert geocode.numbers("2449-52") == [2449, 2450, 2451, 2452]
    assert geocode.numbers("153-174") == [153, 174]


def test_cut_needs_one_network():
    from shapely.geometry import MultiLineString, Point
    far = MultiLineString([[(0, 0), (100, 0)], [(1000, 0), (1100, 0)]])
    assert geocode.cut(far, Point(10, 0), Point(1050, 0)) is None


# --- words ----------------------------------------------------------------------------------

def test_plural_and_counts():
    assert [words.plural(n, "ulici", "ulice", "ulic") for n in (0, 1, 2, 4, 5, 12)] == \
        ["ulic", "ulici", "ulice", "ulice", "ulic", "ulic"]
    t = D(2026, 11, 12)
    assert [words.until(D(2026, 11, d), t) for d in (12, 13, 15, 26)] == ["dnes", "zítra", "za 3 dny", "za 14 dní"]


@pytest.mark.parametrize("name, want", [
    ("Wolkerova", "Wolkerovy"), ("Sokolovská", "Sokolovské"), ("Gorkého", "Gorkého"),
    ("Josefa Ressla", "Josefa Ressla"), ("K Barvírně", "ulice K Barvírně"), ("Sukova třída", "Sukovy třídy"),
    ("Čacké", "ulice Čacké"),
])
def test_genitive(name, want):
    assert words.genitive(name) == want


def item(d, street="Wolkerova", key=None, time=dt.time(7), before=False, side="obe", status="auto", located=True,
         text=None, method="whole", shares=None):
    text = text or f"{street} v celé délce - obě strany komunikace"
    return queries.shape({"key": key or places.place_key(text), "texts": [text], "main_street": street,
                          "streets": [street], "side": side, "status": status, "method": method,
                          "located": located, "date": d, "time": time, "before": before,
                          "obvody": {"mo5": 1.0} if shares is None else shares})


def test_weeks_and_merged():
    t = D(2026, 11, 12)
    its = [item(D(2026, 11, 13)), item(D(2026, 11, 18)), item(D(2026, 11, 24)), item(D(2026, 11, 30), "Lexova"),
           item(D(2026, 12, 1), "Gorkého"), item(D(2026, 12, 1), "Devotyho")]
    g = words.weeks(its, t)
    assert [(x["label"], x["range"], len(x["items"])) for x in g] == [
        ("Tento týden", "12.–15. 11.", 1), ("Příští týden", "16.–22. 11.", 1), ("Za dva týdny", "23.–29. 11.", 1),
        ("Prosinec", "30. 11.–1. 12.", 3)]
    m = words.merged(g[-1]["items"])
    assert [(x["street"], x["short"]) for x in m] == [("Lexova", "v celé délce, obě strany"),
                                                       ("Gorkého, Devotyho", "2 úseky, obě strany")]


# --- iCalendar ------------------------------------------------------------------------------

STAMP = dt.datetime(2026, 11, 12, 10, 0, tzinfo=dt.UTC)


def test_ics_shape_folding_and_uid():
    long = "Wolkerova – komunikace a parkoviště před č. p. 2116–2118 plošně, včetně spojovací komunikace Gorkého – Jilemnického"
    its = [item(D(2026, 11, 26)), item(D(2026, 12, 3), text=long), item(D(2026, 12, 4), time=dt.time(6), before=True),
           item(D(2026, 12, 5), time=None)]
    body = ics.calendar(its, "Blokové čištění – Wolkerova", STAMP, lambda i: "https://otevrenapetka.cz/verejny-prostor/blokove-cisteni/ulice/wolkerova")
    raw = body.encode()
    assert all(len(line) <= 75 for line in raw.split(b"\r\n")) and body.endswith("\r\n") and "\n" not in body.replace("\r\n", "")
    cal = Calendar.from_ical(body)
    ev = list(cal.walk("VEVENT"))
    assert len(ev) == 4
    assert str(ev[0]["SUMMARY"]) == "Blokové čištění: Wolkerova"
    assert ev[0].decoded("DTSTART").replace(tzinfo=None) == dt.datetime(2026, 11, 26, 7)
    assert str(ev[0].decoded("DTSTART").tzinfo) == "Europe/Prague"
    assert str(ev[1]["DESCRIPTION"]) == long + "\nZákaz stání podle dopravních značek."
    assert ev[2].decoded("DTSTART") == D(2026, 12, 4) and "před 6:00" in str(ev[2]["DESCRIPTION"])
    assert ev[3].decoded("DTSTART") == D(2026, 12, 5)
    alarms = [a for e in ev for a in e.walk("VALARM")]
    assert [a.decoded("TRIGGER") for a in alarms[:1]] == [-dt.timedelta(hours=13)]
    assert alarms[2].decoded("TRIGGER") == -dt.timedelta(hours=6)       # all day: from midnight
    # stable: the same place and date always give the same UID, another date another
    again = Calendar.from_ical(ics.calendar(its[:1], "x", STAMP + dt.timedelta(days=3)))
    assert str(list(again.walk("VEVENT"))[0]["UID"]) == str(ev[0]["UID"]) != str(ev[1]["UID"])


def test_fold_never_splits_a_character():
    line = "DESCRIPTION:" + "č" * 100
    folded = ics.fold(line)
    for part in folded.encode().split(b"\r\n"):
        assert len(part) <= 75
        part.decode()
    assert folded.replace("\r\n ", "") == line


# --- pages and API over fixture items -------------------------------------------------------

TODAY = D(2026, 11, 12)
GEOM = {"type": "LineString", "coordinates": [[15.76, 50.03], [15.77, 50.03]]}


@pytest.fixture
def fixture(monkeypatch):
    its = [item(D(2026, 7, 27), text="Wolkerova od ul. Čs. armády k ul. Lexova - obě strany komunikace", method="segment"),
           item(D(2026, 11, 18), "Josefa Ressla", text="Josefa Ressla od ul. Lexova - pravá strana komunikace", side="prava",
                status="approx"),
           item(D(2026, 11, 26)),
           item(D(2026, 12, 9), "Sokolovská", text="Sokolovská od ul. kpt. Nálepky k ul. Wolkerova - obě strany komunikace"),
           item(D(2026, 12, 10), "Lexova", text="Lexova - parkoviště před č. p. 1", located=False, status="manual",
                shares={"mo4": 0.6, "mo5": 0.4})]
    seen = {}

    def items(obvod, since, slugs=None):
        seen.update(obvod=obvod, since=since, slugs=slugs)
        where = obvody.ObvodFilter.only(obvod) if isinstance(obvod, str) else obvod
        out = [i for i in its if i["date"] >= since and where.matches(i["obvody"])]
        return [i for i in out if i["slug"] in slugs] if slugs is not None else out

    geoms = {i["key"]: GEOM for i in its if i["located"]}
    monkeypatch.setattr(queries, "items", items)
    monkeypatch.setattr(queries, "geometries", lambda obvod: geoms)
    monkeypatch.setattr(queries, "checked", lambda: dt.datetime(2026, 11, 12, 6, 0))
    monkeypatch.setattr(web, "_today", lambda: TODAY)
    from petka.ulice import streets as ust
    road = {"type": "LineString", "coordinates": [[15.759, 50.03], [15.771, 50.03]]}
    monkeypatch.setattr(ust, "streets", lambda obvod: {"wolkerova": ust.Street("wolkerova", "Wolkerova", 1, road, 1.0)})
    return seen


def get(path, **kw):
    return TestClient(app).get(path, headers={"host": "otevrenapetka.cz"}, follow_redirects=False, **kw)


def test_overview(fixture):
    r = get("/verejny-prostor/blokove-cisteni")
    assert r.status_code == 200 and fixture["obvod"] == "mo5" and fixture["since"] == D(2026, 1, 1)
    h = r.text
    for s in ("Kdy proběhne čištění mojí ulice?", "Kdy se kde čistí", 'class="pd-rows mbox-rows"', "Kalendář jen pro vaše ulice",
              'aria-current="true">7 dní <b>', '<a href="/verejny-prostor/blokove-cisteni?obdobi=rok">Letos <b>4</b></a>',
              "Harmonogram do konce roku", "Příští týden", "Stav k 12. 11. 2026", "letos 5 termínů na 5 místech",
              'href="/zapojte-se/upozorneni?co=cisteni"', 'href="/verejny-prostor/blokove-cisteni/ulice/wolkerova.ics"',
              "poloha přibližná", "není na mapě", "Letošní proběhlé termíny (1)", 'data-src="/api/v1/cisteni?obvod=mo5&amp;od=2026-11-12"'):
        assert s in h, s
    assert "aplikac" not in h.lower() and "letos už ne" not in h
    assert 'href="/verejny-prostor/ulice" aria-current="true">Veřejný prostor' in h.split("</header>")[0]
    assert get("/verejny-prostor/blokove-cisteni?probehle=1").text.count("Letošní proběhlé termíny") >= 1
    # the map's anchors and the week's rows share the place key, so they light up together
    anchors = json.loads(h.split('<script type="application/json" id="cl-anchors">')[1].split("</script>")[0])
    jr = next(k for a in anchors for k in a["keys"] if k.startswith("josefa ressla"))
    assert f'data-cl-key="{jr}"' in h and 'data-anchors="cl-anchors"' in h
    h = get("/verejny-prostor/blokove-cisteni", params={"obdobi": "rok"}).text      # the whole year beside the map
    assert 'aria-current="true">Letos <b>4</b>' in h and h.split('class="pd-rows mbox-rows"')[1].split("</ol>")[0].count("<li ") == 4


def test_map_anchors():
    t = D(2026, 11, 12)
    right = "Josefa Ressla od ul. Lexova - pravá strana komunikace"
    its = [item(D(2026, 7, 27), text="Wolkerova od ul. Čs. armády k ul. Lexova - obě strany komunikace"),
           item(D(2026, 9, 2), "Josefa Ressla", text=right, side="prava"),     # past: not in the tooltip
           item(D(2026, 11, 18), "Josefa Ressla", text=right, side="prava"),
           item(D(2026, 11, 19), "Josefa Ressla", text="Josefa Ressla od ul. Lexova - levá strana komunikace", side="leva"),
           item(D(2026, 12, 3), "Josefa Ressla", text=right, side="prava"),
           item(D(2026, 11, 26), None, text="Vnitroblok za školou", side=None),
           item(D(2026, 12, 1), "Lexova", located=False)]
    other = {"type": "LineString", "coordinates": [[15.75, 50.02], [15.75, 50.03]]}
    geoms = {i["key"]: GEOM if i["street"] == "Josefa Ressla" else other for i in its if i["located"]}
    geoms[its[0]["key"]] = {"type": "LineString", "coordinates": [[15.70, 50.0], [15.71, 50.0]]}
    a = queries.map_anchors(its, geoms, t)
    assert [(x["street"], x["what"], x["when"], x["href"]) for x in a] == [
        ("Josefa Ressla", "od Lexova", "pravá strana 18.\u00a011. a 3.\u00a012., levá 19.\u00a011.", "/verejny-prostor/ulice/josefa-ressla#cisteni"),
        ("Vnitroblok za školou", "Blokové čištění", "26.\u00a011.", None)]   # Wolkerova: nothing left this year
    assert len(a[0]["keys"]) == 2                                   # both sides drawn as one line are one stretch
    assert a[0]["label"].startswith("Blokové čištění: Josefa Ressla, od Lexova, pravá strana")
    assert (a[0]["lng"], a[0]["lat"]) == (15.765, 50.03)
    assert not any(x["area"] for x in a)


def test_on_street():
    road = {"type": "LineString", "coordinates": [[15.76, 50.03], [15.77, 50.03]]}
    near = {"type": "LineString", "coordinates": [[15.761, 50.0301], [15.769, 50.0301]]}     # ~11 m off
    away = {"type": "LineString", "coordinates": [[15.761, 50.031], [15.769, 50.031]]}       # ~110 m off
    sq = {"type": "Polygon", "coordinates": [[[15.76, 50.03], [15.77, 50.03], [15.77, 50.031], [15.76, 50.03]]]}
    assert queries.on_street(near, road) and not queries.on_street(away, road) and not queries.on_street(sq, road)


def test_areas_are_markers_on_the_overview():
    t = D(2026, 11, 12)
    sq = {"type": "Polygon", "coordinates": [[[15.75, 50.02], [15.76, 50.02], [15.76, 50.03], [15.75, 50.03], [15.75, 50.02]]]}
    park = "Wolkerova - parkoviště u č. p. 2122-2123"
    its = [item(D(2026, 9, 2), text=park, method="area"), item(D(2026, 11, 26), text=park, method="area"),
           item(D(2026, 11, 4), "Benešovo náměstí", text="Benešovo náměstí - místní komunikace za ZŠ - obě strany komunikace",
                method="area"),
           item(D(2026, 11, 26))]
    geoms = {i["key"]: sq for i in its[:3]} | {its[3]["key"]: GEOM}
    assert queries.is_area(sq) and not queries.is_area(GEOM) and not queries.is_area(None)
    assert [x["area"] for x in queries.map_anchors(its, geoms, t)] == [True, False]


def test_search_goes_to_ulice(fixture):
    # the street search left the band (13. 11. 2026): a link from before finds the street on Ulice
    r = get("/verejny-prostor/blokove-cisteni", params={"ulice": "WOLKEROVÁ"})
    assert r.status_code == 303 and r.headers["location"] == "/verejny-prostor/ulice?q=WOLKEROV%C3%81"
    h = get("/verejny-prostor/blokove-cisteni").text
    assert 'href="/verejny-prostor/ulice">najděte svou ulici</a>' in h and 'role="search"' not in h.split("</section>")[0]
    assert 'href="/verejny-prostor/ulice/wolkerova#cisteni"' in h and "Odkud to víme" in h
    assert 'class="btn btn-o btn-s cl-cal"' not in h and 'class="cl-cal"' in h        # a text link in the rows


def test_street_page_moved_into_the_street(fixture):
    # the street's cleaning is a section of its page: the old page redirects there for good,
    # its calendar stays where people subscribed to it
    for old in ("/verejny-prostor/blokove-cisteni/ulice/wolkerova", "/verejny-prostor/blokove-cisteni/ulice/neni"):
        r = get(old)
        assert r.status_code == 301 and r.headers["location"] == old.replace("/blokove-cisteni/ulice/", "/ulice/") + "#cisteni"
    assert get("/verejny-prostor/blokove-cisteni/ulice/wolkerova.ics").status_code == 200


@pytest.mark.parametrize("d, want", [
    (D(2026, 11, 12), ("Čistí se ", "dnes", "Auto přeparkujte ", "co nejdřív")),
    (D(2026, 11, 13), ("Příští čištění ", "zítra", "Auto přeparkujte nejpozději ", "dnes večer")),
    (D(2026, 11, 15), ("Příští čištění za ", "3\u00a0dny", "Auto přeparkujte nejpozději ", "v sobotu 14.\u00a011. večer")),
    (D(2026, 11, 26), ("Příští čištění za ", "14\u00a0dní", "Auto přeparkujte nejpozději ", "ve středu 25.\u00a011. večer")),
])
def test_next_panel_countdown_and_the_evening_before(d, want):
    p = words.next_panel([item(d)], D(2026, 11, 12))
    assert (p["lead"], p["count"], p["move"], p["by"]) == want


@pytest.mark.parametrize("d, on", [(D(2026, 11, 16), "V pondělí"), (D(2026, 11, 17), "V úterý"),
                                   (D(2026, 11, 18), "Ve středu"), (D(2026, 11, 19), "Ve čtvrtek"),
                                   (D(2026, 11, 20), "V pátek"), (D(2026, 11, 21), "V sobotu"), (D(2026, 11, 22), "V neděli")])
def test_next_panel_weekday(d, on):
    p = words.next_panel([item(d)], D(2026, 11, 12))
    assert p["on"] == on and p["date"] == f"{d.day}.\u00a011." and p["clock"] == "od\u00a07:00"


def test_next_panel_without_time_and_where():
    p = words.next_panel([item(D(2026, 12, 9), time=None)], D(2026, 11, 12))
    assert p["clock"] == "" and p["plate"] == ["9.\u00a012.", ""]
    seg = lambda text, side="obe": item(D(2026, 12, 9), "Sokolovská", text=text, side=side, method="segment")
    assert words.where([seg("Sokolovská od ul. kpt. Nálepky k ul. Wolkerova - obě strany komunikace")]) == \
        "od kpt. Nálepky k Wolkerova, po obou stranách"
    assert words.where([seg("Sokolovská od ul. Lexova - pravá strana komunikace", "prava"),
                        seg("Sokolovská od ul. Jiránkova - pravá strana komunikace", "prava")]) == \
        "od Lexova a od Jiránkova, po pravé straně"
    assert words.where([seg("Sokolovská - Vnitrobloková komunikace před č. p. 2070", None)]) == \
        "vnitrobloková komunikace před č. p. 2070"
    assert words.where([item(D(2026, 12, 9), side="leva")]) == "v celé ulici, po levé straně"


def test_old_calendar_page_moved_to_my_overview(fixture):
    r = get("/verejny-prostor/blokove-cisteni/kalendar", params=[("ulice", "wolkerova"), ("ulice", "lexova")])
    assert r.status_code == 301
    assert r.headers["location"] == "/zapojte-se/upozorneni?ulice=wolkerova,lexova&co=cisteni"


def test_feeds(fixture):
    r = get("/verejny-prostor/blokove-cisteni/kalendar.ics", params={"ulice": "wolkerova,lexova"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    cal = Calendar.from_ical(r.text)
    assert len(list(cal.walk("VEVENT"))) == 3 and "Wolkerova\\, Lexova" in str(cal["X-WR-CALNAME"])   # X- property: kept escaped
    assert fixture["slugs"] == ["wolkerova", "lexova"]
    r = get("/verejny-prostor/blokove-cisteni/ulice/wolkerova.ics")
    assert r.status_code == 200 and len(list(Calendar.from_ical(r.text).walk("VEVENT"))) == 2
    assert get("/verejny-prostor/blokove-cisteni/kalendar.ics").status_code == 404


def test_api_shape(fixture):
    r = get("/api/v1/cisteni", params={"ulice": "wolkerova,lexova", "od": "2026-01-01"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/geo+json")
    assert fixture["obvod"] == obvody.ObvodFilter()                  # the whole town by default
    fc = r.json()
    by = {f["properties"]["street"]: f for f in fc["features"]}
    assert set(by) == {"Wolkerova", "Lexova"} and len(fc["features"]) == 3
    lex = by["Lexova"]
    assert lex["geometry"] is None and lex["properties"]["status"] == "manual"
    assert lex["properties"]["obvody"] == ["mo4", "mo5"]
    w = [f for f in fc["features"] if f["properties"]["next"] == "2026-11-26"][0]
    assert w["geometry"] == GEOM
    assert w["properties"] == {"key": w["id"], "street": "Wolkerova", "slug": "wolkerova",
                               "texts": ["Wolkerova v celé délce - obě strany komunikace"], "status": "auto",
                               "side": "obe", "obvody": ["mo5"],
                               "dates": [{"date": "2026-11-26", "time": "07:00", "before": False}],
                               "next": "2026-11-26"}
    assert get("/api/v1/cisteni", params={"od": "1. 1."}).status_code == 422


def test_api_obvod_filter(fixture):
    r = get("/api/v1/cisteni", params={"obvod": " MO4 "})
    assert fixture["obvod"] == obvody.ObvodFilter(("mo4",))
    assert [f["properties"]["street"] for f in r.json()["features"]] == ["Lexova"]     # 0.6 of it in MO IV
    assert len(get("/api/v1/cisteni", params={"obvod": "mo5,mo4"}).json()["features"]) == 5
    assert fixture["obvod"].ids == ("mo4", "mo5")
    r = get("/api/v1/cisteni", params={"obvod": "mo9"})
    assert r.status_code == 422 and "mo1, mo2" in r.json()["detail"]


def test_mcp_tool(fixture, monkeypatch):
    from petka.cisteni import mcp_tools
    out = mcp_tools.cisteni(ulice="wolkerova", od="2026-01-01")
    assert [t["datum"] for t in out["terminy"]] == ["2026-07-27", "2026-11-26"]
    assert out["terminy"][1]["cas"] == "od 7:00" and out["terminy"][1]["den"] == "čtvrtek"
    assert "chyba" in mcp_tools.cisteni(ulice="neexistuje")


# --- with a database ------------------------------------------------------------------------

class FakeGeo:
    def __init__(self):
        self.calls = []
        self.names = geocode.Streets([[1, "Testovací"]])
        self.r = object()

    def place(self, k):
        self.calls.append(k)
        return {"key": k, "pattern": "cela ulice", "main_street": "Testovací", "streets": ["Testovací"], "side": None,
                "method": "whole", "status": "auto", "geometry": GEOM, "obvody": {"mo99": 1.0}, "note": ""}

    def shares(self, g):
        return {"mo99": 1.0}


@pytest.fixture
def conn():
    try:
        db.migrate()
    except Exception:
        pytest.skip("no local database")
    with db.connect() as c:
        yield c
        c.rollback()        # store() replaces future dates of the whole town: never commit here


def test_store_keeps_past_dates_and_geocodes_only_new_places(conn):
    today = D(2030, 6, 1)
    row = lambda r, d, place: source.Row(r, d, "od 7:00", place, dt.time(7))   # noqa: E731
    g = FakeGeo()
    s = jobs.store(conn, [row(2, D(2030, 5, 1), "Testovací ulice A"), row(3, D(2030, 7, 1), "Testovací ulice A"),
                          row(4, D(2030, 8, 1), "Testovací ulice B")], lambda: g, today)
    assert s["places"] == 2 and s["geocoded"] == 2 and s["obvody"]["mo99"]["places"] == 2
    # a new sheet: A's July date moved to September, B is gone, the past May date stays
    g2 = FakeGeo()
    s = jobs.store(conn, [row(5, D(2030, 9, 1), "Testovací  ulice A")], lambda: g2, today)
    assert g2.calls == [] and s["geocoded"] == 0 and s["places_removed"] == 1
    dates = [r["date"] for r in conn.execute(
        "SELECT date FROM cleaning_dates WHERE place_key = %s ORDER BY date", ("testovaci ulice a",))]
    assert dates == [D(2030, 5, 1), D(2030, 9, 1)]
    texts = conn.execute("SELECT texts FROM cleaning_places WHERE key = 'testovaci ulice a'").fetchone()["texts"]
    assert texts == ["Testovací  ulice A", "Testovací ulice A"]
    # an override wins and is marked as drawn by hand
    poly = {"type": "Polygon", "coordinates": [[[15.76, 50.03], [15.77, 50.03], [15.77, 50.04], [15.76, 50.03]]]}
    jobs.store(conn, [row(5, D(2030, 9, 1), "Testovací ulice A")], lambda: g2, today,
               {"testovaci ulice a": {"geometry": poly, "properties": {"key": "testovaci ulice a"}}})
    r = conn.execute("SELECT method, status, geometry FROM cleaning_places WHERE key = 'testovaci ulice a'").fetchone()
    assert (r["method"], r["status"], r["geometry"]) == ("override", "manual", poly)


def test_overrides_file_is_valid():
    from petka.cisteni.ruian import TOWN_BBOX
    fc = json.loads(jobs.OVERRIDES.read_text())
    assert fc["type"] == "FeatureCollection" and fc["features"]
    keys = [f["properties"]["key"] for f in fc["features"]]
    assert all(keys) and len(set(keys)) == len(keys)
    assert all(k == places.place_key(k) for k in keys)                # keys as /api/v1/cisteni gives them

    def coords(c):
        return [c] if isinstance(c[0], (int, float)) else [x for y in c for x in coords(y)]
    x0, y0, x1, y1 = TOWN_BBOX
    for f in fc["features"]:
        g = f["geometry"]
        assert g["type"] in ("LineString", "MultiLineString", "Polygon", "MultiPolygon"), f["properties"]["key"]
        assert all(x0 < x < x1 and y0 < y < y1 for x, y in coords(g["coordinates"])), f["properties"]["key"]
        assert f["properties"].get("note")
    assert len(jobs.load_overrides()) == len(keys)


def test_export_of_the_whole_town(monkeypatch):
    seen = []
    row = {"date": dt.date(2026, 11, 26), "time": "07:00", "before": False, "street": "Wolkerova",
           "place": "Wolkerova v celé délce - obě strany komunikace", "side": "obe", "obvody": ["mo5"],
           "location": "auto", "place_key": "wolkerova v cele delce"}
    monkeypatch.setattr(web.q, "export_rows", lambda since, where=obvody.WHOLE_TOWN: seen.append(where) or [row])
    monkeypatch.setattr(web.q, "checked", lambda: None)               # never checked: still answers
    r = get("/verejny-prostor/blokove-cisteni/data/terminy.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0] == ",".join(queries.EXPORT_FIELDS)
    assert lines[1].startswith("2026-11-26,07:00,false,Wolkerova,") and lines[1].endswith(",obe,mo5,auto,wolkerova v cele delce")
    j = get("/verejny-prostor/blokove-cisteni/data/terminy.json", params={"obvod": "mo4,mo1"}).json()
    assert j[0]["date"] == "2026-11-26"
    assert seen == [obvody.ObvodFilter(), obvody.ObvodFilter(("mo1", "mo4"))]      # the town, then two obvody
    assert get("/verejny-prostor/blokove-cisteni/data/terminy.csv", params={"obvod": "mo9"}).status_code == 422


def test_etag_and_304_from_the_last_check_and_the_parameters(fixture, monkeypatch):
    """The API and both exports send a weak ETag of the sheet's last check, the day and the
    parameters; If-None-Match with it gives 304, a new check or another day a new answer."""
    state = {"checked": dt.datetime(2026, 11, 12, 6, 0, tzinfo=dt.timezone.utc), "today": TODAY}
    monkeypatch.setattr(queries, "checked", lambda: state["checked"])
    monkeypatch.setattr(web, "_today", lambda: state["today"])
    monkeypatch.setattr(web.q, "export_rows", lambda since, where=obvody.WHOLE_TOWN: [])

    def ask(path, tag=None, **params):
        return TestClient(app).get(path, params=params, headers={"host": "otevrenapetka.cz",
                                                                 **({"if-none-match": tag} if tag else {})})

    paths = ("/api/v1/cisteni", "/verejny-prostor/blokove-cisteni/data/terminy.json",
             "/verejny-prostor/blokove-cisteni/data/terminy.csv")
    tags = set()
    for path in paths:
        r = ask(path)
        tag = r.headers["etag"]
        assert r.status_code == 200 and tag.startswith('W/"') and r.headers["cache-control"].startswith("public")
        r = ask(path, tag)
        assert r.status_code == 304 and r.headers["etag"] == tag and not r.content
        assert ask(path, tag.removeprefix("W/")).status_code == 304
        assert ask(path, tag, obvod="mo5").status_code == 200
        assert ask(path, tag, obvod="mo5").headers["etag"] == ask(path, obvod=" MO5 ").headers["etag"]
        tags.add(tag)
    assert len(tags) == 3                                               # each answer its own tag
    api = paths[0]
    tag = ask(api).headers["etag"]
    assert ask(api, tag, ulice="wolkerova").status_code == 200
    assert ask(api, tag, od="2026-11-01").status_code == 200
    state["today"] = TODAY + dt.timedelta(days=1)                       # `next` moves with the day
    assert ask(api, tag).status_code == 200
    tag = ask(api).headers["etag"]
    state["checked"] += dt.timedelta(days=1)                            # the sheet checked again
    assert ask(api, tag).status_code == 200
