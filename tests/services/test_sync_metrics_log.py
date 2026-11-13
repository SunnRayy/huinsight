"""Append-only sync log (audit 2026-11-08 issue 7)."""
import hashlib
from pathlib import Path

import duckdb
import pytest

from src.services import sync_metrics_log as log

MIGRATION = Path("src/database/migrations/204_sync_metrics_log.sql")


@pytest.fixture
def db(tmp_path):
    conn = duckdb.connect(str(tmp_path / "log.duckdb"))
    for stmt in (p for p in MIGRATION.read_text().split(";") if "CREATE" in p):
        conn.execute(stmt)
    conn.execute("CREATE TABLE investment_twr_source (id INTEGER, input_fingerprint VARCHAR, source_sha256 VARCHAR)")
    conn.execute("INSERT INTO investment_twr_source VALUES (1, 'fp-1', 'src-1')")
    yield conn
    conn.close()


@pytest.fixture
def ledger(tmp_path):
    d = tmp_path / "Finance"
    d.mkdir()
    (d / "Gold_transactions.xlsx").write_bytes(b"gold v1")
    (d / "Individual-Positions-2026-11-01.csv").write_bytes(b"pos a")
    (d / "Individual-Positions-2026-11-07.csv").write_bytes(b"pos b")
    config = {
        "finance_dir": str(d),
        "source_registry": {
            "gold": {"enabled": True, "file_patterns": {"workbook": "Gold_transactions.xlsx"}},
            "schwab": {"enabled": True, "data_dir": str(d), "file_patterns": {"positions": "Individual-Positions-*.csv"}},
            "rsu": {"enabled": True, "file_patterns": {"workbook": "RSU_transactions.xlsx"}},
            "off": {"enabled": False, "file_patterns": {"workbook": "x.xlsx"}},
        },
    }
    return d, config


def test_hashes_every_enabled_input_and_flags_missing(ledger):
    d, config = ledger
    hashes = log.ledger_input_hashes(config)
    assert set(hashes) == {"gold", "schwab", "rsu"}
    assert hashes["gold"]["Gold_transactions.xlsx"]["sha256"] == hashlib.sha256(b"gold v1").hexdigest()
    assert set(hashes["schwab"]) == {"Individual-Positions-2026-11-01.csv", "Individual-Positions-2026-11-07.csv"}
    assert hashes["rsu"]["RSU_transactions.xlsx"] == {"missing": True}


def test_rows_append_and_name_the_changed_file(db, ledger, monkeypatch):
    d, config = ledger
    figures = iter([{"returns": {"all_time": {"twr_cumulative": 34.55}}},
                    {"returns": {"all_time": {"twr_cumulative": 34.43}}}])
    monkeypatch.setattr(log, "headline_metrics", lambda _db: next(figures))

    first = log.record_sync_metrics(db, config)
    (d / "Gold_transactions.xlsx").write_bytes(b"gold v2 - back-filled row")
    db.execute("UPDATE investment_twr_source SET input_fingerprint = 'fp-2'")
    second = log.record_sync_metrics(db, config)

    assert second > first
    assert db.execute("SELECT COUNT(*) FROM sync_metrics_log").fetchone()[0] == 2
    newest, oldest = log.list_sync_metrics(db, limit=10)
    assert newest["metrics"]["returns"]["all_time"]["twr_cumulative"] == 34.43
    assert oldest["metrics"]["returns"]["all_time"]["twr_cumulative"] == 34.55  # history is kept
    assert newest["changed_files"] == ["gold/Gold_transactions.xlsx (changed)"]
    assert newest["returns_inputs_changed"] is True
    assert oldest["changed_files"] is None  # nothing before it


def test_a_failure_never_raises_into_the_sync(db, ledger, monkeypatch):
    _, config = ledger
    monkeypatch.setattr(log, "headline_metrics", lambda _db: (_ for _ in ()).throw(RuntimeError("boom")))
    assert log.record_sync_metrics(db, config) is None
    assert db.execute("SELECT COUNT(*) FROM sync_metrics_log").fetchone()[0] == 0
