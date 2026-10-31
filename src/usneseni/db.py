"""Postgres access. DATABASE_URL, e.g. postgresql://app:…@db:5432/app."""

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

URL = os.environ.get("DATABASE_URL", "postgresql:///usneseni")
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

_pool: ConnectionPool | None = None


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)


def migrate() -> None:
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name not in done:
                with conn.transaction():
                    conn.execute(f.read_text())
                    conn.execute("INSERT INTO schema_migrations VALUES (%s)", (f.name,))


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(URL, min_size=1, max_size=8, configure=_configure,
                               kwargs={"row_factory": dict_row}, open=True)
    return _pool


@contextmanager
def connect():
    """A single connection outside the pool (jobs)."""
    with psycopg.connect(URL, row_factory=dict_row) as conn:
        register_vector(conn)
        yield conn
