"""Polls: one vote per install, results come back, bad input is refused."""

import uuid

import pytest
from fastapi.testclient import TestClient

from petka import db
from petka.web.app import app


@pytest.fixture
def poll():
    try:
        db.migrate()
    except Exception:
        pytest.skip("no local database")
    pid = f"test-{uuid.uuid4().hex[:8]}"
    with db.pool().connection() as conn:
        conn.execute("INSERT INTO polls (id, question, options) VALUES (%s, 'Otázka?', '[\"a\", \"b\"]')", (pid,))
    yield pid
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM polls WHERE id = %s", (pid,))


def test_one_vote_per_install(poll):
    c = TestClient(app)
    voter = str(uuid.uuid4())
    r = c.post(f"/api/v1/ankety/{poll}/hlas", json={"option": 1, "voter": voter})
    assert r.status_code == 200 and r.json()["counts"] == [0, 1] and r.json()["my_vote"] == 1
    r = c.post(f"/api/v1/ankety/{poll}/hlas", json={"option": 0, "voter": voter})
    assert r.json()["counts"] == [0, 1] and r.json()["my_vote"] == 1      # the first vote stands
    mine = [p for p in c.get("/api/v1/ankety", params={"voter": voter}).json() if p["id"] == poll][0]
    assert mine["my_vote"] == 1 and mine["total"] == 1
    other = [p for p in c.get("/api/v1/ankety").json() if p["id"] == poll][0]
    assert other["my_vote"] is None


def test_bad_votes_are_refused(poll):
    c = TestClient(app)
    voter = str(uuid.uuid4())
    assert c.post(f"/api/v1/ankety/{poll}/hlas", json={"option": 5, "voter": voter}).status_code == 422
    assert c.post(f"/api/v1/ankety/{poll}/hlas", json={"option": 0, "voter": "x"}).status_code == 422
    assert c.post("/api/v1/ankety/neni/hlas", json={"option": 0, "voter": voter}).status_code == 404
