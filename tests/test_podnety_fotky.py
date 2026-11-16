"""Photos of the reports: shrunk to WebP without EXIF/GPS, refused when an image declares too many
pixels, downloaded only from www.dejtip.eu, served by the portal with a versioned URL, an hour's
caching and only while the report still has that public photo, downloaded once and removed when the report loses its public photo or is
deleted. Images are drawn here; Dej Tip is a fake transport. Tests touching the database skip
without one."""

import datetime as dt
import io
import struct
import zlib

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from petka import db
from petka.podnety import jobs, photos, queries, source, web
from petka.web.app import app

GPS = 0x8825
ORIENTATION = 0x0112


def jpeg(size=(1600, 1200), orientation=None, gps=True) -> bytes:
    """A JPEG photo as a phone takes it: EXIF with the camera, GPS and its orientation."""
    im = Image.new("RGB", size, (200, 30, 30))
    im.paste((30, 30, 200), (0, 0, size[0] // 2, size[1]))          # left half blue: shows a turn
    exif = Image.Exif()
    exif[0x010F] = "Phone Maker"                                    # Make
    exif[0x0132] = "2026:11:12 10:00:00"                            # DateTime
    if orientation:
        exif[ORIENTATION] = orientation
    if gps:
        exif[GPS] = {1: "N", 2: (50.0, 2.0, 0.0), 3: "E", 4: (15.0, 46.0, 0.0)}
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif, comment=b"secret comment")
    return out.getvalue()


# --- the image --------------------------------------------------------------------------------

def test_shrink_makes_a_small_webp_without_metadata():
    original = jpeg()
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(GPS)        # the fixture has GPS
    out = photos.shrink(original)
    im = Image.open(io.BytesIO(out))
    assert im.format == "WEBP" and im.size == (800, 600)
    assert not im.getexif() and "exif" not in im.info and "xmp" not in im.info
    assert b"Phone Maker" not in out and b"secret comment" not in out and b"Exif" not in out
    assert len(out) < len(original)


def test_shrink_turns_by_exif_and_never_enlarges():
    im = Image.open(io.BytesIO(photos.shrink(jpeg(orientation=6))))      # taken holding the phone upright
    assert im.size == (600, 800)
    assert im.convert("RGB").getpixel((300, 10))[2] > 150                  # the blue half is now on top
    assert Image.open(io.BytesIO(photos.shrink(jpeg((400, 300), gps=False)))).size == (400, 300)


def test_shrink_refuses_what_isnt_an_image():
    with pytest.raises(OSError):
        photos.shrink(b"<html>not found</html>")


def png_header(width: int, height: int) -> bytes:
    """A tiny PNG that declares a huge size: signature, IHDR and IEND, no pixels."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IEND", b""))


@pytest.mark.parametrize("w, h", [(10_000, 5_000),        # 50 MP: over MAX_PIXELS, under Pillow's limit
                                  (12_000, 9_000),        # 108 MP: Pillow only warns
                                  (60_000, 60_000)])      # 3.6 GP: Pillow's own error
def test_shrink_refuses_an_image_declaring_too_many_pixels(w, h):
    data = png_header(w, h)
    assert len(data) < 100
    with pytest.raises((ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning)):
        photos.shrink(data)
    image, error, later = photos._one(_fixed(data), "https://www.dejtip.eu/_fotoobce/bomb.png")
    assert image is None and error and not later


def _fixed(body: bytes, ctype: str = "image/png") -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": ctype}, content=body)))


@pytest.mark.parametrize("url", [
    "http://www.dejtip.eu/_fotoobce/a.jpeg",                 # not https
    "https://dejtip.eu/_fotoobce/a.jpeg",                     # another host
    "https://amg.dejtip.eu/_fotoobce/a.jpeg",
    "https://www.dejtip.eu.evil.example/a.jpeg",
    "https://127.0.0.1/a.jpeg", "https://localhost/a.jpeg", "https://[::1]/a.jpeg",
    "https://db:5432/", "https://www.dejtip.eu:8443/a.jpeg",  # another port
    "https://user@www.dejtip.eu/a.jpeg",                      # a user part
    "https://evil.example\\@www.dejtip.eu/a.jpeg",
    "file:///etc/passwd", "ftp://www.dejtip.eu/a.jpeg", "", "not a url"])
def test_only_dejtip_is_ever_asked(url):
    asked = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: asked.append(r) or httpx.Response(200)))
    assert photos.allowed(url) is None
    image, error, later = photos._one(client, url)
    assert image is None and "not a Dej Tip photo URL" in error and not later    # permanent, waits RETRY
    assert asked == []                                                          # no request made
    assert photos.allowed("https://www.dejtip.eu/_fotoobce/a.jpeg") is not None


def test_redirects_are_not_followed():
    asked = []

    def handle(request):
        asked.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
    client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True)
    image, error, later = photos._one(client, "https://www.dejtip.eu/_fotoobce/a.jpeg")
    assert image is None and "302" in error and not later
    assert asked == ["https://www.dejtip.eu/_fotoobce/a.jpeg"]


def test_version_and_url():
    assert photos.version(b"abc") == "ba7816bf8f01cfea"
    assert photos.href(42, "ba7816bf8f01cfea") == "/api/v1/podnety/42/foto/ba7816bf8f01cfea.webp"
    assert photos.href(42, "v", "https://otevrenapetka.cz") == "https://otevrenapetka.cz/api/v1/podnety/42/foto/v.webp"
    assert photos.href(42, None) is None                                  # not public or not downloaded yet


# --- the endpoint ------------------------------------------------------------------------------

@pytest.fixture
def stored(monkeypatch):
    image = photos.shrink(jpeg())
    ver = photos.version(image)
    monkeypatch.setattr(photos, "get", lambda rid: {"version": ver, "image": image} if rid == 7 else None)
    return ver, image


def test_endpoint_serves_the_webp_cached_for_good(stored):
    ver, image = stored
    c = TestClient(app)
    r = c.get(f"/api/v1/podnety/7/foto/{ver}.webp", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and r.content == image
    assert r.headers["content-type"] == "image/webp"
    assert r.headers["cache-control"] == "public, max-age=3600"
    assert r.headers["etag"] == f'"{ver}"' and "content-encoding" not in r.headers
    r = c.get(f"/api/v1/podnety/7/foto/{ver}.webp", headers={"if-none-match": f'"{ver}"'})
    assert r.status_code == 304 and not r.content and r.headers["etag"] == f'"{ver}"'
    assert c.get("/api/v1/podnety/7/foto/0000000000000000.webp").status_code == 404     # an old version
    assert c.get(f"/api/v1/podnety/8/foto/{ver}.webp").status_code == 404              # no photo
    assert c.get(f"/api/v1/podnety/x/foto/{ver}.webp").status_code == 422


# --- the download ------------------------------------------------------------------------------

def dejtip(answers: dict):
    """A Dej Tip that answers each URL with (status, content-type, body) or raises."""
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        a = answers[str(request.url)]
        if isinstance(a, Exception):
            raise a
        status, ctype, body = a
        return httpx.Response(status, headers={"content-type": ctype}, content=body)
    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def test_one_photo_ok_gone_broken_and_later():
    client, _ = dejtip({"https://www.dejtip.eu/_fotoobce/ok.jpeg": (200, "image/jpeg", jpeg()),
                        "https://www.dejtip.eu/_fotoobce/gone.jpeg": (404, "text/html", b"no"),
                        "https://www.dejtip.eu/_fotoobce/page.jpeg": (200, "text/html", b"<html>"),
                        "https://www.dejtip.eu/_fotoobce/broken.jpeg": (200, "image/jpeg", b"\xff\xd8 broken"),
                        "https://www.dejtip.eu/_fotoobce/down.jpeg": (503, "text/html", b""),
                        "https://www.dejtip.eu/_fotoobce/slow.jpeg": httpx.ReadTimeout("slow")})
    image, error, later = photos._one(client, "https://www.dejtip.eu/_fotoobce/ok.jpeg")
    assert Image.open(io.BytesIO(image)).format == "WEBP" and not error and not later
    for url in ("gone", "page", "broken"):
        image, error, later = photos._one(client, f"https://www.dejtip.eu/_fotoobce/{url}.jpeg")
        assert image is None and error and not later, url
    for url in ("down", "slow"):
        assert photos._one(client, f"https://www.dejtip.eu/_fotoobce/{url}.jpeg")[2], url


def test_units_stop_when_dejtip_doesnt_answer(monkeypatch):
    wanted = [(i, f"https://www.dejtip.eu/_fotoobce/{i}.jpeg") for i in range(60)]
    monkeypatch.setattr(photos, "prune", lambda conn: 0)
    monkeypatch.setattr(photos, "todo", lambda conn, limit: wanted[:limit])
    monkeypatch.setattr(photos, "_one", lambda client, url: (None, "ConnectError", True))
    ran = [u.label for u in photos.units("conn", "client", 60) if u.run("conn", "client") is not None]
    assert ran == ["fotky: smazané", "fotky 1–25 z 60"]                     # the second batch never starts


# --- with a database ---------------------------------------------------------------------------

IDS = [-911, -912, -913]
FAR = (10.0, 10.0)


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


def report(rid: int, photo: str | None, day: int = 1) -> dict:
    return {"id": rid, "category_id": 19, "category": "Chodník", "status": 1,
            "reported_at": dt.datetime(2026, 11, day, 12), "lat": FAR[0], "lng": FAR[1],
            "street": "Testovací", "momc": 557072, "first_note_at": None, "last_note_at": None,
            "description": None, "photo_url": photo}


def test_photos_follow_the_reports(conn, monkeypatch):
    urls = {i: f"https://www.dejtip.eu/_fotoobce/t{-i}.jpeg" for i in IDS}
    jobs.store(conn, "mo5", [report(-911, urls[-911], 3), report(-912, urls[-912], 2), report(-913, None, 1)], [])
    conn.commit()
    todo = [t for t in photos.todo(conn, 10_000) if t[0] in IDS]
    assert todo == [(-911, urls[-911]), (-912, urls[-912])]               # newest first, only public ones

    client, seen = dejtip({urls[-911]: (200, "image/jpeg", jpeg()), urls[-912]: (404, "text/html", b"")})
    assert photos.fetch(conn, client, todo) == {"stored": 1, "failed": 1, "later": 0, "kb": pytest.approx(5, abs=5)}
    conn.commit()
    assert [t for t in photos.todo(conn, 10_000) if t[0] in IDS] == []      # each tried once; 404 waits RETRY

    # the API and the pages point at the portal's copy, the failed one has no photo
    monkeypatch.setattr(queries.db, "pool", lambda: _Pool(conn))
    rows = {r["id"]: r for r in queries.search(queries.Filters(near=FAR, radius=50))}
    ver = rows[-911]["photo_version"]
    assert queries.feature(rows[-911])["properties"]["photo"] == \
        f"https://otevrenapetka.cz/api/v1/podnety/-911/foto/{ver}.webp"
    assert queries.feature(rows[-912])["properties"]["photo"] is None
    street = {r["id"]: r for r in queries.street_rows("mo5", "testovaci")}
    assert street[-911]["photo_version"] == ver and street[-912]["photo_version"] is None
    assert photos.get(-911)["version"] == ver
    assert photos.get(-912) is None                                       # failed: nothing to serve

    # the reporter replaces, then hides the photo: not served any more even before the next run
    jobs.store(conn, "mo5", [report(-911, urls[-911] + "?new", 3)], [])
    assert photos.get(-911) is None
    rows = {r["id"]: r for r in queries.search(queries.Filters(near=FAR, radius=50))}
    assert rows[-911]["photo_version"] is None
    jobs.store(conn, "mo5", [report(-911, None, 3)], [-912])
    assert photos.get(-911) is None
    # the next run removes it; a deleted report takes its photo along
    assert photos.prune(conn) == 1
    conn.commit()
    assert conn.execute("SELECT count(*) AS n FROM citizen_report_photos WHERE id = ANY(%s::bigint[])",
                        (IDS,)).fetchone()["n"] == 0
    # a new photo of the same report is downloaded again
    jobs.store(conn, "mo5", [report(-911, urls[-911] + "?2", 3)], [])
    assert [t for t in photos.todo(conn, 10_000) if t[0] in IDS] == [(-911, urls[-911] + "?2")]


class _Pool:
    """db.pool() over the test's connection."""
    def __init__(self, conn):
        self.conn = conn

    def connection(self):
        conn = self.conn

        class _Ctx:
            def __enter__(self):
                return conn

            def __exit__(self, *a):
                return False
        return _Ctx()
