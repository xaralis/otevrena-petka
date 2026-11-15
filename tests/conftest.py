"""Without a database (CI), the pool fails at once instead of waiting 30 s per query, so the
pages that fall back (petka.ulice.web._safe and the like) don't make the suite take minutes;
tests that need the database skip themselves ("no local database")."""

import psycopg
import pytest

from petka import db


def _reachable() -> bool:
    try:
        psycopg.connect(db.URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True, scope="session")
def _no_waiting_for_a_missing_database():
    if _reachable():
        yield
        return

    def unavailable():
        raise psycopg.OperationalError("no database (tests)")
    original, db.pool = db.pool, unavailable
    yield
    db.pool = original
