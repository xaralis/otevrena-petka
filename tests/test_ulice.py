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
D_ = lambda y, m, d: dt.datetime(y, m, d, 10, 0)
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
    part = q.cleaning([item(D(2026, 11, 20), text="Wolkerova - parkoviště u č. p. 2122-2123", method="segment")], TODAY)
    assert not part.whole
    none = q.cleaning([item(D(2026, 3, 1))], TODAY)
    assert none.next is None and none.on_next == [] and not none.whole and none.time == ""


def test_next_cleaning_line():
    its = [item(D(2026, 11, 18), "Josefa Ressla", side="prava"), item(D(2026, 11, 18), "Milheimova", side="prava")]
    assert q.next_cleaning_line(its) == ("Josefa Ressla a Milheimova, pravá strana", "/verejny-prostor/ulice/josefa-ressla#cisteni")
    three = its + [item(D(2026, 11, 18), "Lexova")]
    assert q.next_cleaning_line(three)[0] == "Josefa Ressla, Milheimova a Lexova"


def rep(id, status, at, category="Chodník", street="Wolkerova"):
    return {"id": id, "status": status, "category": category, "category_id": 19, "reported_at": at,
            "lat": 50.03, "lng": 15.76, "street": street}


def test_reports_counts():
    rows = [rep(1, 3, NOW - dt.timedelta(days=3)), rep(2, 1, NOW - dt.timedelta(days=400)),
            rep(3, 1, NOW, "Městská policie")]
    r = q.reports(rows)
    assert (r["n"], r["vyreseno"], r["ceka"], r["predano"]) == (3, 1, 1, 1)
    assert r["since"] == NOW - dt.timedelta(days=400) and q.since_word(r["since"]) == "od října 2025"
    assert q.reports([])["since"] is None and q.since_word(None) == ""
    assert q.thousands(1026) == "1\u00a0026"


NB = "\u00a0"


def test_report_rows_keep_new_and_waiting_and_sum_older_by_month():
    h = dt.timedelta(hours=1)
    rows = [rep(1, 1, NOW - 2 * 24 * h, "Autovrak"),                                  # waits: own row
            dict(rep(2, 3, NOW - 10 * 24 * h, "Odpadky, černá skládka"), first_note_at=NOW - 10 * 24 * h + 16 * h),
            rep(3, 1, NOW - 60 * 24 * h, "Městská policie"),                          # forwarded: own row
            rep(4, 3, D_(2026, 9, 3), "Odpadky, černá skládka"), rep(5, 3, D_(2026, 9, 9), "Odpadky, černá skládka"),
            rep(6, 3, D_(2026, 9, 20), "Jiné"),                                        # september: summed
            rep(7, 3, D_(2026, 7, 2), "Veřejná zeleň"),                                # alone in its month: itself
            rep(8, 3, D_(2025, 6, 2), "Jiné"), rep(9, 3, D_(2025, 6, 5), "Jiné")]
    out = {r["key"]: r for r in q.report_rows(rows, NOW, "wolkerova")}
    assert set(out) == {"r1", "r2", "r3", "m202609", "r7", "m202506"}
    assert (out["r1"]["sub"], out["r1"]["status"]) == (f"čeká 2{NB}dny", ("evidováno", "st st-no"))
    assert out["r2"]["sub"] == f"odpověď úřadu za 16{NB}h" and out["r2"]["ext"] and "?id=2" in out["r2"]["href"]
    assert out["r3"]["sub"] == "předáno strážníkům" and out["r3"]["status"][0] == "předáno"
    m = out["m202609"]
    assert (m["label"], m["year"], m["title"], m["sub"]) == ("zář", None, f"3{NB}podněty", f"odpadky{NB}2, jiné{NB}1")
    assert m["ids"] == [4, 5, 6] and m["date"] == D(2026, 9, 20) and "ulice=wolkerova" in m["href"]
    assert (out["m202506"]["label"], out["m202506"]["year"]) == ("čvn", 2025)
    assert out["r7"]["sub"] == "podnět z Dej Tipu"


def test_rows_newest_first_with_cleanings_resolutions_and_notices():
    its = [item(D(2026, 9, 17), text="Wolkerova - parkoviště u č. p. 2122-2123", method="segment"), item(D(2026, 11, 26))]
    cl = q.cleaning_rows(its, TODAY, "/verejny-prostor/blokove-cisteni/ulice/wolkerova")
    assert [(r["label"], r["status"]) for r in cl] == [(f"17.{NB}9.", ("proběhlo", "st ul-done")), (f"26.{NB}11.", (f"za{NB}14{NB}dní", "st"))]
    assert cl[0]["sub"] == f"parkoviště u č.{NB}p.{NB}2122–2123" and cl[1]["sub"] == f"v celé ulici, po obou stranách, od{NB}7:00"
    res = q.resolution_row({"uid": "u", "number": "310/2026 R", "body": "rmo", "date": D(2026, 9, 23), "title": "Asfalt",
                            "agenda_title": None, "status": "castecne"}, TODAY)
    assert (res["sub"], res["status"]) == (f"rada, usnesení 310/2026{NB}R", ("částečně", "st st-part"))
    marks = q.board_marks(NOTICES, {s.slug: s for s in STREETS if s.name == "Lexova"}, TODAY)
    n = q.notice_row(marks[0], TODAY)
    assert (n["title"], n["sub"], n["status"], n["href"]) == ("Uzavřená stezka kvůli stavebním pracím",
        f"úřední deska, 10.{NB}11. – 20.{NB}11.{NB}2026", (f"do 20.{NB}11.", "st"), "/radnice/uredni-deska/n1")
    rows = q.rows(cl, [res], [n], q.report_rows([rep(1, 1, NOW)], NOW, "wolkerova"))
    assert [r["kind"] for r in rows] == ["cl", "rep", "deska", "res", "cl"]


def test_short_title_and_charts():
    assert q.short_title("Investiční záměry k realizaci") == "investiční záměry k realizaci"
    assert q.short_title("MHD v ulici") == "MHD v ulici"
    assert q.short_title("Slovo " * 30, 20).endswith("…") and len(q.short_title("Slovo " * 30, 20)) <= 21
    rows = [rep(1, 3, dt.datetime(2026, 5, 3)), rep(2, 1, dt.datetime(2026, 11, 1)), rep(3, 1, NOW, "Městská policie")]
    c = q.report_months(rows, TODAY)                      # the Podněty page's chart and its 12 months
    assert ([(x["y"], x["m"]) for x in c["cols"][::12]], len(c["cols"])) == ([(2025, 11), (2026, 11)], 13)
    assert (c["cols"][-1]["n"], c["cols"][6]["n"], c["cols"][6]["done"]) == (2, 1, 1) and q.report_months([], TODAY) is None
    assert q.report_months([rep(9, 3, dt.datetime(2025, 1, 5))], TODAY) is None       # nothing in the 12 months
    assert q.report_kinds(rows, 1) == ([{"id": 19, "name": "Chodník", "n": 2}], 1)
    y = q.resolution_years([{"date": D(2019, 1, 1)}, {"date": D(2026, 3, 1)}], TODAY)
    assert ([x["abbr"] for x in y["cols"][::8]], len(y["cols"])) == (["2018", "2026"], 9) and "2019 1" in y["label"]
    assert y["cols"][1]["n"] == y["cols"][1]["done"] == 1 and q.resolution_years([], TODAY) is None


def test_declension():
    from petka.cisteni import words as cw
    assert [cw.locative(n) for n in ("Jiránkova", "Wolkerova", "Sokolovská", "Josefa Ressla")] == \
        ["v Jiránkově", "ve Wolkerově", "v Sokolovské", "v ulici Josefa Ressla"]
    assert [cw.accusative(n) for n in ("Jiránkova", "Sokolovská", "S. K. Neumanna")] == \
        ["Jiránkovu", "Sokolovskou", "ulici S. K. Neumanna"]


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


OOP = "VV - OOP stanovení přechodné úpravy provozu na pozemních komunikacích v Pardubicích - "


def notice(id, title, kind="doprava", published=D(2026, 11, 4), a=None, b=None, what=None):
    return {"id": id, "title": title, "kind": kind, "published": published, "valid_from": a, "valid_to": b, "what": what}


NOTICES = [
    notice("n1", OOP + "Lexova", a=D(2026, 11, 10), b=D(2026, 11, 20), what="Uzavřená stezka kvůli stavebním pracím"),
    notice("n2", OOP + "Wolkerova", b=D(2026, 11, 11), a=D(2026, 11, 5), what="Zábrany"),           # over
    notice("n3", OOP + "Wolkerova", a=D(2026, 11, 20), b=D(2026, 12, 1), what="Zábrany"),           # starts too late
    notice("n4", "Změna rozhodnutí - povolení stavby - chodníky Wolkerova", "stavby", D(2026, 11, 10)),
    notice("n5", OOP + "Josefa Ressla", published=D(2026, 11, 3)),                                  # not read
    notice("n6", OOP + "Nádražní", a=D(2026, 11, 10), b=D(2026, 11, 20)),                            # not in the obvod
]


def test_dates_on_the_map():
    nb = "\u00a0"
    assert q.days([D(2026, 11, 19), D(2026, 11, 18)]) == f"18. a 19.{nb}11."
    assert q.days([D(2026, 11, 18), D(2026, 11, 19), D(2026, 11, 20)]) == f"18., 19. a 20.{nb}11."
    assert q.days([D(2026, 11, 30), D(2026, 12, 1)]) == f"30.{nb}11. a 1.{nb}12."
    assert q.period(D(2026, 11, 16), D(2026, 12, 16)) == f"16.{nb}11. – 16.{nb}12.{nb}2026"
    assert q.period(D(2026, 11, 15), D(2028, 8, 31)) == f"15.{nb}11.{nb}2026 – 31.{nb}8.{nb}2028"
    assert q.period(D(2026, 11, 5), D(2026, 11, 5)) == f"5.{nb}11.{nb}2026"
    assert q.short_until(D(2026, 11, 20), D(2027, 1, 7), TODAY) == f"od 20.{nb}11."
    assert q.short_until(D(2026, 11, 3), D(2026, 12, 11), TODAY) == f"do 11.{nb}12."
    assert q.short_until(D(2026, 11, 3), D(2028, 8, 31), TODAY) == f"do 31.{nb}8.{nb}2028"


def test_week_cleanings():
    its = [item(D(2026, 11, 18), "Josefa Ressla", side="prava"), item(D(2026, 11, 19), "Josefa Ressla", side="leva"),
           item(D(2026, 11, 18), "Wolkerova", side="prava"), item(D(2026, 11, 13), "Lexova"), item(D(2026, 11, 26)),
           item(D(2026, 11, 10), "Lexova")]
    geoms = {i["key"]: line((15.75, 50.02), (15.76, 50.02)) for i in its}
    w = q.week_cleanings(its, geoms, TODAY)
    assert [(r["day"], r["text"]) for r in w["rows"]] == [
        ("pá 13.\u00a011.", "Lexova, obě strany"), ("st 18.\u00a011.", "Josefa Ressla a Wolkerova, pravá strana"),
        ("čt 19.\u00a011.", "Josefa Ressla, levá strana")]
    when = {a["sid"]: a["when"] for a in w["anchors"]}
    assert when == {"josefa-ressla": "pravá strana 18.\u00a011., levá 19.\u00a011.", "wolkerova": "pravá strana 18.\u00a011.",
                    "lexova": "obě strany 13.\u00a011."}
    assert w["anchors"][0]["lng"] == 15.755 and len(w["lines"]["features"]) == 3      # one per place; 26. 11. and the past left out
    assert q.week_cleanings(its, geoms, D(2026, 11, 11))["rows"][-1]["day"] == "st 18.\u00a011."     # a week, both ends in


def test_week_cleanings_area_is_its_own_marker():
    park = item(D(2026, 11, 13), "Wolkerova", text="Wolkerova - parkoviště u č. p. 2122-2123", method="area")
    its = [item(D(2026, 11, 13)), park]
    sq = {"type": "Polygon", "coordinates": [[[15.75, 50.02], [15.76, 50.02], [15.76, 50.03], [15.75, 50.03], [15.75, 50.02]]]}
    geoms = {its[0]["key"]: line((15.75, 50.02), (15.76, 50.02)), park["key"]: sq}
    w = q.week_cleanings(its, geoms, TODAY)
    by = {a["sid"]: a for a in w["anchors"]}
    assert set(by) == {"wolkerova", park["key"]}
    a = by[park["key"]]
    assert a["area"] and not by["wolkerova"]["area"] and a["what"] == "parkoviště u č. p. 2122-2123"
    assert 15.75 < a["lng"] < 15.76 and 50.02 < a["lat"] < 50.03                    # inside the area
    assert w["rows"][0]["sids"] == ["wolkerova", park["key"]]
    assert [f["properties"]["area"] for f in w["lines"]["features"]] == [False, True]


def test_board_marks():
    marks = q.board_marks(NOTICES, {s.slug: s for s in STREETS}, TODAY)
    assert [(m["nid"], m["street"]) for m in marks] == [("n4", "Wolkerova"), ("n1", "Lexova"), ("n5", "Josefa Ressla")]
    wol, lex, jr = marks
    assert (lex["what"], lex["when"], lex["box"]) == ("Uzavřená stezka kvůli stavebním pracím",
                                                     "10.\u00a011. – 20.\u00a011.\u00a02026", "do 20.\u00a011.")
    assert lex["label"] == "Dopravní omezení: Lexova, Uzavřená stezka kvůli stavebním pracím, 10.\u00a011. – 20.\u00a011.\u00a02026"
    assert (wol["what"], wol["when"], wol["traffic"]) == ("Stavby a řízení: změna rozhodnutí, povolení stavby, chodníky",
                                                         "vyvěšeno 10.\u00a011.", False)
    assert (jr["what"], jr["when"]) == ("Přechodná úprava provozu", "vyvěšeno 3.\u00a011.")
    from shapely.geometry import Point, shape
    on = shape(next(s for s in STREETS if s.name == "Lexova").geometry)
    assert on.distance(Point(lex["lng"], lex["lat"])) < 1e-9                   # on the street's line
    assert Point(lex["lng"], lex["lat"]).distance(Point(wol["lng"], wol["lat"])) >= q.CLEAR   # clear of the other mark
    # two marks on one street don't sit on each other
    two = q.board_marks([NOTICES[0], notice("n7", OOP + "Lexova", a=TODAY, b=TODAY, what="Jiné")],
                        {s.slug: s for s in STREETS}, TODAY)
    assert two[0]["lat"] != two[1]["lat"]


def test_board_marks_keep_clear_of_cleaning():
    lex = next(s for s in STREETS if s.name == "Lexova")
    free = q.board_marks([NOTICES[0]], {lex.slug: lex}, TODAY)[0]
    moved = q.board_marks([NOTICES[0]], {lex.slug: lex}, TODAY, avoid=[{"type": "Point", "coordinates": [free["lng"], free["lat"]]}])[0]
    assert (moved["lng"], moved["lat"]) != (free["lng"], free["lat"])


def test_board_marks_speak_with_the_card():
    card = dict(NOTICES[0], card="Stezka v Lexově bude měsíc zavřená")
    annex = dict(notice("n8", OOP + "Lexova", a=D(2026, 11, 10), b=D(2026, 11, 20), what="Zábrany"), owner="n1",
                 card="Stezka v Lexově bude měsíc zavřená")
    marks = q.board_marks([card, annex], {s.slug: s for s in STREETS}, TODAY)
    assert [(m["nid"], m["what"]) for m in marks] == [("n1", "Stezka v Lexově bude měsíc zavřená")]   # one mark, one link


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
    monkeypatch.setattr(q, "place_notices", lambda: NOTICES)
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
              'action="/verejny-prostor/ulice"', '<option value="Wolkerova">', '<h2 id="dash-h" class="dash-h">Aktuálně</h2>',
              "Blokové čištění tento týden", '<span class="ak-d">st 18.\u00a011.</span><span>Josefa Ressla, pravá strana</span>',
              "Dopravní omezení", "podle oznámení na úřední desce", '<span>Lexova</span><span class="ak-d">do 20.\u00a011.</span>',
              "dopravní omezení, místo podle názvu ulice", "další oznámení z úřední desky, ikona podle druhu",
              "<b>1\u00a0026</b> usnesení", "<b>75</b> oznámení visí",
              "<b>3</b> termínů letos", "Kdo za tím stojí a proč", "Připraveno pro agenty", "hv-tag", "aktualne.js"):
        assert s in h, s
    for s in ("Celý obvod", "Co se děje</h3>", "Nádražní"):
        assert s not in h, s
    d = json.loads(h.split('id="ak-json">')[1].split("</script>")[0])
    assert [f["properties"]["sid"] for f in d["lines"]["features"]] == ["josefa-ressla"]      # 26. 11. is too far
    assert d["anchors"][0]["when"] == "pravá strana 18.\u00a011." and d["days"][0]["sids"] == ["josefa-ressla"]
    assert [(m["street"], m["traffic"]) for m in d["marks"]] == [("Wolkerova", False), ("Lexova", True), ("Josefa Ressla", True)]
    assert "aria-current" not in h.split('class="l1"')[1].split("</nav>")[0]      # no area is current


def test_search_redirects_or_lists(fixture):
    r = get("/verejny-prostor/ulice", params={"q": "WOLKEROVÁ"})
    assert r.status_code == 303 and r.headers["location"] == "/verejny-prostor/ulice/wolkerova"
    r = get("/verejny-prostor/ulice", params={"q": "ova"})
    assert r.status_code == 200 and "je víc" in r.text and 'href="/verejny-prostor/ulice/lexova"' in r.text
    r = get("/verejny-prostor/ulice", params={"q": "Nádražní", "z": "uvod"})      # from the front page: back there
    assert r.status_code == 303 and r.headers["location"] == "/?ulice=N%C3%A1dra%C5%BEn%C3%AD#hledat"
    r = get("/verejny-prostor/ulice", params={"q": "Nádražní"})                    # from the Ulice page: the hint there
    assert r.status_code == 200 and "Tahle ulice v městském obvodě Pardubice V není." in r.text
    h = get("/verejny-prostor/ulice").text
    assert "Co se děje v mé ulici?" in h and "Všechny ulice obvodu" in h and 'href="/verejny-prostor/ulice/wolkerova"' in h
    h = get("/", params={"ulice": "Nádražní"}).text
    assert "Tahle ulice v městském obvodě Pardubice V není." in h and 'value="Nádražní"' in h


def test_street_page(fixture):
    r = get("/verejny-prostor/ulice/wolkerova")
    assert r.status_code == 200
    h = r.text
    m = h.split('<main id="obsah"', 1)[1].split("</main>", 1)[0]
    for s in ("<h1>Wolkerova</h1>", "Kde se v ulici čistí, co se o ní rozhodlo a co v ní lidé hlásí.",
              "Příští čištění za ", f"<em>26.{NB}11.</em>", "Čistí se v celé ulici, po obou stranách.",
              '<a class="cl-nx-a more" href="#cisteni">Celý harmonogram</a>',
              # three tiles over one panel as on the Podněty page, the cleaning open
              'data-pd-tile="cisteni" aria-controls="ul-panel" aria-expanded="true"', f'<b>čt <span class="ul-red">26.{NB}11.</span></b>',
              'data-pd-tile="podnety" aria-controls="ul-panel" aria-expanded="false"', "<b>nic nečeká</b>",
              "<span>1 podnět od května 2026, 1 vyřešený</span>", '<section data-pd-detail="podnety" aria-label="Podněty po měsících" hidden>',
              '<h3 class="side-h ul-panel-h">Na mapě</h3>',
              '<li><a href="/verejny-prostor/ulice/wolkerova?radky=vyreseno#aktualne">Vyřešené</a><b>1</b></li>',
              
              "<b>19 usnesení</b><span>rady a zastupitelstva od roku 2018</span>", '<h3 class="side-h">Naposledy</h3>',
              'href="/radnice/usneseni?q=Wolkerova&amp;rezim=fulltext">Všech 19 usnesení', "kpi.js",
              '<h2 id="ul-akt-h">Aktuálně</h2>',
              # the street's cleaning, a page of its own until 13. 11. 2026
              '<section class="ul-cl" id="cisteni"', "Lokalita podle harmonogramu Služeb", "cl-past",
              "Termíny Wolkerovy do kalendáře", "webcal://otevrenapetka.cz/verejny-prostor/blokove-cisteni/kalendar.ics?ulice=wolkerova",
              'href="/verejny-prostor/blokove-cisteni/ulice/wolkerova.ics"', "Blokové čištění v celém obvodu",
              '<li><a href="#cisteni">Blokové čištění</a><span class="ak-n">', "Odkud to víme", "Stavby a řízení: změna rozhodnutí",
               
              "Všechno k ulici Wolkerova", '<li><a href="/radnice/uredni-deska?q=Wolkerova">Úřední deska</a><span class="ak-n">',
              'href="/verejny-prostor/uzavirky"', "Okolní ulice", '<li><a href="/verejny-prostor/ulice/lexova">Lexova</a></li>',
              'data-icons="/static/deska-ikony.svg', "petkamap.js", "ulice.js"):
        assert s in h, s
    for s in ("Městský obvod Pardubice V", "Najeďte", "·", "Závad", "Související rozhodnutí",
              "Jiná ulice", "crumbs", "/verejny-prostor/blokove-cisteni/ulice/wolkerova\""):
        assert s not in m, s
    keys = [k for k in __import__("re").findall(r'<li data-row="([^"]+)"', m)]
    assert keys == ["c20261126", "dm0"]          # the last 30 days and the coming cleaning on top
    allkeys = __import__("re").findall(r'<li data-row="([^"]+)"', get("/verejny-prostor/ulice/wolkerova?radky=vse").text)
    assert allkeys == ["c20261126", "dm0", "z310-2026-r", "c20260917", "r1"]     # ?radky=vse: everything, newest first
    d = json.loads(h.split('id="ul-map-json">')[1].split("</script>")[0])     # the map shows what the rows show
    assert [f["properties"]["row"] for f in d["cleaning"]["features"]] == ["c20261126"] and d["reports"]["features"] == []
    assert [x["row"] for x in d["marks"]] == ["dm0"] and [a["row"] for a in d["anchors"]] == ["c20261126"]
    h = get("/verejny-prostor/ulice/wolkerova?radky=vse").text
    d = json.loads(h.split('id="ul-map-json">')[1].split("</script>")[0])
    assert [(f["properties"]["row"], f["properties"]["past"]) for f in d["cleaning"]["features"]] == [("c20260917", True), ("c20261126", False)]
    assert [f["properties"]["row"] for f in d["reports"]["features"]] == ["r1"] and d["reports"]["features"][0]["properties"]["o"] == "vyreseno"
    assert [(x["row"], x["traffic"]) for x in d["marks"]] == [("dm0", False)] and [a["row"] for a in d["anchors"]] == ["c20260917", "c20261126"]
    assert d["street"]["type"] == "LineString"
    assert get("/verejny-prostor/ulice/neni").status_code == 404


def test_street_page_rows_beyond_the_first(fixture, monkeypatch):
    many = [rep(100 + i, 3, NOW - dt.timedelta(days=i % 20)) for i in range(25)]
    monkeypatch.setattr(q, "street_reports", lambda obvod, name: many if name == "Wolkerova" else [])
    m = get("/verejny-prostor/ulice/wolkerova").text
    assert m.count("<li data-row=") == q.ROWS                                    # only what is current, capped
    assert f'aria-current="true">Aktuální <b>{q.ROWS}</b></a>' in m and '<a href="/verejny-prostor/ulice/wolkerova?radky=vse#aktualne">Vše <b>' in m
    m = get("/verejny-prostor/ulice/wolkerova?radky=vse").text
    assert m.count("<li data-row=") > q.ROWS and 'aria-current="true">Vše <b>' in m
    m = get("/verejny-prostor/ulice/lexova").text                               # nothing reported or decided
    assert "Přes Dej Tip tu zatím nikdo nic nenahlásil." in m and "Žádné usnesení od roku 2018 ulici nezmiňuje." in m
    assert "Blokově se tu letos nečistí" in m and "Ulice není v letošním harmonogramu" in m


def test_cleaning_of_a_street_outside_the_obvod(fixture, monkeypatch):
    # in the harmonogram but not one of the obvod's streets: a page with only its cleaning
    monkeypatch.setattr(st, "streets", lambda obvod: {s.slug: s for s in STREETS if s.slug != "josefa-ressla"})
    r = get("/verejny-prostor/ulice/josefa-ressla")
    assert r.status_code == 200
    for s in ("<h1>Josefa Ressla</h1>", '<section class="ul-cl" id="cisteni"', "do kalendáře", "Odkud to víme", "cl-sign"):
        assert s in r.text, s
    assert "Aktuálně" not in r.text and get("/verejny-prostor/ulice/neni").status_code == 404


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


def test_current_rows():
    today = dt.date(2026, 11, 13)
    r = lambda kind, d, st=("vyřešeno", "st"): {"kind": kind, "date": d, "status": st}
    rows = [r("cl", dt.date(2026, 11, 26)), r("cl", dt.date(2026, 9, 17)), r("rep", dt.date(2025, 4, 10), ("evidováno", "st st-no")),
            r("rep", dt.date(2026, 6, 1)), r("res", dt.date(2026, 9, 23)), r("month", dt.date(2026, 10, 2))]
    got = q.current(rows, today)
    assert [x["date"] for x in got] == [dt.date(2026, 11, 26)]          # the last 30 days and what is to come
    got = q.current(rows + [r("rep", dt.date(2026, 10, 20))], today)
    assert [x["date"] for x in got] == [dt.date(2026, 11, 26), dt.date(2026, 10, 20)]
    waiting = {**r("rep", dt.date(2025, 4, 10), ("evidováno", "st st-no")), "open": True}
    assert q.current(rows + [waiting], today)[-1] is waiting          # a report still waiting is current, however old


def test_street_tiles_open_by_detail(fixture, monkeypatch):
    m = get("/verejny-prostor/ulice/wolkerova", params={"detail": "usneseni"}).text
    assert 'data-pd-tile="usneseni" aria-controls="ul-panel" aria-expanded="true"' in m
    assert '<section data-pd-detail="usneseni" aria-label="Usnesení po letech">' in m
    assert '<section data-pd-detail="cisteni" aria-label="Příští blokové čištění" hidden>' in m
    assert 'href="?detail=zadny#prehled" data-pd-tile="usneseni"' in m          # the open tile closes itself
    m = get("/verejny-prostor/ulice/wolkerova", params={"detail": "nesmysl"}).text
    assert 'data-pd-tile="cisteni" aria-controls="ul-panel" aria-expanded="true"' in m
    monkeypatch.setattr(q, "street_reports", lambda obvod, name: [])
    m = get("/verejny-prostor/ulice/lexova").text                               # nothing reported or decided
    assert "<b>letos bez čištění</b><span>ulice není v harmonogramu</span>" in m and "<b>žádné</b><span>podněty z Dej Tipu</span>" in m and "<b>žádné usnesení</b><span>rady a zastupitelstva od roku 2018</span>" in m


def test_street_report_views(fixture, monkeypatch):
    rs = [rep(1, 1, NOW - dt.timedelta(days=200)), rep(2, 3, NOW - dt.timedelta(days=3)), rep(3, 3, NOW - dt.timedelta(days=400))]
    monkeypatch.setattr(q, "street_reports", lambda obvod, name: rs if name == "Wolkerova" else [])
    m = get("/verejny-prostor/ulice/wolkerova", params={"radky": "ceka"}).text
    rows = __import__("re").findall(r'<li data-row="([^"]+)"', m)
    assert 'aria-current="true">Čekající podněty <b>' in m and rows and all(k.startswith("r") for k in rows)
    assert '<a href="/verejny-prostor/ulice/wolkerova?radky=ceka#aktualne">Čekající</a>' in m      # the panel filters this map
    assert get("/verejny-prostor/ulice/wolkerova", params={"radky": "nesmysl"}).status_code == 200
