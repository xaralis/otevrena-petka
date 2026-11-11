"""Rozpočet: parsing the GORDIC Excel exports. The workbooks are built here in the layout of
the real exports (checked on MO V 2018, 2022 and 2026 on 11. 11. 2026): texts in column D,
invoice descriptions in G, amounts in J, skupiny bold."""

import datetime as dt
import io

import openpyxl
import pytest
from openpyxl.styles import Font

from petka.rozpocet import jobs, source

HEAD = [{"B": "Statutární město Pardubice | Rozpočet na rok 2026"}, {"I": "Stav ke dni 11.11.2026"}]


def xlsx(rows: list[dict], bold: frozenset[int] | set[int] = frozenset()) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for i, row in enumerate(HEAD + rows, 1):
        for col, v in row.items():
            c = ws[f"{col}{i}"]
            c.value = v
            if i - len(HEAD) - 1 in bold:
                c.font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


FAKTURY = [
    {"D": "SKUPINA / PARAGRAF / POLOŽKA", "G": "DOKLAD", "J": "PROFINANCOVÁNO"},
    {"D": "2 - Průmyslová a ostatní odvětví hospodářství", "J": 110.5},          # 1
    {"D": "2212 - Silnice"},
    {"D": "5171 - Opravy a udržování"},
    {"G": "oprava komunikací  po zimě", "J": 100.0},
    {"G": "obnova VDZ", "J": 10.5},
    {"D": "6 - Všeobecná veřejná správa a služby", "J": 63.0},                   # 6
    {"D": "6171 - Činnost místní správy"},
    {"D": "5169 - Nákup ostatních služeb"},
    {"G": "BOZP", "J": 3.0},
    {"J": 28.65},                                                                # no description
    {"D": "6121 - Stavby"},                                                      # položka, not paragraf
    {"G": "PD k akci", "J": 31.35},
]
ITEMS = {(5171, "Opravy a udržování"), (5169, "Nákup ostatních služeb"), (6121, "Stavby")}


def test_faktury_flattened_with_classification():
    rows = source.parse_faktury(xlsx(FAKTURY, bold={1, 6}), ITEMS)
    assert [(r["group"], r["paragraph"], r["item"], r["amount"]) for r in rows] == [
        (2, 2212, 5171, 100.0), (2, 2212, 5171, 10.5),
        (6, 6171, 5169, 3.0), (6, 6171, 5169, 28.65), (6, 6171, 6121, 31.35)]
    assert rows[0]["description"] == "oprava komunikací po zimě"     # whitespace collapsed
    assert rows[3]["description"] == ""
    assert rows[4]["paragraph_name"] == "Činnost místní správy" and rows[4]["item_name"] == "Stavby"


def test_faktury_totals_must_match():
    bad = [dict(r) for r in FAKTURY]
    bad[1]["J"] = 111.0
    with pytest.raises(ValueError, match="skupina 2"):
        source.parse_faktury(xlsx(bad, bold={1, 6}), ITEMS)


def test_faktury_unknown_item_after_paragraf_is_an_error():
    # 5171 missing from the položky of 0018 would make it a second paragraf in a row
    with pytest.raises(ValueError, match="not a položka"):
        source.parse_faktury(xlsx(FAKTURY, bold={1, 6}), ITEMS - {(5171, "Opravy a udržování")})


def test_odvetvi_and_rekapitulace():
    od = xlsx([{"F": "ODVĚTVÍ", "N": "ROZPOČET\nSCHVÁLENÝ"},
               {"F": "Doprava", "N": 24170.0, "Q": 28538.0, "R": 10785.69, "Y": 37.79},
               {"F": "Kultura", "N": 2814.92, "Q": 3161.66, "R": 2059.73, "Y": 65.15},
               {"F": "CELKEM", "N": 26984.92, "Q": 31699.66, "R": 12845.42, "Y": "40.52"}])
    assert source.parse_odvetvi(od)[1] == {"sector": "Kultura", "approved": 2814.92,
                                           "revised": 3161.66, "actual": 2059.73}
    assert source.as_of(source.rows(od)) == dt.date(2026, 11, 11)
    rek = xlsx([{"G": "Příjmy", "H": 74243.1, "I": 76828.56, "J": 62570.35, "K": 81.44},
                {"G": "Výdaje", "H": 100169.71, "I": 115757.55, "J": 55187.2, "K": 47.67},
                {"G": "Financování", "H": 25926.62, "I": 38929.0, "J": -11.65, "K": -0.03}])
    assert [r["kind"] for r in source.parse_rekapitulace(rek)] == ["prijmy", "vydaje", "financovani"]


def test_report_url_uses_the_district_code():
    assert "Ico=05274046&Rok=2026" in source.report_url("faktury", "mo5", 2026)
    assert source.report_url("odvetvi", "mmp", 2025).endswith("&Odpa=(1=1)")


def test_content_hash_ignores_order_of_keys():
    assert jobs.content_hash({"a": 1, "b": [1]}) == jobs.content_hash({"b": [1], "a": 1})


# years_to_refresh: what any reasonable rule must do
TODAY = dt.date(2026, 11, 11)


def test_refresh_first_run_takes_everything():
    assert jobs.years_to_refresh(TODAY, {}) == list(range(2018, 2027))


def test_refresh_always_takes_current_year():
    # every past year downloaded after its books closed (yesterday), the current one too
    known = {y: dt.date(2026, 11, 10) for y in range(2018, 2027)}
    assert jobs.years_to_refresh(TODAY, known) == [2026]


def test_refresh_keeps_past_year_until_after_june():
    known = {y: dt.date(2026, 11, 10) for y in range(2018, 2027)} | {2025: dt.date(2026, 6, 30)}
    assert jobs.years_to_refresh(TODAY, known) == [2025, 2026]


def test_refresh_takes_last_year_while_books_are_open():
    known = {y: dt.date(y + 1, 3, 14) for y in range(2018, 2025)} | {2025: dt.date(2026, 1, 20),
                                                                     2026: dt.date(2026, 1, 20)}
    assert 2025 in jobs.years_to_refresh(dt.date(2026, 1, 21), known)


ODBORY = [
    {"E": "ODBOR \\ ODPA \\ POL", "N": "ROZPOČET\nSCHVÁLENÝ"},
    {"N": 11.0, "Q": 11.0, "S": 5.0},                                     # 1 odbor, no name
    {"E": "Činnosti knihovnické", "N": 10.0, "Q": 10.0, "S": 5.0},
    {"E": "Knihy a obdobné listinné informační prostředky", "N": 4.0, "Q": 4.0, "S": 2.0},
    {"E": "Nájemné", "N": 6.0, "Q": 6.0, "S": 3.0},
    {"E": "Divadelní činnost", "N": 1.0, "Q": 1.0, "S": 0.0},              # next paragraf
    {"E": "Nájemné", "N": 1.0, "Q": 1.0, "S": 0.0},
    {"E": "sociální fond", "N": 2.0, "Q": 2.0, "S": 1.0},                  # 7 odbor
    {"E": "Činnost místní správy", "N": 2.0, "Q": 2.0, "S": 1.0},
    {"E": "Ostatní neinvestiční transfery fyzickým osobám", "N": 2.0, "Q": 2.0, "S": 1.0},
]


def test_odbory_tree_from_sums():
    rows = source.parse_odbory(xlsx(ODBORY, bold={1, 7}))
    assert [(r["department"], r["paragraph_name"], r["item_name"], r["actual"]) for r in rows] == [
        (None, "Činnosti knihovnické", "Knihy a obdobné listinné informační prostředky", 2.0),
        (None, "Činnosti knihovnické", "Nájemné", 3.0),
        (None, "Divadelní činnost", "Nájemné", 0.0),
        ("sociální fond", "Činnost místní správy", "Ostatní neinvestiční transfery fyzickým osobám", 1.0)]


def test_odbory_items_must_add_up():
    bad = [dict(r) for r in ODBORY]
    bad[4]["S"] = 2.0                                  # knihovna's položky no longer reach 5.0
    with pytest.raises(ValueError):
        source.parse_odbory(xlsx(bad, bold={1, 7}))


def test_code_for_names_as_gordic_writes_them():
    assert source.code_for("Mateřské školy", "paragraf", 2026) == 3111          # exact beats 3112
    assert source.code_for("Sběr a svoz ost. odpadů jiných než nebez. a komun.", "paragraf", 2026) == 3723
    assert source.code_for("Programové vybavení", "polozka", 2026) == 6111
    assert source.code_for("úroky", "paragraf", 2026) is None


# --- pages: grouping into oblasti, the preview's token ------------------------------------

from petka.rozpocet import names, queries


def test_group_oblasti_small_ones_go_to_ostatni():
    cur = {"6171": (26602, 17677, "Činnost místní správy"), "2219": (20915, 7331, "x"),
           "3745": (18763, 9684, "y"), "5512": (15, 15, "z"), "odvod": (8026, 7093, "Úroky z vklad. účtu")}
    prev = {"6171": (24408, 22228, ""), "2219": (30906, 0, ""), "3745": (16111, 0, ""), "6114": (725, 706, "")}
    groups, axis = queries.group(cur, prev, "plan")
    assert [g["name"] for g in groups] == ["Chod úřadu a zastupitelstvo", "Silnice a chodníky", "Zeleň a odpady",
                                           "Odvod a převody městu", "Ostatní"]
    assert groups[-1]["rows"][0]["label"] == "Dobrovolní hasiči"
    assert groups[0]["plan_label"] == "26,6"
    # the change view lists what had a plan last year only, sorted by the change
    groups, axis = queries.group(cur, prev, "zmena")
    assert groups[0]["name"] == "Odvod a převody městu" and groups[0]["d_label"] == "+8,0"
    road = next(g for g in groups if g["name"] == "Silnice a chodníky")
    assert road["tone"] == "down" and road["d_label"] == "−10,0"
    assert any(r["code"] == "6114" for g in groups for r in g["rows"])
    assert axis["ticks"][0]["label"] == "0" and axis["top"] >= 30906


def test_names_and_formatting():
    assert names.key("6330") == names.key("odvod") == "odvod" and names.key("3745") == "37"
    assert queries.mil(115757.55) == "115,8" and queries.tis(12927.8) == "12 928"
    assert queries.describe('akce " Chodníky ul. U Krematoria"') == "Akce Chodníky ul. U Krematoria"


def test_preview_needs_the_token(monkeypatch):
    from fastapi import HTTPException
    from petka.rozpocet import web
    monkeypatch.setenv("ROZPOCET_NAHLED_TOKEN", "a" * 24)
    assert web._check("a" * 24) == "/rozpocet/nahled/" + "a" * 24
    for bad in ("", "b" * 24, "a" * 23):
        with pytest.raises(HTTPException):
            web._check(bad)
    monkeypatch.setenv("ROZPOCET_NAHLED_TOKEN", "")
    with pytest.raises(HTTPException):          # no token configured: the preview doesn't exist
        web._check("")


def test_group_share_of_whole_budget():
    groups, _ = queries.group({"6171": (300, 100, ""), "2219": (700, 0, "")}, {}, "plan")
    assert [(g["name"], g["share"], g["pct"]) for g in groups] == [("Silnice a chodníky", 70, 0),
                                                                  ("Chod úřadu a zastupitelstvo", 30, 33)]
