from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch
from src.services.context_generator import MarkdownContextGenerator


@pytest.fixture(autouse=True)
def mock_context_pnl_engine():
    # Unit fixtures supply cost facts separately from SQL presentation rows.
    with patch('src.services.context_generator.compute_portfolio_pnl',
               side_effect=lambda db, **kwargs: SimpleNamespace(assets=[
                   SimpleNamespace(asset_id=aid, has_known_cost=True, cost_basis_cny=cost)
                   for aid, cost in getattr(db, '_context_costs', {}).items()
               ])):
        yield


def _make_db_mock(**overrides):
    """Return a MagicMock db that returns empty results by default.
    Pass keyword args to override specific query patterns:
      holdings_overview=(reb, non_reb)
      risk_alloc_rows=[(top, sub, pct), ...]
      alloc_rows=[(top_class, val), ...]
      subclass_rows=[(top, sub, val), ...]
      tier_rows=[(name, val, cur_pct, tgt, drift, pl, count), ...]
    """
    db = MagicMock()
    db._context_costs = overrides.get('costs', {
        row[0]: row[3] for row in overrides.get('asset_perf_rows', [('US_STK_AAPL', 'Equity', 4000.0, 3500.0, True)])
    })

    def mock_execute(query, params=None):
        result = MagicMock()

        # Section 1.1 — holdings overview (fetchone returns [total, reb, non_reb])
        # Detected by "as non_reb" alias (unique to section 1.1; section 2.1 uses non_reb_value)
        if "as non_reb" in query and "as non_reb_value" not in query and "FROM holdings h" in query:
            result.fetchone.return_value = overrides.get("holdings_overview", [6000.0, 5000.0, 1000.0])
            result.fetchall.return_value = []

        # Risk profile allocations (for target_map)
        elif "risk_profile_allocations" in query and "risk_profiles" in query:
            result.fetchall.return_value = overrides.get("risk_alloc_rows", [
                ("Equity", "CN Equity", 35.0),
                ("Equity", "US Equity", 20.0),
            ])

        # Section 1.2 — top-class allocation (holdings + taxonomy double-join)
        elif "taxonomy_classes parent_tc ON tc.parent_id" in query and "GROUP BY top_class" in query and "sub_class" not in query:
            key = "reb_alloc_rows" if "is_rebalanceable, r.is_rebalanceable, TRUE) = TRUE" in query else "total_alloc_rows"
            default_rows = [
                ("Equity", 4000.0),
                ("Fixed Income", 1000.0),
            ]
            result.fetchall.return_value = overrides.get(key, overrides.get("alloc_rows", default_rows))

        # Section 1.3 — sub-class breakdown
        elif "taxonomy_classes parent_tc ON tc.parent_id" in query and "GROUP BY top_class, sub_class" in query:
            result.fetchall.return_value = overrides.get("subclass_rows", [
                ("Equity", "CN Equity", 2500.0),
                ("Equity", "US Equity", 1500.0),
                ("Fixed Income", "US Bonds", 1000.0),
            ])

        # Section 1.4 — tier allocation
        elif "FROM asset_tiers" in query:
            result.fetchall.return_value = overrides.get('tier_meta', [])
        elif "GROUP BY r.tier, h.asset_id" in query:
            result.fetchall.return_value = overrides.get('tier_assets', [])
        elif "SUM(h.market_value) as total" in query and "= TRUE" in query and "weight_pct" not in query:
            result.fetchone.return_value = [5000.0]

        # Section 2.1 — performance summary
        elif "total_cost_basis" in query or ("net_worth" in query and "asset_count" in query):
            result.fetchone.return_value = overrides.get(
                "perf_summary", [5000.0, 4000.0, 1000.0, 10]
            )
            result.fetchall.return_value = []

        # Section 3 — market sentiment
        elif "market_sentiment_cache" in query:
            result.fetchall.return_value = overrides.get("sentiment_rows", [])

        # Section 4 — holdings detail
        elif "taxonomy_classes parent_tc ON tc.parent_id" in query and "weight_pct" in query:
            result.fetchall.return_value = overrides.get("holdings_rows", [])

        # Section 2 — per-asset rows for class/lifetime aggregation
        elif "GROUP BY h.asset_id, top_class" in query:
            raw_rows = overrides.get("asset_perf_rows", [
                ("US_STK_AAPL", "Equity", 4000.0, 3500.0, True),
            ])
            result.fetchall.return_value = [
                (aid, cls, mv, 1.0, cost, 'CNY', cls, reb)
                for aid, cls, mv, cost, reb in raw_rows
            ]

        # Rebalanceable asset-id helper query
        elif "SELECT h.asset_id" in query and "COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) = TRUE" in query:
            result.fetchall.return_value = overrides.get("reb_asset_ids_rows", [("US_STK_AAPL",)])

        # Transaction asset universe (for realized calculations including sold-only assets)
        elif "SELECT DISTINCT asset_id FROM transactions" in query:
            result.fetchall.return_value = overrides.get("tx_asset_rows", [("US_STK_AAPL",)])

        # Sold-only class mapping
        elif "FROM asset_registry r" in query and "WHERE r.canonical_id IN" in query:
            result.fetchall.return_value = overrides.get("sold_asset_class_rows", [])

        # Section 2.2 — class performance
        elif "taxonomy_classes parent_tc ON tc.parent_id" in query and "cost_basis" in query:
            result.fetchall.return_value = overrides.get("class_perf", [
                ("Equity", 4000.0, 3500.0, 80.0, 5),
            ])

        # MAX(snapshot_date) for header
        elif "MAX(snapshot_date)" in query:
            result.fetchone.return_value = ["2026-03-01"]
            result.fetchall.return_value = []

        else:
            result.fetchall.return_value = []
            result.fetchone.return_value = None

        return result

    db.execute.side_effect = mock_execute
    return db


# ─── Smoke tests ────────────────────────────────────────────────────────────

def test_generate_returns_markdown_string():
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    db.execute.return_value.fetchone.return_value = None

    generator = MarkdownContextGenerator(db)
    md = generator.generate()

    assert "# Personal Investment Analysis Context" in md
    assert "## 1. Portfolio State" in md
    assert "## 2. Performance Metrics" in md
    assert "## 3. Market Environment" in md
    assert "## 4. Holdings Details" in md


def _freshness_db():
    import duckdb
    from datetime import date, timedelta
    conn = duckdb.connect(":memory:")
    conn.execute("""CREATE TABLE holdings (asset_id VARCHAR, source_system VARCHAR,
        snapshot_date DATE, market_value DOUBLE, price_updated_at TIMESTAMP, is_shadow BOOLEAN)""")
    conn.execute("""CREATE TABLE transactions (asset_id VARCHAR, source_system VARCHAR,
        transaction_date DATE)""")
    today = date.today()
    fresh = today - timedelta(days=2)
    rows = [
        ("FUND_A", "CN_Fund_Excel", today - timedelta(days=60), 100.0, fresh, False),
        ("FUND_B", "CN_Fund_Excel", today - timedelta(days=61), 50.0, fresh, False),
        ("STK_A", "Schwab_CSV", fresh, 300.0, None, False),
        ("STK_A", "Schwab_CSV", today - timedelta(days=200), 999.0, None, False),  # superseded
        ("STK_B", "Schwab_CSV", fresh, 999.0, None, True),                        # shadowed
        ("CASH_X", "Financial_Summary_Excel", date(2026, 9, 1), 70.0, None, False),
        ("HOUSE", "Financial_Summary_Excel", date(2026, 9, 1), 5000.0, None, False),  # not investable
    ]
    conn.executemany("INSERT INTO holdings VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.execute("CREATE TABLE asset_registry (canonical_id VARCHAR, asset_class VARCHAR, is_rebalanceable BOOLEAN)")
    conn.execute("CREATE TABLE taxonomy_classes (name VARCHAR, is_rebalanceable BOOLEAN)")
    conn.execute("INSERT INTO asset_registry VALUES ('HOUSE', 'Real Estate', TRUE)")
    conn.execute("INSERT INTO taxonomy_classes VALUES ('Real Estate', FALSE)")
    conn.execute("INSERT INTO transactions VALUES ('FUND_A', 'CN_Fund_Excel', ?)",
                 [today - timedelta(days=70)])
    return conn, today


def test_header_lists_each_source_with_its_own_dates():
    conn, today = _freshness_db()
    header = MarkdownContextGenerator(conn)._header()
    rows = {line.split("|")[1].strip(): line for line in header.splitlines()
            if line.startswith("| ") and "Source" not in line}

    assert "Generated:" in header
    assert "Data as of" not in header  # one global date hid the stale sources
    from datetime import timedelta
    fund = rows["CN mutual funds"]
    assert f"{today - timedelta(days=61)} – {today - timedelta(days=60)} ⚠ 61 days old" in fund
    assert str(today - timedelta(days=70)) in fund and "¥150" in fund
    schwab = rows["Schwab"]
    assert "⚠" not in schwab and "from file" in schwab and "¥300" in schwab
    month_row = rows["Financial Summary (deposits, bonds, pension)"]
    assert "≈ 2026-09-30 (2026-09 month row)" in month_row
    assert "¥70" in month_row and "¥5,070" not in month_row  # property left out


def test_latest_liabilities_sums_leaf_columns_only():
    import duckdb, json
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE balance_sheet_monthly (snapshot_date DATE, payload JSON)")
    payload = {"长期负债_房贷": 1000.0, "短期负债_信用卡_A": 50.0, "短期负债_信用卡_B": None,
               "短期负债_信用卡_美国_USD": 7.0, "短期负债_信用卡_美国": 49.0,
               "合计负债资产": 999999.0, "资产_存款": 5000.0}
    conn.execute("INSERT INTO balance_sheet_monthly VALUES ('2026-08-01', ?), ('2026-09-01', ?)",
                 [json.dumps({"长期负债_房贷": 1.0}), json.dumps(payload)])
    from datetime import date
    assert MarkdownContextGenerator(conn)._latest_liabilities() == (date(2026, 9, 30), 1000.0, 99.0)


def test_header_without_holdings_says_unavailable():
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    header = MarkdownContextGenerator(db)._header()
    assert "Data freshness by source: unavailable." in header


# ─── Section 1 ──────────────────────────────────────────────────────────────

def test_section_1_portfolio_state_headings():
    db = _make_db_mock()
    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    assert "## 1. Portfolio State" in section
    assert "1.1 Current Holdings Overview" in section
    assert "Investable Assets" in section
    assert "Total Portfolio Value" not in section
    assert "1.2a" not in section
    assert "1.2 Investable Allocation vs Target" in section
    assert "1.3 Sub-Class Breakdown" in section
    assert "1.4 Tier Allocation" in section


def test_context_generator_uses_latest_per_asset_not_global_max():
    db = _make_db_mock()

    def execute_with_snapshot_behavior(query, params=None):
        result = MagicMock()
        if "as non_reb" in query and "FROM holdings h" in query:
            if "latest_per_asset" in query:
                result.fetchone.return_value = [300.0, 300.0, 0.0]
            else:
                result.fetchone.return_value = [200.0, 200.0, 0.0]
            return result
        return db.execute.side_effect.__wrapped__(query, params)  # type: ignore[attr-defined]

    original = db.execute.side_effect
    execute_with_snapshot_behavior.__wrapped__ = original  # type: ignore[attr-defined]
    db.execute.side_effect = execute_with_snapshot_behavior

    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    assert "¥300" in section


def test_section_1_2_shows_top_class_names():
    """Section 1.2 must show top-class names resolved via taxonomy double-join."""
    db = _make_db_mock(
        total_alloc_rows=[("Equity", 4000.0), ("Real Estate", 1000.0)],
        reb_alloc_rows=[("Equity", 4000.0), ("Fixed Income", 1000.0)],
    )
    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    assert "Equity" in section
    assert "Fixed Income" in section
    assert "Real Estate" not in section


def test_section_1_2b_uses_top_target_map():
    """Section 1.2b target % should aggregate sub-class targets to top-class level."""
    db = _make_db_mock(
        risk_alloc_rows=[
            ("Equity", "CN Equity", 35.0),
            ("Equity", "US Equity", 20.0),
        ],
        reb_alloc_rows=[("Equity", 5000.0)],
    )
    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    # Equity target should be 35+20=55%, shown in section
    assert "55.00%" in section


def test_section_1_3_subclass_breakdown_exists():
    """Section 1.3 must show sub-class breakdown with Top Class and Sub-Class columns."""
    db = _make_db_mock(
        subclass_rows=[
            ("Equity", "CN Equity", 2000.0),
            ("Equity", "US Equity", 1000.0),
        ]
    )
    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    assert "Sub-Class Breakdown" in section
    assert "Top Class" in section
    assert "Sub-Class" in section
    assert "CN Equity" in section
    assert "US Equity" in section


def test_section_1_3_uses_sub_target_map():
    """Section 1.3 target % should use sub-class level targets."""
    db = _make_db_mock(
        risk_alloc_rows=[
            ("Equity", "CN Equity", 35.0),
        ],
        subclass_rows=[("Equity", "CN Equity", 2000.0)],
    )
    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    # CN Equity target should be 35%
    assert "35.00%" in section


def test_section_1_4_enriched_tier_data():
    """Section 1.4 must show Value, Current %, Target %, Drift, P&L, Assets."""
    db = _make_db_mock(
        tier_meta=[('Tier 1 Core', 50.0, 1)],
        tier_assets=[('Tier 1 Core', 'EQ', 3000.0, 1, 2800.0, 'CNY', 'US Equity', 'Equity')],
        costs={'EQ': 2800.0}
    )
    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    assert "Tier 1 Core" in section
    assert "Unrealized P&L" in section
    assert "Assets" in section
    assert "60.00%" in section  # current %
    assert "50.00%" in section  # target %


def test_section_1_no_non_rebalanceable_assets_in_tables():
    """Non-rebalanceable asset classes must not appear as rows in allocation tables 1.2/1.3.
    Note: 'Insurance' and 'Real Estate' may appear in the section 1.1 informational note."""
    db = _make_db_mock(
        total_alloc_rows=[("Equity", 5000.0), ("Real Estate", 500.0)],
        reb_alloc_rows=[("Equity", 5000.0), ("Fixed Income", 1000.0)],
    )
    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    # Section 1.2b table should only have Equity and Fixed Income rows
    assert "| Equity |" in section
    assert "| Fixed Income |" in section
    # Property is not investable: no table row reports it
    assert "| Real Estate |" not in section


def test_context_generator_omits_property_allocation():
    db = _make_db_mock(
        total_alloc_rows=[("Equity", 5000.0), ("Real Estate", 2600000.0)],
        reb_alloc_rows=[("Equity", 5000.0), ("Fixed Income", 1000.0)],
    )
    generator = MarkdownContextGenerator(db)
    section = generator._section_1_portfolio_state()

    assert "### 1.2a" not in section
    assert "| Real Estate |" not in section


# ─── Section 2 ──────────────────────────────────────────────────────────────

def test_section_2_performance_headings():
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    db.execute.return_value.fetchone.return_value = None

    generator = MarkdownContextGenerator(db)
    section = generator._section_2_performance()

    assert "## 2. Performance Metrics" in section


def test_section_2_includes_realized_and_lifetime_metrics():
    db = _make_db_mock(
        perf_summary=[5000.0, 4000.0, 1000.0, 4500.0, 3500.0, 2],
        class_perf=[("Equity", 4000.0, 3500.0, 80.0, 1)],
    )
    with patch(
        "src.services.context_generator.calculate_realized_pnl",
        return_value=(120.0, "CNY"),
        create=True,
    ):
        section = MarkdownContextGenerator(db)._section_2_performance()

    assert "Realized Gains" in section
    assert "Lifetime P&L" in section
    assert "Realized P&L" in section


def test_section_2_includes_returns_and_risk_metrics_reference_block():
    db = _make_db_mock(
        perf_summary=[5000.0, 4000.0, 1000.0, 4500.0, 3500.0, 2],
        class_perf=[("Equity", 4000.0, 3500.0, 80.0, 1)],
        asset_perf_rows=[], tx_asset_rows=[], reb_asset_ids_rows=[],
    )
    with patch(
        "src.services.context_generator.build_investment_returns",
        return_value=ACCOUNT_RETURNS,
        create=True,
    ), patch(
        "src.services.context_generator.build_investment_risk",
        return_value={
            "sharpe_ratio": 1.1,
            "sortino_ratio": 1.5,
            "max_drawdown": 8.2,
            "calmar_ratio": 0.7,
            "volatility_annual": 12.3,
            "total_return": 15.8,
            "data_points": 24,
        },
        create=True,
    ) as mock_risk:
        section = MarkdownContextGenerator(db)._section_2_performance()
        mock_risk.side_effect = RuntimeError("optional risk query failed")
        degraded = MarkdownContextGenerator(db)._section_2_performance()

    assert "Returns & Risk Metrics" in section
    assert "Sharpe Ratio" in section
    assert "Max Drawdown" in section
    assert "TWR (Cumulative)" in section

    from src.services.investment_returns import format_account_returns
    assert format_account_returns(ACCOUNT_RETURNS) in section
    assert format_account_returns(ACCOUNT_RETURNS) in degraded
    assert "2020-01-31 to 2026-08-31" in section
    assert "candidate" in section
    assert "cannot rule out ambiguity" in section
    assert "scope differs from XIRR" not in section


def test_section_2_asset_class_realized_includes_sold_only_assets():
    db = _make_db_mock(
        perf_summary=[5000.0, 5000.0, 0.0, 4500.0, 4500.0, 1],
        asset_perf_rows=[("US_STK_AAPL", "Equity", 5000.0, 4500.0, True)],
        reb_asset_ids_rows=[("US_STK_AAPL",)],
        tx_asset_rows=[("US_STK_AAPL",), ("US_STK_SOLD",)],
        sold_asset_class_rows=[("US_STK_SOLD", "Equity", True)],
    )

    def realized_side_effect(_db, aid, start_date=None):
        amount = 100.0 if aid == "US_STK_AAPL" else 50.0 if aid == "US_STK_SOLD" else 0.0
        return amount, "CNY"

    with patch(
        "src.services.context_generator.calculate_realized_pnl",
        side_effect=realized_side_effect,
        create=True,
    ), patch(
        "src.services.context_generator.build_investment_returns",
        return_value=ACCOUNT_RETURNS,
        create=True,
    ), patch(
        "src.services.context_generator.build_investment_risk",
        return_value={"sharpe_ratio": 1.0, "sortino_ratio": 1.2, "max_drawdown": 5.0, "calmar_ratio": 0.7, "volatility_annual": 12.0, "total_return": 10.0, "data_points": 24},
        create=True,
    ):
        section = MarkdownContextGenerator(db)._section_2_performance()

    # Realized must include active (100) + sold-only (50) for Equity class.
    assert "| Equity | ¥5,000 | 100.00% | ¥500 | ¥150 | ¥650 | 14.44% | 1 |" in section


def test_section_2_2_no_non_rebalanceable_assets():
    """Section 2.2 asset class list must not include Insurance or Property."""
    db = _make_db_mock(class_perf=[
        ("Equity", 5000.0, 4000.0, 80.0, 10),
        ("Fixed Income", 1000.0, 900.0, 20.0, 3),
    ])
    generator = MarkdownContextGenerator(db)
    section = generator._section_2_performance()

    class_section = section.split('### 2.2')[1].split('### 2.3')[0]
    assert "Insurance" not in class_section
    assert "Property" not in class_section
    assert "Real Estate" not in class_section


# ─── Section 3 ──────────────────────────────────────────────────────────────

def test_section_3_market_environment():
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ("fear_greed", "equity_macro", "Fear & Greed", 30.0, "30 (Fear)", "Fear", "orange", "Fear area", "{}", "2026-03-01")
    ]
    db.execute.return_value = mock_result

    generator = MarkdownContextGenerator(db)
    section = generator._section_3_market_environment()

    assert "## 3. Market Environment" in section
    assert "Fear & Greed" in section
    assert "30 (Fear)" in section


def test_context_generator_market_status_summary_present():
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    db.execute.return_value = mock_result

    with patch(
        "src.services.context_generator.assess_portfolio_regime",
        return_value={
            "trend": "Bull",
            "volatility_level": "Normal",
            "drawdown_pct": -1.84,
            "momentum_3m_pct": 6.3,
        },
        create=True,
    ):
        section = MarkdownContextGenerator(db)._section_3_market_environment()

    assert "### 3.0 Market Regime Summary" in section
    assert "Trend: Bull" in section
    assert "Volatility: Normal" in section


def test_context_generator_market_status_summary_absent_gracefully():
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    db.execute.return_value = mock_result

    with patch(
        "src.services.context_generator.assess_portfolio_regime",
        return_value=None,
        create=True,
    ):
        section = MarkdownContextGenerator(db)._section_3_market_environment()

    assert "### 3.0 Market Regime Summary" in section
    assert "Market regime data unavailable — run market data sync." in section


def test_context_generator_escapes_pipe_in_markdown_cells():
    generator = MarkdownContextGenerator(MagicMock())
    table = generator.generate_markdown_table(
        ["Indicator", "Value"],
        [["BTC Vol", "$69,955 | 52.7% vol"]],
    )
    assert "\\|" in table
    assert "$69,955 | 52.7% vol" not in table


# ─── Section 4 ──────────────────────────────────────────────────────────────

def test_section_4_holdings_detail_heading():
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    db.execute.return_value.fetchone.return_value = None

    generator = MarkdownContextGenerator(db)
    section = generator._section_4_holdings_detail()

    assert "## 4. Holdings Details" in section


def test_section_4_holding_details_keep_rebalanceable_and_aggregate_cash():
    """Section 4 should keep rebalanceable assets only and aggregate cash to one row."""
    db = _make_db_mock(holdings_rows=[
        ("Apple Inc", "US_STK_AAPL", "Equity", "US Equity", 10000.0, 1, 8000.0, 'CNY', 5.0, True),
        ("Cash Account 1", "CASH_1", "Cash", "Cash Checking", 3000.0, 1, 3000.0, 'CNY', 1.5, True),
        ("Cash Account 2", "CASH_2", "Cash", "Money Market", 2000.0, 1, 2000.0, 'CNY', 1.0, True),
        ("Property A", "Property_A", "Real Estate", "Property", 2600000.0, 1, 2820000.0, 'CNY', 47.8, False),
    ])
    with patch(
        "src.services.context_generator.calculate_realized_pnl",
        return_value=(0.0, "CNY"),
        create=True,
    ):
        section = MarkdownContextGenerator(db)._section_4_holdings_detail()

    assert "| Property A |" not in section
    assert "Rebalanceable" not in section
    assert "| Cash Total |" in section
    assert "| CASH_TOTAL |" in section
    assert "Cash Account 1" not in section
    assert "Cash Account 2" not in section


ACCOUNT_RETURNS = {
    "scope": "investment_accounts", "currency": "CNY", "period": "all_time",
    "twr_cumulative": 12.34, "twr_annualized": 8.12, "mwr_xirr": 10.2,
    "twr_period_start": "2020-01-31", "twr_as_of": "2026-08-31",
    "mwr_period_start": "2020-01-31", "mwr_as_of": "2026-08-31",
    "twr_review_state": "candidate", "mwr_review_state": "candidate",
    "twr_method": "monthly_modified_dietz", "mwr_method": "dated_external_flow_xirr",
    "mwr_solver_status": "solved_ambiguity_not_ruled_out",
}


def test_export_risk_uses_same_account_result_and_loss_sign():
    db = _make_db_mock(asset_perf_rows=[], tx_asset_rows=[])
    with patch('src.services.context_generator.build_investment_returns', return_value=ACCOUNT_RETURNS), patch(
        'src.services.context_generator.build_investment_risk', return_value={
            'scope': 'investment_accounts', 'quality': 'estimated', 'period_start': '2020-01-31',
            'as_of': '2026-08-31', 'max_drawdown': 4.7, 'volatility_annual': 8.1, 'data_points': 79,
        }
    ) as calculator:
        text = MarkdownContextGenerator(db)._section_2_performance()
    calculator.assert_called_once_with(db, account_result=ACCOUNT_RETURNS)
    assert 'Max Drawdown: -4.70%' in text
    assert 'Volatility (Annualized): 8.10%' in text
    assert 'Data Points: 79 monthly returns' in text
    assert '2020-01-31 to 2026-08-31' in text
    risk_text = text.split('### 2.3')[1]
    assert 'separate' not in risk_text and 'Rebalanceable Only' not in risk_text


def test_export_holdings_omit_noise_and_near_zero_cost_return():
    db = _make_db_mock(holdings_rows=[
        ('Tiny', 'TINY', 'Equity', 'US Equity', .5, 1, .1, 'CNY', .1, True),
        ('Sold', 'SOLD', 'Equity', 'US Equity', 100, 0, 0, 'CNY', 10, True),
        ('Open', 'OPEN', 'Equity', 'US Equity', 100, 1, .01, 'CNY', 10, True),
    ], costs={'OPEN': .01})
    text = MarkdownContextGenerator(db)._section_4_holdings_detail()
    assert 'Tiny' not in text and 'Sold' not in text
    assert '| Open |' in text
    assert '| — | 100.00% |' in text
    assert '999900' not in text
    assert '| — |' in text
