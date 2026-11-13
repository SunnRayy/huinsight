"""Estimated investment-account time-weighted return from monthly valuations."""

import calendar
import hashlib
import json
import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, List, Optional

INVESTMENT_VALUE_COLUMNS = (
    '投资资产_股票基金_A股基金',
    '投资资产_股票基金_美股基金_Schwab',
    '投资资产_股票基金_美股基金_IBKR',
    '投资资产_公司RSU_Amazon Stock',
    '投资资产_公司RSU_Google Stock',
    '投资资产_黄金_纸黄金(元)',
)


def calculate_twr_from_snapshots(snapshots: List[dict], cashflows: List[dict]) -> Optional[float]:
    """Chain monthly Modified Dietz returns; positive flow enters the boundary."""
    if len(snapshots) < 2:
        return None
    snapshots = sorted(snapshots, key=lambda point: point['date'])
    cashflows = sorted(cashflows, key=lambda flow: flow['date'])
    cumulative = 1.0
    for start, end in zip(snapshots, snapshots[1:]):
        days = (end['date'] - start['date']).days
        if days <= 0 or start['value'] <= 0 or end['value'] < 0:
            return None
        period = [flow for flow in cashflows if start['date'] < flow['date'] <= end['date']]
        net = sum(flow['amount'] for flow in period)
        weighted = sum(flow['amount'] * (end['date'] - flow['date']).days / days for flow in period)
        denominator = start['value'] + weighted
        if denominator <= 0:
            return None
        cumulative *= 1 + (end['value'] - start['value'] - net) / denominator
    return cumulative - 1


def _to_date(value) -> date:
    if isinstance(value, date):
        return value.date() if hasattr(value, 'date') else value
    return date.fromisoformat(str(value))


def _month_end(label: date) -> date:
    return date(label.year, label.month, calendar.monthrange(label.year, label.month)[1])


def _valuation_fingerprint(db: Any, coverage_start, coverage_end) -> str:
    """Hash covered investment values and their stored source identities."""
    first = _to_date(coverage_start).replace(day=1)
    last = _to_date(coverage_end)
    rows = db.execute(
        'SELECT snapshot_date, payload, record_key, source_system FROM balance_sheet_monthly '
        'WHERE snapshot_date >= ? AND snapshot_date <= ? ORDER BY snapshot_date',
        [first, last],
    ).fetchall()
    values = []
    for day, payload, record_key, source_system in rows:
        data = json.loads(payload) if isinstance(payload, str) else payload
        values.append([str(day), record_key, source_system, [
            [key in data, _canonical_number(data.get(key))]
            if isinstance(data, dict) else [False, None]
            for key in INVESTMENT_VALUE_COLUMNS
        ]])
    encoded = json.dumps(values, ensure_ascii=False, separators=(',', ':'), default=str)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _valuation_identity_fingerprint(db, start, end):
    rows = db.execute('SELECT snapshot_date, record_key, source_system FROM balance_sheet_monthly '
                      'WHERE snapshot_date >= ? AND snapshot_date <= ? ORDER BY snapshot_date',
                      [_to_date(start).replace(day=1), _to_date(end)]).fetchall()
    return hashlib.sha256(json.dumps(rows, default=str, ensure_ascii=False).encode()).hexdigest()


def _canonical_number(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    return str(number.normalize()) if number.is_finite() else str(value)


def _input_fingerprint(db: Any, coverage_start, coverage_end, *, valuation_sha=None) -> str:
    """Bind valuation, flow, scope, FX and timing policy to one input version."""
    flow_rows = db.execute('''
        SELECT flow_id, event_date, amount_cny, original_amount,
               original_currency, fx_date, fx_cny_per_native, source, kind,
               evidence_status, evidence, date_basis
        FROM investment_external_flows ORDER BY flow_id
    ''').fetchall()
    flows = []
    for row in flow_rows:
        flows.append([
            value.isoformat() if isinstance(value, date)
            else _canonical_number(value) if isinstance(value, (Decimal, float, int))
            else value for value in row
        ])
    document = {
        'version': 2,
        'coverage': [_to_date(coverage_start).isoformat(), _to_date(coverage_end).isoformat()],
        'scope': ['Schwab', 'IBKR', 'TTFund', 'Gold', 'RSU'],
        'valuation_columns': INVESTMENT_VALUE_COLUMNS,
        'valuation_date_policy': 'monthly_label_as_approximate_month_end',
        'fx_policy': 'source_dated_rate_max_5_days',
        'valuation_sha256': valuation_sha or _valuation_fingerprint(db, coverage_start, coverage_end),
        'flows': flows,
    }
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _investment_value(payload) -> Optional[float]:
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict) or any(key not in data for key in INVESTMENT_VALUE_COLUMNS):
        return None
    values = []
    for key in INVESTMENT_VALUE_COLUMNS:
        raw = data[key]
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        values.append(value)
    return sum(values)


def investment_twr_unavailable_reason(db: Any) -> str:
    """Return a stable operator-facing reason when the estimate is unavailable."""
    present = db.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name = 'investment_twr_source'"
    ).fetchall()
    if not present:
        return 'source_not_imported'
    columns = {row[1] for row in db.execute("PRAGMA table_info('investment_twr_source')").fetchall()}
    fields = 'coverage_start, coverage_end, quality, valuation_sha256, input_fingerprint, invalid_reason'
    if not {'valuation_sha256', 'input_fingerprint', 'invalid_reason'} <= columns:
        return 'valuation_changed_or_incomplete'
    rows = db.execute(f'SELECT {fields} FROM investment_twr_source LIMIT 2').fetchall()
    if len(rows) != 1:
        return 'source_not_imported'
    start, end, quality, valuation_sha, input_sha, invalid_reason = rows[0]
    if quality != 'estimated':
        return invalid_reason or 'source_invalid'
    if not valuation_sha or _valuation_fingerprint(db, start, end) != valuation_sha:
        return 'valuation_changed_or_incomplete'
    if not input_sha or _input_fingerprint(db, start, end) != input_sha:
        return 'input_changed_or_incomplete'
    covered = db.execute(
        'SELECT payload FROM balance_sheet_monthly WHERE snapshot_date >= ? '
        'AND snapshot_date <= ? ORDER BY snapshot_date',
        [_to_date(start).replace(day=1), _to_date(end)],
    ).fetchall()
    if any(_investment_value(payload) is None for (payload,) in covered):
        return 'valuation_changed_or_incomplete'
    return 'coverage_or_valuation_incomplete'


def load_investment_return_inputs(
    db: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_asset_ids: Optional[List[str]] = None,
    exclude_non_balanceable: bool = False,
    *,
    require_monthly_values: bool = True,
) -> Optional[dict]:
    """Load matched investment values and external flows within explicit coverage.

    Household and rebalanceability filters do not redefine this fixed boundary.
    Raw trade types are never interpreted as external flows.
    """
    del include_asset_ids, exclude_non_balanceable
    available = db.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('investment_twr_source', 'investment_external_flows')
    """).fetchall()
    if {row[0] for row in available} != {'investment_twr_source', 'investment_external_flows'}:
        return None
    source_columns = {row[1] for row in db.execute("PRAGMA table_info('investment_twr_source')").fetchall()}
    if not {'valuation_sha256', 'input_fingerprint'} <= source_columns:
        return None
    source_rows = db.execute(
        'SELECT coverage_start, coverage_end, quality, valuation_sha256, input_fingerprint '
        'FROM investment_twr_source LIMIT 2'
    ).fetchall()
    if (len(source_rows) != 1 or source_rows[0][2] != 'estimated'
            or not source_rows[0][3] or not source_rows[0][4]):
        return None
    coverage_start, coverage_end = map(_to_date, source_rows[0][:2])
    if (coverage_end <= coverage_start or coverage_start != _month_end(coverage_start)
            or coverage_end != _month_end(coverage_end)):
        return None
    history_changed = _valuation_fingerprint(db, coverage_start, coverage_end) != source_rows[0][3]
    # A valuation edit remains visible. Flow/evidence edits still fail closed.
    if _input_fingerprint(db, coverage_start, coverage_end, valuation_sha=source_rows[0][3]) != source_rows[0][4]:
        return None
    if 'history_changed_since_review' in source_columns:
        stored = db.execute('SELECT history_changed_since_review, frozen_coverage_end, '
                            'frozen_valuation_sha256, valuation_identity_sha256 '
                            'FROM investment_twr_source WHERE id = 1').fetchone()
        if history_changed and (not stored[1] or not stored[3] or
                _valuation_identity_fingerprint(db, coverage_start, coverage_end) != stored[3]):
            return None
        history_changed = history_changed or bool(stored[0])
        if stored[1] and stored[2]:
            history_changed = history_changed or _valuation_fingerprint(db, coverage_start, stored[1]) != stored[2]
    elif history_changed:
        return None

    reviewed = db.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name = 'investment_twr_reviews'"
    ).fetchone()
    review_state = 'candidate'
    if reviewed and db.execute(
        'SELECT 1 FROM investment_twr_reviews WHERE input_fingerprint = ?',
        [source_rows[0][4]],
    ).fetchone():
        review_state = 'reviewed' if not history_changed else 'candidate'

    # Select calendar endpoints before inspecting values: an unrelated missing month
    # must not block a valid shorter window, nor may we silently skip a missing endpoint.
    def preceding_month_end(day):
        end = _month_end(day)
        if day == end:
            return end
        return day.replace(day=1) - timedelta(days=1)

    first = preceding_month_end(_to_date(start_date)) if start_date else coverage_start
    last = min(preceding_month_end(_to_date(end_date)), coverage_end) if end_date else coverage_end
    if first < coverage_start or first >= last:
        return None
    if require_monthly_values:
        values = db.execute(
            'SELECT snapshot_date, payload FROM balance_sheet_monthly '
            'WHERE snapshot_date >= ? AND snapshot_date <= ? ORDER BY snapshot_date',
            [first.replace(day=1), last],
        ).fetchall()
    else:
        values = db.execute(
            'SELECT snapshot_date, payload FROM balance_sheet_monthly '
            'WHERE snapshot_date IN (?, ?) ORDER BY snapshot_date',
            [first.replace(day=1), last.replace(day=1)],
        ).fetchall()
    snapshots = []
    for raw_date, payload in values:
        label = _to_date(raw_date)
        if label.day != 1:
            return None
        point_date = _month_end(label)
        amount = _investment_value(payload)
        if amount is None or amount <= 0:
            return None
        if snapshots and point_date <= snapshots[-1]['date']:
            return None
        if require_monthly_values and snapshots and (label.year * 12 + label.month) - (
            snapshots[-1]['date'].year * 12 + snapshots[-1]['date'].month
        ) != 1:
            return None
        snapshots.append({'date': point_date, 'value': amount})
    if (len(snapshots) < 2 or snapshots[0]['date'] != first
            or snapshots[-1]['date'] != last):
        return None

    first, last = snapshots[0]['date'], snapshots[-1]['date']
    flow_rows = db.execute(
        'SELECT event_date, amount_cny FROM investment_external_flows '
        'WHERE event_date > ? AND event_date <= ? ORDER BY event_date, flow_id',
        [first, last],
    ).fetchall()
    cashflows = [{'date': _to_date(day), 'amount': float(amount)} for day, amount in flow_rows]
    if any(not math.isfinite(flow['amount']) for flow in cashflows):
        return None
    return {
        'snapshots': snapshots,
        'cashflows': cashflows,
        'estimated': True,
        'history_changed_since_review': history_changed,
        'review_state': review_state,
        'input_fingerprint': source_rows[0][4],
        'period_start': first.isoformat(),
        'as_of': last.isoformat(),
        'scope': 'investment_accounts',
    }


def calculate_portfolio_twr(
    db: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_asset_ids: Optional[List[str]] = None,
    exclude_non_balanceable: bool = False,
) -> Optional[dict]:
    """Chain monthly estimates using the same qualified inputs as account XIRR."""
    inputs = load_investment_return_inputs(
        db, start_date, end_date, include_asset_ids, exclude_non_balanceable,
    )
    if inputs is None:
        return None
    snapshots, cashflows = inputs['snapshots'], inputs['cashflows']
    first, last = snapshots[0]['date'], snapshots[-1]['date']
    cumulative = calculate_twr_from_snapshots(snapshots, cashflows)
    if cumulative is None or not math.isfinite(cumulative) or 1 + cumulative <= 0:
        return None
    days = (last - first).days
    annualized = (1 + cumulative) ** (365 / days) - 1 if days >= 365 else None
    net_external_flow = sum(flow['amount'] for flow in cashflows)
    return {
        **{key: value for key, value in inputs.items() if key not in ('snapshots', 'cashflows')},
        'cumulative': cumulative,
        'annualized': annualized,
        'flow_count': len(cashflows),
        'start_value_cny': snapshots[0]['value'],
        'end_value_cny': snapshots[-1]['value'],
        'net_external_flow_cny': net_external_flow,
        'investment_gain_cny': snapshots[-1]['value'] - snapshots[0]['value'] - net_external_flow,
        'method': 'monthly_modified_dietz',
    }
