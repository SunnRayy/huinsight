"""Structural guard (AGENTS.md Rule 24), Round 7 #2: Forecast > Your Path and
integrity check `twr_in_range` decide "is there enough history to trust a
measured return?" with ONE predicate,
`data_integrity_gate.twr_history_sufficiency`.

The incident: on a fresh demo the gate skipped `twr_in_range` (history too
short) while the forecast projected from that same short history (-7.1% /
9.7% vol) and told the user their goal was unreachable. Two places, two
answers. These tests fail if either side grows its own rule again.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema
from src.services import forecast_levers
from src.validation import data_integrity_gate
from src.validation.data_integrity_gate import _check_twr_in_range, twr_history_sufficiency

PREDICATE = "twr_history_sufficiency"
# The rule's internals — only the predicate itself may touch them.
RULE_INTERNALS = {"_windowed_portfolio_valuation", "TWR_MIN_LIKE_FOR_LIKE_COVERAGE"}


def _names_used(source: str) -> set[str]:
    tree = ast.parse(textwrap.dedent(source))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name)
    return names


def test_integrity_check_delegates_to_the_shared_predicate():
    used = _names_used(inspect.getsource(_check_twr_in_range))
    assert PREDICATE in used
    assert not (used & RULE_INTERNALS), used & RULE_INTERNALS
    assert "TWR_CHECK_LOOKBACK_CANDIDATES" not in used


def test_forecast_uses_the_shared_predicate_and_no_rule_of_its_own():
    used = _names_used(inspect.getsource(forecast_levers))
    assert PREDICATE in used
    assert not (used & RULE_INTERNALS), used & RULE_INTERNALS


def test_forecast_has_no_history_length_literals():
    """A second threshold would most likely arrive as a day count."""
    tree = ast.parse(inspect.getsource(forecast_levers))
    day_counts = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, int)
        and n.value in set(data_integrity_gate.TWR_CHECK_LOOKBACK_CANDIDATES) | {90, 360}
    }
    assert not day_counts, day_counts


# ── Behavioural: same DB, same answer on both sides ─────────────────────────

@pytest.fixture
def conn():
    db = DatabaseConnector(":memory:")
    initialize_schema(db)
    yield db
    db.close()


def _holding(db, snapshot_date, market_value, asset_id="US_STK_TEST"):
    db.execute(
        """
        INSERT INTO holdings (snapshot_date, asset_id, asset_name, quantity, market_value,
                              currency, account, source_system, is_shadow)
        VALUES (?, ?, 'Test', 10, ?, 'CNY', 'Test', 'Schwab_CSV', FALSE)
        """,
        (snapshot_date, asset_id, market_value),
    )


def _levers(db):
    # Measured inputs are patched so the only thing deciding the basis is
    # the sufficiency predicate.
    with patch(
        "src.financial_analysis.projection_defaults.suggested_return_basis", return_value=0.07
    ), patch(
        "src.financial_analysis.metrics.calculate_portfolio_metrics",
        return_value={"volatility_annual": 14.0},
    ):
        return forecast_levers.compute_levers(db)


def test_short_history_skips_the_check_and_switches_the_forecast_to_the_assumption(conn):
    today = date.today()
    _holding(conn, today - timedelta(days=60), 1_000_000.0)
    _holding(conn, today, 1_050_000.0)

    assert twr_history_sufficiency(conn)["sufficient"] is False
    assert _check_twr_in_range(conn).skipped is True
    assert _levers(conn)["base"]["return_basis"] == "assumption"


def test_year_of_history_runs_the_check_and_the_forecast_on_measured_figures(conn):
    today = date.today()
    _holding(conn, today - timedelta(days=365), 1_000_000.0)
    _holding(conn, today, 1_080_000.0)

    assert twr_history_sufficiency(conn)["sufficient"] is True
    assert _check_twr_in_range(conn).skipped is False
    result = _levers(conn)
    assert result["base"]["return_basis"] == "measured"
    assert result["assumption"] is None
