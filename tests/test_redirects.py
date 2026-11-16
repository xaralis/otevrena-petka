"""The URLs from before the header areas (13. 11. 2026, petka.nav.MOVED): pages redirect for
good to the same subpath and query under the new prefix, feeds and calendars are served in place,
an area's own URL goes to its first page. No database needed."""

import pytest
from fastapi.testclient import TestClient

from petka import nav
from petka.web.app import app

from test_cisteni import fixture  # noqa: F401  (street-cleaning items without a database)

c = TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("old, new", [
    ("/uredni-deska", "/radnice/uredni-deska"),
    ("/uredni-deska/abc123", "/radnice/uredni-deska/abc123"),
    ("/uredni-deska/navrhy", "/radnice/uredni-deska/navrhy"),
    ("/uredni-deska/obrazky/abc/mapa.webp", "/radnice/uredni-deska/obrazky/abc/mapa.webp"),
    ("/uredni-deska/data/notices.csv", "/radnice/uredni-deska/data/notices.csv"),
    ("/usneseni", "/radnice/usneseni"),
    ("/usneseni/mapa", "/radnice/usneseni/mapa"),
    ("/usneseni/jednani/zmo-2026-05", "/radnice/usneseni/jednani/zmo-2026-05"),
    ("/usneseni/metodika", "/radnice/usneseni/metodika"),
    ("/usneseni/310-2026-r", "/radnice/usneseni/310-2026-r"),
    ("/usneseni/pdf/zmo-2026-05.pdf", "/radnice/usneseni/pdf/zmo-2026-05.pdf"),
    ("/usneseni/data/datapackage.json", "/radnice/usneseni/data/datapackage.json"),
    ("/usneseni/clenove", "/radnice/zastupitele"),
    ("/usneseni/clenove/ucast", "/radnice/zastupitele/ucast"),
    ("/usneseni/clenove/jan-novak", "/radnice/zastupitele/jan-novak"),
    ("/rozpocet", "/finance/rozpocet"),
    ("/rozpocet/nahled/tajne/oblasti", "/finance/rozpocet/nahled/tajne/oblasti"),
    ("/smlouvy", "/finance/smlouvy"),
    ("/blokove-cisteni", "/verejny-prostor/blokove-cisteni"),
    ("/ulice/wolkerova", "/verejny-prostor/ulice/wolkerova"),
    ("/blokove-cisteni/ulice/wolkerova", "/verejny-prostor/blokove-cisteni/ulice/wolkerova"),
    ("/blokove-cisteni/kalendar", "/verejny-prostor/blokove-cisteni/kalendar"),
    ("/uzavirky", "/verejny-prostor/uzavirky"),
    ("/podnety", "/verejny-prostor/podnety"),
    ("/ankety", "/zapojte-se/ankety"),
])
def test_old_pages_redirect_for_good(old, new):
    r = c.get(old)
    assert (r.status_code, r.headers["location"]) == (301, new)
    assert nav.moved(old) == new


@pytest.mark.parametrize("old, new", [
    ("/usneseni?q=parkov%C3%A1n%C3%AD&rezim=fulltext", "/radnice/usneseni?q=parkov%C3%A1n%C3%AD&rezim=fulltext"),
    ("/podnety?obdobi=2025&detail=mesice", "/verejny-prostor/podnety?obdobi=2025&detail=mesice"),
    ("/blokove-cisteni/kalendar?ulice=wolkerova&ulice=lexova", "/verejny-prostor/blokove-cisteni/kalendar?ulice=wolkerova&ulice=lexova"),
])
def test_query_is_kept(old, new):
    r = c.get(old)
    assert (r.status_code, r.headers["location"]) == (301, new)


def test_query_typed_with_diacritics():
    r = c.get("/usneseni", params={"q": "parkování"})
    assert r.headers["location"] == "/radnice/usneseni?q=parkov%C3%A1n%C3%AD"


def test_head_redirects_too():
    r = c.head("/usneseni/clenove")
    assert (r.status_code, r.headers["location"]) == (301, "/radnice/zastupitele")


@pytest.mark.parametrize("path", ["/api/v1/usneseni/stats", "/data/usneseni", "/usneseni-x", "/ulice-x",
                                  "/radnice/usneseni", "/radnice/zastupitele", "/data", "/"])
def test_what_stays(path):
    assert nav.moved(path) is None


@pytest.mark.parametrize("area, first", [
    ("/radnice", "/radnice/uredni-deska"),
    ("/radnice/", "/radnice/uredni-deska"),
    ("/finance", "/finance/rozpocet"),
    ("/verejny-prostor", "/verejny-prostor/ulice"),
    ("/zapojte-se", "/zapojte-se/ankety"),
])
def test_area_goes_to_its_first_page(area, first):
    r = c.get(area)
    assert (r.status_code, r.headers["location"]) == (302, first)
    assert first == {g.path: g for g in nav.GROUPS}[area.rstrip("/")].href


@pytest.mark.parametrize("old", ["/smlouvy", "/ankety", "/rozpocet"])
def test_planned_pages_follow(old):
    r = c.get(old, follow_redirects=True)
    assert r.status_code == 200 and "ve výstavbě" in r.text and str(r.url).endswith(nav.moved(old))


# --- subscriptions: served at the old path, no redirect ------------------------------------------

def _events(body: str) -> list[str]:
    return [line for line in body.splitlines() if not line.startswith("DTSTAMP")]


@pytest.mark.parametrize("old", ["/blokove-cisteni/kalendar.ics?ulice=wolkerova,lexova",
                                 "/blokove-cisteni/ulice/wolkerova.ics"])
def test_calendars_at_the_old_path(fixture, old):  # noqa: F811
    r, new = c.get(old), c.get("/verejny-prostor" + old)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VEVENT" in r.text and _events(r.text) == _events(new.text)


def test_feeds_at_the_old_path(monkeypatch):
    from petka.uredni_deska import web as deska
    from petka.usneseni import web as usneseni
    monkeypatch.setattr(usneseni.search, "search", lambda *a, **kw: ([], 0))
    monkeypatch.setattr(deska.queries, "search", lambda *a, **kw: ([], 0))
    for old, new in [("/usneseni/feed.xml", "/radnice/usneseni/feed.xml"),
                     ("/uredni-deska/rss.xml", "/radnice/uredni-deska/rss.xml"),
                     ("/uredni-deska/rss.xml?zneni=uredni", "/radnice/uredni-deska/rss.xml?zneni=uredni")]:
        r = c.get(old)
        assert r.status_code == 200 and r.text == c.get(new).text, old
        assert f"{new.split('?')[0]}" in r.text      # the self link is the new URL


def test_share_image_of_an_old_url():
    assert c.get("/og/smlouvy.png").status_code == 200
    assert c.get("/og/finance/smlouvy.png").status_code == 200


def test_drafts_stay_closed_at_the_new_path():
    assert c.get("/radnice/uredni-deska/navrhy").status_code == 404     # no X-Auth-User from the ingress
