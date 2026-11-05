"""Share images: the title of the page itself, wrapped to fit the brand image."""

import io

from fastapi.testclient import TestClient
from PIL import Image

from petka.web import og
from petka.web.app import app


def test_render_fits_any_title():
    for title in ("Data a API", "Usnesení 262/2025 R: " + "velmi dlouhý název usnesení " * 12):
        im = Image.open(io.BytesIO(og.render(title, "Usnesení a hlasování")))
        assert im.size == (1200, 630)


def test_wrap_keeps_one_letter_words_with_the_next():
    lines = og._wrap("smlouvy o dílo s vítězným uchazečem v Pardubicích", og._font(84, 800), 520)
    assert len(lines) > 1 and not any(line.endswith((" o", " s", " v")) for line in lines)


def test_route_draws_only_existing_pages():
    c = TestClient(app)
    page = c.get("/pristupnost")
    assert 'content="https://opendata.mov.varecha.work/og/pristupnost.png"' in page.text
    r = c.get("/og/pristupnost.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert c.get("/og/neexistuje.png").status_code == 404
    assert c.get("/og/og/pristupnost.png.png").status_code == 404
