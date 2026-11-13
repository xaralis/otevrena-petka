"""Traffic orders on the úřední deska read for the front page's map (petka.uredni_deska.measures):
validity, reason, signs and the one human line, over the parts of real orders of the Magistrát
(posted on the MO V board 4.–10. 11. 2026) that carry them; applicants, officials and contacts
cut out. And which of the obvod's streets a notice's title names."""

import datetime as dt
from pathlib import Path

import pytest

from petka.uredni_deska import measures as m

FIX = Path(__file__).parent / "fixtures" / "uredni_deska" / "opatreni"
D = dt.date


def text(nid):
    return (FIX / f"{nid}.txt").read_text()


@pytest.mark.parametrize("nid, valid, reason, what", [
    ("mo5-15700", (D(2026, 11, 16), D(2026, 12, 16)), "stavební práce", "Uzavřená stezka kvůli stavebním pracím"),
    ("mo5-15699", (D(2026, 11, 14), D(2026, 12, 20)), "stavební práce", "Zábrany na chodníku kvůli stavebním pracím"),
    ("mo5-15711", (D(2026, 11, 15), D(2028, 8, 31)), "stavební práce",
     "Na parkovišti zákaz zastavení v úseku 20 m kvůli stavebním pracím"),
    # the towing days on the continuation lines are inside the validity; "206" is a typo, ignored
    ("mo5-15630", (D(2026, 11, 20), D(2027, 1, 7)), "kulturní akce", "Zákaz vjezdu a zastavení kvůli kulturní akci"),
    ("mo5-15627", (D(2026, 10, 31), D(2027, 10, 30)), "BESIP", "Dočasný přechod pro chodce"),
    ("mo5-15628", (D(2026, 11, 3), D(2026, 12, 11)), "stavební práce", "Zábrany kvůli stavebním pracím"),
    ("mo5-15626", (D(2026, 11, 5), D(2026, 11, 11)), "stavební práce",
     "Zákaz zastavení a uzavřený chodník kvůli stavebním pracím"),
    ("mo5-15629", (D(2026, 11, 9), D(2028, 12, 15)), "stavební práce", "Pohyb vozidel stavby kvůli stavebním pracím"),
    # a substitute date on the next line extends the validity
    ("mo5-15622", (D(2026, 10, 31), D(2026, 11, 8)), "kontrola stavu nadjezdu, drobné opravy",
     "Práce na silnici a provoz řízený semafory kvůli kontrole stavu nadjezdu"),
    # another office's layout: "Termín: od 8:00 hod. 9. 11. 2026 do 16:00 hod. 13. 11. 2026", signs listed with words
    ("mo5-15625", (D(2026, 11, 9), D(2026, 11, 13)), None,
     "Úplná uzavírka a zákaz zastavení kvůli opravě nájezdu zvýšené křižovatky"),
    # the regional office: "Termín:" with the date on the next line, "Důvod přechodné úpravy:"
    ("mo5-15623", (D(2026, 10, 28), D(2026, 10, 31)), "oprava vozovky", "Přechodná úprava provozu kvůli opravě vozovky"),
])
def test_read_orders(nid, valid, reason, what):
    r = m.read(text(nid))
    assert (r["valid_from"], r["valid_to"]) == valid
    if reason:
        assert r["reason"] == reason
    assert r["what"] == what


def test_signs_in_order_once():
    assert m.signs(text("mo5-15630")) == ["IZ8a", "B29", "B28", "E13", "E8c", "B1", "Z2"]
    assert m.signs(text("mo5-15700")) == ["Z2", "E13"]          # not TP66 or B/17
    assert m.signs(text("mo5-15625"))[:3] == ["B28", "E13", "E8a"]


def test_nothing_to_read():
    assert m.read("Oznámení bez obvyklých řádků.") == {"valid_from": None, "valid_to": None, "reason": None,
                                                       "signs": [], "what": "Přechodná úprava provozu"}


def test_because():
    assert m.because("stavební práce") == "kvůli stavebním pracím"
    assert m.because("výkopové práce") == "kvůli výkopovým pracím"
    assert m.because("umístění kabelového vedení") == "kvůli umístění kabelového vedení"
    assert m.because("BESIP") == ""
    assert m.because("dopravní značení v rámci projektu") == ""       # no safe dative
    assert m.what([], "", "", "dopravní značení v rámci projektu") == \
        "Přechodná úprava provozu, důvod: dopravní značení v rámci projektu"


NAMES = ["V Ráji", "Gorkého", "náměstí Dukelských hrdinů", "Dukelských hrdinů", "Češkova", "Zborovské náměstí",
         "Staňkova", "Jana Palacha", "Na Spravedlnosti"]
OOP = "VV - OOP stanovení přechodné úpravy provozu na pozemních komunikacích v Pardubicích - "


def test_streets_in_the_title():
    assert m.streets_in(OOP + "V Ráji a Gorkého", NAMES) == ["V Ráji", "Gorkého"]
    assert m.streets_in(OOP + "náměstí Dukelských hrdinů a Gorkého", NAMES) == ["náměstí Dukelských hrdinů", "Gorkého"]
    assert m.streets_in(OOP + "parkoviště Zborovské náměstí", NAMES) == ["Zborovské náměstí"]
    assert m.streets_in(OOP + "NA SPRAVEDLNOSTI", NAMES) == ["Na Spravedlnosti"]
    assert m.streets_in(OOP + "stezka Jesničánky - Dražkovice", NAMES) == []       # not a street of the obvod
    assert m.streets_in("Změna rozhodnutí - povolení stavby - chodníky Staňkova", NAMES) == ["Staňkova"]
    assert m.streets_in("Jana Palacha - zápis", NAMES) == []           # only the place part counts


def test_subject():
    t = "Změna rozhodnutí - povolení stavby - chodníky Staňkova"
    assert m.subject(t, ["Staňkova"]) == "změna rozhodnutí, povolení stavby, chodníky"
    assert m.subject("Vyrozumění - zahájení řízení - Pod Břízkami", ["Pod Břízkami"]) == "vyrozumění, zahájení řízení"
