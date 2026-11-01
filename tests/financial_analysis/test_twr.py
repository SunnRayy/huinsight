"""Tests for Time-Weighted Return (TWR) calculation."""
import pytest

pytestmark = pytest.mark.critical

from datetime import date


def test_twr_simple_two_periods():
    """TWR for two periods: +10% then -5% = 1.1 * 0.95 - 1 = 4.5%."""
    from src.financial_analysis.twr import calculate_twr_from_snapshots

    snapshots = [
        {"date": date(2025, 1, 1), "value": 1000000.0},
        {"date": date(2025, 2, 1), "value": 1100000.0},
        {"date": date(2025, 3, 1), "value": 1045000.0},
    ]
    # No cash flows between periods
    cashflows = []
    result = calculate_twr_from_snapshots(snapshots, cashflows)
    assert result is not None
    assert abs(result - 0.045) < 0.001  # 4.5%


def test_twr_with_cash_inflow():
    """TWR adjusts for cash flow: deposit 100k mid-period shouldn't inflate return."""
    from src.financial_analysis.twr import calculate_twr_from_snapshots

    snapshots = [
        {"date": date(2025, 1, 1), "value": 1000000.0},
        {"date": date(2025, 2, 1), "value": 1200000.0},  # +100k deposit + 100k gain
    ]
    cashflows = [{"date": date(2025, 1, 15), "amount": 100000.0}]  # deposit
    result = calculate_twr_from_snapshots(snapshots, cashflows)
    # Gain is 100k on base of ~1050k (mid-period), return ~9.5% not 20%
    assert result is not None
    assert result < 0.20  # Should not be 20%


def test_twr_returns_none_for_insufficient_data():
    """TWR needs at least 2 snapshots."""
    from src.financial_analysis.twr import calculate_twr_from_snapshots

    result = calculate_twr_from_snapshots([{"date": date(2025, 1, 1), "value": 1000000}], [])
    assert result is None
