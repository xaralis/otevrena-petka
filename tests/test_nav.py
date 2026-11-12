"""The header navigation (petka.nav): areas, their pages, what is current and what is only
planned. No database needed."""

import pytest
from fastapi.testclient import TestClient

from petka import nav
from petka.web.app import app


@pytest.mark.parametrize("path, group, item", [
    ("/usneseni", "Radnice", "Usnesení"),
    ("/usneseni/310-2026-r", "Radnice", "Usnesení"),
    ("/usneseni/jednani", "Radnice", "Usnesení"),
    ("/usneseni/clenove", "Radnice", "Zastupitelé"),
    ("/usneseni/clenove/ucast", "Radnice", "Zastupitelé"),
    ("/uredni-deska", "Radnice", "Úřední deska"),
    ("/rozpocet", "Finance", "Rozpočet"),
    ("/blokove-cisteni/ulice/wolkerova", "Veřejný prostor", "Blokové čištění ulic"),
    ("/podnety", "Veřejný prostor", "Závady"),
    ("/ankety", "Zapojte se", "Ankety"),
])
def test_current(path, group, item):
    g, i = nav.current(path)
    assert (g.label, i.label) == (group, item)


@pytest.mark.parametrize("path", ["/", "/data", "/ulice/wolkerova", "/usneseni-x", "/prehled"])
def test_outside_the_areas(path):
    assert nav.current(path) == (None, None)


def test_planned_pages_and_where_an_area_links():
    soon = {i.label for g in nav.GROUPS for i in g.items if i.soon}
    assert soon == {"Rozpočet", "Smlouvy", "Uzavírky", "Ankety"}
    by = {g.label: g for g in nav.GROUPS}
    assert by["Radnice"].href == "/usneseni"
    assert by["Finance"].href == "/rozpocet"            # nothing live yet: the first page
    assert by["Veřejný prostor"].href == "/blokove-cisteni"
    assert nav.SOON == {"rozpocet", "smlouvy", "uzavirky", "ankety"}


def test_header_rows_and_phone_menu():
    c = TestClient(app)
    html = c.get("/blokove-cisteni/kalendar").text
    assert '<a href="/blokove-cisteni" aria-current="true">Veřejný prostor</a>' in html
    assert 'aria-label="Sekce v oblasti Veřejný prostor"' in html
    assert '<a href="/uzavirky" class="soon"><span>Uzavírky</span><span class="sr"> (připravujeme)</span></a>' in html
    assert 'id="menu"' in html and 'href="#menu" role="button" aria-expanded="false"' in html
    assert "<b>Ankety<small>připravujeme</small></b>" in html


@pytest.mark.parametrize("slug", ["uzavirky", "ankety"])
def test_planned_items_have_a_page(slug):
    r = TestClient(app).get(f"/{slug}")
    assert r.status_code == 200 and "ve výstavbě" in r.text
