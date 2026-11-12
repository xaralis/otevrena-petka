"""The job runner: a failing unit is rolled back and reported, the others still run; the report
keeps its shape; one alert at the end. Fake connection and client, no database or network."""

import contextlib

from petka import jobs
from petka.jobs import Unit


class FakeConn:
    def __init__(self):
        self.log = []

    def commit(self):
        self.log.append("commit")

    def rollback(self):
        self.log.append("rollback")


def _run(units, **kw):
    conn, alerts = FakeConn(), []
    report = jobs.run("fake-update", "fake", lambda c, client: units, alert=alerts.append,
                      connect=lambda: contextlib.nullcontext(conn), migrate=lambda: None,
                      http=lambda **o: contextlib.nullcontext("client"), **kw)
    return report, conn, alerts


def _fail(conn, client):
    raise RuntimeError("boom")


def test_failure_is_isolated_and_reported_once():
    seen = []
    units = [Unit(("a",), "a", lambda conn, client: seen.append(client) or {"n": 1}),
             Unit(("b",), "b", _fail),
             Unit(("c",), "c", lambda conn, client: {"n": 3})]
    report, conn, alerts = _run(units)
    assert report == {"a": {"n": 1}, "b": {"error": "boom"}, "c": {"n": 3}, "failures": ["b: boom"]}
    assert list(report) == ["a", "b", "c", "failures"]
    assert conn.log == ["commit", "rollback", "commit"]
    assert seen == ["client"]
    assert alerts == ["fake-update: b: boom"]


def test_nested_keys_and_no_alert_when_all_pass():
    units = [Unit(("mo5", 2024), "mo5 2024", lambda c, h: {"changed": True}),
             Unit(("mo5", 2025), "mo5 2025", lambda c, h: {"changed": False})]
    finished = []
    report, conn, alerts = _run(units, finish=lambda c: finished.append(c))
    assert report == {"mo5": {2024: {"changed": True}, 2025: {"changed": False}}, "failures": []}
    assert alerts == [] and finished == [conn]


def test_every_failure_in_one_alert():
    report, _, alerts = _run([Unit(("x",), "x", _fail), Unit(("y",), "y", _fail)])
    assert report["failures"] == ["x: boom", "y: boom"]
    assert alerts == ["fake-update: x: boom; y: boom"]
