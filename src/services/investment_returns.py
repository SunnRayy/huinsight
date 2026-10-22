"""Shared fixed-boundary investment-account return result assembly."""
from datetime import date

from src.financial_analysis.twr import calculate_portfolio_twr, investment_twr_unavailable_reason, load_investment_return_inputs
from src.financial_analysis.xirr import calculate_investment_account_xirr


def build_investment_returns(db, period: str = "all_time") -> dict:
    """Assemble existing account calculations in the API's percentage units."""
    # Both metrics share the investment boundary; XIRR needs only endpoint values.
    twr_source = calculate_portfolio_twr(db)
    mwr_source = calculate_investment_account_xirr(db)
    source = twr_source or mwr_source
    qualified_end = date.fromisoformat(source['as_of']) if source else None
    window_start = None
    if qualified_end and period in ("last_12m", "last_36m"):
        years = 1 if period == "last_12m" else 3
        # March 1 selects the preceding February month-end in leap-year windows.
        try:
            window_start = qualified_end.replace(year=qualified_end.year - years).isoformat()
        except ValueError:
            window_start = date(qualified_end.year - years, 3, 1).isoformat()
    twr_result = (calculate_portfolio_twr(db, start_date=window_start)
                  if window_start else twr_source)
    twr = twr_result["cumulative"] if twr_result else None
    twr_annualized = twr_result["annualized"] if twr_result else None
    mwr_result = (calculate_investment_account_xirr(db, start_date=window_start)
                  if window_start else mwr_source)
    mwr = mwr_result['annualized'] if mwr_result else None

    today = date.today()
    twr_ytd_result = calculate_portfolio_twr(
        db, start_date=date(today.year, 1, 1).isoformat(),
    ) if qualified_end and qualified_end.year == today.year else None
    twr_ytd = twr_ytd_result["cumulative"] if twr_ytd_result else None
    if qualified_end:
        try:
            one_year_start = qualified_end.replace(year=qualified_end.year - 1).isoformat()
        except ValueError:
            one_year_start = date(qualified_end.year - 1, 3, 1).isoformat()
        twr_1y_result = calculate_portfolio_twr(db, start_date=one_year_start)
    else:
        twr_1y_result = None
    twr_1y = twr_1y_result["cumulative"] if twr_1y_result else None

    account_series = []
    investment_bridge = None
    if twr_result:
        investment_bridge = {
            'period_start': twr_result['period_start'],
            'period_end': twr_result['as_of'],
            'opening_value_cny': twr_result['start_value_cny'],
            'net_external_flow_cny': twr_result['net_external_flow_cny'],
            'investment_gain_cny': twr_result['investment_gain_cny'],
            'closing_value_cny': twr_result['end_value_cny'],
        }

        inputs = load_investment_return_inputs(db, twr_result['period_start'], twr_result['as_of'])
        if inputs:
            invested = inputs['snapshots'][0]['value']
            flows = iter(inputs['cashflows'])
            flow = next(flows, None)
            for point in inputs['snapshots']:
                while flow is not None and flow['date'] <= point['date']:
                    invested += flow['amount']
                    flow = next(flows, None)
                account_series.append(dict(date=point['date'].isoformat(),
                                           value_cny=point['value'], invested_cny=invested))

    return {
        "account_series": account_series,
        "history_changed_since_review": bool(source and source.get("history_changed_since_review")),
        "scope": "investment_accounts",
        "currency": "CNY",
        "period": period,
        "input_fingerprint": source.get('input_fingerprint') if source else None,
        "mwr_method": mwr_result.get('method', 'dated_external_flow_xirr') if mwr_result else None,
        "mwr_unavailable_reason": (None if mwr is not None else
            mwr_result['solver_status'] if mwr_result else 'coverage_or_endpoint_unavailable'),
        "twr_cumulative": round(twr * 100, 2) if twr is not None else None,
        "twr_annualized": twr_annualized * 100 if twr_annualized is not None else None,
        "twr_ytd": round(twr_ytd * 100, 2) if twr_ytd is not None else None,
        "twr_1y": round(twr_1y * 100, 2) if twr_1y is not None else None,
        "twr_quality": "estimated" if twr_result else "unavailable",
        "twr_review_state": twr_result['review_state'] if twr_result else None,
        "twr_unavailable_reason": None if twr_result else investment_twr_unavailable_reason(db),
        "investment_bridge": investment_bridge,
        "twr_scope": "investment_accounts" if twr_result else None,
        "twr_as_of": qualified_end.isoformat() if qualified_end else None,
        "twr_period_start": twr_result['period_start'] if twr_result else None,
        "twr_ytd_start": twr_ytd_result['period_start'] if twr_ytd_result else None,
        "twr_1y_start": twr_1y_result['period_start'] if twr_1y_result else None,
        "twr_method": twr_result['method'] if twr_result else None,
        "mwr_xirr": round(mwr * 100, 2) if mwr is not None else None,
        "mwr_quality": "estimated" if mwr is not None else "unavailable",
        "mwr_scope": mwr_result['scope'] if mwr_result else None,
        "mwr_period_start": mwr_result['period_start'] if mwr_result else None,
        "mwr_as_of": mwr_result['as_of'] if mwr_result else None,
        "mwr_review_state": mwr_result['review_state'] if mwr_result else None,
        "mwr_solver_status": mwr_result['solver_status'] if mwr_result else None,
    }


def format_account_returns(result: dict) -> str:
    """Render safe account facts identically in both AI context paths."""
    lines = ["Investment-account returns — fixed investment_accounts scope; CNY.",
             "Includes Schwab, IBKR, TTFund, vested RSU, paper gold and their cash/receivables; excludes household cash, bank investments, pension, insurance and property.",
             "Monthly values and some flow dates are approximate."]
    for label, key, prefix in (("TWR (Cumulative)", "twr_cumulative", "twr"),
                               ("TWR (Annualized)", "twr_annualized", "twr"),
                               ("MWR (XIRR)", "mwr_xirr", "mwr")):
        value = result[key]
        display = (f"{value:.2f}%" if value is not None else
                   f"N/A ({result.get(prefix + '_unavailable_reason') or 'unavailable'})")
        details = ""
        if result.get(prefix + '_period_start') and result.get(prefix + '_as_of'):
            details = (f" (estimated inputs; {result[prefix + '_period_start']} to "
                       f"{result[prefix + '_as_of']}; {result.get(prefix + '_review_state')}; "
                       f"method={result.get(prefix + '_method')})")
        lines.append(f"- {label}: {display}{details}.")
    lines.append(f"- XIRR solver: {result.get('mwr_solver_status') or 'unavailable'}.")
    if result.get('mwr_solver_status') == 'solved_ambiguity_not_ruled_out':
        lines.append("- XIRR warning: finite root scanning cannot rule out ambiguity.")
    return "\n".join(lines)
