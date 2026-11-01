"""Request read paths stay READ-ONLY (2026-06-24 lockout rule) and never mix modes with each other."""
from concurrent.futures import ThreadPoolExecutor

import duckdb
import pytest

from src.database.connector import (
    DatabaseConnector, connect_read_connection, connect_readonly_with_retry,
)


def _db(tmp_path, name='modes.duckdb'):
    path = str(tmp_path / name)
    with DatabaseConnector(path) as db:
        db.execute('CREATE TABLE sample AS SELECT 42 AS value')
        db.execute("CREATE TABLE user_profile AS SELECT 1 AS id, 'Synthetic' AS display_name, "
                   "NULL::VARCHAR AS avatar_base64, '{}' AS philosophy, 'en' AS language")
    return path


def test_duckdb_rejects_mixed_modes(tmp_path):
    path = str(tmp_path / 'raw.duckdb')
    with duckdb.connect(path):
        with pytest.raises(duckdb.ConnectionException, match='different configuration'):
            duckdb.connect(path, read_only=True)


def test_read_helpers_open_read_only(tmp_path):
    path = _db(tmp_path)
    with connect_readonly_with_retry(path) as db:
        with pytest.raises(Exception):
            db.execute('CREATE TABLE should_fail (x INT)')
    raw = connect_read_connection(path)
    try:
        with pytest.raises(Exception):
            raw.execute('CREATE TABLE should_fail (x INT)')
    finally:
        raw.close()


def test_concurrent_request_reads_coexist(tmp_path):
    path = _db(tmp_path)

    def request():
        with connect_readonly_with_retry(path) as db:
            return db.execute('SELECT value FROM sample').fetchone()[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda _: request(), range(16))) == [42] * 16


def test_profile_read_does_not_fall_back_while_a_request_read_is_open(tmp_path, monkeypatch):
    """Regression: get_profile used a read-WRITE connection, which DuckDB refuses while a
    read-only request connection is open ("different configuration") → "Set your name"."""
    from src.services.settings_manager import get_profile
    path = _db(tmp_path, 'profile.duckdb')
    monkeypatch.setenv('UIS_DB_PATH', path)
    with connect_readonly_with_retry(path):
        assert get_profile()['display_name'] == 'Synthetic'
