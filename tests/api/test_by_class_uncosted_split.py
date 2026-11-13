"""Audit 2026-11-08 issue 2: by-class keeps no-cost value out of the costed value."""
import pytest

from src.database.connector import DatabaseConnector
from tests.api.test_by_class_engine_parity import _new, _seed, frozen_fx  # noqa: F401


def test_by_class_splits_no_cost_value_from_costed_value(tmp_path, frozen_fx):  # noqa: F811
    """Audit 2026-11-08 issue 2: a row's value and cost must cover the same positions."""
    db_path = tmp_path / "by_class_uncosted.duckdb"
    _seed(db_path)
    db = DatabaseConnector(str(db_path))
    try:
        out = _new(db, "all_time", False)
    finally:
        db.close()
    for row in out["top_classes"] + out["sub_classes"]:
        assert row["costed_market_value"] + row["uncosted_market_value"] == pytest.approx(row["market_value"])
        assert row["uncosted_count"] == len(row["uncosted_assets"])
    fixed = next(r for r in out["top_classes"] if r["cost_basis"] == 0.0 and r["market_value"] == 200000.0)
    assert fixed["uncosted_market_value"] == pytest.approx(200000.0)   # the balance-only bond
    assert fixed["costed_market_value"] == pytest.approx(0.0)
