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
from petka.podnety import jobs, queries, source
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
    r = TestClient(app).get("/api/v1/podnety", params={"near": "50.03,15.76", "r": 9999, "stav": "1,3",
                                                       "od": "2026-01-01"}, headers={"host": "otevrenapetka.cz"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/geo+json")
    fc = r.json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 1
    feat = fc["features"][0]
    assert feat["geometry"] == {"type": "Point", "coordinates": [15.7602, 50.0301]}
    assert feat["properties"] == {"id": 10000000001, "category_id": 19, "category": "Chodník", "status_id": 1,
                                  "status": "Evidováno", "reported_at": "2026-11-01T12:57", "street": "Na Záboří",
                                  "obvod": "mo5", "status_changed_at": None,
                                  "description": "Nemám rád souseda, volejte [telefon] nebo [e-mail]",
                                  "photo": "https://www.dejtip.eu/_fotoobce/0000-abc.jpeg",
                                  "detail": "https://amg.dejtip.eu/pardubice/?id=10000000001", "distance": 42}
    f = seen["f"]
    assert (f.obvod, f.statuses, f.near, f.radius, f.date_from) == ("mo5", (1, 3), (50.03, 15.76), 5000,
                                                                    dt.date(2026, 1, 1))
    for bad in ({"near": "x"}, {"od": "1. 1. 2026"}, {"kategorie": "chodník"}):
        assert TestClient(app).get("/api/v1/podnety", params=bad).status_code == 422


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
