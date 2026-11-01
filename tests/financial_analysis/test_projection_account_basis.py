"""Forecast and risk share a qualified, flow-adjusted monthly account window."""
import calendar
from datetime import date
from unittest.mock import patch

import pytest

from src.financial_analysis.projection_defaults import forecast_basis


def monthly_inputs(months):
    points = []
    value = 1000.0
    for i in range(months + 1):
        year, month = divmod(2019 * 12 + 10 + i, 12)
        day = date(year, month + 1, calendar.monthrange(year, month + 1)[1])
        if i:
            value *= 1 + (0.05 if i % 2 else -0.04)
        points.append({'date': day, 'value': value})
    return dict(snapshots=points, cashflows=[], period_start=points[0]['date'].isoformat(),
                as_of=points[-1]['date'].isoformat(), input_fingerprint='fixture',
                review_state='reviewed', scope='investment_accounts')


@pytest.mark.parametrize('months, measured', [(35, False), (36, True), (81, True)])
def test_basis_uses_same_account_window_and_requires_36_returns(months, measured):
    from src.services.investment_risk import risk_from_inputs
    inputs = monthly_inputs(months)
    account = dict(investment_bridge={'period_start': inputs['period_start'], 'period_end': inputs['as_of']},
                   twr_annualized=5.5, scope='investment_accounts', input_fingerprint='fixture')
    with patch('src.services.investment_returns.build_investment_returns', return_value=account), patch(
        'src.services.investment_risk.load_investment_return_inputs', return_value=inputs
    ):
        basis = forecast_basis(object())
    assert basis['return_basis'] == ('measured' if measured else 'assumption')
    assert basis['month_count'] == months
    if measured:
        assert basis['expected_return'] == pytest.approx(0.055)
        assert basis['volatility'] == pytest.approx(risk_from_inputs(inputs)['volatility_annual'] / 100)
        assert basis['window_start'] == '2019-11-30'
        assert basis['window_end'] == inputs['as_of']

# Reuse the existing isolated account schema, never a real portfolio database.
from tests.financial_analysis.test_estimated_investment_twr import db, isolate_flow_visibility  # noqa: E402,F401


@pytest.fixture
def measured_db(db):  # noqa: F811
    import json
    import math
    import statistics
    from src.financial_analysis.twr import _input_fingerprint, _valuation_fingerprint

    points = monthly_inputs(81)['snapshots']
    deviations = [1 if i % 2 else -1 for i in range(81)]
    scale = 0.15 / math.sqrt(12) / statistics.stdev(deviations)
    deviations = [v * scale for v in deviations]
    days = (points[-1]['date'] - points[0]['date']).days
    lo, hi = -0.1, 0.1
    for _ in range(70):
        mid = (lo + hi) / 2
        annualized = math.prod(1 + mid + v for v in deviations) ** (365 / days) - 1
        if annualized < 0.055:
            lo = mid
        else:
            hi = mid
    db.execute('DELETE FROM balance_sheet_monthly')
    db.execute('DELETE FROM investment_external_flows')
    value = 1000.0
    for i, point in enumerate(points):
        day = point['date']
        if i:
            flow_day = day.replace(day=15)
            amount = 50 if i % 3 else -20
            weight = (day - flow_day).days / (day - points[i-1]['date']).days
            value += amount + (mid + deviations[i-1]) * (value + weight * amount)
            db.execute("INSERT INTO investment_external_flows (flow_id, event_date, amount_cny) VALUES (?, ?, ?)",
                       [str(i), flow_day, amount])
        payload = {'投资资产_股票基金_A股基金': value,
                   '投资资产_股票基金_美股基金_Schwab': 0,
                   '投资资产_股票基金_美股基金_IBKR': 0,
                   '投资资产_公司RSU_Amazon Stock': 0,
                   '投资资产_公司RSU_Google Stock': 0,
                   '投资资产_黄金_纸黄金(元)': 0, '合计总资产': 9_999_999}
        db.execute('INSERT INTO balance_sheet_monthly VALUES (?, ?, ?, ?)',
                   [day.replace(day=1), json.dumps(payload), str(day), 'Financial_Summary_Excel'])
    db.execute('UPDATE investment_twr_source SET coverage_start=?, coverage_end=?',
               [points[0]['date'], points[-1]['date']])
    db.execute('UPDATE investment_twr_source SET valuation_sha256=?, input_fingerprint=?', [
        _valuation_fingerprint(db, points[0]['date'], points[-1]['date']),
        _input_fingerprint(db, points[0]['date'], points[-1]['date'])])
    return db


def test_measured_account_basis_matches_risk_and_reference_numbers(measured_db):
    from src.services.investment_risk import build_investment_risk
    basis = forecast_basis(measured_db)
    risk = build_investment_risk(measured_db)
    # Synthetic calibration proves the calculation.
    assert basis == pytest.approx(dict(expected_return=0.055, volatility=0.15,
        return_basis='measured', window_start='2019-11-30', window_end='2026-08-31', month_count=81))
    assert risk['volatility_annual'] == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_forecast_consumers_use_identical_account_basis(measured_db):
    from src.api.routes.analytics import get_projection_defaults
    from src.services.forecast_levers import compute_levers
    from src.services.north_star_glide import glide_path
    basis = forecast_basis(measured_db)
    with patch('src.services.north_star_glide._default_net_worth', return_value=100_000), patch(
        'src.services.north_star_glide._contribution_run_rate', return_value=(1000, 'available')
    ), patch('src.services.goal_resolver.resolve_north_star_goal', return_value=dict(
        target_amount=1_000_000, source='test', name='Test', goal_id=None, target_date=None,
        fallback_reason=None
    )), patch('src.services.investment_contributions.contributions_summary_v2', return_value={'window_start_month': None}):
        levers = compute_levers(measured_db)['base']
        glide = glide_path(measured_db)['assumptions']
        defaults = await get_projection_defaults(db=measured_db)
    for key, value in basis.items():
        for result in (levers, glide, defaults):
            assert result[key] == pytest.approx(value) if isinstance(value, float) else result[key] == value
    assert defaults['suggested_return'] == pytest.approx(0.055)
    assert defaults['suggested_volatility'] == pytest.approx(0.15)


@pytest.mark.parametrize('period, months', [('all_time', 81), ('last_36m', 36), ('last_12m', 12)])
@pytest.mark.asyncio
async def test_returns_api_series_bridge_and_period_window_match(measured_db, period, months):
    from src.api.routes.performance import get_performance_returns, get_risk_metrics
    from src.financial_analysis.twr import calculate_portfolio_twr
    result = await get_performance_returns(period=period, db=measured_db)
    risk = await get_risk_metrics(period=period, db=measured_db)
    series, bridge = result['account_series'], result['investment_bridge']
    assert len(series) == months + 1
    assert risk['data_points'] == months
    assert series[0]['date'] == bridge['period_start']
    assert series[-1]['date'] == bridge['period_end'] == '2026-08-31'
    assert series[0]['invested_cny'] == series[0]['value_cny'] == bridge['opening_value_cny']
    assert series[-1]['value_cny'] == bridge['closing_value_cny']
    assert series[-1]['invested_cny'] == pytest.approx(bridge['opening_value_cny'] + bridge['net_external_flow_cny'])
    assert series[-1]['value_cny'] - series[-1]['invested_cny'] == pytest.approx(bridge['investment_gain_cny'])
    assert result['twr_cumulative'] == round(calculate_portfolio_twr(measured_db, bridge['period_start'])['cumulative'] * 100, 2)


@pytest.mark.asyncio
async def test_monte_carlo_and_goals_defaults_share_basis_and_allow_overrides(measured_db):
    from types import SimpleNamespace
    from src.api.routes.analytics import get_projection, get_goal_probability
    with patch('src.financial_analysis.monte_carlo.calculate_portfolio_projection', return_value={}) as mc:
        result = await get_projection(db=measured_db, years=10, simulations=100,
            annual_return=None, annual_volatility=None, annual_contribution=0,
            goal_target=None, include_non_rebalanceable=False, seed=42)
    assert mc.call_args.kwargs['annual_return'] == pytest.approx(0.055)
    assert mc.call_args.kwargs['annual_volatility'] == pytest.approx(0.15)
    assert result['return_basis'] == 'measured'
    with patch('src.financial_analysis.goals.get_goal', return_value=SimpleNamespace(
        target_amount=1_000_000, months_remaining=120
    )), patch('src.services.north_star_glide._default_net_worth', return_value=100_000), patch(
        'src.services.north_star_glide._contribution_run_rate', return_value=(1000, 'available')
    ), patch('src.financial_analysis.goals.calculate_goal_probability', return_value=0.5) as goal:
        result = await get_goal_probability(goal_id=1, db=measured_db, annual_return=None, annual_volatility=None)
        assert goal.call_args.kwargs['annual_return'] == pytest.approx(0.055)
        assert goal.call_args.kwargs['annual_volatility'] == pytest.approx(0.15)
        assert result['return_basis'] == 'measured'
        await get_goal_probability(goal_id=1, db=measured_db, annual_return=0.07, annual_volatility=0.2)
        assert goal.call_args.kwargs['annual_return'] == 0.07
        assert goal.call_args.kwargs['annual_volatility'] == 0.2
