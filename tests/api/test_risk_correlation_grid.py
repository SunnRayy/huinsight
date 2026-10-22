"""Mixed-cadence correlation coverage — regression tests for issue #34.

The pre-existing suite (tests/api/test_risk_correlation.py) builds every fixture
from dense, contiguous, same-date daily series for all classes. That is why it
stayed green while production rendered a wall of en-dashes: no fixture modelled
the thing that actually breaks, which is classes stamped on *different* calendar
dates by readers with different cadences.

These tests model that, and pin both halves of the contract:
  * a mixed-cadence portfolio must produce a populated matrix, and
  * it must not do so by inventing returns nobody observed.
"""
import asyncio
from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest


class DuckDBAdapter:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, params=None):
        if params is None:
            return self.connection.execute(query)
        return self.connection.execute(query, params)


def _create_schema(conn):
    conn.execute(
        "CREATE TABLE holdings (asset_id VARCHAR, snapshot_date DATE, "
        "market_value DOUBLE, is_shadow BOOLEAN)"
    )
    conn.execute("CREATE TABLE asset_registry (canonical_id VARCHAR, asset_class VARCHAR)")
    conn.execute("CREATE TABLE taxonomy_classes (id INTEGER, name VARCHAR, parent_id INTEGER)")
    conn.execute(
        """
        INSERT INTO taxonomy_classes VALUES
            (1, 'Equity', NULL),
            (2, 'Fixed Income', NULL),
            (4, 'Cash', NULL),
            (5, 'Pension', NULL),
            (11, 'US Equity', 1),
            (21, 'US Bonds', 2),
            (41, 'Cash Deposit', 4),
            (51, 'Pension Fund', 5)
        """
    )
    conn.execute(
        """
        INSERT INTO asset_registry VALUES
            ('US_STK_AAPL', 'US Equity'),
            ('US_ETF_TLT', 'US Bonds'),
            ('CASH_DEPOSIT_1', 'Cash Deposit'),
            ('Pension_CN', 'Pension Fund')
        """
    )


def _insert(conn, asset_id, rows):
    conn.executemany(
        "INSERT INTO holdings VALUES (?, ?, ?, ?)",
        [(asset_id, d, float(v), False) for d, v in rows],
    )


def _drift(n, start_value, step):
    """Deterministic monotone-ish series — value shape is irrelevant to coverage."""
    return [start_value * (1.0 + step * i + 0.01 * ((i * 7) % 5)) for i in range(n)]


ANCHOR = date(2026, 8, 28)


def _business_days(start, end):
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _month_ends(start, end):
    out, first = [], date(start.year, start.month, 1)
    while first <= end:
        nxt = (first + timedelta(days=32)).replace(day=1)
        me = nxt - timedelta(days=1)
        if start <= me <= end:
            out.append(me)
        first = nxt
    return out


def _make_mixed_cadence_db(stale_cash=False):
    """The real Huinsight cadence mix, per src/services/freshness.py.

    'fast' classes (broker CSV / ETF feed) are stamped every business day.
    'slow' classes (Financial Summary Excel, pension) are snapshot-only: Cash on
    month-end, Pension on the 15th — a date that never coincides with either.
    """
    conn = duckdb.connect(":memory:")
    _create_schema(conn)
    start = ANCHOR - timedelta(days=800)

    biz = _business_days(start, ANCHOR)
    _insert(conn, "US_STK_AAPL", list(zip(biz, _drift(len(biz), 1000.0, 0.0009))))
    _insert(conn, "US_ETF_TLT", list(zip(biz, _drift(len(biz), 800.0, 0.0002))))

    months = _month_ends(start, ANCHOR)
    cash_months = months[: len(months) // 2] if stale_cash else months
    _insert(conn, "CASH_DEPOSIT_1", list(zip(cash_months, _drift(len(cash_months), 500.0, 0.02))))

    fifteenths = [m.replace(day=15) for m in months]
    _insert(conn, "Pension_CN", list(zip(fifteenths, _drift(len(fifteenths), 300.0, 0.03))))

    return DuckDBAdapter(conn)


def _run(db, level="top"):
    from src.api.routes.data import get_risk_correlation

    return asyncio.run(
        get_risk_correlation(level=level, include_non_rebalanceable=True, db=db)
    )


def _cell(result, row_asset, col_asset):
    row = next(r for r in result["matrix"] if r["asset"] == row_asset)
    return row["correlations"][col_asset]


# ---------------------------------------------------------------------------
# The issue #34 regression
# ---------------------------------------------------------------------------

def test_mixed_cadence_portfolio_produces_a_populated_matrix():
    """Before the grid, EVERY cross-cadence pair had overlap 0 and rendered '–'."""
    result = _run(_make_mixed_cadence_db())

    assert result["method"] == "empirical_holdings"
    assert set(result["assets"]) == {"Equity", "Fixed Income", "Cash", "Pension"}

    # The banner fires above 50%; this portfolio used to sit at 100%.
    assert result["total_pairs"] == 6
    assert result["insufficient_pairs"] == 0, (
        f"{result['insufficient_pairs']}/{result['total_pairs']} pairs still short of "
        f"{result['min_overlap_periods']} overlapping periods"
    )

    # Specifically: the daily-vs-monthly pairs that were structurally impossible.
    for a, b in [("Equity", "Cash"), ("Equity", "Pension"), ("Fixed Income", "Cash")]:
        cell = _cell(result, a, b)
        assert cell["value"] is not None, f"{a} x {b} still unmeasurable"
        assert cell["overlap"] >= result["min_overlap_periods"]


def test_mixed_cadence_selects_a_grid_the_slowest_class_can_populate():
    result = _run(_make_mixed_cadence_db())

    assert result["grid_frequency"] == "ME"
    assert result["grid_label"] == "monthly"
    # A monthly grid cannot make 8 returns out of 180 days; the window must scale.
    assert result["window_days"] > 180
    assert result["effective_periods"] >= result["min_overlap_periods"]


def test_widening_the_window_alone_would_not_have_fixed_it():
    """Pins the reason the grid exists rather than a bigger CORR_WINDOW_DAYS.

    On the raw union index a monthly class sits between daily rows, so pct_change
    yields NaN for it at every row — at any window length.
    """
    import numpy as np

    db = _make_mixed_cadence_db()
    rows = db.execute(
        """
        SELECT h.snapshot_date, COALESCE(p.name, t.name, r.asset_class) AS cls,
               SUM(h.market_value)
        FROM holdings h
        LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
        LEFT JOIN taxonomy_classes t ON r.asset_class = t.name
        LEFT JOIN taxonomy_classes p ON t.parent_id = p.id
        GROUP BY 1, 2
        """
    ).fetchall()
    pivot_data = {}
    for d, cls, val in rows:
        pivot_data.setdefault(d, {})[cls] = float(val)
    pivot = pd.DataFrame(pivot_data).T.sort_index()
    pivot.index = pd.to_datetime(pivot.index)

    raw_returns = pivot.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    # Full history, no window at all — and the slow classes still yield nothing.
    assert int(raw_returns["Cash"].notna().sum()) == 0
    assert int(raw_returns["Pension"].notna().sum()) == 0


# ---------------------------------------------------------------------------
# Anti-fabrication: the matrix must not fill in by inventing evidence
# ---------------------------------------------------------------------------

def test_a_class_that_stopped_reporting_emits_no_fabricated_returns():
    """Carrying a dead class forward would manufacture a wall of zero returns.

    Those zeros would sail past the min-overlap gate and print a confident 0.00
    built from nothing — the same failure commit c085931 removed from
    /risk/metrics. The carried endpoint must be dropped, not differenced.
    """
    result = _run(_make_mixed_cadence_db(stale_cash=True))

    evidence = result["class_evidence"]["Cash"]
    assert evidence["last_observed"] < result["window_end"], "fixture is not actually stale"

    # Whatever Cash's overlap is, it must be bounded by its real observations —
    # not by the number of grid periods it was carried across.
    cash_overlap = _cell(result, "Cash", "Cash")["overlap"]
    assert cash_overlap <= evidence["observations"]

    # And the suppression is counted, not silent.
    assert result["fabricated_returns_suppressed"] > 0


def test_carried_denominators_are_disclosed_per_cell_and_in_aggregate():
    result = _run(_make_mixed_cadence_db())

    assert "bridged_return_share" in result
    assert 0.0 <= result["bridged_return_share"] <= 1.0
    for row in result["matrix"]:
        for cell in row["correlations"].values():
            assert "bridged_share" in cell
            assert 0.0 <= cell["bridged_share"] <= 1.0


def test_intra_period_lag_is_reported():
    """Cash lands on month-end, Pension on the 15th — inside one monthly bin they
    are ~15 days apart, and the payload must say so rather than implying they
    were observed together."""
    result = _run(_make_mixed_cadence_db())

    assert result["max_intra_period_lag_days"] > 0
    assert result["mean_intra_period_lag_days"] > 0


def test_diagonal_is_null_when_a_class_has_no_usable_returns():
    """A class with nothing to measure has not been shown to correlate 1.00 with
    itself; the old code hardcoded 1.0 regardless of evidence."""
    conn = duckdb.connect(":memory:")
    _create_schema(conn)
    biz = _business_days(ANCHOR - timedelta(days=60), ANCHOR)
    _insert(conn, "US_STK_AAPL", list(zip(biz, _drift(len(biz), 1000.0, 0.001))))
    _insert(conn, "US_ETF_TLT", list(zip(biz, _drift(len(biz), 800.0, 0.0004))))
    # One lone observation: no return is derivable from a single point.
    _insert(conn, "CASH_DEPOSIT_1", [(ANCHOR - timedelta(days=30), 500.0)])

    result = _run(DuckDBAdapter(conn))
    cash_diag = _cell(result, "Cash", "Cash")
    assert cash_diag["overlap"] == 0
    assert cash_diag["value"] is None


# ---------------------------------------------------------------------------
# Rule 12
# ---------------------------------------------------------------------------

def test_failure_returns_an_error_response_not_an_empty_matrix():
    """AGENTS.md Rule 12 — an empty matrix with HTTP 200 is indistinguishable
    from 'this portfolio genuinely has no correlations'."""
    from src.api.routes._errors import ApiErrorResponse

    class ExplodingDB:
        def execute(self, query, params=None):
            raise RuntimeError("simulated query failure")

    result = _run(ExplodingDB())
    assert isinstance(result, ApiErrorResponse)
    assert result.status_code >= 500


# ---------------------------------------------------------------------------
# Grid selection unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "gap_days,expected",
    [(1, "D"), (3, "D"), (7, "W-FRI"), (10, "W-FRI"), (30, "ME"), (90, "ME")],
)
def test_detect_grid_frequency_follows_the_slowest_class(gap_days, expected):
    from src.api.routes._correlation_grid import detect_grid_frequency

    idx = pd.date_range("2025-01-01", periods=200, freq="D")
    frame = pd.DataFrame({"fast": range(200)}, index=idx, dtype=float)
    slow = pd.Series(
        range(len(idx[::gap_days])), index=idx[::gap_days], dtype=float
    )
    frame["slow"] = slow
    freq, _ = detect_grid_frequency(frame)
    assert freq == expected


def test_window_scales_with_the_grid_period():
    from src.api.routes._correlation_grid import MAX_WINDOW_DAYS, window_days_for

    assert window_days_for("D", 180) == 180          # daily: the floor already suffices
    assert window_days_for("W-FRI", 180) > 180       # weekly: needs ~194 days
    assert window_days_for("ME", 180) > 700          # monthly: needs ~841 days
    assert window_days_for("ME", 180) <= MAX_WINDOW_DAYS


def test_jump_threshold_scales_with_the_grid_period():
    """A 30% move is an outlier in a day and ordinary in a month — a cash balance
    swings that much between month-ends as salary lands and spending clears."""
    from src.api.routes._correlation_grid import jump_scale_for

    assert jump_scale_for("D") == pytest.approx(1.0)
    assert jump_scale_for("W-FRI") > 1.0
    assert jump_scale_for("ME") > jump_scale_for("W-FRI")


def test_a_carried_endpoint_never_becomes_a_zero_return():
    """The core anti-fabrication guarantee, pinned directly.

    Bin 3 has no observation, so its level is carried from bin 2. Differencing
    that carry against bin 2 yields exactly 0.0 — a return nobody observed. It
    must be dropped and counted, never emitted: a wall of such zeros is what
    would let a stale class clear the min-overlap gate and print a confident
    0.00 built from nothing.
    """
    from src.api.routes._correlation_grid import build_grid, classify_returns

    idx = pd.date_range("2025-01-01", periods=6, freq="D")
    # Bin 3 (2025-01-04) is missing for "b"; every other bin is observed.
    frame = pd.DataFrame(
        {
            "a": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "b": [20.0, 21.0, 22.0, None, 24.0, 25.0],
        },
        index=idx,
    )

    levels, real_mask, _ = build_grid(frame, "D")
    returns, bridged, fabricated = classify_returns(levels, real_mask)

    # The carry happened...
    assert levels["b"].iloc[3] == 22.0
    assert not bool(real_mask["b"].iloc[3])
    # ...but produced no return, and was counted rather than silently dropped.
    assert pd.isna(returns["b"].iloc[3]), "a carried endpoint produced a fabricated 0.0 return"
    assert fabricated >= 1

    # The step back to a real observation IS emitted, and marked as bridged.
    assert returns["b"].iloc[4] == pytest.approx(24.0 / 22.0 - 1.0)
    assert bool(bridged["b"].iloc[4])

    # No emitted return for "b" is an artefact zero.
    assert not (returns["b"].dropna() == 0.0).any()


def test_leading_gap_is_never_backfilled():
    """ffill must not invent a value before a class's first real snapshot."""
    from src.api.routes._correlation_grid import build_grid, classify_returns

    idx = pd.date_range("2025-01-01", periods=12, freq="D")
    frame = pd.DataFrame({"a": [float(i) for i in range(12)]}, index=idx)
    frame["b"] = [None] * 8 + [1.0, 2.0, 3.0, 4.0]

    levels, real_mask, _ = build_grid(frame, "D")
    returns, _bridged, _fab = classify_returns(levels, real_mask)

    assert levels["b"].iloc[:8].isna().all()
    assert returns["b"].iloc[:9].isna().all()
