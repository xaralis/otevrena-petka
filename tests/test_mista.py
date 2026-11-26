"""Místa (petka.mista): Overpass elements into places for every kind, waste kinds, the Czech
`what`, point -> obvod, the 70 % guard, and the API's shape, filters, 422 and ETag/304 over a
mocked query layer. The store test needs the local database and skips without it."""

import datetime as dt

import httpx
import pytest
from fastapi.testclient import TestClient

from petka import db, obvody
from petka.mista import export, jobs, osm, queries, where
from petka.web.app import app


def node(i, lon=15.77, lat=50.03, **tags):
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags}


def way(i, lon=15.77, lat=50.03, **tags):
    return {"type": "way", "id": i, "center": {"lat": lat, "lon": lon}, "tags": tags}


def one(**tags):
    places = osm.places_of([node(1, **tags)])
    return places[0] if places else None


# --- parsing ---------------------------------------------------------------------------------

@pytest.mark.parametrize("tags, kind, what", [
    ({"shop": "supermarket", "name": "Albert"}, "potraviny", "Supermarket"),
    ({"shop": "convenience"}, "potraviny", "Večerka"),
    ({"amenity": "atm", "operator": "ČSOB"}, "bankomat", "Bankomat"),
    ({"amenity": "bank", "atm": "yes", "name": "KB"}, "bankomat", "Bankomat u pobočky"),
    ({"amenity": "pharmacy"}, "lekarna", "Lékárna"),
    ({"amenity": "fast_food"}, "jidlo", "Rychlé občerstvení"),
    ({"amenity": "biergarten"}, "jidlo", "Pivní zahrádka"),
    ({"historic": "castle", "name": "Zámek Pardubice"}, "pamatky", "Zámek"),
    ({"historic": "boundary_stone", "name": "Kámen"}, "pamatky", "Památka"),
    ({"tourism": "museum", "name": "Východočeské muzeum"}, "pamatky", "Muzeum"),
    ({"tourism": "attraction", "name": "Zelená brána"}, "pamatky", "Zajímavé místo"),
    ({"amenity": "place_of_worship", "name": "Sv. Jan", "building": "chapel"}, "pamatky", "Kaple"),
    ({"amenity": "place_of_worship", "name": "Sv. Bartoloměj"}, "pamatky", "Kostel"),
    ({"amenity": "toilets", "fee": "yes"}, "wc", "Toaleta, placená"),
    ({"amenity": "toilets", "fee": "no"}, "wc", "Toaleta, zdarma"),
    ({"amenity": "toilets"}, "wc", "Toaleta"),
    ({"amenity": "post_office", "name": "Balíkovna Albert"}, "posta", "Balíkovna"),
    ({"amenity": "post_office", "operator": "Česká pošta, s.p."}, "posta", "Pobočka České pošty"),
    ({"amenity": "post_office", "name": "Zásilkovna"}, "posta", "Pošta"),
    ({"amenity": "bicycle_parking"}, "stojan", "Stojan na kola"),
    ({"amenity": "bicycle_parking", "covered": "yes"}, "stojan", "Kryté stání pro kola"),
    ({"amenity": "bicycle_parking", "bicycle_parking": "shed"}, "stojan", "Kryté stání pro kola"),
    ({"amenity": "bicycle_parking", "bicycle_parking": "lockers"}, "stojan", "Boxy na kola"),
    ({"amenity": "recycling", "recycling_type": "container", "recycling:glass": "yes"}, "kontejner",
     "Kontejnery na tříděný odpad"),
    ({"amenity": "recycling", "recycling:paper": "yes"}, "kontejner", "Kontejnery na tříděný odpad"),
    ({"amenity": "recycling", "recycling_type": "centre"}, "dvur", "Sběrný dvůr"),
])
def test_kind_and_what(tags, kind, what):
    assert osm.classify(tags) == (kind, what)


@pytest.mark.parametrize("tags", [
    {"amenity": "atm", "name": "Bitcoinmat"},
    {"amenity": "atm", "operator": "Kvakomat"},
    {"amenity": "toilets", "access": "customers"},
    {"historic": "memorial", "memorial": "stolperstein", "name": "Kámen zmizelých"},
    {"historic": "castle"},                        # a sight without a name
    {"amenity": "bicycle_parking", "access": "private"},
    {"amenity": "bench"},
])
def test_left_out(tags):
    assert osm.classify(tags) is None


def test_place_fields():
    p = osm.places_of([way(42, 15.776694, 50.038091, shop="supermarket", brand="Albert ",
                           **{"addr:street": "Teplého", "addr:housenumber": "2119",
                              "opening_hours": " Mo-Su 07:00-21:00 "})])[0]
    assert p == {"id": "w42", "kind": "potraviny", "name": "Albert", "what": "Supermarket",
                 "address": "Teplého 2119", "at": [15.77669, 50.03809], "hours": "Mo-Su 07:00-21:00"}
    assert one(amenity="toilets")["name"] == "Veřejné WC"
    assert one(amenity="atm", operator="ČSOB")["name"] == "ČSOB"
    assert one(amenity="pharmacy")["name"] == "Lékárna"                  # no name: what it is
    assert one(amenity="pharmacy", **{"addr:place": "Hostovice"})["address"] == "Hostovice"
    assert one(amenity="pharmacy", **{"addr:housenumber": "5"})["address"] is None


@pytest.mark.parametrize("tags, contact", [
    ({}, {}),
    ({"phone": "466 535 200"}, {"phone": "+420 466 535 200"}),
    ({"contact:phone": "+420466535200; +420 777 111 222"}, {"phone": "+420 466 535 200"}),
    ({"phone": "00420 777 111 222"}, {"phone": "+420 777 111 222"}),
    ({"phone": "+49 30 1234567"}, {"phone": "+49301234567"}),
    ({"phone": "neuvedeno"}, {}),
    ({"website": "www.medila.cz"}, {"web": "https://www.medila.cz"}),
    ({"contact:website": "https://a.cz/x", "website": "https://b.cz"}, {"web": "https://b.cz"}),
    ({"contact:facebook": "medila.pardubice"}, {"web": "https://www.facebook.com/medila.pardubice"}),
    ({"contact:instagram": "@kavarna"}, {"web": "https://www.instagram.com/kavarna"}),
    ({"website": "https://a.cz", "contact:facebook": "a"}, {"web": "https://a.cz"}),
    ({"email": "mailto:info@a.cz"}, {"email": "info@a.cz"}),
    ({"email": "není"}, {}),
])
def test_contact(tags, contact):
    p = one(amenity="pharmacy", **tags)
    assert {k: p[k] for k in ("phone", "web", "email") if k in p} == contact


def test_racks_containers_and_dvur():
    rack = one(amenity="bicycle_parking", capacity="10")
    assert rack["name"] is None and rack["capacity"] == 10 and "odpad" not in rack
    assert one(amenity="bicycle_parking", capacity="cca 10")["capacity"] is None
    assert one(amenity="bicycle_parking")["capacity"] is None
    c = one(amenity="recycling", recycling_type="container", name="Hnízdo Jiráskova",
            **{"recycling:plastic": "yes", "recycling:glass_bottles": "yes", "recycling:paper": "no",
               "recycling:cardboard": "yes", "recycling:beverage_cartons": "yes"})
    assert c["name"] == "Hnízdo Jiráskova" and c["odpad"] == ["papir", "plast", "sklo"] and "capacity" not in c
    assert one(amenity="recycling", recycling_type="container", **{"recycling:books": "yes"}) is None
    d = one(amenity="recycling", recycling_type="centre", brand="SmP")
    assert d["kind"] == "dvur" and d["name"] is None and d["odpad"] == []


@pytest.mark.parametrize("key, kind", [
    ("cardboard", "papir"), ("pet_drink_bottles", "plast"), ("glass", "sklo"), ("scrap_metal", "kov"),
    ("shoes", "textil"), ("small_electrical_appliances", "elektro"), ("batteries", "baterie"),
    ("cooking_oil", "olej"), ("food_waste", "bio"),
])
def test_waste_kinds(key, kind):
    assert osm.waste({f"recycling:{key}": "yes"}) == [kind]


def test_sorted_and_without_position():
    ps = osm.places_of([node(20, amenity="pharmacy"), node(3, amenity="atm"), node(100, amenity="pharmacy"),
                        {"type": "relation", "id": 5, "tags": {"amenity": "pharmacy"}}])   # no centre
    assert [(p["kind"], p["id"]) for p in ps] == [("bankomat", "n3"), ("lekarna", "n100"), ("lekarna", "n20")]


# --- obvody ----------------------------------------------------------------------------------

SQUARE = lambda x0, x1: {"type": "Polygon", "coordinates": [[[x0, 50.0], [x1, 50.0], [x1, 50.1], [x0, 50.1], [x0, 50.0]]]}  # noqa: E731


def test_point_in_obvod():
    o = where.Obvody({"mo5": SQUARE(15.70, 15.75), "mo1": SQUARE(15.75, 15.80)})
    assert o.of(15.72, 50.05) == ["mo5"]
    assert o.of(15.78, 50.05) == ["mo1"]
    assert o.of(15.80015, 50.05) == ["mo1"]         # ~11 m outside: still the nearest obvod
    assert o.of(15.81, 50.05) == []                  # outside the town
    assert where.Obvody({}).of(15.72, 50.05) == []
    ps = where.place_all([{"at": [15.72, 50.05]}], o)
    assert ps[0]["obvody"] == ["mo5"]


# --- the guard -------------------------------------------------------------------------------

LAST = {"potraviny": 100, "stojan": 600, "kontejner": 500, "dvur": 12, "wc": 6}


def test_guard():
    assert jobs.problem(LAST, None) is None
    assert jobs.problem({k: 0 for k in LAST}, None) == "no places"
    assert jobs.problem(LAST, LAST) is None
    assert jobs.problem({**LAST, "stojan": 420}, LAST) is None                 # exactly 70 %
    assert jobs.problem({**LAST, "stojan": 419}, LAST) == "stojan 419 < 70% of 600"
    assert jobs.problem({**LAST, "dvur": 8}, LAST) == "dvur 8 < 70% of 12"
    assert jobs.problem({**LAST, "wc": 1}, LAST) is None                       # a small kind alone
    half = {k: v // 2 for k, v in LAST.items()}
    assert jobs.problem(half, LAST).startswith("total 609 < 70% of 1218")
    assert jobs.problem({k: v for k, v in LAST.items() if k != "kontejner"}, LAST).endswith("kontejner 0 < 70% of 500")


@pytest.fixture
def conn():
    try:
        db.migrate()
    except Exception:
        pytest.skip("no local database")
    with db.connect() as c:
        yield c
        c.rollback()


def test_store_replaces_and_refuses(conn):
    conn.execute("DELETE FROM mista_builds")
    rack = {"id": "n1", "kind": "stojan", "name": None, "what": "Stojan na kola", "address": None,
            "at": [15.77, 50.03], "hours": None, "obvody": ["mo5"], "capacity": 4}
    many = [{**rack, "id": f"n{i}"} for i in range(20)]
    s = jobs.store(conn, many)
    assert s["places"] == 20 and s["kinds"]["stojan"] == 20 and s["obvody"] == {"mo5": 20}
    with pytest.raises(jobs.Refused):
        jobs.store(conn, many[:10])
    assert conn.execute("SELECT count(*) AS n FROM mista_places").fetchone()["n"] == 20
    assert jobs.store(conn, many[:10], force=True)["places"] == 10


# --- fetch -----------------------------------------------------------------------------------

def test_fetch_retries_once_and_sends_a_user_agent():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(504 if len(seen) == 1 else 200, json={"elements": []})
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert osm.fetch(c, "https://overpass.test/api", sleep=lambda s: None) == {"elements": []}
    assert len(seen) == 2 and seen[0].headers["user-agent"] == osm.USER_AGENT
    assert b"bicycle_parking" in seen[0].content

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as c:
        with pytest.raises(osm.OverpassError, match="429"):
            osm.fetch(c, "https://overpass.test/api", sleep=lambda s: None)
    partial = {"elements": [], "remark": "runtime error: Query timed out"}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=partial))) as c:
        with pytest.raises(osm.OverpassError, match="timed out"):
            osm.fetch(c, "https://overpass.test/api")


# --- API -------------------------------------------------------------------------------------

BUILT = dt.datetime(2026, 11, 16, 4, 40, 3, 123, tzinfo=dt.timezone.utc)
ROWS = [
    {"id": "n1", "kind": "kontejner", "name": None, "what": "Kontejnery na tříděný odpad", "address": None,
     "lon": 15.77, "lat": 50.03, "hours": None, "obvody": ["mo5"], "odpad": ["papir", "plast"], "capacity": None},
    {"id": "n2", "kind": "potraviny", "name": "Albert", "what": "Supermarket", "address": "Teplého 2119",
     "lon": 15.77669, "lat": 50.03809, "hours": "Mo-Su 07:00-21:00", "obvody": ["mo5"], "odpad": None,
     "capacity": None},
    {"id": "w3", "kind": "stojan", "name": None, "what": "Stojan na kola", "address": None,
     "lon": 15.78, "lat": 50.04, "hours": None, "obvody": ["mo1"], "odpad": None, "capacity": 10},
    {"id": "n4", "kind": "wc", "name": "Veřejné WC", "what": "Toaleta", "address": None,
     "lon": 15.9, "lat": 50.1, "hours": None, "obvody": [], "odpad": None, "capacity": None},
    {"id": "n5", "kind": "misto", "name": "Medila", "what": "Poliklinika", "address": "Pernerova 444",
     "lon": 15.77, "lat": 50.04, "hours": None, "obvody": ["mo1"], "odpad": None, "capacity": None,
     "phone": "+420 466 535 200", "web": "https://www.medila.cz", "email": None},
]


@pytest.fixture
def api(monkeypatch):
    state = {"built": BUILT}
    monkeypatch.setattr(queries, "built", lambda: state["built"])
    monkeypatch.setattr(queries, "places", lambda at: [export.place(r) for r in ROWS])
    return state


def get(path, **kw):
    return TestClient(app).get(path, headers={"host": "otevrenapetka.cz", **kw.pop("headers", {})}, **kw)


def test_file_v2(api):
    r = get("/api/v1/mista")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.headers["cache-control"] == "public, max-age=3600" and r.headers["etag"].startswith('W/"')
    f = r.json()
    assert {k: f[k] for k in ("v", "built", "licence", "source")} == {
        "v": 2, "built": "2026-11-16T04:40:03Z", "licence": "© přispěvatelé OpenStreetMap, ODbL 1.0",
        "source": "https://otevrenapetka.cz/data#mista"}
    by = {p["id"]: p for p in f["places"]}
    assert by["n1"] == {"id": "n1", "kind": "kontejner", "name": None, "what": "Kontejnery na tříděný odpad",
                        "address": None, "at": [15.77, 50.03], "hours": None, "obvody": ["mo5"],
                        "odpad": ["papir", "plast"]}
    assert by["w3"]["capacity"] == 10 and "odpad" not in by["w3"]
    assert "odpad" not in by["n2"] and "capacity" not in by["n2"]
    assert by["n4"]["obvody"] == []                                   # the whole town takes it
    assert by["n5"]["phone"] == "+420 466 535 200" and by["n5"]["web"] == "https://www.medila.cz"
    assert "email" not in by["n5"] and "phone" not in by["n2"]        # only what OSM has


def test_filters(api):
    ids = lambda **params: [p["id"] for p in get("/api/v1/mista", params=params).json()["places"]]  # noqa: E731
    assert ids() == ["n1", "n2", "w3", "n4"]
    assert ids(obvod="mo5") == ["n1", "n2"]
    assert ids(obvod="mo1,mo5", druh="stojan, KONTEJNER") == ["n1", "w3"]
    assert ids(druh="dvur") == []
    r = get("/api/v1/mista", params={"druh": "kos"})
    assert r.status_code == 422 and "stojan" in r.json()["detail"]
    assert get("/api/v1/mista.geojson", params={"obvod": "mo9"}).status_code == 422


def test_geojson(api):
    r = get("/api/v1/mista.geojson", params={"druh": "stojan"})
    assert r.headers["content-type"].startswith("application/geo+json")
    fc = r.json()
    assert fc["type"] == "FeatureCollection" and fc["licence"].endswith("ODbL 1.0")
    assert fc["features"] == [{"type": "Feature", "id": "w3", "geometry": {"type": "Point", "coordinates": [15.78, 50.04]},
                               "properties": {"id": "w3", "kind": "stojan", "name": None, "what": "Stojan na kola",
                                              "address": None, "hours": None, "obvody": ["mo1"], "capacity": 10}}]


def test_etag_and_304(api):
    tag = get("/api/v1/mista").headers["etag"]
    r = get("/api/v1/mista", headers={"if-none-match": tag})
    assert r.status_code == 304 and r.headers["etag"] == tag and not r.content
    assert get("/api/v1/mista", headers={"if-none-match": tag.removeprefix("W/")}).status_code == 304
    assert get("/api/v1/mista", params={"obvod": "mo5"}, headers={"if-none-match": tag}).status_code == 200
    assert get("/api/v1/mista.geojson", headers={"if-none-match": tag}).status_code == 200
    api["built"] = BUILT + dt.timedelta(days=1)                       # a new build
    assert get("/api/v1/mista", headers={"if-none-match": tag}).status_code == 200


def test_gzip(api, monkeypatch):
    many = [{**ROWS[1], "id": f"n{i}"} for i in range(50)]
    monkeypatch.setattr(queries, "places", lambda at: [export.place(r) for r in many])
    r = TestClient(app).get("/api/v1/mista", headers={"accept-encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip" and len(r.json()["places"]) == 50


def test_not_built_yet(monkeypatch):
    monkeypatch.setattr(queries, "built", lambda: None)
    assert get("/api/v1/mista").status_code == 503


def test_etag_depends_on_filter():
    a = export.etag(BUILT, "v2", obvody.WHOLE_TOWN, ())
    assert a == export.etag(BUILT, "v2", obvody.ObvodFilter(), ())
    assert a != export.etag(BUILT, "v2", obvody.ObvodFilter(("mo5",)), ())
    assert a != export.etag(BUILT, "v2", obvody.WHOLE_TOWN, ("stojan",))


def test_data_page_lists_mista(monkeypatch):
    """The Místa tab of Data a API; the other sections' numbers (from the database) left blank."""
    from jinja2 import ChainableUndefined

    from petka.web import app as webapp
    from petka.web.render import tpl
    monkeypatch.setattr(tpl.env, "undefined", ChainableUndefined)
    monkeypatch.setattr(webapp, "_merged", lambda hook: {"mi_cat": {"total": 2345, "built_at": BUILT}, "deska": {"total": 0}, "tables": []})
    html = get("/data").text
    i = html.index('id="mista"')
    assert "/api/v1/mista.geojson" in html[i:] and "ODbL" in html[i:] and "2 345 míst" in html[i:]
    assert '<a href="#mista" data-tab="mista">Místa</a>' in html


def test_city_yards_apart_from_private_centres():
    city = [{"key": "dvur-hurka", "name": "Hůrka", "address": "areál SmP a.s., Hůrka 1803", "point": [15.80939, 50.04825],
             "hours": [{"days": ["út", "st", "čt"], "from": "13:00", "to": "17:00"}, {"days": ["so"], "from": "8:00", "to": "12:00"}]},
            {"key": "dvur-drazkovice", "name": "Dražkovice", "address": "areál překladiště odpadu", "point": [15.76453, 50.00655],
             "hours": [{"days": ["po"], "from": "6:30", "to": "15:00"}]}]
    places = [{"id": "w1", "kind": "dvur", "name": "Sběrný dvůr - Hůrka", "what": "Sběrný dvůr", "address": "Hůrka 1803",
               "at": [15.80941, 50.04826], "hours": None, "odpad": []},
              {"id": "w2", "kind": "dvur", "name": "KOVOŠROT Hůrka s.r.o.", "what": "Sběrný dvůr", "address": "Hůrka 1786",
               "at": [15.81209, 50.05041], "hours": None, "odpad": ["kov"]},
              {"id": "n3", "kind": "kontejner", "name": None, "what": "x", "address": None, "at": [15.8, 50.0], "hours": None, "odpad": ["sklo"]}]
    out = {p["id"]: p for p in osm.split_yards(places, city)}
    assert out["w1"]["kind"] == "dvur" and out["w1"]["name"] == "Sběrný dvůr Hůrka" and out["w1"]["hours"] == "Tu,We,Th 13:00-17:00; Sa 08:00-12:00"
    assert out["w2"]["kind"] == "vykupna" and out["w2"]["name"] == "KOVOŠROT Hůrka s.r.o."
    assert out["dvur-drazkovice"]["kind"] == "dvur" and out["dvur-drazkovice"]["at"] == [15.76453, 50.00655]   # not in OSM
    assert out["n3"]["kind"] == "kontejner"


# --- misto: every other named place -----------------------------------------------------------

@pytest.mark.parametrize("tags, what", [
    ({"office": "company", "name": "Medila"}, "Firma"),
    ({"building": "industrial", "name": "Medila"}, "Průmyslová budova"),
    ({"shop": "clothes", "name": "Pepco"}, "Oblečení"),
    ({"shop": "clothes", "brand": "Pepco"}, "Oblečení"),
    ({"amenity": "dentist", "name": "MUDr. Nováková"}, "Zubař"),
    ({"healthcare": "doctor", "amenity": "doctors", "name": "Praktik"}, "Lékař"),
    ({"amenity": "school", "name": "ZŠ Studánka"}, "Škola"),
    ({"leisure": "pitch", "name": "Hřiště Dukla"}, "Hřiště"),
    ({"landuse": "industrial", "name": "Synthesia"}, "Průmyslový areál"),
    ({"craft": "unknown_craft", "name": "Dílna"}, "Řemeslo"),
    ({"healthcare": "laboratory", "name": "MEDILA - Odběrové centrum Polabiny"}, "Laboratoř"),
    ({"amenity": "clinic", "healthcare": "clinic", "name": "MEDILA poliklinika"}, "Poliklinika"),
    ({"place": "neighbourhood", "name": "Dukla"}, "Čtvrť"),
    ({"tourism": "artwork", "name": "Socha Jana Pernera"}, "Umělecké dílo"),
    ({"shop": "supermarket", "name": "Billa", "building": "retail"}, "Supermarket"),
])
def test_other_named_places(tags, what):
    p = one(**tags)
    if tags.get("shop") == "supermarket":
        assert p["kind"] == "potraviny"
        return
    assert (p["kind"], p["what"]) == ("misto", what)
    assert p["name"] == (tags.get("name") or tags.get("brand"))


@pytest.mark.parametrize("tags", [
    {"amenity": "bench", "name": "Lavička"},
    {"building": "garage", "name": "Garáž"},
    {"building": "house", "name": "Vila"},
    {"landuse": "residential", "name": "Sídliště"},
    {"shop": "vacant", "name": "Bývalý obchod"},
    {"shop": "clothes"},
    {"man_made": "mast", "name": "Stožár"},
    {"tourism": "information", "name": "Rozcestník"},
    {"place": "city", "name": "Pardubice"},
])
def test_other_left_out(tags):
    assert one(**tags) is None


def test_a_place_mapped_twice_is_listed_once():
    """A firm as its building and as a point in it is one place; a pharmacy in a building of its
    name, and a firm of another name in the same building, stay."""
    places = osm.places_of([
        way(1, building="industrial", name="Medila"),
        node(2, lon=15.7701, office="company", name="Medila"),
        node(3, lon=15.7702, amenity="pharmacy", name="Lékárna Medila"),
        way(4, lon=15.7702, building="commercial", name="Lékárna Medila"),
        node(5, lon=15.7703, office="lawyer", name="AK Novák"),
        node(6, lon=15.80, office="company", name="Medila"),
    ])
    got = sorted((p["id"], p["kind"], p["what"]) for p in places)
    assert got == [("n2", "misto", "Firma"), ("n3", "lekarna", "Lékárna"), ("n5", "misto", "Advokát"), ("n6", "misto", "Firma"),
                   ("w4", "misto", "Komerční budova")]
