"""Shared fixtures.

Most of this suite (test_analysis_engine, test_domain, test_scanner,
test_sentiment_engine) is pure functions and needs nothing here. A handful
of tests exercise the real Postgres schema end-to-end (the analysis-job
worker actually writing/reading rows) because that plumbing is exactly the
part most likely to break in a way pure unit tests can't catch -- a wrong
column name or a bad state transition only shows up against a real
database. Those tests are skipped, not failed, when no database is
reachable (e.g. `docker compose up -d` hasn't been run locally) so the fast
unit tests still run anywhere.
"""

import psycopg2
import pytest

from config import get_settings
from database import init_db
from migrations import run_migrations


@pytest.fixture(scope="session")
def postgres_available() -> bool:
    try:
        with psycopg2.connect(get_settings().postgres_url, connect_timeout=2):
            return True
    except psycopg2.Error:
        return False


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(postgres_available):
    if postgres_available:
        init_db()
        run_migrations()


@pytest.fixture
def require_postgres(postgres_available):
    if not postgres_available:
        pytest.skip("No reachable Postgres (run `docker compose up -d`) -- skipping DB-backed test.")
