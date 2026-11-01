"""Read-only deterministic investment-boundary rules, independent of sync/network."""
import hashlib
import json
import math
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from src.financial_analysis.fx_daily import lookup_fx
from src.financial_analysis.twr import _canonical_number, _month_end, _to_date

SOURCE_NAMES = {'CN_Fund_Excel': 'TTFund', 'Schwab_CSV': 'Schwab',
                'Broker_IBKR': 'IBKR', 'Gold_Excel': 'Gold', 'RSU_Excel': 'RSU'}
CN_IN = {'银行卡定投', '银行卡支付买入', '活期宝充值'}
CN_OUT = {'卖出回银行卡', '活期宝快速取现', '活期宝普通取现'}
# 活期宝转入 = paying for a fund from the 活期宝 balance (internal), even though the
# linked bank card is shown on the row (reviewed history treats it as internal).
CN_INTERNAL = {'活期宝转入', '活期宝互转', '活期宝每日分红', '红利再投资', '份额调增', '份额调减'}


def _norm(text):
    # Pasted web cells carry newlines/spaces and full-width brackets ("超级转换\n(有充值)").
    return ''.join(str(text or '').split()).replace('（', '(').replace('）', ')')


def _cn_classify(row):
    raw, status = _norm(row['business_type']), _norm(row['status'])
    if status == '已撤单(已支付)':
        return None, None, 'CN cancelled paid application needs confirmation'
    if status.startswith('受理失败') or status.startswith('已撤单') or status == '无效申请':
        return None, None, None
    if status not in {'成功', '确认成功', '充值成功'}:
        return None, None, 'CN status needs confirmation'
    account = row.get('account') or ''
    card = bool(account.strip() and account.strip() not in {'--', '-'} and '活期宝' not in account)
    # 超级转换 (including "有充值") is internal: the reviewed history (2025-09 → 2026-08, 11 events)
    # never booked an external leg for it.
    if raw in CN_INTERNAL or raw.startswith('卖出回活期宝') or raw.startswith('超级转换'):
        return None, None, None
    if raw in CN_IN and card:
        value = _number(row.get('applied_value')) if row.get('applied_unit') == '元' else None
        return abs(value) if value is not None else None, 'cn_bank_in', None
    if raw in CN_OUT:
        value = (_number(row.get('confirmed_value')) if row.get('confirmed_unit') == '元'
                 else row.get('ledger_cash') if row.get('confirmed_unit') == '份' else None)
        return -abs(value) if value is not None else None, 'cn_bank_out', None
    if raw == '现金分红':
        if '活期宝' in account:
            return None, None, None
        if card:
            value = row.get('ledger_cash')
            return -abs(value) if value is not None else None, 'cn_bank_out', None
    return None, None, 'CN website business type or bank account needs confirmation'


def _cn_rows(db):
    cursor = db.execute('SELECT * FROM cn_platform_events ORDER BY event_date, event_time, event_key')
    events = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
    cursor = db.execute("SELECT * FROM transactions WHERE source_system='CN_Fund_Excel' "
                        "AND LOWER(transaction_type) IN ('sell','dividend_cash') ORDER BY transaction_date, id")
    ledger = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
    consumed = set()
    for row in events:
        row.update(source_system='CN_Fund_Excel', transaction_date=row['event_date'],
                   transaction_type='web', id=row['event_key'])
        needs_sell = (row['business_type'] in CN_OUT and row['confirmed_unit'] == '份')
        needs_dividend = row['business_type'] == '现金分红' and '活期宝' not in (row['account'] or '')
        if row['status'] not in {'成功', '确认成功', '充值成功'} or not (needs_sell or needs_dividend):
            continue
        for entry in ledger:
            if entry['id'] in consumed or entry['asset_id'] != 'CN_FUND_' + row['fund_code']:
                continue
            if abs((_to_date(entry['transaction_date']) - _to_date(row['event_date'])).days) > 10:
                continue
            if entry['transaction_type'].lower() != ('sell' if needs_sell else 'dividend_cash'):
                continue
            if needs_sell and (row['confirmed_value'] is None or entry['quantity'] is None or
                               abs(abs(float(entry['quantity'])) - float(row['confirmed_value'])) > .01 + 1e-9):
                continue
            value = _number(entry.get('amount_net'))
            if value is None:
                continue
            row['ledger_cash'] = abs(value)
            row['ledger_transaction_id'] = entry['id']
            consumed.add(entry['id'])
            break
    return events


def event_key(row):
    """Stable across destructive reader reimports that allocate new transaction IDs."""
    identity = row.get('source_event_key') or '|'.join(
        str(_canonical_number(row.get(k))) if k in {'quantity', 'price_unit', 'amount_gross'}
        else str(row.get(k) or '')
        for k in ('transaction_date', 'asset_id', 'transaction_type', 'quantity',
                  'price_unit', 'amount_gross', 'memo', 'account', 'raw_business_type')
    )
    return hashlib.sha256(f"{row['source_system']}|{identity}".encode()).hexdigest()


def _number(value):
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _classify(row):
    source, kind = row['source_system'], row['transaction_type'].lower()
    raw = row.get('raw_business_type') or ''
    gross, net = _number(row.get('amount_gross')), _number(row.get('amount_net'))
    if source == 'CN_Fund_Excel':
        return _cn_classify(row)
    if source == 'Schwab_CSV':
        action = (raw + ' ' + str(row.get('memo') or '')).lower()
        # Older rows keep only the transfer description ("Tfr <BANK>, <NAME>"), not the action.
        if 'moneylink' in action or action.strip().startswith('tfr '):
            return net, 'schwab_moneylink', None
        if kind in {'other', 'unknown'}:
            return None, None, 'Schwab unclassified cash action'
        return None, None, None
    if source == 'Broker_IBKR':
        if raw == 'Deposits/Withdrawals':
            return net, 'ibkr_cash', None
        return None, None, None
    if source == 'Gold_Excel':
        if kind == 'buy':
            return abs(gross) if gross is not None else None, 'gold_buy', None
        if kind == 'sell':
            return -abs(net) if net is not None else None, 'gold_sell', None
        if kind not in {'interest', 'interest_income'}:
            return None, None, 'Gold unknown transaction type'
        return None, None, None
    if source == 'RSU_Excel':
        if kind == 'vest':
            qty, price = _number(row.get('quantity')), _number(row.get('price_unit'))
            withheld = _number(row.get('tax_withheld_shares')) or 0
            amount = (qty - withheld) * price if qty is not None and price is not None and qty >= withheld else None
            return amount, 'rsu_net_vest', None
        if kind in {'sell', 'tax', 'tax_cover', 'sell_to_cover'}:
            received = abs(gross) - abs(_number(row.get('commission_fee')) or 0) if gross is not None else None
            if received is not None and received < 0:
                return None, None, 'RSU commission exceeds gross proceeds'
            return -abs(received) if received is not None else None, 'rsu_sale', None
        return None, None, 'RSU unknown transaction type'
    return None, None, None


UPLOAD_KEYS = {'Gold_Excel': 'gold', 'Schwab_CSV': 'schwab', 'RSU_Excel': 'rsu',
               'CN_Fund_Excel': 'cn_fund', 'Broker_IBKR': 'ibkr'}


def source_completeness(db, source, end):
    """Shared read-only evidence gate; an owner confirmation never creates a flow."""
    latest = db.execute("""
        SELECT MAX(day) FROM (
            SELECT MAX(transaction_date) AS day FROM transactions WHERE source_system = ?
            UNION ALL SELECT MAX(snapshot_date) FROM holdings WHERE source_system = ?
        )
    """, [source, source]).fetchone()[0]
    key = f'no-activity:{source}:{end:%Y-%m}'
    uploaded = db.execute("SELECT 1 FROM source_upload_history WHERE reader = ? "
                          "AND is_valid = TRUE AND CAST(uploaded_at AS DATE) > ? LIMIT 1",
                          [UPLOAD_KEYS[source], end]).fetchone()
    confirmed = db.execute("SELECT 1 FROM external_flow_decisions WHERE event_key = ? "
                           "AND decision = 'internal'", [key]).fetchone()
    if (latest is not None and _to_date(latest) >= end) or uploaded or confirmed:
        return None, None
    name = SOURCE_NAMES[source]
    latest_day = _to_date(latest) if latest else None
    # Activity already recorded inside the month: only a newer file can complete it, so never
    # offer "no activity" (a wrong click would silently drop real flows).
    active_in_month = latest_day is not None and latest_day >= end.replace(day=1)
    hint, reason = (('upload_newer', 'upload_needed') if active_in_month
                    else ('confirm_no_activity_or_upload', 'no_activity_unconfirmed'))
    return (dict(code='source_data_behind', source=name,
                 latest_date=latest_day.isoformat() if latest_day else None, action_hint=hint),
            dict(event_key=key, event_date=end, source=name, reason=reason,
                 latest_date=latest_day.isoformat() if latest_day else None))


def no_activity_reviews(db, after):
    from datetime import timedelta
    # Expose the next finished month even before its FS row arrives.
    last = db.execute('SELECT MAX(snapshot_date) FROM balance_sheet_monthly WHERE snapshot_date > ?', [after]).fetchone()[0]
    end = _month_end(after + timedelta(days=1))
    last = max(end, _month_end(_to_date(last))) if last else end
    reviews = []
    while end <= last and end < date.today():
        sources = db.execute("""
            WITH latest AS (
                SELECT asset_id, source_system, MAX(snapshot_date) AS day FROM holdings
                WHERE snapshot_date <= ? GROUP BY asset_id, source_system
            )
            SELECT DISTINCT h.source_system FROM holdings h JOIN latest l
            ON h.asset_id = l.asset_id AND h.source_system = l.source_system AND h.snapshot_date = l.day
            WHERE COALESCE(h.quantity, 0) <> 0 ORDER BY h.source_system
        """, [end]).fetchall()
        for (source,) in sources:
            if source in SOURCE_NAMES:
                _, review = source_completeness(db, source, end)
                if review:
                    reviews.append(review)
        end = _month_end(end + timedelta(days=1))
    return reviews


def derive_flows(db, after_date):
    """Return flow dictionaries and unresolved items without any writes or network."""
    after = _to_date(after_date)
    cursor = db.execute("SELECT * FROM transactions WHERE transaction_date > ? AND source_system <> 'CN_Fund_Excel' ORDER BY transaction_date, id", [after])
    rows = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
    rows.extend(row for row in _cn_rows(db) if _to_date(row['event_date']) > after)
    decisions = {r[0]: r[1:] for r in db.execute(
        'SELECT event_key, decision, amount_cny, note FROM external_flow_decisions').fetchall()}
    flows, reviews, seen = [], [], set()

    def emit(row, key, reason=None):
        source = SOURCE_NAMES[row['source_system']]
        day = _to_date(row['transaction_date'])
        amount, rule, problem = _classify(row) if reason is None else (None, None, reason)
        decision = decisions.get(key)
        status = 'auto_rule'
        currency = 'USD' if source in {'Schwab', 'IBKR', 'RSU'} else 'CNY'
        if decision:
            action, override, _ = decision
            if action == 'internal':
                return
            status = 'owner_decision'
            if override is not None:
                amount, currency = float(override), 'CNY'
                if action != 'manual':
                    amount = abs(amount) * (1 if action == 'external_in' else -1)
            elif action in {'external_in', 'external_out'}:
                if source == 'TTFund':
                    native = (_number(row.get('applied_value')) if action == 'external_in' and row.get('applied_unit') == '元'
                              else _number(row.get('confirmed_value')) if action == 'external_out' and row.get('confirmed_unit') == '元'
                              else row.get('ledger_cash'))
                else:
                    native = _number(row.get('amount_gross') if action == 'external_in' else row.get('amount_net'))
                amount = abs(native) * (1 if action == 'external_in' else -1) if native is not None else None
            problem, rule = None, 'owner_decision'
        if problem is None and amount is None and rule is None:
            return
        if problem is None and (amount is None or not math.isfinite(amount) or amount == 0):
            problem = 'Boundary amount unavailable or zero'
        fx = lookup_fx(db, day) if currency == 'USD' else (day, 1.0)
        if problem is None and fx is None:
            problem = 'Dated FX unavailable'
        if problem:
            if _month_end(day) >= date.today():
                return
            reviews.append(dict(event_key=key, event_date=day, source=source, reason=problem,
                                amount=amount if amount is not None else (
                                    _number(row.get('applied_value')) if row.get('applied_unit') == '元'
                                    else _number(row.get('amount_gross'))), currency=currency,
                                evidence=[row.get('id')]))
            return
        native = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        converted = (native * Decimal(str(fx[1]))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        flows.append(dict(flow_id='auto:' + key, event_date=day,
                          amount_cny=float(converted), original_amount=float(native),
                          original_currency=currency, fx_date=fx[0], fx_rate=fx[1],
                          source=source, kind=rule, rule_id=rule,
                          evidence=json.dumps(dict(event_id=row.get('id'), ledger_id=row.get('ledger_transaction_id'),
                                                   bank_receipt=row.get('bank_receipt')), default=str),
                          evidence_status=status, date_basis='transaction_date'))

    for row in rows:
        if row['source_system'] not in SOURCE_NAMES:
            continue
        key = row['event_key'] if row['source_system'] == 'CN_Fund_Excel' else event_key(row)
        if key not in seen:
            seen.add(key)
            emit(row, key)
    # No CTRN section is different from an explicitly present, empty section.
    from datetime import timedelta
    valuation_days = db.execute('SELECT snapshot_date FROM balance_sheet_monthly WHERE snapshot_date > ?', [after]).fetchall()
    holding_days = db.execute("SELECT snapshot_date FROM holdings WHERE source_system = 'Broker_IBKR' AND snapshot_date > ?", [after]).fetchall()
    last = max([_month_end(day) for (day,) in valuation_days + holding_days], default=after)
    month = (after + timedelta(days=1)).replace(day=1)
    months = []
    while _month_end(month) <= last and _month_end(month) < date.today():
        end = _month_end(month)  # only finished months can be asked about
        active = db.execute("""
            WITH latest AS (
                SELECT asset_id, MAX(snapshot_date) AS day FROM holdings
                WHERE source_system = 'Broker_IBKR' AND snapshot_date <= ? GROUP BY asset_id
            )
            SELECT 1 FROM holdings h JOIN latest l ON h.asset_id = l.asset_id AND h.snapshot_date = l.day
            WHERE h.source_system = 'Broker_IBKR' AND h.quantity <> 0 LIMIT 1
        """, [end]).fetchone()
        if active and end > after:
            months.append(month)
        month = (end + timedelta(days=1)).replace(day=1)
    for month in months:
        end = _month_end(month)
        if not db.execute("SELECT 1 FROM flow_source_coverage WHERE source = 'Broker_IBKR' "
                          "AND period_end >= ? AND period_start <= ? AND cash_transactions_present", [end, month]).fetchone():
            key = 'ibkr-unknown:' + end.isoformat()
            row = dict(source_system='Broker_IBKR', transaction_date=end, transaction_type='other')
            emit(row, key, 'IBKR deposits unknown')
    # Standalone manual entries use a dated key: manual:YYYY-MM-DD:<unique suffix>.
    for key, (action, amount, note) in decisions.items():
        if action == 'manual' and key.startswith('manual:') and key not in seen:
            day = date.fromisoformat(key.split(':')[1])
            if day > after:
                emit(dict(source_system='Broker_IBKR', transaction_date=day,
                          transaction_type='other'), key, 'manual')
    reviews.extend(no_activity_reviews(db, after))
    reviews.extend(fs_value_reviews(db, after))
    return flows, reviews


# Financial Summary valuation column → (reader source, asset) used to sanity-check the monthly value.
FS_VALUE_SOURCES = {
    '投资资产_股票基金_A股基金': ('CN_Fund_Excel', None),
    '投资资产_股票基金_美股基金_Schwab': ('Schwab_CSV', None),
    '投资资产_股票基金_美股基金_IBKR': ('Broker_IBKR', None),
    '投资资产_公司RSU_Amazon Stock': ('RSU_Excel', 'RSU_AMZN'),
    '投资资产_公司RSU_Google Stock': ('RSU_Excel', 'RSU_GOOG'),
    '投资资产_黄金_纸黄金(元)': ('Gold_Excel', None),
}
_FS_MIN_POSITION_CNY = 5000.0


def _position_value_cny(db, source, asset, end):
    """Rough month-end position value from reader data, only to catch a blank/zero FS cell.

    Returns None when a position exists but cannot be valued (e.g. no dated FX).
    """
    if source == 'RSU_Excel':
        # RSU holdings have no month-end snapshots: shares from the ledger × last known price.
        row = db.execute(
            "SELECT SUM(quantity), MAX_BY(price_unit, transaction_date) FROM transactions "
            "WHERE source_system = 'RSU_Excel' AND asset_id = ? AND transaction_date <= ?",
            [asset, end]).fetchone()
        shares, price = _number(row[0]) or 0.0, _number(row[1]) or 0.0
        if shares <= 0:
            return 0.0
        fx = lookup_fx(db, end)
        return shares * price * fx[1] if fx else None
    row = db.execute("""
        WITH latest AS (
            SELECT asset_id, MAX(snapshot_date) AS day FROM holdings
            WHERE source_system = ? AND snapshot_date <= ? AND is_shadow = FALSE GROUP BY asset_id
        )
        SELECT SUM(h.market_value) FROM holdings h JOIN latest l
        ON h.asset_id = l.asset_id AND h.snapshot_date = l.day
        WHERE h.source_system = ? AND h.is_shadow = FALSE AND COALESCE(h.quantity, 0) <> 0
    """, [source, end, source]).fetchone()
    return _number(row[0]) or 0.0


def fs_value_reviews(db, after):
    """Flag finished months whose Financial Summary investment value looks unfilled.

    Each check is asked once and cleared by an owner "value is correct" decision
    (event_key fs-ok:<column>:<YYYY-MM>, decision internal):
      * fs_zero_with_position — the cell is 0/blank while the account still held a position;
      * fs_value_unchanged — the cell equals the previous month to the yuan (market-priced
        holdings always move, so an identical value usually means the month was copied forward).
    """
    after = _to_date(after)
    rows = db.execute('SELECT snapshot_date, payload FROM balance_sheet_monthly '
                      'WHERE snapshot_date > ? ORDER BY snapshot_date', [after.replace(day=1)]).fetchall()
    first = db.execute('SELECT payload FROM balance_sheet_monthly WHERE snapshot_date = ?',
                       [after.replace(day=1)]).fetchone()
    previous = (json.loads(first[0]) if isinstance(first[0], str) else first[0]) if first else None
    decided = {r[0] for r in db.execute(
        "SELECT event_key FROM external_flow_decisions WHERE event_key LIKE 'fs-ok:%'").fetchall()}
    reviews = []
    for label, payload in rows:
        data = json.loads(payload) if isinstance(payload, str) else payload
        end = _month_end(_to_date(label))
        if end < date.today() and isinstance(data, dict):
            for column, (source, asset) in FS_VALUE_SOURCES.items():
                key = f'fs-ok:{column}:{end:%Y-%m}'
                if key in decided:
                    continue
                value = _number(data.get(column)) or 0.0
                before = _number(previous.get(column)) if isinstance(previous, dict) else None
                reason, estimate = None, None
                if value <= 0:
                    held = _position_value_cny(db, source, asset, end)
                    if held is None or held >= max(_FS_MIN_POSITION_CNY, 0.05 * (before or 0)):
                        reason, estimate = 'fs_zero_with_position', (round(held, 2) if held else None)
                elif before is not None and abs(value - before) < 0.5:
                    reason = 'fs_value_unchanged'
                if reason:
                    reviews.append(dict(event_key=key, event_date=end, source='Financial Summary',
                                        reason=reason, column=column, amount=value or None,
                                        currency='CNY', estimate_cny=estimate,
                                        previous_value=before, evidence=[]))
        previous = data
    return reviews
