"""The tests' database is their own: the schema `petka_test` of the local database (or
TEST_DATABASE_URL), emptied and migrated once per run, so tests never touch the data a dev server
shows. Without a database (CI) the pool fails at once instead of waiting 30 s per query, so the
pages that fall back don't make the suite take minutes; tests that need the database skip
themselves ("no local database")."""

import os
from urllib.parse import quote

SCHEMA = "petka_test"
_base = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "postgresql:///usneseni")
# every connection of the run (pool, jobs, migrations) reads petka.db.URL: set before importing it
os.environ["DATABASE_URL"] = _base + ("&" if "?" in _base else "?") + "options=" + quote(f"-csearch_path={SCHEMA},public")

import psycopg  # noqa: E402
import pytest  # noqa: E402

from petka import db  # noqa: E402


def _reachable() -> bool:
    try:
        psycopg.connect(_base, connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True, scope="session")
def _own_database():
    if _reachable():
        with psycopg.connect(_base, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
            conn.execute(f"CREATE SCHEMA {SCHEMA}")
        db.migrate()
        yield
        return

    def unavailable():
        raise psycopg.OperationalError("no database (tests)")
    original, db.pool = db.pool, unavailable
    yield
    db.pool = original
