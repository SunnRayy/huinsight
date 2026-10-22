"""Append forward flows and advance only fully evidenced consecutive months."""
import logging
from datetime import date, timedelta

from src.financial_analysis.flow_rules import SOURCE_NAMES, derive_flows, source_completeness
from src.financial_analysis.fx_daily import cache_fred_fx
from src.financial_analysis.twr import (
    _input_fingerprint, _investment_value, _month_end, _to_date, _valuation_fingerprint,
    _valuation_identity_fingerprint,
)

logger = logging.getLogger(__name__)


def frozen_end(db):
    row = db.execute('SELECT frozen_coverage_end, coverage_end FROM investment_twr_source WHERE id = 1').fetchone()
    return _to_date(row[0] or row[1]) if row else None


def _frozen_flows_fingerprint(db, frozen):
    """Hash of the reviewed (non-automatic) flows dated on or before the frozen end."""
    import hashlib
    import json
    rows = db.execute(
        "SELECT flow_id, CAST(event_date AS VARCHAR), CAST(amount_cny AS VARCHAR), source, kind "
        "FROM investment_external_flows WHERE event_date <= ? "
        "AND evidence_status NOT IN ('auto_rule', 'owner_decision') ORDER BY flow_id",
        [frozen]).fetchall()
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def freeze_reviewed_history(db):
    """Pin the reviewed end on first forward sync, never a calendar constant."""
    row = db.execute('SELECT coverage_start, coverage_end, valuation_sha256, input_fingerprint, '
                     'frozen_coverage_end, quality FROM investment_twr_source WHERE id = 1').fetchone()
    if not row:
        return False
    if row[4]:
        return True
    if row[5] != 'estimated' or _to_date(row[1]) != _month_end(_to_date(row[1])):
        return False
    if _input_fingerprint(db, row[0], row[1]) != row[3]:
        raise ValueError('Reviewed baseline changed before history freeze')
    db.execute('UPDATE investment_twr_source SET frozen_coverage_end = coverage_end, '
               'frozen_valuation_sha256 = valuation_sha256, valuation_identity_sha256 = ?, '
               'frozen_flows_sha256 = ? WHERE id = 1',
               [_valuation_identity_fingerprint(db, row[0], row[1]),
                _frozen_flows_fingerprint(db, row[1])])
    return True


def _source_blockers(db, end):
    blockers = []
    # Include carried positions, even when that source has no snapshot this month.
    sources = db.execute('''
        WITH latest AS (
            SELECT asset_id, source_system, MAX(snapshot_date) AS day
            FROM holdings WHERE snapshot_date <= ? GROUP BY asset_id, source_system
        )
        SELECT DISTINCT h.source_system FROM holdings h JOIN latest l
        ON h.asset_id = l.asset_id AND h.source_system = l.source_system AND h.snapshot_date = l.day
        WHERE COALESCE(h.quantity, 0) <> 0 ORDER BY h.source_system
    ''', [end]).fetchall()
    # Web event dates prove the CN paste reaches this month, even with no active position.
    cn_latest = db.execute('SELECT MAX(event_date) FROM cn_platform_events').fetchone()[0]
    if cn_latest is None or _to_date(cn_latest).replace(day=1) < end.replace(day=1):
        blockers.append({'code': 'cn_web_list_missing'})
    for (source,) in sources:
        if source in SOURCE_NAMES:
            blocker, _ = source_completeness(db, source, end)
            if blocker:
                blockers.append(blocker)
    return blockers


def _month_blockers(db, end, reviews):
    blockers = []
    values = db.execute('SELECT payload FROM balance_sheet_monthly WHERE snapshot_date = ?',
                        [end.replace(day=1)]).fetchall()
    if len(values) != 1 or _investment_value(values[0][0]) is None:
        blockers.append({'code': 'fs_month_missing'})
    blockers.extend(_source_blockers(db, end))
    pending = [item for item in reviews if item['event_date'] <= end]
    if any(item['reason'] == 'IBKR deposits unknown' for item in pending):
        blockers.append({'code': 'ibkr_cash_transactions_missing'})
    if any(item['reason'] == 'Dated FX unavailable' for item in pending):
        blockers.append({'code': 'fx_unavailable'})
    fs_checks = [item for item in pending if item['reason'].startswith('fs_')]
    if fs_checks:
        blockers.append({'code': 'fs_value_check', 'count': len(fs_checks)})
    others = [item for item in pending if not item['reason'].startswith('fs_')]
    if others:
        blockers.append({'code': 'open_reviews', 'count': len(others)})
    return blockers


def coverage_review_items(db, current=None):
    """The same finished-month confirmation set for the card and coverage chip."""
    if current is None:
        row = db.execute('SELECT coverage_end FROM investment_twr_source WHERE id = 1').fetchone()
        if not row:
            return []
        current = _to_date(row[0])
    end = _month_end(current + timedelta(days=1))
    if end >= date.today():
        return []
    return [item for item in derive_flows(db, frozen_end(db) or current)[1] if item['event_date'] <= end]


def coverage_status(db):
    """Read the next month's gates without freezing, writing or fetching FX."""
    row = db.execute('SELECT frozen_coverage_end, coverage_end FROM investment_twr_source WHERE id = 1').fetchone()
    if not row:
        return dict(frozen_end=None, coverage_end=None, next_month=None, blockers=[])
    current = _to_date(row[1])
    next_day = current + timedelta(days=1)
    in_progress = _month_end(next_day) >= date.today()
    reviews = [] if in_progress else coverage_review_items(db, current)
    return dict(frozen_end=_to_date(row[0] or current).isoformat(),
                coverage_end=current.isoformat(), next_month=next_day.replace(day=1).isoformat(),
                blockers=[] if in_progress else _month_blockers(db, _month_end(next_day), reviews),
                **({'in_progress': True} if in_progress else {}))


def extend_flow_coverage(db, *, fetch_fx=False):
    """One atomic, idempotent sync step. It cannot replace any frozen row."""
    db.execute('BEGIN TRANSACTION')
    try:
        if not freeze_reviewed_history(db):
            db.execute('COMMIT')
            return {'status': 'skipped', 'reason': 'reviewed_baseline_required'}
        start, frozen, frozen_sha, frozen_identity, frozen_flows = db.execute(
            'SELECT coverage_start, frozen_coverage_end, frozen_valuation_sha256, '
            'valuation_identity_sha256, frozen_flows_sha256 FROM investment_twr_source WHERE id = 1').fetchone()
        # Only the frozen history is immutable, and tampering with it still fails closed:
        # its valuation provenance and its reviewed flows are fingerprinted. FS *values* inside
        # it may be corrected (flagged as history_changed_since_review, never blanked).
        current_identity = _valuation_identity_fingerprint(db, start, frozen)
        current_flows = _frozen_flows_fingerprint(db, frozen)
        if frozen_flows is None:
            # First run after V199 on a database frozen by 0.1.3 (which re-stamped the identity
            # over the whole covered window): pin both fingerprints to the frozen range.
            db.execute('UPDATE investment_twr_source SET frozen_flows_sha256 = ?, '
                       'valuation_identity_sha256 = ? WHERE id = 1', [current_flows, current_identity])
        else:
            if frozen_identity != current_identity:
                raise ValueError('Frozen valuation provenance changed')
            if frozen_flows != current_flows:
                raise ValueError('Frozen boundary evidence changed outside automatic flow sync')
        # Every month after the frozen end is provisional and recomputed on each run, so a
        # corrected Financial Summary month or a new owner decision flows through. (Raising on a
        # changed whole-window fingerprint used to leave the Returns page unavailable after an
        # owner corrected a month.) Owner decisions persist in their own table.
        if fetch_fx:
            usd = db.execute("SELECT MIN(transaction_date), MAX(transaction_date) FROM transactions "
                             "WHERE transaction_date > ? AND source_system IN "
                             "('Schwab_CSV', 'Broker_IBKR', 'RSU_Excel')", [frozen]).fetchone()
            if usd[0]:
                cache_fred_fx(db, *usd)
        db.execute("DELETE FROM investment_external_flows WHERE event_date > ? "
                   "AND evidence_status IN ('auto_rule', 'owner_decision')", [frozen])
        flows, reviews = derive_flows(db, frozen)
        for flow in flows:
            db.execute('''INSERT INTO investment_external_flows
                (flow_id, event_date, amount_cny, original_amount, original_currency,
                 fx_date, fx_cny_per_native, source, kind, evidence_status, evidence, date_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(flow_id) DO NOTHING''',
                [flow[k] for k in ('flow_id', 'event_date', 'amount_cny', 'original_amount',
                                  'original_currency', 'fx_date', 'fx_rate', 'source', 'kind',
                                  'evidence_status', 'evidence', 'date_basis')])
        end = _to_date(frozen)
        while True:
            candidate = _month_end(end + timedelta(days=1))
            if candidate >= date.today() or _month_blockers(db, candidate, reviews):
                break
            end = candidate
        changed = _valuation_fingerprint(db, start, frozen) != frozen_sha
        valuation = _valuation_fingerprint(db, start, end)
        fingerprint = _input_fingerprint(db, start, end)
        # valuation_identity_sha256 stays pinned to the frozen range (checked above).
        db.execute('UPDATE investment_twr_source SET coverage_end = ?, valuation_sha256 = ?, '
                   'input_fingerprint = ?, history_changed_since_review = ? WHERE id = 1',
                   [end, valuation, fingerprint, changed])
        db.execute('COMMIT')
        return {'status': 'ok', 'coverage_end': end.isoformat(), 'review_count': len(reviews),
                'derived_count': len(flows), 'history_changed_since_review': changed}
    except Exception:
        db.execute('ROLLBACK')
        raise
