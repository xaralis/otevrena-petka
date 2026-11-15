"""Podněty: Dej Tip rows are parsed by position, only the public fields survive (the description
with phones and e-mails masked, the photo only when public), chybné/spam/
smazané are dropped, the window, near and the API's GeoJSON. Rows here are made up in the
shape of the real answer (23 positional fields, checked 12. 11. 2026); no real report is in
the repository. Tests touching the database skip without one."""

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from petka import db, obvody
from petka.podnety import jobs, queries, source, web
from petka.web.app import app

MO5 = obvody.MO5.momc
COMMENT = "Nemám rád souseda, volejte 777 123 456 nebo pis.mi@example.cz"
PHOTO = "http://www.dejtip.eu/_fotoobce/0000-abc.jpeg"
SECRETS = ("12.11.2026 10:00:00¦jan.urednik@example.cz¦předáno TS",
           "urednik.login", "https://example.com/admin/abc",
           "Android 14", "Pixel Fake", "jan.urednik@example.cz", "777 123 456", "pis.mi", "Pixel")


def row(id=10000000001, status=1, momc=MO5, address="Pardubice, Na Záboří 223, Pardubice, 53002, Nové Jesenčany",
        date="01.11.2026 12:57", lat=50.0301, lng=15.7602, comment=COMMENT, image=PHOTO, public=1):
    """One fake row in Dej Tip's positional layout, with something private in every column
    we must not keep."""
    return [id, 4242, "Android 14", "Pixel Fake", 0.0, "Chodník", address,
            comment, lat, lng, image,
            "https://example.com/admin/abc", "12.11.2026 10:00:00¦jan.urednik@example.cz¦předáno TS",
            19, 12.5, 1, public, status, date, momc, None, "urednik.login", None]


def answer(rows) -> dict:
    return {"d": json.dumps(rows)}


def test_positions_and_sanitize_keep_only_public_fields():
    r = source.sanitize(source.parse(answer([row()]))[0])
    assert r == {"id": 10000000001, "category_id": 19, "category": "Chodník", "status": 1,
                 "reported_at": dt.datetime(2026, 11, 1, 12, 57), "lat": 50.0301, "lng": 15.7602,
                 "street": "Na Záboří", "momc": MO5,
                 "first_note_at": dt.datetime(2026, 11, 12, 10), "last_note_at": dt.datetime(2026, 11, 12, 10),
                 "description": "Nemám rád souseda, volejte [telefon] nebo [e-mail]",
                 "photo_url": "https://www.dejtip.eu/_fotoobce/0000-abc.jpeg"}
    stored = json.dumps(r, default=str, ensure_ascii=False)
    for s in SECRETS + ("223", "53002", "Nové Jesenčany", "@", "http://"):
        assert s not in stored


@pytest.mark.parametrize("text, masked", [
    ("volejte 777 123 456", "volejte [telefon]"),
    ("tel. +420777123456.", "tel. [telefon]."),
    ("+420 777 123 456 večer", "[telefon] večer"),
    ("00420 608-123-456", "[telefon]"),
    ("777-123-456, 777.123.456 a 777123456", "[telefon], [telefon] a [telefon]"),
    ("číslo 777 12 34 56", "číslo [telefon]"),
    ("pište na Jan.Novak+dejtip@seznam.cz!", "pište na [e-mail]!"),
    ("a@b.cz, x_y@sub.domena.eu", "[e-mail], [e-mail]"),
])
def test_mask_phones_and_emails(text, masked):
    assert source.mask(text) == masked


@pytest.mark.parametrize("text", [
    "Od 12. 11. 2026 tu leží odpad", "u domu č. p. 2517-2521", "č. p. 2517/21", "IČO 00274046",
    "datum 12.11.2026 10:00", "Sokolovská 2869, 530 02", "rok 2025 a 2026", "linie 1234 5678",
])
def test_mask_leaves_dates_and_numbers(text):
    assert source.mask(text) == text


def test_mask_empty_and_long():
    assert source.mask(None) is None and source.mask("  ") is None and source.mask(3) is None
    assert len(source.mask("x" * 5000)) == source.DESCRIPTION_MAX


def test_photo_only_when_public_and_https():
    assert source.photo(PHOTO, 1) == "https://www.dejtip.eu/_fotoobce/0000-abc.jpeg"
    assert source.photo(PHOTO, 0) is None and source.photo(PHOTO, None) is None
    assert source.photo(None, 1) is None
    assert source.photo("http://example.com/x.jpg", 1) is None                # not https, not Dej Tip
    assert source.photo("https://example.com/x.jpg", 1) == "https://example.com/x.jpg"
    assert source.photo('https://example.com/"><script>', 1) is None
    r = source.sanitize(row(image=PHOTO, public=0, comment=None))
    assert r["photo_url"] is None and r["description"] is None
    assert source.detail(10000101690) == "https://amg.dejtip.eu/pardubice/?id=10000101690"


def test_note_dates_only_the_dates_of_every_entry():
    note = ("02.01.2025 08:32:12¦a@example.cz¦Předáno OŽP 15.01.2025 09:00 jinak"
            "03.02.2025 10:00:00¦b@example.cz¦Vyřešeno")
    assert source.note_dates(note) == (dt.datetime(2025, 1, 2, 8, 32, 12), dt.datetime(2025, 2, 3, 10))
    assert source.note_dates(None) == (None, None)
    assert source.note_dates("bez data") == (None, None)
    assert source.note_dates("31.02.2025 08:00:00¦a@example.cz¦x") == (None, None)


def test_street_without_number_postcode_or_part():
    assert source.street("Pardubice, S. K. Neumanna 2869, Pardubice, 53002, Zelené Předměstí") == "S. K. Neumanna"
    assert source.street("Pardubice, náměstí Dukelských hrdinů 2157/3a, Pardubice, 53002, X") == "náměstí Dukelských hrdinů"
    assert source.street("Pardubice, 17. listopadu 120, Pardubice, 53002, Zelené Předměstí") == "17. listopadu"
    assert source.street("Pardubice,  12, Pardubice, 53002, Dražkovice") is None       # no street, only a number
    assert source.street("volejte mi na 777 123 456") is None                           # not an address at all
    assert source.street(None) is None


def test_parse_refuses_a_moved_layout():
    with pytest.raises(ValueError, match="fields"):
        source.parse(answer([row()[:21]]))
    shifted = row()
    shifted[source.DATE], shifted[source.MOMC] = MO5, "01.11.2026 12:57"
    with pytest.raises(ValueError, match="columns"):
        source.parse(answer([shifted]))
    assert source.parse({"d": "[]"}) == []


def test_reports_keep_the_obvod_and_drop_bad_statuses():
    rows = [row(1), row(2, momc=555126), row(3, status=5), row(4, status=7), row(5, status=99), row(6, status=3)]
    keep, drop = source.reports(rows, MO5)
    assert [r["id"] for r in keep] == [1, 6] and drop == [3, 4, 5]


def test_request_body_is_json_in_json():
    body = source.request(dt.date(2026, 1, 1), dt.date(2026, 11, 12))
    q = json.loads(body["json"])["db"]
    assert (q["app"], q["city"], q["dateFrom"], q["dateTo"]) == ("dejtip", "pardubice", "2026-01-01", "2026-11-12")


def test_window_two_years_first_then_recent():
    today = dt.date(2026, 11, 12)
    assert jobs.window(today, False) == (dt.date(2024, 11, 12), dt.date(2026, 11, 13))
    assert jobs.window(today, True) == (dt.date(2026, 7, 15), dt.date(2026, 11, 13))
    assert jobs.window(dt.date(2028, 2, 29), False)[0] == dt.date(2026, 2, 28)


def test_meters_and_box():
    assert abs(queries.meters(50.0, 15.0, 50.001, 15.0) - 111.2) < 0.5
    la0, la1, ln0, ln1 = queries.box(50.03, 15.76, 500)
    assert la0 < 50.03 < la1 and ln0 < 15.76 < ln1
    assert queries.meters(50.03, 15.76, la1, 15.76) == pytest.approx(500, rel=0.01)
    assert queries.meters(50.03, 15.76, 50.03, ln1) == pytest.approx(500, rel=0.01)


def _stored(**over) -> dict:
    return {**source.sanitize(row()), "obvod": "mo5", "status_changed_at": None, **over}


def test_api_shape(monkeypatch):
    seen = {}

    def search(f, limit):
        seen.update(f=f, limit=limit)
        return [{**_stored(), "distance": 42}]

    monkeypatch.setattr(queries, "search", search)
    monkeypatch.setattr(queries, "version", lambda: VERSION)
    r = TestClient(app).get("/api/v1/podnety", params={"near": "50.03,15.76", "r": 9999, "stav": "1,3",
                                                       "od": "2026-01-01"}, headers={"host": "otevrenapetka.cz"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/geo+json")
    fc = r.json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 1
    feat = fc["features"][0]
    assert feat["geometry"] == {"type": "Point", "coordinates": [15.7602, 50.0301]}
    assert feat["properties"] == {"id": 10000000001, "category_id": 19, "category": "Chodník", "status_id": 1,
                                  "status": "Evidováno", "reported_at": "2026-11-01T12:57", "street": "Na Záboří",
                                  "obvod": "mo5", "obvody": ["mo5"], "status_changed_at": None,
                                  "changed_at": "2026-11-12T10:00",
                                  "description": "Nemám rád souseda, volejte [telefon] nebo [e-mail]",
                                  "photo": "https://www.dejtip.eu/_fotoobce/0000-abc.jpeg",
                                  "detail": "https://amg.dejtip.eu/pardubice/?id=10000000001", "distance": 42}
    f = seen["f"]
    assert (f.obvod, f.statuses, f.near, f.radius, f.date_from) == (obvody.WHOLE_TOWN, (1, 3), (50.03, 15.76),
                                                                    5000, dt.date(2026, 1, 1))
    assert f.max_age is None                                          # the whole town, any age, by default
    for bad in ({"near": "x"}, {"od": "1. 1. 2026"}, {"kategorie": "chodník"}, {"obvod": "mo9"},
                {"stari": "0"}, {"stari": "tri"}):
        assert TestClient(app).get("/api/v1/podnety", params=bad).status_code == 422


VERSION = dt.datetime(2026, 11, 15, 8, 0, tzinfo=dt.timezone.utc)
NOW = dt.datetime(2026, 11, 15, 12, 0)


@pytest.fixture
def api(monkeypatch):
    """The API over one stored report; `state` changes the data's version, the time and what
    the last search was asked."""
    state = {"version": VERSION, "now": NOW}

    def search(f, limit):
        state.update(f=f, limit=limit)
        return [_stored()]

    monkeypatch.setattr(queries, "search", search)
    monkeypatch.setattr(queries, "version", lambda: state["version"])
    monkeypatch.setattr(web, "_now", lambda: state["now"])
    return state


def ask(params=None, tag=None):
    return TestClient(app).get("/api/v1/podnety", params=params or {},
                               headers={"host": "otevrenapetka.cz", **({"if-none-match": tag} if tag else {})})


def test_api_obvod_filter_and_age(api):
    ask({"obvod": "MO1, mo5"})
    assert api["f"].obvod == obvody.ObvodFilter(("mo1", "mo5"))
    ask({"stari": "90", "stav": "1,2,8,9"})
    f = api["f"]
    assert (f.max_age, f.today, f.statuses, f.obvod) == (90, NOW.date(), (1, 2, 8, 9), obvody.WHOLE_TOWN)


def test_api_etag_and_304(api):
    r = ask()
    tag = r.headers["etag"]
    assert r.status_code == 200 and tag.startswith('W/"') and r.headers["cache-control"] == "public, max-age=600"
    r = ask(tag=tag)
    assert r.status_code == 304 and r.headers["etag"] == tag and not r.content
    assert ask(tag=tag.removeprefix("W/")).status_code == 304
    assert ask({"obvod": "mo5"}, tag).status_code == 200
    assert ask({"obvod": "mo5"}).headers["etag"] == ask({"obvod": " MO5"}).headers["etag"]
    assert ask({"stav": "3"}, tag).status_code == 200
    assert ask({"near": "50.03,15.76"}, tag).status_code == 200
    aged = ask({"stari": "90"}).headers["etag"]
    api["now"] = NOW + dt.timedelta(hours=1)                         # the same day: the same answer
    assert ask(tag=tag).status_code == 304 and ask({"stari": "90"}, aged).status_code == 304
    api["now"] = NOW + dt.timedelta(days=1)                          # stari counts from today
    assert ask(tag=tag).status_code == 304 and ask({"stari": "90"}, aged).status_code == 200
    api["version"] = VERSION + dt.timedelta(hours=4)                 # the job ran again
    assert ask(tag=tag).status_code == 200


def test_filters_sql():
    where, params = queries.Filters().sql()
    assert where == "TRUE" and params == []                          # the whole town
    where, params = queries.Filters(obvody.ObvodFilter(("mo1", "mo5")), statuses=(3,)).sql()
    assert where == "obvod = ANY(%s) AND status = ANY(%s::int[])" and params == [["mo1", "mo5"], [3]]
    where, params = queries.Filters("mo5").sql()                    # a page's own obvod
    assert where == "obvod = %s" and params == ["mo5"]
    where, params = queries.Filters(max_age=90, today=dt.date(2026, 11, 15)).sql()
    assert "GREATEST(reported_at, last_note_at" in where and params == [dt.datetime(2026, 8, 17)]


def test_changed_at_is_the_last_move_in_local_time():
    r = _stored(last_note_at=None)
    assert queries.changed_at(r) == dt.datetime(2026, 11, 1, 12, 57)                   # reported
    r = _stored(last_note_at=dt.datetime(2026, 11, 12, 10),
                status_changed_at=dt.datetime(2026, 11, 13, 5, 0, tzinfo=dt.timezone.utc))
    assert queries.changed_at(r) == dt.datetime(2026, 11, 13, 6, 0)                     # seen, in Prague


def test_job_takes_every_obvod_of_the_town_with_one_download_per_window(monkeypatch):
    rows = [row(1), row(2, momc=555126), row(3, momc=575020), row(4, momc=999999), row(5, momc=555126, status=7)]
    fetched, stored, marked = [], {}, {}

    def fetch(start, end, client):
        fetched.append((start, end))
        return rows

    def run(job, name, units, **kw):
        return {u.key[0]: u.run("conn", "client") for u in units("conn", "client")}

    monkeypatch.setattr(jobs.runner, "run", run)
    monkeypatch.setattr(jobs.source, "fetch", fetch)
    monkeypatch.setattr(jobs, "synced", lambda conn, obvod: obvod == "mo5")
    monkeypatch.setattr(jobs, "store", lambda conn, obvod, keep, drop: stored.update(
        {obvod: ([r["id"] for r in keep], drop)}) or {})
    monkeypatch.setattr(jobs, "mark", lambda conn, obvod, start: marked.update({obvod: start}))
    report = jobs.update(today=dt.date(2026, 11, 15))
    assert list(report) == [o.id for o in obvody.TOWN]
    assert fetched == [(dt.date(2024, 11, 15), dt.date(2026, 11, 16)),      # mo1 first, two years
                       (dt.date(2026, 7, 18), dt.date(2026, 11, 16))]       # mo5, known: 120 days
    assert stored["mo5"] == ([1], []) and stored["mo2"] == ([2], [5]) and stored["mo8"] == ([3], [])
    assert all(stored[o] == ([], []) for o in ("mo1", "mo3", "mo4", "mo6", "mo7"))      # 4 is in no obvod
    assert marked["mo5"] == dt.date(2026, 7, 18) and marked["mo8"] == dt.date(2024, 11, 15)
    jobs.update(["mo3"], since=dt.date(2020, 1, 1), today=dt.date(2026, 11, 15))
    assert fetched[-1] == (dt.date(2020, 1, 1), dt.date(2026, 11, 16)) and marked["mo3"] == dt.date(2020, 1, 1)


# --- with a database ------------------------------------------------------------------------

FAR = (10.0, 10.0)      # where no real report is, so the tests see only their own rows
IDS = [-901, -902, -903]


@pytest.fixture
def conn():
    try:
        db.migrate()
    except Exception:
        pytest.skip("no local database")
    with db.connect() as c:
        c.execute("DELETE FROM citizen_reports WHERE id = ANY(%s::bigint[])", (IDS,))
        c.commit()
        yield c
        c.rollback()
        c.execute("DELETE FROM citizen_reports WHERE id = ANY(%s::bigint[])", (IDS,))
        c.commit()


def test_store_tracks_status_changes_and_drops(conn):
    lat, lng = FAR
    near = row(-901, lat=lat, lng=lng + 0.002)           # ~220 m east
    far = row(-902, lat=lat + 0.01, lng=lng, public=0)   # ~1.1 km north, photo not public
    gone = row(-903, lat=lat, lng=lng)
    keep, drop = source.reports([near, far, gone], MO5)
    assert jobs.store(conn, "mo5", keep, drop) == {"reports": 3, "new": 3, "changed": 0, "removed": 0}
    conn.commit()

    keep, drop = source.reports([row(-901, status=3, lat=lat, lng=lng + 0.002), far,
                                 row(-903, status=99, lat=lat, lng=lng)], MO5)
    assert jobs.store(conn, "mo5", keep, drop) == {"reports": 2, "new": 0, "changed": 1, "removed": 1}
    conn.commit()
    hist = conn.execute("SELECT status, initial FROM citizen_report_statuses WHERE id = -901 ORDER BY seen_at").fetchall()
    assert [(h["status"], h["initial"]) for h in hist] == [(1, True), (3, False)]
    r = conn.execute("SELECT * FROM citizen_reports WHERE id = -901").fetchone()
    assert r["status"] == 3 and r["status_changed_at"] is not None
    cols = {c.name for c in conn.execute("SELECT * FROM citizen_reports LIMIT 0").description}
    assert cols == {"id", "obvod", "momc", "category_id", "category", "status", "reported_at", "lat", "lng",
                    "street", "first_seen", "last_seen", "status_changed_at", "first_note_at", "last_note_at",
                    "description", "photo_url"}
    assert r["description"] == "Nemám rád souseda, volejte [telefon] nebo [e-mail]"
    assert r["photo_url"] == "https://www.dejtip.eu/_fotoobce/0000-abc.jpeg"
    assert conn.execute("SELECT photo_url FROM citizen_reports WHERE id = -902").fetchone()["photo_url"] is None

    hits = queries.near("mo5", lat, lng, radius=500)
    assert [h["id"] for h in hits] == [-901] and 200 < hits[0]["distance"] < 240
    assert [h["id"] for h in queries.near("mo5", lat, lng, radius=2000)] == [-901, -902]
    assert queries.near("mo4", lat, lng, radius=2000) == []
    around = dict(near=(lat, lng), radius=2000)
    assert [h["id"] for h in queries.search(queries.Filters(**around))] == [-901, -902]          # the town
    assert [h["id"] for h in queries.search(queries.Filters(obvody.ObvodFilter(("mo4", "mo5")), **around))] \
        == [-901, -902]
    assert queries.search(queries.Filters(obvody.ObvodFilter(("mo1",)), **around)) == []
    # stari: -901 changed status just now, -902 last moved on 12. 11. 2026 (its office note)
    young = queries.search(queries.Filters(**around, max_age=1, today=dt.date.today()))
    assert [h["id"] for h in young] == [-901]


def test_synced_and_mark(conn):
    assert not jobs.synced(conn, "test")
    jobs.mark(conn, "test", dt.date(2026, 7, 1))
    jobs.mark(conn, "test", dt.date(2024, 11, 15))
    jobs.mark(conn, "test", dt.date(2026, 7, 18))
    assert jobs.synced(conn, "test")
    assert conn.execute("SELECT since FROM citizen_report_obvody WHERE obvod = 'test'").fetchone()["since"] \
        == dt.date(2024, 11, 15)                                      # the earliest download stays
