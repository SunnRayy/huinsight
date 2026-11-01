"""Fixed-boundary account risk from cash-flow-adjusted monthly estimates."""
import calendar
import math
import statistics

from src.financial_analysis.metrics import max_drawdown
from src.financial_analysis.twr import calculate_twr_from_snapshots, load_investment_return_inputs
from src.services.investment_returns import build_investment_returns

_METRICS = ('sharpe_ratio', 'sortino_ratio', 'max_drawdown', 'calmar_ratio',
            'volatility_annual', 'total_return')


def risk_from_inputs(inputs, annual_risk_free_rate=0.03):
    """Percent units for returns/volatility/drawdown; dimensionless ratios.

    Risk-free rate is an explicit fixed annual decimal assumption, not a dated
    feed. Monthly rate compounds to that annual assumption. Annual statistics
    require twelve consecutive monthly returns; drawdown uses observed months.
    """
    result = {key: None for key in _METRICS}
    result.update(scope='investment_accounts', currency='CNY', sampling='monthly',
                  periods_per_year=12, data_points=0, min_annual_return_points=12,
                  quality='unavailable', reason='account_window_unavailable',
                  drawdown_basis='month_end_observed',
                  risk_free={'annual_rate_decimal': annual_risk_free_rate,
                             'source': 'fixed_assumption', 'as_of': None})
    if not math.isfinite(annual_risk_free_rate) or annual_risk_free_rate <= -1:
        raise ValueError('Invalid annual risk-free assumption')
    if not inputs:
        return result
    for key in ('period_start', 'as_of', 'input_fingerprint', 'review_state'):
        result[key] = inputs.get(key)
    points, flows = inputs['snapshots'], inputs['cashflows']
    if any(p['date'].day != calendar.monthrange(p['date'].year, p['date'].month)[1] for p in points):
        result['reason'] = 'monthly_series_incomplete'
        return result
    returns = []
    for start, end in zip(points, points[1:]):
        if end['date'].year * 12 + end['date'].month - (
            start['date'].year * 12 + start['date'].month) != 1:
            result['reason'] = 'monthly_series_incomplete'
            return result
        rate = calculate_twr_from_snapshots([start, end], flows)
        if rate is None or not math.isfinite(rate) or rate <= -1:
            result['reason'] = 'monthly_return_invalid'
            return result
        returns.append(rate)
    if not returns:
        return result
    index = [1.0]
    for rate in returns:
        index.append(index[-1] * (1 + rate))
    dd = max_drawdown(index)
    result.update(total_return=(index[-1] - 1) * 100, max_drawdown=dd * 100,
                  data_points=len(returns), observation_count=len(points),
                  quality='estimated', reason='fewer_than_12_monthly_returns')
    if len(returns) < 12:
        return result
    mean, deviation = statistics.mean(returns), statistics.stdev(returns)
    monthly_rf = (1 + annual_risk_free_rate) ** (1 / 12) - 1
    downside = math.sqrt(sum(min(r - monthly_rf, 0) ** 2 for r in returns) / len(returns))
    days = (points[-1]['date'] - points[0]['date']).days
    result.update(
        volatility_annual=deviation * math.sqrt(12) * 100,
        sharpe_ratio=(mean - monthly_rf) / deviation * math.sqrt(12) if deviation else None,
        sortino_ratio=(mean - monthly_rf) / downside * math.sqrt(12) if downside else None,
        calmar_ratio=(index[-1] ** (365 / days) - 1) / dd if dd and days >= 365 else None,
        reason=None,
    )
    return result


def build_investment_risk(db, period='all_time', account_result=None):
    """Anchor risk to the same qualified account window as the Returns bridge."""
    account = account_result if account_result is not None else build_investment_returns(db, period)
    bridge = account.get('investment_bridge')
    if not bridge:
        return risk_from_inputs(None)
    inputs = load_investment_return_inputs(db, bridge['period_start'], bridge['period_end'])
    if inputs is not None and (inputs['input_fingerprint'] != account.get('input_fingerprint')
                              or inputs['scope'] != account.get('scope')
                              or inputs['period_start'] != bridge['period_start']
                              or inputs['as_of'] != bridge['period_end']):
        return risk_from_inputs(None)
    return risk_from_inputs(inputs)

