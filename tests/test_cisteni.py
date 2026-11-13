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

from petka import db
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
         text=None, method="whole"):
    text = text or f"{street} v celé délce - obě strany komunikace"
    return queries.shape({"key": key or places.place_key(text), "texts": [text], "main_street": street,
                          "streets": [street], "side": side, "status": status, "method": method,
                          "located": located, "date": d, "time": time, "before": before})


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
           item(D(2026, 12, 10), "Lexova", text="Lexova - parkoviště před č. p. 1", located=False, status="manual")]
    seen = {}

    def items(obvod, since, slugs=None):
        seen.update(obvod=obvod, since=since, slugs=slugs)
        out = [i for i in its if i["date"] >= since]
        return [i for i in out if i["slug"] in slugs] if slugs is not None else out

    geoms = {i["key"]: GEOM for i in its if i["located"]}
    monkeypatch.setattr(queries, "items", items)
    monkeypatch.setattr(queries, "geometries", lambda obvod: geoms)
    monkeypatch.setattr(queries, "checked", lambda: dt.datetime(2026, 11, 12, 6, 0))
    monkeypatch.setattr(web, "_today", lambda: TODAY)
    return seen


def get(path, **kw):
    return TestClient(app).get(path, headers={"host": "otevrenapetka.cz"}, follow_redirects=False, **kw)


def test_overview(fixture):
    r = get("/verejny-prostor/blokove-cisteni")
    assert r.status_code == 200 and fixture["obvod"] == "mo5" and fixture["since"] == D(2026, 1, 1)
    h = r.text
    for s in ("Kdy proběhne čištění mojí ulice?", "Příštích 7 dní", "Kalendář jen pro vaše ulice",
              "Harmonogram do konce roku", "Příští týden", "Stav k 12. 11. 2026", "letos 5 termínů na 5 místech",
              "Funguje v Google Kalendáři, Apple Kalendáři i Outlooku.", 'href="/verejny-prostor/blokove-cisteni/ulice/wolkerova.ics"',
              "poloha přibližná", "není na mapě", "Letošní proběhlé termíny (1)", 'data-src="/api/v1/cisteni?od=2026-11-12"'):
        assert s in h, s
    assert "aplikac" not in h.lower() and "letos už ne" not in h
    assert 'href="/verejny-prostor/blokove-cisteni" aria-current="true">Veřejný prostor' in h.split("</header>")[0]
    assert get("/verejny-prostor/blokove-cisteni?probehle=1").text.count("Letošní proběhlé termíny") >= 1
    # the map's anchors and the week's rows share the place key, so they light up together
    anchors = json.loads(h.split('<script type="application/json" id="cl-anchors">')[1].split("</script>")[0])
    jr = next(k for a in anchors for k in a["keys"] if k.startswith("josefa ressla"))
    assert f'data-cl-key="{jr}"' in h and 'data-anchors="cl-anchors"' in h


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
        ("Josefa Ressla", "od Lexova", "pravá strana 18.\u00a011. a 3.\u00a012., levá 19.\u00a011.", "/verejny-prostor/blokove-cisteni/ulice/josefa-ressla"),
        ("Vnitroblok za školou", "Blokové čištění", "26.\u00a011.", None)]   # Wolkerova: nothing left this year
    assert len(a[0]["keys"]) == 2                                   # both sides drawn as one line are one stretch
    assert a[0]["label"].startswith("Blokové čištění: Josefa Ressla, od Lexova, pravá strana")
    assert (a[0]["lng"], a[0]["lat"]) == (15.765, 50.03)


def test_search(fixture):
    r = get("/verejny-prostor/blokove-cisteni", params={"ulice": "WOLKEROVÁ"})
    assert r.status_code == 303 and r.headers["location"] == "/verejny-prostor/blokove-cisteni/ulice/wolkerova"
    r = get("/verejny-prostor/blokove-cisteni", params={"ulice": "ova"})       # Wolkerova, Sokolovská, Lexova
    assert r.status_code == 200 and "je víc" in r.text and "/verejny-prostor/blokove-cisteni/ulice/lexova" in r.text
    assert "nemáme" in get("/verejny-prostor/blokove-cisteni", params={"ulice": "Nádražní"}).text


def test_street_page(fixture):
    r = get("/verejny-prostor/blokove-cisteni/ulice/wolkerova")
    assert r.status_code == 200
    h = r.text
    for s in ("Příští čištění", "26. 11.", "čtvrtek od 7:00, za 14 dní", "Celá ulice, obě strany.",
              "Termíny Wolkerovy do kalendáře", "webcal://otevrenapetka.cz/verejny-prostor/blokove-cisteni/kalendar.ics?ulice=wolkerova",
              "Harmonogram čištění pro letošek", "příští", "cl-past", "Okolní ulice", "/verejny-prostor/blokove-cisteni/ulice/sokolovska",
              "Wolkerova od ul. Čs. armády k ul. Lexova - obě strany komunikace", "ve čtvrtek 26. 11. od 7:00",
              "Přidat i další ulice"):
        assert s in h, s
    assert "Ulice je teď uzavřená" not in h and "aplikac" not in h.lower()
    fc = json.loads(h.split('id="cl-street-json">')[1].split("</script>")[0])
    assert {f["properties"]["when"] for f in fc["features"]} == {"next", "past"}
    assert get("/verejny-prostor/blokove-cisteni/ulice/neni").status_code == 404


def test_calendar_page_without_js(fixture):
    r = get("/verejny-prostor/blokove-cisteni/kalendar", params=[("ulice", "wolkerova"), ("pridat", "lexova")])
    assert r.status_code == 200
    assert "Přidat 2 ulice do kalendáře" in r.text
    assert "webcal://otevrenapetka.cz/verejny-prostor/blokove-cisteni/kalendar.ics?ulice=wolkerova,lexova" in r.text
    assert "https://otevrenapetka.cz/verejny-prostor/blokove-cisteni/kalendar.ics?ulice=wolkerova,lexova" in r.text.replace("http://", "https://")


def test_absolute_links_ignore_the_host_header(fixture):
    r = TestClient(app).get("/verejny-prostor/blokove-cisteni/kalendar", params={"ulice": "wolkerova"}, headers={"host": "localhost:8000"})
    assert r.status_code == 200 and "localhost" not in r.text


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
    fc = r.json()
    by = {f["properties"]["street"]: f for f in fc["features"]}
    assert set(by) == {"Wolkerova", "Lexova"} and len(fc["features"]) == 3
    lex = by["Lexova"]
    assert lex["geometry"] is None and lex["properties"]["status"] == "manual"
    w = [f for f in fc["features"] if f["properties"]["next"] == "2026-11-26"][0]
    assert w["geometry"] == GEOM
    assert w["properties"] == {"key": w["id"], "street": "Wolkerova", "slug": "wolkerova",
                               "texts": ["Wolkerova v celé délce - obě strany komunikace"], "status": "auto",
                               "side": "obe", "dates": [{"date": "2026-11-26", "time": "07:00", "before": False}],
                               "next": "2026-11-26"}
    assert get("/api/v1/cisteni", params={"od": "1. 1."}).status_code == 422


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
    assert jobs.load_overrides() == {}
    fc = json.loads(jobs.OVERRIDES.read_text())
    assert fc["type"] == "FeatureCollection"
