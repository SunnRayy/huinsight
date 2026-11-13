"""Investment TWR uses account valuations and explicit boundary flows."""

import json

import duckdb
import pytest

from src.financial_analysis.twr import (
    calculate_portfolio_twr, _input_fingerprint, _valuation_fingerprint,
)


@pytest.fixture(autouse=True)
def isolate_flow_visibility(monkeypatch):
    # Metric-only fixtures predate flow tables; full coverage contracts have their own synthetic schema.
    monkeypatch.setattr('src.financial_analysis.flow_coverage.coverage_status', lambda db: {
        'frozen_end': None, 'coverage_end': None, 'next_month': None, 'blockers': [],
    })


@pytest.fixture
def db():
    connection = duckdb.connect(':memory:')
    connection.execute('CREATE TABLE balance_sheet_monthly '
                       '(snapshot_date DATE, payload JSON, record_key VARCHAR, source_system VARCHAR)')
    connection.execute('''
        CREATE TABLE investment_twr_source (
            coverage_start DATE, coverage_end DATE, quality VARCHAR,
            valuation_sha256 VARCHAR, input_fingerprint VARCHAR
        )
    ''')
    connection.execute('''
        CREATE TABLE investment_external_flows (
            flow_id VARCHAR, event_date DATE, amount_cny DECIMAL(18,2),
            original_amount DECIMAL(18,2), original_currency VARCHAR,
            fx_date DATE, fx_cny_per_native DECIMAL(18,10), source VARCHAR,
            kind VARCHAR, evidence_status VARCHAR, evidence VARCHAR,
            date_basis VARCHAR
        )
    ''')
    connection.execute("INSERT INTO investment_twr_source (coverage_start, coverage_end, quality) VALUES ('2025-01-31', '2025-03-31', 'estimated')")
    for month, invest, household in [
        ('2025-01-01', 1000, 1_000_000),
        ('2025-02-01', 1210, 9_000_000),
        ('2025-03-01', 1331, 100),
    ]:
        payload = {
            '投资资产_股票基金_A股基金': invest,
            '投资资产_股票基金_美股基金_Schwab': 0,
            '投资资产_股票基金_美股基金_IBKR': 0,
            '投资资产_公司RSU_Amazon Stock': 0,
            '投资资产_公司RSU_Google Stock': 0,
            '投资资产_黄金_纸黄金(元)': 0,
            '合计总资产': household,
            '投资资产_股票基金_美股基金_Schwab_USD': 9999,
        }
        connection.execute('INSERT INTO balance_sheet_monthly VALUES (?, ?, ?, ?)',
                           [month, json.dumps(payload), month, 'Financial_Summary_Excel'])
    connection.execute(
        'UPDATE investment_twr_source SET valuation_sha256 = ?',
        [_valuation_fingerprint(connection, '2025-01-31', '2025-03-31')],
    )
    connection.execute("""
        INSERT INTO investment_external_flows VALUES
        ('deposit', '2025-02-15', 100, 100, 'CNY', '2025-02-15', 1,
         'TTFund', 'external_deposit', 'confirmed', 'synthetic', 'posted')
    """)
    connection.execute(
        'UPDATE investment_twr_source SET input_fingerprint = ?',
        [_input_fingerprint(connection, '2025-01-31', '2025-03-31')],
    )
    try:
        yield connection
    finally:
        connection.close()


def test_uses_investment_valuations_and_only_explicit_boundary_flows(db):
    result = calculate_portfolio_twr(db)
    assert result is not None
    # First period: (1210 - 1000 - 100) / (1000 + 100 * 13/28).
    first = 110 / (1000 + 100 * 13 / 28)
    second = (1331 - 1210) / 1210
    assert result['cumulative'] == pytest.approx((1 + first) * (1 + second) - 1)
    assert result['estimated'] is True
    assert result['as_of'] == '2025-03-31'
    assert result['flow_count'] == 1


def test_scope_filter_does_not_change_fixed_investment_boundary(db):
    all_assets = calculate_portfolio_twr(db)
    filtered = calculate_portfolio_twr(db, include_asset_ids=['property'], exclude_non_balanceable=True)
    assert filtered['cumulative'] == all_assets['cumulative']


def test_no_flow_coverage_returns_unavailable(db):
    db.execute('DELETE FROM investment_twr_source')
    assert calculate_portfolio_twr(db) is None


def test_month_gap_returns_unavailable(db):
    db.execute("DELETE FROM balance_sheet_monthly WHERE snapshot_date = '2025-02-01'")
    assert calculate_portfolio_twr(db) is None


def test_start_date_uses_prior_month_end_as_base(db):
    result = calculate_portfolio_twr(db, start_date='2025-03-01')
    assert result is not None
    assert result['period_start'] == '2025-02-28'
    assert result['cumulative'] == pytest.approx(0.10)


def test_no_current_holdings_terminal_point(db):
    db.execute('CREATE TABLE holdings (snapshot_date DATE, market_value DOUBLE)')
    db.execute("INSERT INTO holdings VALUES ('2025-04-01', 99999999)")
    result = calculate_portfolio_twr(db)
    assert result['as_of'] == '2025-03-31'


def test_account_xirr_matches_twr_dates_and_uses_dated_cny_inputs(db, monkeypatch):
    from datetime import date
    from src.financial_analysis.xirr import calculate_investment_account_xirr, xnpv

    monkeypatch.setattr('src.financial_analysis.xirr.get_currency_service',
                        lambda: pytest.fail('Account returns must not request current FX'))
    twr = calculate_portfolio_twr(db)
    result = calculate_investment_account_xirr(db)
    assert result['solver_status'] == 'solved'
    for key in ('period_start', 'as_of', 'scope', 'input_fingerprint', 'review_state'):
        assert result[key] == twr[key]
    vector = [(date(2025, 1, 31), -1000), (date(2025, 2, 15), -100),
              (date(2025, 3, 31), 1331)]
    assert abs(xnpv(result['annualized'], vector)) < 0.01
    # A historical end date uses that month's value, never current holdings.
    historical = calculate_investment_account_xirr(db, end_date='2025-02-28')
    assert historical['as_of'] == '2025-02-28'
    assert abs(xnpv(historical['annualized'], vector[:2] + [(date(2025, 2, 28), 1210)])) < 0.01


def test_account_xirr_opening_value_excludes_earlier_funding(db):
    from src.financial_analysis.xirr import calculate_investment_account_xirr

    result = calculate_investment_account_xirr(db, start_date='2025-03-01')
    assert result['period_start'] == '2025-02-28'
    assert result['annualized'] == pytest.approx(1.1 ** (365 / 31) - 1)
    db.execute("UPDATE investment_external_flows SET amount_cny = 10000")
    assert calculate_investment_account_xirr(db) is None


def _bind_fixture_inputs(db):
    db.execute('UPDATE investment_twr_source SET valuation_sha256 = ?, input_fingerprint = ?', [
        _valuation_fingerprint(db, '2025-01-31', '2025-03-31'),
        _input_fingerprint(db, '2025-01-31', '2025-03-31'),
    ])


def test_xirr_requires_endpoints_but_not_intermediate_months(db):
    from src.financial_analysis.xirr import calculate_investment_account_xirr

    expected = calculate_investment_account_xirr(db)['annualized']
    db.execute("DELETE FROM balance_sheet_monthly WHERE snapshot_date = '2025-02-01'")
    _bind_fixture_inputs(db)
    assert calculate_portfolio_twr(db) is None
    assert calculate_investment_account_xirr(db)['annualized'] == pytest.approx(expected)
    # Requested missing endpoint must not silently roll back to January.
    assert calculate_investment_account_xirr(db, end_date='2025-02-28') is None


def test_twr_short_window_ignores_bound_missing_value_outside_window(db):
    row = db.execute("SELECT payload FROM balance_sheet_monthly WHERE snapshot_date = '2025-01-01'").fetchone()
    payload = json.loads(row[0])
    payload['投资资产_股票基金_A股基金'] = None
    db.execute("UPDATE balance_sheet_monthly SET payload = ? WHERE snapshot_date = '2025-01-01'",
               [json.dumps(payload)])
    _bind_fixture_inputs(db)
    assert calculate_portfolio_twr(db) is None
    short = calculate_portfolio_twr(db, start_date='2025-03-01')
    assert short['period_start'] == '2025-02-28'
    assert short['cumulative'] == pytest.approx(0.10)


@pytest.mark.parametrize('include_non_rebalanceable', [False, True])
def test_wealthos_and_returns_share_account_result_and_dates(db, include_non_rebalanceable):
    import asyncio
    from unittest.mock import AsyncMock, patch
    from src.api.routes.data import get_wealthos_summary
    from src.api.routes.performance import get_performance_returns

    db.execute('CREATE TABLE transactions (asset_id VARCHAR)')
    returns = asyncio.run(get_performance_returns(period='all_time', db=db))
    with patch('src.api.routes.performance.get_performance_summary', new=AsyncMock(return_value={})):
        summary = asyncio.run(get_wealthos_summary(
            include_non_rebalanceable=include_non_rebalanceable, db=db,
        ))
    route_only = {'coverage_status', 'locked_history_corrections'}  # added by the returns route
    assert summary['account_returns'] == {k: v for k, v in returns.items() if k not in route_only}
    assert summary['annualized_return'] == returns['mwr_xirr']
    assert summary['account_returns']['mwr_as_of'] == '2025-03-31'
    assert summary['account_returns']['scope'] == 'investment_accounts'


def test_shared_account_result_does_not_substitute_legacy_xirr(db):
    import asyncio
    from unittest.mock import patch
    from src.api.routes.performance import get_performance_returns

    db.execute('DELETE FROM investment_twr_source')
    with patch('src.financial_analysis.xirr.calculate_portfolio_xirr', side_effect=AssertionError('legacy XIRR')):
        result = asyncio.run(get_performance_returns(period='all_time', db=db))
    assert result['mwr_xirr'] is None
    assert result['twr_cumulative'] is None
    assert result['mwr_quality'] == 'unavailable'
