import pytest
from datetime import date
from src.financial_analysis.risk_calculator import calculate_portfolio_risk

def test_risk_calculation_balanced():
    # 50% Equity, 50% Bonds
    weights = {'股票': 0.5, '固定收益': 0.5}
    metrics = calculate_portfolio_risk(weights)
    
    # Equity Vol 18%, Bond Vol 6% -> Avg 12%
    assert metrics['volatility'] == pytest.approx(12.0)
    assert metrics['volatility_status'] in ["LOW", "MED", "HIGH"]
    assert metrics['sharpe'] > 0

def test_risk_calculation_conservative():
    # 100% Cash
    weights = {'现金': 1.0}
    metrics = calculate_portfolio_risk(weights)
    
    # Cash Vol 0.5%
    assert metrics['volatility'] == pytest.approx(0.5)
    assert metrics['volatility_status'] == "LOW"

def test_risk_calculation_empty():
    metrics = calculate_portfolio_risk({})
    assert metrics['volatility'] == 0


def test_account_risk_deposit_does_not_create_return_or_drawdown():
    from src.services.investment_risk import risk_from_inputs
    inputs = {'snapshots': [{'date': date(2026, 7, 31), 'value': 100},
                            {'date': date(2026, 8, 31), 'value': 200}],
              'cashflows': [{'date': date(2026, 8, 15), 'amount': 100}]}
    result = risk_from_inputs(inputs)
    assert result['total_return'] == pytest.approx(0)
    assert result['max_drawdown'] == 0
    assert result['volatility_annual'] is None
    assert result['data_points'] == 1


def test_account_risk_monthly_annualization_and_compounded_drawdown():
    import calendar
    import math
    import statistics
    from src.services.investment_risk import risk_from_inputs
    points = [{'date': date(2025, 12, 31), 'value': 100}]
    returns = [0.1, -0.1] * 6
    for month, rate in enumerate(returns, 1):
        points.append({'date': date(2026, month, calendar.monthrange(2026, month)[1]),
                       'value': points[-1]['value'] * (1 + rate)})
    result = risk_from_inputs({'snapshots': points, 'cashflows': []})
    assert result['volatility_annual'] == pytest.approx(statistics.stdev(returns) * math.sqrt(12) * 100)
    rf = 1.03 ** (1 / 12) - 1
    assert result['sharpe_ratio'] == pytest.approx(-rf / statistics.stdev(returns) * math.sqrt(12))
    assert result['total_return'] == pytest.approx((0.99 ** 6 - 1) * 100)
    assert result['max_drawdown'] == pytest.approx((1 - 0.99 ** 6 / 1.1) * 100)
    assert result['calmar_ratio'] is not None


def test_account_risk_missing_month_is_not_filled_with_zero():
    from src.services.investment_risk import risk_from_inputs
    result = risk_from_inputs({'snapshots': [{'date': date(2026, 1, 31), 'value': 100},
                                           {'date': date(2026, 3, 31), 'value': 110}],
                              'cashflows': []})
    assert result['total_return'] is None
    assert result['reason'] == 'monthly_series_incomplete'
