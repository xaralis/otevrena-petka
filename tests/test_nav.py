"""The header navigation (petka.nav): areas, their pages, what is current and what is only
planned. No database needed."""

import pytest
from fastapi.testclient import TestClient

from petka import nav
from petka.web.app import app


@pytest.mark.parametrize("path, group, item", [
    ("/radnice/usneseni", "Radnice", "Usnesení"),
    ("/radnice/usneseni/310-2026-r", "Radnice", "Usnesení"),
    ("/radnice/usneseni/jednani", "Radnice", "Usnesení"),
    ("/radnice/zastupitele", "Radnice", "Zastupitelé"),
    ("/radnice/zastupitele/ucast", "Radnice", "Zastupitelé"),
    ("/radnice/uredni-deska", "Radnice", "Úřední deska"),
    ("/finance/rozpocet", "Finance", "Rozpočet"),
    ("/verejny-prostor/blokove-cisteni/ulice/wolkerova", "Veřejný prostor", "Blokové čištění ulic"),
    ("/verejny-prostor/podnety", "Veřejný prostor", "Podněty"),
    ("/verejny-prostor/ulice/wolkerova", "Veřejný prostor", "Ulice"),
    ("/zapojte-se/ankety", "Zapojte se", "Ankety"),
])
def test_current(path, group, item):
    g, i = nav.current(path)
    assert (g.label, i.label) == (group, item)


@pytest.mark.parametrize("path", ["/", "/data", "/usneseni-x", "/prehled"])
def test_outside_the_areas(path):
    assert nav.current(path) == (None, None)


def test_planned_pages_and_where_an_area_links():
    soon = {i.label for g in nav.GROUPS for i in g.items if i.soon}
    assert soon == {"Rozpočet", "Smlouvy", "Uzavírky", "Ankety"}
    by = {g.label: g for g in nav.GROUPS}
    assert by["Radnice"].href == "/radnice/uredni-deska"
    assert by["Finance"].href == "/finance/rozpocet"            # nothing live yet: the first page
    assert by["Veřejný prostor"].href == "/verejny-prostor/ulice"
    assert nav.SOON == {"/finance/rozpocet", "/finance/smlouvy", "/verejny-prostor/uzavirky", "/zapojte-se/ankety"}


def test_header_rows_and_phone_menu(monkeypatch):
    from petka.cisteni import web as cweb
    monkeypatch.setattr(cweb.q, "items", lambda obvod, since, slugs=None: [])    # no database needed
    monkeypatch.setattr(cweb.q, "checked", lambda: None)
    c = TestClient(app)
    html = c.get("/verejny-prostor/blokove-cisteni/kalendar").text
    assert '<a href="/verejny-prostor/ulice" aria-current="true">Veřejný prostor</a>' in html
    assert 'aria-label="Sekce v oblasti Veřejný prostor"' in html
    assert '<a href="/verejny-prostor/uzavirky" class="soon"><span>Uzavírky</span><span class="sr"> (připravujeme)</span></a>' in html
    assert 'id="menu"' in html and 'href="#menu" role="button" aria-expanded="false"' in html
    assert "<b>Ankety<small>připravujeme</small></b>" in html


@pytest.mark.parametrize("path", ["/verejny-prostor/uzavirky", "/zapojte-se/ankety", "/finance/smlouvy",
                                  "/finance/rozpocet"])
def test_planned_items_have_a_page(path):
    r = TestClient(app).get(path)
    assert r.status_code == 200 and "ve výstavbě" in r.text


def test_planned_pages_last_in_each_area():
    for g in nav.GROUPS:
        soon = [i.soon for i in g.items]
        assert soon == sorted(soon), g.label
    vp = next(g for g in nav.GROUPS if g.label == "Veřejný prostor")
    assert [i.label for i in vp.items] == ["Ulice", "Blokové čištění ulic", "Podněty", "Uzavírky"]


# --- the one page template: band, tabs, „Odkud to víme“ ----------------------------------------

def test_section_tabs():
    assert nav.section_tabs("/radnice/usneseni/311-2026-r") == [
        ("Usnesení", "/radnice/usneseni", True), ("Mapa", "/radnice/usneseni/mapa", False),
        ("Jednání", "/radnice/usneseni/jednani", False), ("Metodika", "/radnice/usneseni/metodika", False)]
    assert [on for _, _, on in nav.section_tabs("/radnice/usneseni/jednani/rmo-2026-09-23-66")] == [False, False, True, False]
    assert [on for _, _, on in nav.section_tabs("/radnice/zastupitele/ucast")] == [False, True]
    assert [on for _, _, on in nav.section_tabs("/radnice/zastupitele/jiri-havrda")] == [True, False]
    assert nav.section_tabs("/verejny-prostor/ulice") == []


@pytest.mark.parametrize("path", ["/pristupnost", "/soukromi", "/finance/smlouvy", "/neni-tu"])
def test_one_band_no_crumbs(path):
    h = TestClient(app).get(path).text
    band = h.split('<section class="band', 1)[1].split("</section>", 1)[0]
    assert "<h1>" in band and 'class="band-lead"' in band
    assert "crumbs" not in h and "sub-band" not in h and "band-page" not in h and "band-section" not in h


def test_planned_page_lists_without_bullets():
    h = TestClient(app).get("/finance/smlouvy").text
    m = h.split("<main", 1)[1]
    assert 'class="tape"' in m and 'class="link-list"' in m and 'class="links"' not in m
    assert 'planned-side panel' in m and "Odkud to víme" in m
