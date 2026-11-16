"""The /verejny-prostor/podnety page: outcomes (the forwarded rule), periods, buckets, medians, the month series,
the grid map and the routes. Rows are made up; the page's queries are replaced, except in the
database test, which skips without one."""

import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient

from petka import db
from petka.podnety import queries, stats, web, words
from petka.web.app import app

NOW = dt.datetime(2026, 11, 12, 14, 0)
TODAY = NOW.date()
H = dt.timedelta(hours=1)
D = dt.timedelta(days=1)


def rep(id=1, status=1, category="Chodník", category_id=19, at=NOW - 10 * D, first=None, last=None,
        lat=50.03, lng=15.76, street="Wolkerova"):
    return {"id": id, "status": status, "category": category, "category_id": category_id, "reported_at": at,
            "first_note_at": first, "last_note_at": last, "lat": lat, "lng": lng, "street": street}


# --- outcomes -------------------------------------------------------------------------------

def test_forwarded_categories_are_named_and_never_wait():
    assert stats.FORWARDED == ("Městská policie", "Zastávky MHD")
    assert stats.outcome(rep(status=1, category="Městská policie")) == "predano"
    assert stats.outcome(rep(status=2, category="Zastávky MHD")) == "predano"
    assert stats.outcome(rep(status=3, category="Městská policie")) == "predano"


def test_each_dejtip_status_has_its_outcome():
    assert {s: stats.outcome(rep(status=s)) for s in range(1, 10)} == {
        1: "ceka", 2: "ceka", 3: "vyreseno", 4: "nelze", 5: "chybne", 6: "neprislusi", 7: "chybne",
        8: "predano", 9: "ceka"}
    for c in stats.FORWARDED:                                      # forwarded: předáno whatever the status
        assert {stats.outcome(rep(status=s, category=c)) for s in range(1, 10)} == {"predano"}
    assert stats.OUTCOMES == ("vyreseno", "ceka", "predano", "neprislusi", "nelze", "chybne")
    assert [k for k, *_ in stats.SEGMENTS] == list(stats.OUTCOMES)


def test_the_four_outcomes_add_up_like_the_sanity_check():
    # 12. 11. 2026, last 12 months: 446 = 294 vyřešeno + 94 čeká + 41 předáno + 14 nepřísluší + 3 nelze
    rows = ([rep(i, 3) for i in range(294)] + [rep(1000 + i, 1) for i in range(60)]
            + [rep(2000 + i, 2) for i in range(34)]
            + [rep(3000 + i, 1, "Městská policie", 25) for i in range(33)]
            + [rep(4000 + i, 1, "Zastávky MHD", 13) for i in range(3)]
            + [rep(5000 + i, 6) for i in range(14)] + [rep(6000 + i, 8) for i in range(5)]
            + [rep(7000 + i, 4) for i in range(3)])
    s = stats.summary(rows, stats.period("12m", TODAY), NOW)
    assert s["n"] == 446
    assert s["count"] == {"vyreseno": 294, "ceka": 94, "predano": 41, "neprislusi": 14, "nelze": 3, "chybne": 0}
    assert s["done_pct"] == 66 and s["handled"] == 410
    assert (s["in_progress"], s["received"]) == (34, 60)
    mp = next(c for c in s["categories"] if c["name"] == "Městská policie")
    assert mp["forwarded"] and mp["ceka"] == 0 and mp["median"] == "–" and mp["note"].startswith("předávají")
    assert [c["name"] for c in s["categories"]][-2:] == ["Městská policie", "Zastávky MHD"]


# --- periods --------------------------------------------------------------------------------

def test_period_12_months_and_years():
    p = stats.period("12m", TODAY)
    assert (p.start, p.end) == (dt.date(2025, 11, 12), dt.date(2026, 11, 13))
    assert p.months()[0] == (2025, 11) and p.months()[-1] == (2026, 11) and len(p.months()) == 13
    y = stats.period("2025", TODAY)
    assert (y.start, y.end, y.phrase) == (dt.date(2025, 1, 1), dt.date(2026, 1, 1), "v roce 2025")
    assert stats.period("2026", TODAY).end == dt.date(2026, 11, 13)
    assert stats.period("2099", TODAY).key == "12m" and stats.period("x", TODAY).key == "12m"
    assert stats.period("12m", dt.date(2028, 2, 29)).start == dt.date(2027, 2, 28)
    sw = stats.switch([2024, 2026, 2025, 2026], "2025")
    assert [s["key"] for s in sw] == ["12m", "2026", "2025", "2024"]
    assert [s["label_m"] for s in sw][0] == "12 měsíců" and sw[2]["on"]


# --- buckets and medians --------------------------------------------------------------------

def test_bucket_edges():
    edges, labels, none = stats.ANSWERED_IN
    b = stats.buckets([0, 3.99, 4, 23.99, 24, 71.99, 72, 500, None], edges, labels, none)
    assert [x["n"] for x in b] == [2, 2, 2, 2, 1] and b[-1]["muted"] and b[-1]["label"] == "zatím bez odpovědi"
    edges, labels, none = stats.WAITING_FOR
    b = stats.buckets([6.9, 7, 29.9, 30, 90.9, 91], edges, labels, none)
    assert [x["n"] for x in b] == [1, 2, 2, 1] and len(b) == 4
    assert b[0]["pct"] == pytest.approx(16.7)
    assert stats.buckets([], edges, labels)[0]["pct"] == 0


def test_durations_from_notes_and_never_negative():
    r = rep(at=NOW, first=NOW - H, last=NOW + 36 * H)
    assert stats.response_hours(r) == 0 and stats.resolution_days(r) == 1.5
    assert stats.response_hours(rep()) is None


def test_median_needs_five_notes():
    four = [rep(i, 3, at=NOW - 10 * D, last=NOW - 8 * D) for i in range(4)]
    assert stats.median_days(four) == "–"
    assert stats.median_days(four + [rep(9, 3)]) == "–"              # resolved without a note
    assert stats.median_days(four + [rep(9, 3, at=NOW - 10 * D, last=NOW - 7 * D)]) == "2 dny"
    fast = [rep(i, 3, at=NOW - D, last=NOW - D + 3 * H) for i in range(5)]
    assert stats.median_days(fast) == "do 1 dne"


def test_words():
    assert [words.days(x) for x in (0.5, 1, 1.4, 3, 9)] == ["do 1 dne", "1 den", "1 den", "3 dny", "9 dní"]
    assert [words.hours(x) for x in (0.2, 17.4, 47, 72)] == ["1 h", "17 h", "47 h", "3 dny"]
    assert words.podnetu(1) == "1 podnět" and words.podnetu(3) == "3 podněty" and words.podnetu(64) == "64 podnětů"
    assert words.waits(1) == "1 čeká" and words.waits(4) == "4 čekají" and words.waits(30) == "30 čeká"
    assert words.from_date(dt.date(2025, 11, 14)) == "ze 14. 11. 2025"
    assert words.from_date(dt.date(2025, 11, 21)) == "z 21. 11. 2025"
    assert words.join(["a"]) == "a" and words.join(["a", "b", "c"]) == "a, b a c" and words.join([]) == ""


# --- months ---------------------------------------------------------------------------------

def test_month_series_has_empty_months_and_flags_the_running_one():
    rows = [rep(1, 3, at=dt.datetime(2025, 11, 20)), rep(2, 1, at=dt.datetime(2026, 9, 1)),
            rep(3, 3, at=dt.datetime(2026, 9, 2)), rep(4, 1, at=dt.datetime(2026, 11, 1))]
    m = stats.months(rows, stats.period("12m", TODAY), TODAY)
    cols = m["cols"]
    assert len(cols) == 13 and [c["n"] for c in cols].count(0) == 10
    assert (cols[0]["n"], cols[0]["done"]) == (1, 1)
    assert cols[0]["tip"] == "listopad 2025 (od 12. 11.): 1 podnět, vyřešeno 1"
    assert cols[10]["tip"] == "září 2026: 2 podněty, vyřešeno 1"
    assert cols[-1]["now"] and not any(c["now"] for c in cols[:-1])
    assert cols[-1]["tip"].startswith("listopad 2026 (do 12. 11.)")
    assert [c["year_m"] for c in cols][:3] == [2025, None, 2026]
    assert m["busiest"][0] == "v září (2)"
    assert [t["v"] for t in m["ticks"]] == [0, 1, 2]
    past = stats.months(rows, stats.period("2025", TODAY), TODAY)
    assert len(past["cols"]) == 12 and not any(c["now"] for c in past["cols"])


# --- highlight and map ----------------------------------------------------------------------

def test_highlight_needs_ten_reports_and_names_the_category():
    rows = ([rep(i, 1, "Pískoviště, hřiště, sportoviště", 20, at=NOW - (i + 1) * D, street="Sokolovská")
             for i in range(8)] + [rep(100 + i, 3, "Pískoviště, hřiště, sportoviště", 20) for i in range(2)]
            + [rep(200 + i, 1, "Kanalizace", 15) for i in range(5)]
            + [rep(300 + i, 1, "Městská policie", 25) for i in range(20)])
    s = stats.summary(rows, stats.period("12m", TODAY), NOW)
    hl = s["highlight"]
    assert hl["name"] == "Pískoviště, hřiště, sportoviště" and hl["title"] == "Nejdéle čekají podněty k hřištím"
    assert (hl["n"], hl["vyreseno"], hl["ceka"], hl["street"]) == (10, 2, 8, "Sokolovská")
    assert hl["oldest"] == (NOW - 8 * D).date()
    assert stats.highlight(rows, [], stats.period("12m", TODAY)) is None
    assert words.phrase("Nové")[0] == "v kategorii „Nové“"


def test_grid_counts_cells_never_points():
    rows = [rep(1, 1, lat=50.03001, lng=15.76001), rep(2, 3, lat=50.03002, lng=15.76002),
            rep(3, 1, "Autovrak", 17, lat=50.04, lng=15.77)]
    g = stats.grid(rows)
    assert len(g["features"]) == 2
    big = g["features"][0]
    assert big["properties"] == {"n": 2, "waiting": 1, "cats": [("Chodník", 2)]}
    assert big["geometry"]["coordinates"] != [15.76001, 50.03001]
    assert "street" not in str(g) and "Wolkerova" not in str(g)
    assert stats.grid([])["features"] == []


def test_points_carry_the_card_and_forwarded_never_wait():
    rows = [rep(1, 1, at=NOW - 3 * D, first=NOW - 3 * D + 2 * H, street="Wolkerova"),
            rep(2, 3, at=NOW - D, street=None),
            rep(3, 1, "Městská policie", 25, at=NOW - 2 * D)]
    rows[0].update(description="Rozbitá dlažba", photo_url="https://www.dejtip.eu/_fotoobce/x.jpeg",
                   photo_version="0123abcd")
    rows[2].update(photo_url="https://www.dejtip.eu/_fotoobce/y.jpeg")          # public, not downloaded yet
    g = stats.points(rows, NOW)
    assert [f["id"] for f in g["features"]] == [2, 3, 1]                         # newest first
    p = {f["id"]: f["properties"] for f in g["features"]}
    assert p[1] == {"id": 1, "o": "ceka", "w": "evidováno", "k": 19, "c": "Chodník", "s": "Wolkerova",
                    "t": "2026-11-09T14:00", "a": "2026-11-09T16:00", "d": "Rozbitá dlažba",
                    "p": "/api/v1/podnety/1/foto/0123abcd.webp", "wd": 3}
    assert "s" not in p[2] and "d" not in p[2] and "p" not in p[2] and "wd" not in p[2]
    assert "p" not in p[3]                                  # never Dej Tip's own URL
    assert (p[3]["o"], p[3]["w"]) == ("predano", "předáno")                        # status 1, yet forwarded
    assert g["features"][0]["geometry"]["coordinates"] == [15.76, 50.03]
    assert stats.points([], NOW) == {"type": "FeatureCollection", "features": [], "bounds": None}


def test_facets_count_each_filter_within_the_other():
    rows = [rep(1, 1), rep(2, 3), rep(3, 3), rep(4, 1, "Autovrak", 17), rep(5, 1, "Městská policie", 25)]
    f = stats.facets(rows, "", None)
    assert [(x["key"], x["n"]) for x in f["stav"]] == [("ceka", 2), ("vyreseno", 2), ("", 5)]   # waiting first, all last
    assert {x["name"]: x["n"] for x in f["druh"]} == {"Chodník": 3, "Autovrak": 1, "Městská policie": 1}
    f = stats.facets(rows, "ceka", 19)
    assert [(x["key"], x["n"], x["on"]) for x in f["stav"]] == [("ceka", 1, True), ("vyreseno", 2, False), ("", 3, False)]
    assert {x["name"]: x["n"] for x in f["druh"]} == {"Chodník": 1, "Autovrak": 1, "Městská policie": 0}
    assert f["all"] == 2
    assert stats.druh_key("19", rows) == 19 and stats.druh_key("99", rows) is None and stats.druh_key("x", rows) is None
    assert stats.stav_key("ceka") == "ceka" and stats.stav_key("predano") == "ceka" and stats.stav_key("vse") == ""
    assert [stats.stav_url(k) for k in ("ceka", "vyreseno", "")] == ["", "vyreseno", "vse"]


# --- the page -------------------------------------------------------------------------------

ROWS = ([rep(i, 3, at=NOW - (i + 1) * D, first=NOW - (i + 1) * D + 5 * H, last=NOW - i * D) for i in range(12)]
        + [rep(100 + i, 1, "Pískoviště, hřiště, sportoviště", 20, at=NOW - (40 + i) * D, street="Sokolovská")
           for i in range(10)]
        + [rep(200, 1, "Městská policie", 25, at=NOW - 2 * H, street="Jiránkova"),
           rep(201, 6, "Autovrak", 17, at=NOW - 3 * H), rep(202, 4, "Jiné", 24), rep(203, 2, at=NOW - H)])


@pytest.fixture
def page(monkeypatch):
    seen = {}

    def rows(obvod, start, end):
        seen.update(obvod=obvod, start=start, end=end)
        return [r for r in ROWS if start <= r["reported_at"].date() < end]

    monkeypatch.setattr(queries, "period_rows", rows)
    monkeypatch.setattr(queries, "years", lambda obvod: [2025, 2026])
    monkeypatch.setattr(queries, "checked", lambda obvod: dt.datetime(2026, 11, 12, 6, 0))
    monkeypatch.setattr(web, "_now", lambda: NOW)

    def get(path):
        r = TestClient(app).get(path, headers={"host": "otevrenapetka.cz"})
        assert r.status_code == 200
        return r.text
    get.seen = seen
    return get


def main(html: str) -> str:
    return html.split('<main id="obsah"', 1)[1].split("</main>", 1)[0]


def open_detail(html: str) -> list[str]:
    return re.findall(r'data-pd-detail="(\w+)" aria-label="[^"]*">', html)


@pytest.mark.parametrize("detail", ["mesice", "vyreseno", "ceka", "odpoved"])
def test_each_detail_is_rendered_open(page, detail):
    html = page(f"/verejny-prostor/podnety?detail={detail}")
    assert open_detail(html) == [detail]
    assert html.count('aria-expanded="true"') == 1
    assert f'data-pd-tile="{detail}" aria-controls="kpi-panel" aria-expanded="true"' in html


def test_default_and_closed(page):
    assert open_detail(page("/verejny-prostor/podnety")) == ["mesice"]
    assert open_detail(page("/verejny-prostor/podnety?detail=nesmysl")) == ["mesice"]
    html = page("/verejny-prostor/podnety?detail=zadny")
    assert open_detail(html) == [] and 'aria-expanded="true"' not in html


def test_page_content(page):
    html = page("/verejny-prostor/podnety")
    assert page.seen["obvod"] == "mo5" and page.seen["start"] == dt.date(2025, 11, 12)
    m = main(html)
    assert "Co lidé hlásí a jak se to řeší?" in html and "Nahlásit závadu přes Dej Tip" in html
    assert "<b>26</b>" in m and "vyřešeno (46 %)" in m                     # 12 of 26
    assert "Nejdéle čekají" not in m                                       # no highlight box any more
    assert "předávají se strážníkům, stav v Dej Tipu se nemění" in m
    assert '<span class="st st-no">' in m and '<span class="st">vyřešeno</span>' not in m.split('class="mbox-col pd-side"')[1]
    assert '<span class="st">vyřešeno</span>' in main(page("/verejny-prostor/podnety?stav=vse"))   # every state
    assert "Stav k 12. 11. 2026." in m and "Odkud to víme" in m
    assert "Všechny podněty" not in m and "Co tu neuvidíte" not in m
    assert "aplikac" not in m.replace("aplikace Dej Tip", "").replace("aplikace <a", "")   # no app of ours
    assert "Jiránkova" in m                                                  # newest, street only
    assert "Podněty ukazujeme seskupené" not in m and "Nejnovější" not in m
    assert "Klik na shluk" not in m
    # the list (every state): newest first, one row a link to the report on Dej Tip; the description only in the card
    side = main(page("/verejny-prostor/podnety?stav=vse")).split('class="mbox-col pd-side"')[1].split("</aside>")[0]
    assert "26 podnětů v mapě, nejnovější nahoře" in side and side.count("<li ") == 15
    assert re.findall(r'<li data-id="(\d+)"', side)[:4] == ["203", "200", "201", "0"]
    assert 'href="https://amg.dejtip.eu/pardubice/?id=200"' in side
    assert '<span class="pd-rd">12.\u00a011.</span><span class="pd-rt"><b>Městská policie</b><span>Jiránkova</span></span><span class="st">předáno</span>' in side
    assert 'href="/verejny-prostor/podnety?stav=vse&amp;pocet=30#kde" data-pd-rows-more>Další podněty' in side
    # the filters: counts for the period, links and a GET form without JS
    assert '<a href="/verejny-prostor/podnety#kde" data-stav="" aria-current="true">Čeká <b>11</b></a>' in m   # the default
    assert '<a href="/verejny-prostor/podnety?stav=vse#kde" data-stav="vse">Vše <b>26</b></a>' in m
    assert '<option value="20">Pískoviště, hřiště, sportoviště (10)</option>' in m
    assert '<a href="/verejny-prostor/podnety?druh=20#kde">Pískoviště, hřiště, sportoviště</a>' in m      # the table
    pts = m.split('id="pd-points">')[1].split("</script>")[0]
    assert '"o": "predano", "w": "předáno"' in pts and "Jiránkova" in pts


def test_no_middle_dot_anywhere_in_the_page(page):
    for path in ("/verejny-prostor/podnety", "/verejny-prostor/podnety?detail=mesice", "/verejny-prostor/podnety?detail=odpoved", "/verejny-prostor/podnety?obdobi=2025"):
        assert "·" not in main(page(path))
    assert "·" not in open(web.__file__.replace("podnety/web.py", "web/templates/podnety/prehled.html")).read()
    assert "·" not in open(web.__file__.replace("podnety/web.py", "web/static/podnety.js")).read()


def test_periods_and_links(page):
    page("/verejny-prostor/podnety?obdobi=2025")
    assert page.seen["start"] == dt.date(2025, 1, 1) and page.seen["end"] == dt.date(2026, 1, 1)
    html = page("/verejny-prostor/podnety?obdobi=2026&detail=mesice")
    assert page.seen["end"] == dt.date(2026, 11, 13)
    assert 'href="/verejny-prostor/podnety?obdobi=2026&amp;detail=vyreseno#kpi"' in html
    assert 'href="/verejny-prostor/podnety?obdobi=2026&amp;detail=zadny#kpi"' in html          # the open tile closes
    assert '<a href="/verejny-prostor/podnety"><span class="pd-d">Posledních 12 měsíců' in html       # links leave the open tile out
    assert 'href="/verejny-prostor/podnety?obdobi=2026" aria-current="page"' in html
    assert "podnětů v roce 2026" in html
    html = page("/verejny-prostor/podnety?obdobi=2026&kategorie=20")          # an older link
    assert '<option value="20" selected>' in html


def test_filters_without_js(page):
    m = main(page("/verejny-prostor/podnety?obdobi=2026&stav=ceka&druh=20&detail=mesice"))
    side = m.split('class="mbox-col pd-side"')[1].split("</aside>")[0]
    assert "10 podnětů v mapě, nejnovější nahoře" in side and side.count("<li ") == 10 and "Další podněty" not in side
    assert all(x in side for x in ("Sokolovská", 'class="st st-no"')) and "vyřešeno" not in side
    assert 'data-stav="" aria-current="true">Čeká <b>10</b>' in m          # the default, left out of the address
    assert '<option value="20" selected>Pískoviště, hřiště, sportoviště (10)</option>' in m
    assert '<option value="19">Chodník (1)</option>' in m                                  # waiting Chodník
    for hidden in ('name="obdobi" value="2026"',):
        assert f'<input type="hidden" {hidden}>' in m
    assert 'name="stav"' not in m.split("data-pd-filter")[1].split("</form>")[0].replace('aria-label="Stav', '')
    # the period switch and the tiles keep the filter
    assert 'href="/verejny-prostor/podnety?druh=20"' in m
    assert 'href="/verejny-prostor/podnety?obdobi=2026&amp;detail=zadny&amp;druh=20#kpi"' in m
    m = main(page("/verejny-prostor/podnety?stav=vyreseno&pocet=30"))
    side = m.split('class="mbox-col pd-side"')[1].split("</aside>")[0]
    assert side.count("<li ") == 12 and "st-no" not in side
    assert stats.LIST == 15
    assert web.link("12m") == "/verejny-prostor/podnety" and web.link("2025", detail="", kategorie=3) == "/verejny-prostor/podnety?obdobi=2025&kategorie=3"


def test_empty_period(page, monkeypatch):
    monkeypatch.setattr(queries, "period_rows", lambda *a: [])
    assert "žádné podněty nemáme" in page("/verejny-prostor/podnety?obdobi=2026")


def test_db_queries():
    try:
        db.migrate()
    except Exception:
        pytest.skip("no local database")
    rows = queries.period_rows("mo5", dt.date(2025, 1, 1), dt.date(2026, 1, 1))
    assert all(dt.datetime(2025, 1, 1) <= r["reported_at"] < dt.datetime(2026, 1, 1) for r in rows)
    assert queries.period_rows("neni", dt.date(2025, 1, 1), dt.date(2026, 1, 1)) == []
    assert queries.years("neni") == []


def test_resolution_time_from_the_status_change():
    t0 = dt.datetime(2026, 11, 1, 8)
    seen = {"reported_at": t0, "resolved_seen_at": t0 + dt.timedelta(days=2), "last_note_at": t0 + dt.timedelta(days=9)}
    assert stats.resolution_days(seen) == 2                                   # the change we saw wins
    assert stats.resolution_days({"reported_at": t0, "last_note_at": t0 + dt.timedelta(days=9)}) == 9   # older: the last note
    assert stats.resolution_days({"reported_at": t0}) is None                 # neither: unknown


def test_the_bar_has_a_segment_per_outcome(page):
    m = main(page("/verejny-prostor/podnety"))
    bar = m.split('<div class="pd-bar"')[1].split("</div>")[0]
    assert ('aria-label="Vyřešeno 12, čeká 11, předáno jinam 1, nepřísluší obvodu 1, nelze vyřídit 1, '
            'chybné nebo nepravdivé 0"') in bar
    assert re.findall(r'<i class="([\w-]+)" style="width:([\d.]+)%"', bar) == [
        ("pd-k-ok", "46.2"), ("pending-alert", "42.3"), ("pd-k-away", "3.8"), ("pd-k-np", "3.8"), ("pd-k-cant", "3.8")]
    lg = m.split('<p class="pd-lg">')[1].split("</p>")[0]
    assert re.sub(r"<[^>]+>", "", lg) == ("vyřešeno 12čeká 11předáno jinam (městská policie, dopravní podnik, jiný úřad) 1"
                                         "nepřísluší obvodu 1nelze vyřídit 1")      # no chybné: none in the period
    mini = re.findall(r'<span class="pd-mini" role="img" aria-label="([^"]*)">', m)
    assert "vyřešeno 0, čeká 0, předáno jinam 1, nepřísluší obvodu 0, nelze vyřídit 0, chybné nebo nepravdivé 0" in mini


def test_street_filter(page, monkeypatch):
    from petka.ulice import streets as ust
    line = {"type": "LineString", "coordinates": [[15.75, 50.02], [15.76, 50.02]]}
    monkeypatch.setattr(ust, "streets", lambda obvod: {
        "sokolovska": ust.Street("sokolovska", "Sokolovská", 1, line, 1.0),
        "jirankova": ust.Street("jirankova", "Jiránkova", 2, line, 1.0)})
    assert stats.on_street(rep(street="SOKOLOVSKA "), "Sokolovská") and not stats.on_street(rep(street=None), "Sokolovská")
    m = main(page("/verejny-prostor/podnety?ulice=sokolovska"))
    side = m.split('class="mbox-col pd-side"')[1].split("</aside>")[0]
    assert "10 podnětů v mapě, nejnovější nahoře" in side and "Wolkerova" not in side
    assert 'data-stav="" aria-current="true">Čeká <b>10</b>' in m and 'data-stav="vse">Vše <b>10</b>' in m
    assert '<input type="hidden" name="ulice" value="sokolovska">' in m
    assert 'Ulice <b>Sokolovská</b> <a href="/verejny-prostor/podnety#kde" data-pd-street-clear>Všechny ulice</a>' in m
    assert 'href="/verejny-prostor/podnety?stav=vse&amp;ulice=sokolovska#kde" data-stav="vse"' in m      # the filters keep it
    m = main(page("/verejny-prostor/podnety?ulice=jirankova&stav=vse&druh=25"))
    side = m.split('class="mbox-col pd-side"')[1].split("</aside>")[0]
    assert side.count("<li ") == 1 and "Městská policie" in side
    m = main(page("/verejny-prostor/podnety?ulice=neni"))                     # not a street of the obvod: ignored
    assert "data-pd-street" not in m and "11 podnětů v mapě" in m
