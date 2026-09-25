"""Tests for src/services/alert_generator.py — Round 5 finding #8.

Drift alerts were computed only against `review_allocation_alignment(db)
["target_scope_alignment"]` — rows in `target_allocations WHERE
source='Strategic_Profile'`, which exist only in the owner's hand-curated
database. Every other install has no such rows but does have an active risk
profile (`risk_profile_allocations`, seeded by migration V193) — so drift
alerts read a hard zero on every non-owner install, no matter how far the
portfolio had actually drifted. `generate_alerts()` must fall back to the
risk-profile scope (`uis_scope_alignment`) when the strategic scope is empty,
and `drift_basis()` must say plainly when *neither* scope has any targets at
all, so a caller can tell "checked, nothing drifted" from "not measurable".
"""
from pathlib import Path

import duckdb
import pytest

from src.database.connector import DatabaseConnector
from src.database.schema import bootstrap_database
from src.services.alert_generator import drift_basis, generate_alerts


def _seed_concentrated_us_equity_holding(db) -> None:
    """A single holding, entirely in one sub-class, guarantees >5pp drift
    against any of the seeded risk-profile targets (none target 100%)."""
    db.execute(
        """
        INSERT INTO asset_registry (canonical_id, display_name, asset_class)
        VALUES ('US_STK_AAPL', 'Apple', 'US Equity')
        """
    )
    db.execute(
        """
        INSERT INTO holdings (snapshot_date, asset_id, market_value, source_system, is_shadow)
        VALUES ('2026-09-20', 'US_STK_AAPL', 100000, 'Schwab_CSV', FALSE)
        """
    )


@pytest.fixture
def fresh_db(tmp_path):
    """A brand-new install taken through the real bootstrap path: V193 seeds
    the active ('Balanced') risk profile, but no owner-curated
    Strategic_Profile target_allocations row exists anywhere."""
    db = DatabaseConnector(str(tmp_path / "fresh.duckdb"))
    bootstrap_database(db)
    yield db
    db.close()


def test_drift_basis_is_risk_profile_on_a_fresh_install(fresh_db):
    assert drift_basis(fresh_db) == "risk_profile"


def test_generate_alerts_falls_back_to_risk_profile_targets_on_fresh_install(fresh_db):
    _seed_concentrated_us_equity_holding(fresh_db)

    alerts = generate_alerts(fresh_db)
    drift_alerts = [a for a in alerts if a["category"] == "drift"]

    assert drift_alerts, "expected at least one drift alert against the active risk profile"
    for alert in drift_alerts:
        assert alert["data"]["basis"] == "risk_profile"
        assert "risk-profile target" in alert["title"], alert["title"]
        assert "strategic target" not in alert["title"], alert["title"]


def test_generate_alerts_prefers_strategic_targets_when_present(fresh_db):
    """Owner's DB: once Strategic_Profile rows exist, they take precedence
    over the risk-profile scope, and the pre-fix title wording is unchanged."""
    _seed_concentrated_us_equity_holding(fresh_db)
    fresh_db.execute(
        """
        INSERT INTO target_allocations (asset_class, target_pct, tolerance_pct, taxonomy_type, source, effective_date)
        VALUES
          ('US Equity', 30, 5, 'Asset Class', 'Strategic_Profile', '2026-09-01'),
          ('CN Equity', 30, 5, 'Asset Class', 'Strategic_Profile', '2026-09-01'),
          ('固定收益', 30, 5, 'Asset Class', 'Strategic_Profile', '2026-09-01'),
          ('现金', 10, 5, 'Asset Class', 'Strategic_Profile', '2026-09-01')
        """
    )

    assert drift_basis(fresh_db) == "strategic"

    alerts = generate_alerts(fresh_db)
    drift_alerts = [a for a in alerts if a["category"] == "drift"]

    assert drift_alerts, "expected drift against the strategic target too (100% concentration)"
    for alert in drift_alerts:
        assert alert["data"]["basis"] == "strategic"
        assert alert["title"].endswith("from strategic target"), alert["title"]


def test_drift_basis_is_none_when_neither_scope_has_targets():
    """No risk profile, no strategic targets — a fresh schema before V193 has
    ever run (or one where both were cleared). Drift is not measurable."""
    conn = duckdb.connect(":memory:")
    schema_sql = Path("src/database/schema.sql").read_text(encoding="utf-8")
    conn.execute(schema_sql)

    assert drift_basis(conn) is None


def test_generate_alerts_reports_no_drift_alerts_when_no_targets_exist():
    """The honest-zero case: with nothing to compare against, generate_alerts
    must not fabricate a drift alert, but it also must not be the sole signal
    a caller sees — that is what drift_basis() is for (see /decisions/stats)."""
    conn = duckdb.connect(":memory:")
    schema_sql = Path("src/database/schema.sql").read_text(encoding="utf-8")
    conn.execute(schema_sql)
    conn.execute(
        """
        INSERT INTO asset_registry (canonical_id, display_name, asset_class)
        VALUES ('US_STK_AAPL', 'Apple', 'US Equity')
        """
    )
    conn.execute(
        """
        INSERT INTO holdings (snapshot_date, asset_id, market_value, source_system, is_shadow)
        VALUES ('2026-09-20', 'US_STK_AAPL', 100000, 'Schwab_CSV', FALSE)
        """
    )

    alerts = generate_alerts(conn)
    assert not [a for a in alerts if a["category"] == "drift"]
