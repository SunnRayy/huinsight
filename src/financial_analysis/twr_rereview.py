"""Owner re-review of the frozen Returns history.

The reviewed flows up to ``frozen_coverage_end`` are immutable to the sync: once
frozen, the workbook's TWR外部现金流 tab is never re-imported and any change to
those rows fails closed. When the owner corrects that history in the ledger
(2026-11-09: the RSU 2026-03 vest booked net of the actual tax), this module is
the only way in:

1. ``frozen_window_diff`` compares the workbook rows dated on or before the
   frozen end with the stored ones, so the owner sees exactly what changes.
2. ``apply_rereview`` archives the stored rows, writes the workbook rows,
   re-pins the frozen fingerprints (flows, valuation, valuation identity),
   re-derives the months after the frozen end, records the review against the
   new input fingerprint and appends a sync-log row naming the revision.

Rows after the frozen end stay with the automatic flow rules.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from src.financial_analysis.flow_coverage import _frozen_flows_fingerprint, extend_flow_coverage, frozen_end
from src.financial_analysis.twr import _to_date, _valuation_fingerprint, _valuation_identity_fingerprint
from src.financial_analysis.twr_import import _read_source

FLOW_COLUMNS = ('flow_id', 'event_date', 'amount_cny', 'original_amount', 'original_currency', 'fx_date',
                'fx_cny_per_native', 'source', 'kind', 'evidence_status', 'evidence', 'date_basis')
AUTOMATIC = ('auto_rule', 'owner_decision')
_ECONOMIC = ('event_date', 'amount_cny', 'original_amount', 'original_currency', 'fx_cny_per_native',
             'source', 'kind', 'evidence_status')


def funding_workbook_path(config: Dict[str, Any]) -> Path:
    """The workbook the sync imports the TWR tabs from (same resolution as the sync)."""
    cn = config.get('source_registry', {}).get('cn_fund', {})
    name = cn.get('file_patterns', {}).get('workbook', 'funding_transactions.xlsx')
    return Path(cn.get('data_dir') or config.get('finance_dir') or './data/import') / name


def _norm(field: str, value):
    if field in ('amount_cny', 'original_amount'):
        # Stored as DECIMAL(20,2), which rounds half away from zero.
        return str(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    if field == 'fx_cny_per_native':
        return str(Decimal(str(value)).quantize(Decimal('0.0000000001')).normalize())
    if field in ('event_date', 'fx_date'):
        return _to_date(value).isoformat()
    return '' if value is None else str(value)


def _row(values) -> Dict[str, Any]:
    return dict(zip(FLOW_COLUMNS, values))


def frozen_window_diff(db, workbook_path) -> Dict[str, Any]:
    """What a re-review would change, without writing anything."""
    frozen = frozen_end(db)
    if frozen is None:
        return {'available': False, 'reason': 'no_frozen_history'}
    path = Path(workbook_path)
    if not path.is_file():
        return {'available': False, 'reason': 'workbook_missing'}
    parsed = _read_source(path)
    if parsed is None:
        return {'available': False, 'reason': 'twr_tabs_missing'}
    incoming = {r[0]: _row(r) for r in parsed[2] if _to_date(r[1]) <= frozen}
    stored = {r[0]: _row(r) for r in db.execute(
        f"SELECT {', '.join(FLOW_COLUMNS)} FROM investment_external_flows "
        "WHERE event_date <= ? AND evidence_status NOT IN (?, ?)", [frozen, *AUTOMATIC]).fetchall()}
    changes, text_only = [], 0
    for flow_id in sorted(set(incoming) | set(stored)):
        new, old = incoming.get(flow_id), stored.get(flow_id)
        if new is None or old is None:
            row = new or old
            changes.append({'flow_id': flow_id, 'change': 'added' if new else 'removed',
                            'event_date': _norm('event_date', row['event_date']), 'source': row['source'],
                            'before_cny': None if new else float(old['amount_cny']),
                            'after_cny': float(new['amount_cny']) if new else None})
            continue
        fields = [f for f in _ECONOMIC if _norm(f, new[f]) != _norm(f, old[f])]
        if fields:
            changes.append({'flow_id': flow_id, 'change': 'changed', 'fields': fields,
                            'event_date': _norm('event_date', new['event_date']), 'source': new['source'],
                            'before_cny': float(old['amount_cny']), 'after_cny': float(new['amount_cny']),
                            'before_native': float(old['original_amount']),
                            'after_native': float(new['original_amount']),
                            'before_status': old['evidence_status'], 'after_status': new['evidence_status']})
        elif any(_norm(f, new[f]) != _norm(f, old[f]) for f in ('evidence', 'date_basis')):
            text_only += 1
    state = db.execute('SELECT history_changed_since_review FROM investment_twr_source WHERE id = 1').fetchone()
    net = sum((c['after_cny'] or 0) - (c['before_cny'] or 0) for c in changes)
    return {
        'available': True,
        'frozen_end': frozen.isoformat(),
        'workbook': path.name,
        'workbook_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'changes': changes,
        'evidence_text_changes': text_only,
        'net_change_cny': round(net, 2),
        'history_changed_since_review': bool(state[0]) if state else False,
        'needs_review': bool(changes or text_only or (state and state[0])),
    }


_PENDING_CACHE: Dict[tuple, Optional[int]] = {}


def pending_corrections(db, config: Dict[str, Any]) -> Optional[int]:
    """How many locked-month records the uploaded funding workbook would change
    (0 = none, None = cannot tell). The Returns page shows a banner when > 0.

    Reading the workbook takes ~0.6 s, so the answer is cached per workbook
    file (mtime, size) and per frozen-flows pin; a new upload or an applied
    re-review invalidates it.
    """
    path = funding_workbook_path(config)
    try:
        stat = path.stat()
        pin = db.execute('SELECT frozen_flows_sha256, frozen_coverage_end FROM investment_twr_source '
                         'WHERE id = 1').fetchone()
    except Exception:
        return None
    if not pin or pin[1] is None:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size, pin[0])
    if key not in _PENDING_CACHE:
        try:
            diff = frozen_window_diff(db, path)
            _PENDING_CACHE.clear()
            _PENDING_CACHE[key] = len(diff['changes']) if diff.get('available') else None
        except Exception:
            return None
    return _PENDING_CACHE[key]


def apply_rereview(db, workbook_path, *, reviewer: str, evidence_ref: str,
                   config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Replace the frozen window from the workbook and record the owner's review."""
    if not reviewer.strip() or not evidence_ref.strip():
        raise ValueError('reviewer and evidence_ref are required')
    pinned = db.execute('SELECT frozen_coverage_end FROM investment_twr_source WHERE id = 1').fetchone()
    if not pinned or pinned[0] is None:
        raise ValueError('re-review unavailable: history is not frozen yet (run a sync first)')
    diff = frozen_window_diff(db, workbook_path)
    if not diff['available']:
        raise ValueError(f"re-review unavailable: {diff['reason']}")
    frozen = _to_date(diff['frozen_end'])
    _, _, rows = _read_source(Path(workbook_path))
    incoming = [r for r in rows if _to_date(r[1]) <= frozen]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    reason = f"twr_rereview {now:%Y-%m-%d}: {evidence_ref}"[:200]
    columns = ', '.join(FLOW_COLUMNS)
    db.execute('BEGIN TRANSACTION')
    try:
        archived = db.execute(
            f"INSERT INTO investment_external_flows_archive ({columns}, archived_at, archive_reason) "
            f"SELECT {columns}, ?, ? FROM investment_external_flows "
            "WHERE event_date <= ? AND evidence_status NOT IN (?, ?)",
            [now, reason, frozen, *AUTOMATIC]).fetchone()[0]
        db.execute("DELETE FROM investment_external_flows WHERE event_date <= ? AND evidence_status NOT IN (?, ?)",
                   [frozen, *AUTOMATIC])
        db.executemany(f"INSERT INTO investment_external_flows ({columns}) VALUES ({', '.join('?' * 12)})",
                       incoming)
        start = db.execute('SELECT coverage_start FROM investment_twr_source WHERE id = 1').fetchone()[0]
        db.execute('UPDATE investment_twr_source SET frozen_flows_sha256 = ?, frozen_valuation_sha256 = ?, '
                   'valuation_identity_sha256 = ?, history_changed_since_review = FALSE WHERE id = 1',
                   [_frozen_flows_fingerprint(db, frozen), _valuation_fingerprint(db, start, frozen),
                    _valuation_identity_fingerprint(db, start, frozen)])
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
    coverage = extend_flow_coverage(db)
    fingerprint = db.execute('SELECT input_fingerprint FROM investment_twr_source WHERE id = 1').fetchone()[0]
    db.execute('INSERT INTO investment_twr_reviews (input_fingerprint, reviewer, evidence_ref) VALUES (?, ?, ?) '
               'ON CONFLICT (input_fingerprint) DO NOTHING', [fingerprint, reviewer.strip(), evidence_ref.strip()[:500]])
    note = json.dumps({'action': 'twr_rereview', 'evidence_ref': evidence_ref.strip(), 'reviewer': reviewer.strip(),
                       'frozen_end': diff['frozen_end'], 'workbook_sha256': diff['workbook_sha256'],
                       'changed_flows': [c['flow_id'] for c in diff['changes']],
                       'net_change_cny': diff['net_change_cny'], 'archived_rows': archived}, ensure_ascii=False)
    log_id = None
    if config is not None:
        from src.services.sync_metrics_log import record_sync_metrics
        log_id = record_sync_metrics(db, config, trigger='twr_rereview', note=note)
    return {'status': 'ok', 'archived_rows': archived, 'written_rows': len(incoming),
            'changes': diff['changes'], 'coverage': coverage, 'input_fingerprint': fingerprint,
            'sync_log_id': log_id}
