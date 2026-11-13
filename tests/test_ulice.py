"""The front page and the street pages (petka.ulice): which streets belong to the obvod, the
search, the streets around, the shaping of cleanings, reports and the feed, and the pages over
fixture data (every query replaced). The database test skips without one."""

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from petka import db
from petka.cisteni import places, queries as cq
from petka.podnety import queries as pq
from petka.ulice import queries as q, streets as st, web
from petka.usneseni import queries as uq, search as us
from petka.uredni_deska import queries as dq
from petka.web.app import app

D = dt.date
TODAY = D(2026, 11, 12)
NOW = dt.datetime(2026, 11, 12, 14, 0)

# a square obvod around (0..1, 0..1) and lines in and around it
SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


def line(*pts):
    return {"type": "LineString", "coordinates": [list(p) for p in pts]}


def test_streets_in_the_obvod_by_share():
    names = [[1, "Wolkerova"], [2, "Lexova"], [3, "Pražská"], [4, "Daleká"], [5, "Bez čáry"], [6, "Čs. armády"]]
    geoms = {1: line((.2, .5), (.8, .5)),            # inside
             2: line((.5, .2), (.5, .8)),            # inside, crosses Wolkerova
             3: line((.9, .9), (5, .9)),             # 0.1 / 4.1 inside, ~2 %: left out
             4: line((2, 2), (3, 3)),                # outside
             5: None,
             6: line((.5, .8), (.5, 1.2))}           # half inside: on the border, listed
    got = st.in_obvod(names, geoms, SQUARE)
    assert [s.name for s in got] == ["Čs. armády", "Lexova", "Wolkerova"]       # accent-blind order
    assert {s.slug: s.share for s in got} == {"cs-armady": .5, "lexova": 1, "wolkerova": 1}


def test_find():
    names = {"wolkerova": "Wolkerova", "lexova": "Lexova", "sokolovska": "Sokolovská", "k-barvirne": "K Barvírně"}
    assert st.find("WOLKEROVÁ", names) == ["wolkerova"]
    assert st.find("ul. Lexova", names) == ["lexova"]
    assert st.find("ova", names) == ["wolkerova", "lexova"]
    assert st.find("lex", names) == ["lexova"]
    assert st.find("so", names) == ["sokolovska"]
    assert st.find("barv", names) == ["k-barvirne"]
    assert st.find("  ", names) == [] and st.find("Nádražní", names) == []


def test_around_puts_crossing_streets_first():
    every = {s.slug: s for s in st.in_obvod(
        [[1, "Wolkerova"], [2, "Lexova"], [3, "Blízká"], [4, "Vzdálená"]],
        {1: line((.2, .5), (.8, .5)), 2: line((.5, .2), (.5, .9)), 3: line((.2, .52), (.4, .52)),
         4: line((.9, .9), (.95, .95))}, SQUARE)}
    assert [s.name for s in st.around("wolkerova", every)] == ["Lexova", "Blízká", "Vzdálená"]
    assert [s.name for s in st.around("wolkerova", every, n=1)] == ["Lexova"]
    assert st.around("neni", every) == []


# --- shaping -------------------------------------------------------------------------------

def item(d, street="Wolkerova", text=None, side="obe", method="whole", time=dt.time(7)):
    text = text or f"{street} v celé délce - obě strany komunikace"
    return cq.shape({"key": places.place_key(text), "texts": [text], "main_street": street, "streets": [street],
                     "side": side, "status": "auto", "method": method, "located": True, "date": d, "time": time,
                     "before": False})


def test_cleaning():
    its = [item(D(2026, 7, 27)), item(D(2026, 9, 17), text="Wolkerova - parkoviště u č. p. 2122-2123", method="segment"),
           item(D(2026, 11, 26)), item(D(2026, 12, 9))]
    cl = q.cleaning(its, TODAY)
    assert cl.next == D(2026, 11, 26) and cl.whole and cl.side == "obě strany" and cl.time == "od 7:00"
    assert [i["date"] for i in cl.past] == [D(2026, 9, 17), D(2026, 7, 27)]
    assert len(cl.upcoming) == 2
    assert q.cleaning_text(cl) == "Celá ulice, obě strany, od 7:00"
    part = q.cleaning([item(D(2026, 11, 20), text="Wolkerova - parkoviště u č. p. 2122-2123", method="segment")], TODAY)
    assert not part.whole and q.cleaning_text(part).startswith("Parkoviště u č. p. 2122-2123")
    none = q.cleaning([item(D(2026, 3, 1))], TODAY)
    assert none.next is None and none.on_next == [] and not none.whole and none.time == ""


def test_next_cleaning_line():
    its = [item(D(2026, 11, 18), "Josefa Ressla", side="prava"), item(D(2026, 11, 18), "Milheimova", side="prava")]
    assert q.next_cleaning_line(its) == ("Josefa Ressla a Milheimova, pravá strana", "/blokove-cisteni/ulice/josefa-ressla")
    three = its + [item(D(2026, 11, 18), "Lexova")]
    assert q.next_cleaning_line(three)[0] == "Josefa Ressla, Milheimova a Lexova"


def rep(id, status, at, category="Chodník", street="Wolkerova"):
    return {"id": id, "status": status, "category": category, "category_id": 19, "reported_at": at,
            "lat": 50.03, "lng": 15.76, "street": street}


def test_reports_and_their_items():
    rows = [rep(1, 3, NOW - dt.timedelta(days=3)), rep(2, 1, NOW - dt.timedelta(days=400)),
            rep(3, 1, NOW, "Městská policie")]
    r = q.reports(rows)
    assert (r["n"], r["vyreseno"], r["ceka"], r["jinam"]) == (3, 1, 1, 1)
    assert r["since"] == NOW - dt.timedelta(days=400) and q.since_word(r["since"]) == "od října 2025"
    assert q.reports([])["since"] is None and q.since_word(None) == ""
    i = q.report_item(rows[1], "/ulice/wolkerova")
    assert i["text"] == "Chodník, Wolkerova" and i["status"] == ("čeká", "st st-no") and i["source"] == "Závady"


def test_feed_puts_the_next_cleaning_first_then_newest():
    items = [{"date": D(2026, 9, 23), "text": "a"}, {"date": D(2026, 11, 26), "text": "next", "next": True},
             {"date": D(2026, 11, 10), "text": "b"}, {"date": None, "text": "no date"}, {"date": D(2026, 6, 1), "text": "c"}]
    assert [i["text"] for i in q.feed(items, 3)] == ["next", "b", "a"]


def test_items_of_resolutions_and_notices():
    r = {"uid": "310-2026-r", "number": "310/2026 R", "body": "rmo", "date": D(2026, 9, 23), "title": "Přímé zadání",
         "agenda_title": None, "mainvote": {"pro": 5}}
    assert q.resolution_item(r) | {} == {"date": D(2026, 9, 23), "source": "Rada", "number": "310/2026 R",
                                         "text": "Přímé zadání", "href": "/usneseni/310-2026-r", "vote": {"pro": 5}, "body": "rmo"}
    n = {"id": "n1", "published": D(2026, 11, 10), "title": "VV - OOP", "digest": {"headline": "Úprava provozu"}}
    assert q.notice_item(n)["text"] == "Úprava provozu" and q.notice_item(n | {"digest": None})["text"] == "VV - OOP"
    assert q.thousands(1026) == "1 026"


def test_loose_matches_are_not_counted(monkeypatch):
    class H:
        row = {"date": D(2026, 1, 1)}
    monkeypatch.setattr(us, "search", lambda *a, **kw: ([H()], {"total": 40, "loose": True}))
    assert q.resolutions("Boženy Němcové") == ([], 0)
    monkeypatch.setattr(us, "search", lambda *a, **kw: ([H()], {"total": 19}))
    assert q.resolutions("Wolkerova") == ([{"date": D(2026, 1, 1)}], 19)


# --- the pages over fixtures ---------------------------------------------------------------

STREETS = st.in_obvod([[1, "Wolkerova"], [2, "Lexova"], [3, "Josefa Ressla"]],
                      {1: line((15.755, 50.026), (15.763, 50.026)), 2: line((15.759, 50.022), (15.759, 50.03)),
                       3: line((15.753, 50.024), (15.758, 50.024))},
                      {"type": "Polygon", "coordinates": [[[15.7, 49.9], [15.9, 49.9], [15.9, 50.1], [15.7, 50.1], [15.7, 49.9]]]})


@pytest.fixture
def fixture(monkeypatch):
    its = [item(D(2026, 9, 17), text="Wolkerova - parkoviště u č. p. 2122-2123", method="segment"),
           item(D(2026, 11, 18), "Josefa Ressla", side="prava"), item(D(2026, 11, 26))]
    geom = line((15.756, 50.026), (15.76, 50.026))
    reps = [rep(1, 3, NOW - dt.timedelta(days=170), "Lavičky, zábradlí"), rep(2, 1, NOW - dt.timedelta(days=1), street="Lexova")]
    res = [{"uid": "310-2026-r", "number": "310/2026 R", "body": "rmo", "date": D(2026, 9, 23),
            "title": "Přímé zadání opravy asfaltu", "agenda_title": None,
            "mainvote": {"pro": 5, "proti": 0, "zdrzel": 0, "nehl": 0, "quorum": 3, "parts": 0, "whole": True}}]

    class Hit:
        def __init__(self, row):
            self.row = row
    monkeypatch.setattr(st, "streets", lambda obvod: {s.slug: s for s in STREETS})
    monkeypatch.setattr(cq, "items", lambda obvod, since, slugs=None: its)
    monkeypatch.setattr(cq, "geometries", lambda obvod: {i["key"]: geom for i in its})
    monkeypatch.setattr(pq, "period_rows", lambda obvod, a, b: reps)
    monkeypatch.setattr(q, "street_reports", lambda obvod, name: [r for r in reps if r["street"] == name])
    monkeypatch.setattr(q, "resolutions", lambda name: (res, 19) if name == "Wolkerova" else ([], 0))
    monkeypatch.setattr(q, "notices_posted", lambda name: 0)
    monkeypatch.setattr(q, "latest_notices", lambda n: [{"id": "n1", "published": D(2026, 11, 10), "title": "Změna povolení stavby",
                                                         "digest": None}])
    monkeypatch.setattr(us, "search", lambda *a, **kw: ([Hit(res[0])], {"total": 1}))
    monkeypatch.setattr(uq, "stats", lambda: {"resolutions": 1026, "meetings": 184, "first_date": D(2018, 1, 10)})
    monkeypatch.setattr(dq, "stats", lambda: {"posted_mo5": 75, "posted": 303})
    monkeypatch.setattr(web, "_now", lambda: NOW)


def get(path, **kw):
    return TestClient(app).get(path, headers={"host": "otevrenapetka.cz"}, follow_redirects=False, **kw)


def test_front_page(fixture):
    r = get("/")
    assert r.status_code == 200
    h = r.text
    for s in ("Co se děje na&nbsp;Pětce?", "Příklad: Wolkerova, sídliště Dukla", "Podívejte se na svou ulici",
              'action="/ulice"', '<option value="Wolkerova">', "Celý obvod", "Co se děje",
              "Josefa Ressla, pravá strana", "Lexova</a> <span class=\"st st-no\">čeká</span>",
              "Změna povolení stavby", "Přímé zadání opravy asfaltu", "1 026 usnesení ze 184 jednání od roku 2018",
              "75 oznámení k obvodu, 228 magistrátu", "3 termínů na 3 místech letos", "Kdo za tím stojí a proč",
              "Připraveno pro agenty", "hv-tag"):
        assert s in h, s
    assert '<li class="row next"><span class="feed-d">18. 11.</span>' in h
    fc = json.loads(h.split('id="ul-map-json">')[1].split("</script>")[0])
    kinds = {(f["properties"]["kind"], f["properties"].get("when")) for f in fc["features"]}
    assert kinds == {("cleaning", "week"), ("cleaning", "two"), ("reports", None)}
    assert "aria-current" not in h.split('class="l1"')[1].split("</nav>")[0]      # no area is current


def test_search_redirects_or_lists(fixture):
    r = get("/ulice", params={"q": "WOLKEROVÁ"})
    assert r.status_code == 303 and r.headers["location"] == "/ulice/wolkerova"
    r = get("/ulice", params={"q": "ova"})
    assert r.status_code == 200 and "je víc" in r.text and 'href="/ulice/lexova"' in r.text
    r = get("/ulice", params={"q": "Nádražní"})
    assert r.status_code == 303 and r.headers["location"] == "/?ulice=N%C3%A1dra%C5%BEn%C3%AD#hledat"
    h = get("/", params={"ulice": "Nádražní"}).text
    assert "Tahle ulice v městském obvodě Pardubice V není." in h and 'value="Nádražní"' in h


def test_street_page(fixture):
    r = get("/ulice/wolkerova")
    assert r.status_code == 200
    h = r.text
    for s in ("<h1>Wolkerova</h1>", "Příští blokové čištění", "26. 11.", "čtvrtek od 7:00, obě strany",
              "Související rozhodnutí", "<b>19</b>", "naposledy 23. 9.", 'href="/usneseni?q=Wolkerova&amp;rezim=fulltext"',
              "nic nečeká", "1 nahlášená od května 2026, 1 vyřešená", "Co se tu děje", "Celá ulice, obě strany, od 7:00",
              "Rada, usnesení 310/2026 R", "5 pro; potřeba 3", "parkoviště u č. p. 2122-2123",
              "Lavičky, zábradlí", "Všechno k ulici Wolkerova", "teď nic nevisí", "Okolní ulice", 'href="/ulice/lexova"',
              'href="/uzavirky"'):
        assert s in h, s
    assert "Uzavírka</small>" not in h          # no data on closures yet: no box
    fc = json.loads(h.split('id="ul-map-json">')[1].split("</script>")[0])
    assert [f["properties"].get("when") for f in fc["features"] if f["properties"]["kind"] != "reports"] == [None, "past", "next"]
    assert get("/ulice/neni").status_code == 404


def test_db_queries():
    try:
        with db.pool().connection() as conn:
            conn.execute("SELECT 1 FROM ruian_cache LIMIT 1")
    except Exception:
        pytest.skip("no local database")
    mo5 = st.streets("mo5")
    if not mo5:
        pytest.skip("RÚIAN not fetched (petka ulice-update)")
    assert "wolkerova" in mo5 and mo5["wolkerova"].share > .9
    assert all(s.share >= cq.MIN_SHARE for s in mo5.values())
    res, n = q.resolutions("Wolkerova")
    assert n >= len(res) and all(r["date"] for r in res)
    assert isinstance(q.notices_posted("Wolkerova"), int)
    assert all(r["street"] == "Wolkerova" for r in q.street_reports("mo5", "wolkerova"))
