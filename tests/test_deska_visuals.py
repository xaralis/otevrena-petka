from petka.uredni_deska import parking, photo


def test_parking_schema_marks_only_what_changed():
    spec = {"street": "Bartoňova", "kind": "kolme", "evidence": "výkres: 4 + 1 + 3 stání",
            "before": [{"type": "bezne", "n": 4, "label": None}, {"type": "ztp", "n": 1, "label": None},
                       {"type": "bezne", "n": 3, "label": None}],
            "after": [{"type": "bezne", "n": 4, "label": None}, {"type": "kratkodobe", "n": 1, "label": "max. 30 min"},
                      {"type": "bezne", "n": 3, "label": None}]}
    assert parking.changed(spec["before"], spec["after"]) == {1}
    svg = parking.svg(spec)
    assert svg.startswith("<svg") and svg.count('stroke-dasharray="6 4"') == 1
    assert "krátkodobé stání" in svg and "max. 30 min" in svg and "Bartoňova" in svg


def test_new_signs_on_one_post_share_a_panel():
    marks = [{"action": "nova", "code": "IP13b", "text": None, "x": .40, "y": .30},
             {"action": "nova", "code": "E13", "text": "MAX. 30 min", "x": .41, "y": .36},
             {"action": "nova", "code": "B29", "text": None, "x": .80, "y": .30}]
    assert [len(g) for g in photo._groups(marks)] == [2, 1]


def test_bearing_and_distance():
    a, b = (15.8089, 50.0420), (15.8089, 50.0423)
    assert abs(photo._bearing(a, b)) < 1 or abs(photo._bearing(a, b) - 360) < 1     # due north
    assert 30 < photo._dist(a, b) < 36
