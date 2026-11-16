"""Můj přehled (petka.ulice.feed and its page): the events of chosen streets, the RSS, the page
without JS, its preview and the old calendar page that moved there. Sources are fakes, no database."""

import datetime as dt
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from petka.ulice import feed, streets as st, web
from petka.web.app import app
from test_ulice import STREETS, item, rep

NOW = dt.datetime.now(feed.TZ).replace(microsecond=0)
ago = lambda days: (NOW - dt.timedelta(days=days)).replace(tzinfo=None)


def sources():
    reps = [rep(1, 1, ago(3), "Autovrak"), rep(2, 1, ago(200), "Chodník"),
            {**rep(3, 3, ago(40), "Lavičky, zábradlí"), "resolved_seen_at": ago(10)},
            rep(4, 1, ago(5), "Zeleň", street="Lexova")]
    notices = [{"id": 77, "published": ago(4).date(), "title": "VV - OOP stanovení přechodné úpravy provozu", "card": "Uzavírka chodníku"}]
    res = [{"uid": "310-2026-r", "number": "310/2026 R", "body": "rmo", "date": ago(50).date(), "title": "Oprava asfaltu", "agenda_title": None}]
    cleanings = [item((NOW + dt.timedelta(days=3)).date()), item((NOW + dt.timedelta(days=30)).date())]
    return feed.Sources(reports=lambda name: [r for r in reps if r["street"] == name],
                        notices=lambda name, since: notices if name == "Wolkerova" else [],
                        resolutions=lambda name: res if name == "Wolkerova" else [],
                        cleanings=lambda name: [i for i in cleanings if i["street"] == name])


def test_events_of_streets_newest_first():
    evs = feed.events([("Wolkerova", "wolkerova"), ("Lexova", "lexova")], sources(), NOW)
    # the cleaning in 3 days shows up a week before it, at 18:00
    assert [e.kind for e in evs] == ["podnet", "cisteni", "deska", "podnet", "vyreseno", "podnet", "usneseni"]
    assert evs[0].status == ("čeká", "st-no") and evs[0].head == "Autovrak"
    assert evs[1].sub.startswith("Wolkerova, ") and evs[1].status[1] == ""      # still to come
    assert evs[2].sub == "Wolkerova, Uzavírka chodníku"
    assert not any(e.key == "podnet-2" for e in evs)          # older than the window
    assert sum(e.kind == "cisteni" for e in evs) == 1          # the one a month ahead: not yet


def test_events_of_chosen_kinds_and_dedup():
    evs = feed.events([("Wolkerova", "wolkerova"), ("Wolkerova", "wolkerova")], sources(), NOW, {"deska", "usneseni"})
    assert [e.kind for e in evs] == ["deska", "usneseni"]


def test_rss_is_valid_xml():
    evs = feed.events([("Wolkerova", "wolkerova")], sources(), NOW)
    xml = feed.rss(evs, ["Wolkerova"], "https://otevrenapetka.cz", "https://otevrenapetka.cz/muj-prehled/rss.xml?ulice=wolkerova")
    ch = ET.fromstring(xml).find("channel")
    assert ch.findtext("title") == "Otevřená Pětka – Wolkerova"
    assert len(ch.findall("item")) == len(evs)
    assert ch.find("item/link").text.startswith("https://")


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(st, "streets", lambda obvod: {s.slug: s for s in STREETS})
    monkeypatch.setattr(web, "_sources", lambda obvod: sources())


def get(path, **kw):
    return TestClient(app).get(path, headers={"host": "otevrenapetka.cz"}, follow_redirects=False, **kw)


def test_page_empty(page):
    r = get("/muj-prehled")
    assert r.status_code == 200 and "<h1>Můj přehled</h1>" in r.text
    assert "Nejdřív vyberte aspoň jednu ulici." in r.text and 'data-up-ways hidden' in r.text


def test_page_without_js_adds_and_drops(page):
    r = get("/muj-prehled", params=[("ulice", "wolkerova"), ("ulice", "lexova"), ("pridat", "Josefa Ressla"), ("odebrat", "lexova")])
    assert 'value="wolkerova"' in r.text and 'value="josefa-ressla"' in r.text and 'name="ulice" value="lexova"' not in r.text
    assert 'aria-label="Odebrat Wolkerova"' in r.text
    assert "webcal://otevrenapetka.cz/verejny-prostor/blokove-cisteni/kalendar.ics?ulice=wolkerova,josefa-ressla" in r.text
    assert 'data-copy="https://otevrenapetka.cz/muj-prehled/rss.xml?ulice=wolkerova,josefa-ressla"' in r.text
    assert "Uzavírka chodníku" in r.text and "Oprava asfaltu" not in r.text    # 50 days back: counted, not previewed
    r = get("/muj-prehled", params={"pridat": "Neexistující"})
    assert "Ulici „Neexistující“ v obvodu nemáme" in r.text


def test_preview_json(page):
    out = get("/muj-prehled/nahled.json", params={"ulice": "wolkerova", "co": "podnety,deska"}).json()
    assert out["counts"] == {"podnety": 3, "deska": 1, "usneseni": 1, "cisteni": 1}   # filed 40 days back and resolved 10: two
    assert [r["head"] for r in out["rows"]] == ["Autovrak", "Úřední deska", "Lavičky, zábradlí"]
    assert out["feed"].endswith("rss.xml?ulice=wolkerova&co=podnety,deska")
    assert out["webcal"].startswith("webcal://")


def test_rss_route(page):
    assert get("/muj-prehled/rss.xml").status_code == 404
    r = get("/muj-prehled/rss.xml", params={"ulice": "wolkerova", "co": "deska"})
    assert r.headers["content-type"].startswith("application/rss+xml")
    assert [i.findtext("category") for i in ET.fromstring(r.text).iter("item")] == ["deska"]


def test_my_overview_is_a_top_level_item(page):
    h = get("/muj-prehled").text.split("</header>")[0]
    assert '<a href="/muj-prehled" aria-current="true">Můj přehled</a>' in h
    r = get("/zapojte-se/upozorneni", params={"ulice": "wolkerova"})     # where it was for a day
    assert r.status_code == 301 and r.headers["location"] == "/muj-prehled?ulice=wolkerova"


# --- notifications (petka.ulice.push) --------------------------------------------------------

def test_messages_one_each_or_a_summary():
    from petka.ulice import push
    evs = feed.events([("Wolkerova", "wolkerova")], sources(), NOW)
    one = push.messages(evs[:2], ["Wolkerova"], "https://p.cz", "/muj-prehled?ulice=wolkerova")
    assert [m["tag"] for m in one] == [evs[1].key, evs[0].key]           # older first: the newest ends on top
    assert one[1]["url"] == evs[0].path and evs[0].path.startswith("https://")     # a report: its Dej Tip page
    many = push.messages(evs[:5], ["Wolkerova"], "https://p.cz", "/muj-prehled?ulice=wolkerova")
    assert len(many) == 1 and many[0]["title"] == "5 novinek v ulici Wolkerova"
    assert push.messages(evs[:4], ["Wolkerova", "Lexova"], "https://p.cz", "/")[0]["title"] == "4 novinky ve vašich ulicích"


def test_push_subscribe_and_deliver():
    import uuid

    from petka import db
    from petka.ulice import push
    try:
        db.migrate()
    except Exception:
        pytest.skip("no local database")
    extra = []
    base = sources()
    src = feed.Sources(reports=lambda name: base.reports(name) + [r for r in extra if r["street"] == name],
                       notices=base.notices, resolutions=base.resolutions, cleanings=base.cleanings)
    sent, gone = [], set()

    def send(info, msg):
        if info["endpoint"] in gone:
            raise push.Gone
        sent.append((info["endpoint"], msg))
    ep = f"https://push.example/{uuid.uuid4()}"
    sub = {"endpoint": ep, "keys": {"p256dh": "k", "auth": "a"}}
    names = lambda obvod: {s.slug: s.name for s in STREETS}
    with db.connect() as conn, conn.transaction(force_rollback=True):
        deliver = lambda: push.deliver(conn, send, lambda o: src, names, "https://p.cz", NOW)
        if True:
            conn.execute("DELETE FROM push_subscriptions")        # rolled back: the test sees only its own
            push.save(conn, sub, "mo5", [("Wolkerova", "wolkerova")], ["podnety", "deska"], src, NOW)
            assert deliver()["messages"] == 0                    # what was there before: never sent
            extra.append(rep(90, 1, ago(0), "Autovrak"))
            assert deliver()["messages"] == 1 and sent[-1][1]["title"] == "Wolkerova: nový podnět – Autovrak"
            assert deliver()["messages"] == 0                    # once only
            extra.extend(rep(91 + i, 1, ago(0), "Zeleň") for i in range(4))
            deliver()
            assert sent[-1][1]["title"] == "4 novinky v ulici Wolkerova"
            push.save(conn, sub, "mo5", [("Wolkerova", "wolkerova"), ("Lexova", "lexova")], ["podnety"], src, NOW)
            assert deliver()["messages"] == 0                    # a new street's past: not sent either
            new = {"endpoint": ep + "-2", "keys": {"p256dh": "k2", "auth": "a2"}}
            assert push.renew(conn, ep, new)
            gone.add(new["endpoint"])
            extra.append(rep(99, 1, ago(0), "Chodník"))
            assert deliver()["gone"] == 1
            assert not conn.execute("SELECT 1 FROM push_subscriptions WHERE endpoint LIKE %s", (ep + "%",)).fetchall()


def test_subscribe_route_checks_input(page):
    c = TestClient(app)
    assert c.post("/muj-prehled/odber", json={"subscription": {"endpoint": "http://x", "keys": {}}, "ulice": ["wolkerova"]}).status_code == 400
    ok = {"endpoint": "https://push.example/1", "keys": {"p256dh": "k", "auth": "a"}}
    assert c.post("/muj-prehled/odber", json={"subscription": ok, "ulice": ["neni"]}).status_code == 400
