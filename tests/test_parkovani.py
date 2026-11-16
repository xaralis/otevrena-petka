"""Parkování (petka.parkovani): the source's answers into lots and numbers, the join with the
curated files (SMS code, the regulation's price, hours that differ), obvody of points and areas,
the guard, the fetcher (changed_at, the 5-minute history, the last good data on failure, one
alert), the statistics and the API (shapes, ?obvod=, ETag/304, 503) and the page. Tests with the
database skip without it."""

import datetime as dt

import httpx
import pytest
from fastapi.testclient import TestClient

from petka import db, obvody
from petka.parkovani import build, data, jobs, queries, source, stats, web
from petka.web.app import app

UTC = dt.UTC


def occ_item(dev, name="Sladkovského I.", free=5, total=20, number="1", area=1, loc=10, ticket="LI-1",
             lng=15.7723, lat=50.0382, prices=None, spec="mixed", description="Cena za první a za každou další hodinu."):
    return {"devID": dev, "deviceName": name, "description": description, "appName": "Sladkovského",
            "position": {"lat": lat, "lng": lng}, "data": {"free": free, "total": total},
            "config": {"priceList": prices if prices is not None else [{"day": "pondělí-neděle", "time": "07:00 - 20:00", "price": "50/50 Kč"}]},
            "configParking": {"areaID": area, "locationID": loc, "zoneNumber": number, "specification": spec},
            "deviceClass": "ParkingZone", "ticketID": ticket}


LOCATIONS = [{"config": {"areaID": 1, "locationID": 10, "zoneNumber": "L.1/A-1/2"}},
             {"config": {"areaID": 2, "locationID": 10, "zoneNumber": "B-2/53"}},
             {"config": {"areaID": 1, "locationID": 11, "zoneNumber": ""}}]


# --- source -----------------------------------------------------------------------------------

def test_lots_of_keeps_the_sources_facts():
    occ = [occ_item("B"), occ_item("A", area=2, ticket=None, description="Jen pro rezidenty", spec="resident"),
           occ_item("C", total=0), {"devID": "D", "data": {"total": 3}, "position": {}}]
    lots = source.lots_of(occ, LOCATIONS)
    assert [lt["id"] for lt in lots] == ["A", "B"]          # no places, no position: left out; by id
    a, b = lots
    assert b["locality"] == "L.1" and a["locality"] == "B-2"     # (areaID, locationID), the code's first part
    assert b["paid"] and not a["paid"] and a["kind"] == "resident" and b["capacity"] == 20
    assert b["at"] == [15.7723, 50.0382] and b["number"] == "1"
    assert b["prices"] == [{"day": "pondělí-neděle", "time": "07:00 - 20:00", "price": "50/50 Kč"}]


def test_occupancy_of():
    occ = [occ_item("A", free=3, total=10), occ_item("B", free=None, total=4), occ_item("C", total=0),
           occ_item("D", free=50, total=10)]
    assert source.occupancy_of(occ) == {"A": (3, 10), "B": (0, 4), "D": (10, 10)}


def test_fetch_sends_a_user_agent_without_personal_data():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"status": 0, "data": [occ_item("A")]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert source.fetch(c, source.OCCUPANCY)[0]["devID"] == "A"
    ua = seen[0].headers["user-agent"]
    assert ua == source.USER_AGENT and "@" not in ua
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status": 1}))) as c:
        with pytest.raises(source.SourceError, match="no data"):
            source.fetch(c, source.OCCUPANCY)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502))) as c:
        with pytest.raises(source.SourceError, match="502"):
            source.fetch(c, source.OCCUPANCY)


# --- the join with the curated files ----------------------------------------------------------

TARIFFS = {"L.1": {"hours": [{"day": "pondělí–neděle", "time": "7:00–20:00"}], "halfHour": 25, "firstHour": 50, "nextHour": 50},
           "L.6": {"hours": [{"day": "pondělí–pátek", "time": "7:00–18:00"}], "wholeDay": 5}}
CODES = {"1": {"number": "1", "zone": "A", "name": "Pernštýnske náměstí", "sms": "1"}}


def src(**kw):
    return source.lots_of([occ_item("A", **kw)], LOCATIONS)[0]


def test_lot_joins_sms_code_and_price():
    lot, notes = build.lot(src(), CODES, TARIFFS)
    assert lot["zone"] == "A" and lot["smsCode"] == "1" and lot["locality"] == "L.1" and notes == []
    assert lot["tariff"] == TARIFFS["L.1"] and lot["note"] == ""
    assert set(lot) >= {"id", "name", "area", "zone", "smsCode", "paid", "note", "at", "locality", "tariff"}


def test_lot_whose_operator_lists_other_hours_or_prices():
    lot, notes = build.lot(src(prices=[{"day": "pondělí-pátek", "time": "07:00 - 18:00", "price": "40/40 Kč"}]), CODES, TARIFFS)
    assert lot["tariff"]["hoursDiffer"] is True and "hoursDiffer" not in TARIFFS["L.1"]   # a copy
    assert any("price differs" in n for n in notes) and any("hours differ" in n for n in notes)


def test_unpaid_lot_keeps_its_description_and_no_code():
    lot, _ = build.lot(src(ticket=None, description="Jen pro rezidenty"), CODES, TARIFFS)
    assert not lot["paid"] and lot["smsCode"] is None and lot["tariff"] is None and lot["note"] == "Jen pro rezidenty"


def test_price_conflicts_whole_day():
    assert build.price_conflicts([{"day": "pondělí-pátek", "time": "07:00 - 18:00", "price": "5/5 Kč"}], TARIFFS["L.6"]) == (False, False)


def test_curated_files_name_source_and_checked_date():
    for key in data.FILES:
        m = data.meta(key)
        assert m["source"] and dt.date.fromisoformat(m["checked"]), key
    assert len(data.payload("smsCodes")) == 102 and len(data.payload("machines")) == 102
    assert {z["zone"] for z in data.payload("zones")} == {"A", "B", "C"}
    assert set(data.payload("tariffs")) >= {"L.1", "L.8"}
    assert len(data.version()) == 16


# --- obvody -----------------------------------------------------------------------------------

def square(lon0, lat0, lon1, lat1):
    return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}


POLYS = {"mo1": square(15.70, 50.00, 15.78, 50.10), "mo5": square(15.78, 50.00, 15.90, 50.10)}


def test_placer_points_and_areas():
    p = build.Placer(POLYS)
    assert p.point([15.75, 50.03]) == ["mo1"] and p.point([15.80, 50.03]) == ["mo5"]
    assert p.point([16.5, 50.5]) == []
    across = [[15.77, 50.03], [15.79, 50.03], [15.79, 50.04], [15.77, 50.04], [15.77, 50.03]]
    assert p.ring(across) == ["mo1", "mo5"]
    assert p.rings([[[15.75, 50.03], [15.751, 50.03], [15.751, 50.031], [15.75, 50.03]]]) == ["mo1"]
    assert build.Placer({}).ring(across) == [] and build.Placer(None).point([15.75, 50.03]) == []


SRCS = [src(), {**source.lots_of([occ_item("B", lng=15.85)], LOCATIONS)[0]}]
BUILT = dt.datetime(2026, 11, 16, 4, 0, tzinfo=UTC)


def test_document_keeps_the_apps_files_and_narrows_places_only():
    doc, _ = build.document(BUILT, SRCS, build.Placer(POLYS))
    assert set(doc) == {"v", "built", "source", "sources", "parking", "zones", "adjacent", "localities", "sections", "smsCodes"}
    assert doc["built"] == "2026-11-16T04:00:00Z" and doc["sources"]["lots"]["fetched"] == doc["built"]
    assert doc["sources"]["tariffs"]["checked"] and doc["sources"]["smsCodes"]["url"].startswith("https://www.dpmp.cz/")
    assert set(doc["localities"]) == {"localities", "visitor", "tariffs"}
    assert [lt["obvody"] for lt in doc["parking"]["lots"]] == [["mo1"], ["mo5"]]
    assert all("obvody" in x for x in doc["parking"]["machines"] + doc["zones"] + doc["sections"] + doc["localities"]["localities"])
    mo5 = build.narrowed(doc, obvody.parse("mo5"))
    assert [lt["id"] for lt in mo5["parking"]["lots"]] == ["B"]
    assert mo5["zones"] == doc["zones"] and mo5["localities"] == doc["localities"]     # rules of the whole town
    assert all("mo5" in s["obvody"] for s in mo5["sections"]) and len(mo5["sections"]) < len(doc["sections"])
    assert build.narrowed(doc, obvody.WHOLE_TOWN) is doc


# --- guard and statistics (pure) --------------------------------------------------------------

def test_guard():
    assert jobs.problem(0, None) == "no lots"
    assert jobs.problem(111, None) is None and jobs.problem(80, 111) is None
    assert jobs.problem(70, 111) == "70 lots < 70% of 111"


def test_slot():
    assert jobs.slot(dt.datetime(2026, 11, 16, 10, 7, 31, tzinfo=UTC)) == dt.datetime(2026, 11, 16, 10, 5, tzinfo=UTC)


def test_grid_and_lots():
    rows = [{"id": "A", "dow": 1, "hour": 8, "n": 12, "occupied": 90, "total": 120, "full": 3},
            {"id": "B", "dow": 1, "hour": 8, "n": 12, "occupied": 30, "total": 120, "full": 0},
            {"id": "A", "dow": 7, "hour": 23, "n": 12, "occupied": 120, "total": 120, "full": 12}]
    g = stats.grid(rows)
    assert len(g["occupancy"]) == 7 and all(len(d) == 24 for d in g["occupancy"])
    assert g["occupancy"][0][8] == 0.5 and g["full"][0][8] == 0.125 and g["occupancy"][6][23] == 1.0
    assert g["occupancy"][2][12] is None
    ls = stats.lots(rows, {"A": "Atrium"}, {"A": ["mo1"]}, profiles=True)
    assert [x["id"] for x in ls] == ["A", "B"] and ls[0]["name"] == "Atrium" and ls[1]["name"] == "B"
    assert ls[0]["occupancy"] == 0.875 and ls[0]["capacity"] == 10 and ls[0]["profile"]["occupancy"][6][23] == 1.0
    assert stats.busiest_hours(g, 1) == [{"day": "neděle", "hour": 23, "occupancy": 1.0}]


# --- database ---------------------------------------------------------------------------------

@pytest.fixture
def conn():
    try:
        db.migrate()
    except Exception:
        pytest.skip("no local database")
    with db.connect() as c:
        for t in ("parkovani_history", "parkovani_lots", "parkovani_now", "parkovani_state", "parkovani_builds"):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM ruian_cache WHERE key LIKE 'momc_all:%%'")
        c.commit()
        queries._cache.clear()
        web._stats.clear()
        yield c
        c.rollback()


def test_store_and_refuse(conn):
    many = [{**SRCS[0], "id": f"L{i}"} for i in range(10)]
    assert jobs.store(conn, many)["lots"] == 10
    conn.commit()
    with pytest.raises(jobs.Refused):
        jobs.store(conn, many[:5])
    assert conn.execute("SELECT count(*) AS n FROM parkovani_builds WHERE accepted").fetchone()["n"] == 1
    assert jobs.store(conn, many[:5], force=True)["lots"] == 5


T0 = dt.datetime(2026, 11, 16, 10, 0, 10, tzinfo=UTC)


def test_save_moves_changed_at_only_on_change_and_writes_a_slot_once(conn):
    jobs.save(conn, {"A": (5, 20), "B": (1, 4)}, T0)
    jobs.save(conn, {"A": (5, 20), "B": (2, 4)}, T0 + dt.timedelta(minutes=1))
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM parkovani_now")}
    assert rows["A"]["changed_at"] == T0 and rows["B"]["changed_at"] == T0 + dt.timedelta(minutes=1)
    assert rows["A"]["seen_at"] == T0 + dt.timedelta(minutes=1)
    hist = conn.execute("SELECT at, free FROM parkovani_history ORDER BY lot").fetchall()
    assert [h["free"] for h in hist] == [5, 1] and {h["at"] for h in hist} == {dt.datetime(2026, 11, 16, 10, 0, tzinfo=UTC)}
    jobs.save(conn, {"A": (4, 20), "B": (2, 4)}, T0 + dt.timedelta(minutes=5))
    assert conn.execute("SELECT count(*) AS n FROM parkovani_history").fetchone()["n"] == 4
    # the small sequence of lot numbers is taken only by new lots
    assert conn.execute("SELECT max(n) AS n FROM parkovani_lots").fetchone()["n"] == 2
    with pytest.raises(source.SourceError):
        jobs.save(conn, {}, T0)


def test_failed_fetch_keeps_the_last_good_and_alerts_once(conn):
    jobs.save(conn, {"A": (5, 20)}, T0)
    conn.commit()
    alerts = []
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    for minutes in (1, 5, 11, 12):
        out = jobs.fetch_once(conn, bad, now=lambda m=minutes: T0 + dt.timedelta(minutes=m), alert=alerts.append)
        assert "error" in out
    assert len(alerts) == 1 and "parkovani-obsazenost" in alerts[0]
    st = conn.execute("SELECT * FROM parkovani_state").fetchone()
    assert st["fetched_at"] == T0 and st["error"] and st["failing_since"] == T0 + dt.timedelta(minutes=1)
    assert conn.execute("SELECT free FROM parkovani_now WHERE id = 'A'").fetchone()["free"] == 5
    good = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [occ_item("A", free=7)]})))
    assert jobs.fetch_once(conn, good, now=lambda: T0 + dt.timedelta(minutes=13))["lots"] == 1
    st = conn.execute("SELECT * FROM parkovani_state").fetchone()
    assert st["error"] is None and st["failing_since"] is None and not st["alerted"]


def test_watch_once(conn, monkeypatch):
    def client(**kw):
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [occ_item("A")]})), **kw)
    assert jobs.watch(once=True, http=client) == {"lots": 1, "free": 5, "total": 20, "history": 1}


# --- API and page -----------------------------------------------------------------------------

def get(path, **kw):
    return TestClient(app).get(path, headers={"host": "otevrenapetka.cz", **kw.pop("headers", {})}, **kw)


def test_before_the_first_build_and_fetch(conn):
    assert get("/api/v1/parkovani").status_code == 503
    assert get("/api/v1/parkovani/obsazenost").status_code == 503
    assert get("/api/v1/parkovani?obvod=mo9").status_code == 422
    assert get("/verejny-prostor/parkovani").status_code == 200


@pytest.fixture
def filled(conn):
    import json

    from petka.usneseni.geo import OBEC
    conn.execute("INSERT INTO ruian_cache (key, value) VALUES (%s, %s::jsonb) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                 (f"momc_all:{OBEC}", json.dumps(POLYS)))
    jobs.store(conn, SRCS)
    now = dt.datetime.now(UTC)
    for m in range(55, 0, -5):
        jobs.save(conn, {"A": (2, 20), "B": (10, 20)}, now - dt.timedelta(minutes=m))
    jobs.save(conn, {"A": (1, 20), "B": (10, 20)}, now)
    conn.commit()
    return conn


def test_parkovani_api(filled):
    r = get("/api/v1/parkovani")
    assert r.status_code == 200 and r.headers["etag"].startswith('W/"') and r.headers["cache-control"] == web.CACHE
    d = r.json()
    assert [lt["id"] for lt in d["parking"]["lots"]] == ["A", "B"] and d["parking"]["lots"][0]["smsCode"] == "1"
    assert get("/api/v1/parkovani", headers={"if-none-match": r.headers["etag"]}).status_code == 304
    r5 = get("/api/v1/parkovani?obvod=mo5")
    assert r5.headers["etag"] != r.headers["etag"] and [lt["id"] for lt in r5.json()["parking"]["lots"]] == ["B"]


def test_obsazenost_api(filled):
    r = get("/api/v1/parkovani/obsazenost")
    assert r.status_code == 200 and r.headers["cache-control"] == web.LIVE_CACHE
    d = r.json()
    a = d["lots"][0]
    assert a == {"id": "A", "free": 1, "total": 20, "changed_at": d["fetched_at"], "obvody": ["mo1"]}
    assert d["lots"][1]["changed_at"] < d["fetched_at"]      # B has not changed
    assert get("/api/v1/parkovani/obsazenost", headers={"if-none-match": r.headers["etag"]}).status_code == 304
    assert [x["id"] for x in get("/api/v1/parkovani/obsazenost?obvod=mo5").json()["lots"]] == ["B"]
    # a new fetch changes the ETag even when no number changed: fetched_at moved
    jobs.save(filled, {"A": (1, 20), "B": (10, 20)}, dt.datetime.now(UTC) + dt.timedelta(minutes=1))
    filled.commit()
    assert get("/api/v1/parkovani/obsazenost", headers={"if-none-match": r.headers["etag"]}).status_code == 200


def test_statistiky_api(filled):
    r = get("/api/v1/parkovani/statistiky?profily=true")
    assert r.status_code == 200 and r.headers["cache-control"] == web.STATS_CACHE
    d = r.json()
    assert d["days"] == 28 and len(d["profile"]["occupancy"]) == 7
    assert [x["id"] for x in d["lots"]] == ["A", "B"] and d["lots"][0]["occupancy"] >= 0.9 and "profile" in d["lots"][0]
    assert [x["id"] for x in get("/api/v1/parkovani/statistiky?obvod=mo5").json()["lots"]] == ["B"]
    assert get("/api/v1/parkovani/statistiky?dni=0").status_code == 422
    assert get("/api/v1/parkovani/statistiky", headers={"if-none-match": r.headers["etag"]}).status_code == 200  # other params
    r2 = get("/api/v1/parkovani/statistiky")
    assert get("/api/v1/parkovani/statistiky", headers={"if-none-match": r2.headers["etag"]}).status_code == 304


def test_page(filled):
    r = get("/verejny-prostor/parkovani?kde=mesto")
    assert r.status_code == 200
    assert "Volno teď" in r.text and "Kdy bývá plno" in r.text and "pk-heat" in r.text and "Sladkovského I." in r.text
    r = get("/verejny-prostor/parkovani")             # MO V has one lot here: the town, said so
    assert "ukazujeme celé město" in r.text


def test_data_page_lists_parkovani(filled):
    r = get("/data")
    assert 'id="parkovani"' in r.text and "/api/v1/parkovani/obsazenost" in r.text
