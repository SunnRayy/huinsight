"""Price freshness: the headline number says when it rests on non-live prices."""
from datetime import datetime

import duckdb
import pytest

from src.services.price_freshness import compute_price_freshness

NOW = datetime(2026, 9, 24, 12, 0)


@pytest.fixture
def db():
    conn = duckdb.connect(":memory:")
    conn.execute(
        """CREATE TABLE holdings (
            asset_id VARCHAR, source_system VARCHAR, snapshot_date DATE, quantity DOUBLE,
            market_value DOUBLE, is_shadow BOOLEAN, price_source VARCHAR, price_updated_at TIMESTAMP)"""
    )
    yield conn
    conn.close()


def _row(db, asset, source, value, price_source, updated=None, qty=10.0, shadow=False, day="2026-09-20"):
    db.execute(
        "INSERT INTO holdings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [asset, source, day, qty, value, shadow, price_source, updated],
    )


def test_live_recent_prices_are_fresh(db):
    _row(db, "US_STK_VTI", "Schwab_CSV", 100_000, "yfinance", datetime(2026, 9, 23))
    _row(db, "CN_FUND_000198", "CN_Fund_Excel", 5_000, "file")  # small file-priced remainder
    result = compute_price_freshness(db, now=NOW)
    assert result["status"] == "fresh"
    assert result["unpriced_count"] == 1


def test_failed_refresh_is_unpriced(db):
    _row(db, "US_STK_VTI", "Schwab_CSV", 100_000, "file")
    _row(db, "CN_FUND_519674", "CN_Fund_Excel", 80_000, "file")
    result = compute_price_freshness(db, now=NOW)
    assert result["status"] == "unpriced"
    assert result["unpriced_share"] == 1.0
    assert result["last_price_at"] is None


def test_old_live_prices_are_stale(db):
    _row(db, "US_STK_VTI", "Schwab_CSV", 100_000, "yfinance", datetime(2026, 9, 2))
    assert compute_price_freshness(db, now=NOW)["status"] == "stale"


def test_non_market_sources_and_shadow_rows_are_ignored(db):
    _row(db, "Property_X", "Financial_Summary_Excel", 2_000_000, "file")
    _row(db, "US_STK_VTI", "Schwab_CSV", 100_000, "file", shadow=True)
    assert compute_price_freshness(db, now=NOW)["status"] == "none"


def test_only_latest_snapshot_per_source_counts(db):
    _row(db, "US_STK_VTI", "Schwab_CSV", 100_000, "file", day="2026-05-01")
    _row(db, "US_STK_VTI", "Schwab_CSV", 110_000, "yfinance", datetime(2026, 9, 23), day="2026-09-20")
    assert compute_price_freshness(db, now=NOW)["status"] == "fresh"
