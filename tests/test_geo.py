from petka.usneseni.geo import parse_parcel


def test_parcel_kinds_and_ku():
    assert parse_parcel("p. p. č. 2515/14, k. ú. Pardubice", "pardubice") == {
        "ku": "pardubice", "druh": 2, "numbers": [(2515, 14)], "ku_inferred": False}
    p = parse_parcel("st. p. č. 3815", "pardubice")
    assert (p["druh"], p["numbers"], p["ku_inferred"]) == (1, [(3815, None)], True)


def test_parcel_lists_and_ocr_slips():
    p = parse_parcel("č. parc. st. 10089 a 10090, k. ú. Dražkovice", "pardubice")
    assert (p["ku"], p["druh"], p["numbers"]) == ("drazkovice", 1, [(10089, None), (10090, None)])
    p = parse_parcel("p. č. l2047", "pardubice")   # "l" for "1"; kind unknown -> tried both
    assert (p["druh"], p["numbers"]) == (None, [(12047, None)])
