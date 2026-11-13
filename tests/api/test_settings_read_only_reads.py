"""Settings source-health and upload-history reads must open the DB read-only.

Production (2026-10-19, V0.1.5): get_source_health opened the DB read-write
while request readers held read-only connections, so DuckDB refused with
"Can't open a connection to same database file with a different configuration
than existing connections" and the Data Sources health quietly went empty.
These tests hold a read-only connection open, like the request readers do.
"""
from datetime import datetime
from unittest.mock import patch

import duckdb
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.dependencies import get_db
    from src.api.main import app
    from src.database.connector import DatabaseConnector

    connector = DatabaseConnector(":memory:")
    app.dependency_overrides[get_db] = lambda: connector
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        connector.close()


def _seed(db_path, with_origin=True):
    origin_col = ", origin VARCHAR DEFAULT 'upload'" if with_origin else ""
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE sync_audit_reports (id VARCHAR, created_at TIMESTAMP, "
            "report_type VARCHAR, reader_counts JSON, by_source_after JSON)"
        )
        conn.execute(
            "INSERT INTO sync_audit_reports VALUES ('r1', ?, 'sync', '{}', ?)",
            [datetime(2026, 10, 19, 10, 46), '{"Schwab_CSV": {"count": 5, "value": 1.0}}'],
        )
        conn.execute(
            "CREATE TABLE source_upload_history (id INTEGER, reader VARCHAR, filename VARCHAR, "
            "file_size_bytes BIGINT, uploaded_at TIMESTAMP, is_valid BOOLEAN, warnings JSON, "
            f"previous_filename VARCHAR{origin_col})"
        )
        conn.execute(
            "INSERT INTO source_upload_history (id, reader, filename, file_size_bytes, uploaded_at, "
            "is_valid, warnings, previous_filename) VALUES (1, 'schwab', 'a.csv', 10, ?, TRUE, '[]', NULL)",
            [datetime(2026, 10, 1)],
        )


def test_get_source_health_alongside_read_only_reader(tmp_path):
    from src.services.settings_manager import get_source_health

    db_path = tmp_path / "unified.duckdb"
    _seed(db_path)
    held = duckdb.connect(str(db_path), read_only=True)
    try:
        health = get_source_health(str(db_path))
    finally:
        held.close()
    assert health["db_available"] is True
    assert health["by_source_after"]["Schwab_CSV"]["count"] == 5


@pytest.mark.parametrize("with_origin", [True, False])
@pytest.mark.parametrize(
    "url",
    [
        "/settings/sources/upload-history",
        "/settings/sources/upload-history/schwab",
        "/settings/sources/events",
        "/settings/sources/events/schwab",
    ],
)
def test_upload_history_reads_alongside_read_only_reader(client, tmp_path, url, with_origin):
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "unified.duckdb"
    _seed(db_path, with_origin=with_origin)
    held = duckdb.connect(str(db_path), read_only=True)
    try:
        with patch.dict("os.environ", {"UIS_DB_PATH": str(db_path)}):
            resp = client.get(url)
    finally:
        held.close()
    assert resp.status_code == 200
    body = resp.json()
    rows = body.get("entries", body.get("events"))
    assert len(rows) == 1
    assert rows[0]["filename"] == "a.csv"
    if "events" in body:
        assert rows[0]["origin"] == "upload"
