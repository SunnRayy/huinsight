"""ContextBuilder opens the DB read-only and releases it on close().

Regression: it opened read-write, so on a server with concurrent read-only
requests (the AI Advisor page loads several at once) DuckDB refused it with
"different configuration than existing connections" and the context preview
returned 500 — seen on a fresh demo install, 2026-10-24.
"""

import duckdb
import pytest

from src.database.connector import DatabaseConnector
from src.services.ai_advisor.context_builder import ContextBuilder


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "ctx.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (x INTEGER)")
    con.close()
    monkeypatch.setenv("UIS_DB_PATH", str(path))
    return str(path)


def test_builds_while_another_read_only_connection_is_open(db_file):
    concurrent_reader = DatabaseConnector(db_file, read_only=True)
    try:
        cb = ContextBuilder()  # raised ConnectionException when it opened read-write
        try:
            assert cb._db.read_only is True
        finally:
            cb.close()
    finally:
        concurrent_reader.close()


def test_close_lets_a_writer_open_afterwards(db_file):
    cb = ContextBuilder()
    cb.close()
    writer = DatabaseConnector(db_file)  # read-write; fails if cb still held a read-only handle
    try:
        writer.execute("INSERT INTO t VALUES (1)")
    finally:
        writer.close()


def test_close_is_safe_without_init():
    cb = ContextBuilder.__new__(ContextBuilder)  # tests build it this way, no _db
    cb.close()
