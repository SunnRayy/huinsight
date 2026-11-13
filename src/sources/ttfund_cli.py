"""TTFund coverage from the ttskill CLI (TRADE_QUERY) or an owner attestation.

The CN boundary gate needs proof that TTFund activity is known through a month's
end. The web-list paste only proves it up to its last event, so a month without
any TTFund trade could never pass. Two records fix that (``cn_platform_coverage``):

- ``cli_pull`` (sourced): a ``scripts/ttfund_pull.py`` export of ``ttskill invoke
  TRADE_QUERY trade_list`` for an explicit date range. Its events after the last
  web-list event are stored as ``cn_platform_events`` (the flow rules classify
  them like pasted rows); the queried range is recorded as covered.
- ``owner_attestation`` (attested): the owner states there were no TTFund
  transactions in a range. No events; the month shows as attested, not sourced.

Coverage counts only when it joins up with the evidence before it (no gaps).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.sources.cn_platform_events import persist_events

PULL_FORMAT = 'huinsight.ttfund_cli_pull.v1'
BASES = ('cli_pull', 'owner_attestation')
_REQUIRED_TRADE_TYPES = {'all'}
_COUNT = re.compile(r'([+-]?[\d,]+(?:\.\d+)?)\s*(元|份)')


def _count(text) -> Tuple[Optional[str], Optional[str]]:
    """'12,345.67元' → ('12345.67', '元'); '--' → (None, None)."""
    raw = str(text or '').strip()
    if raw in ('', '--', '-'):
        return None, None
    match = _COUNT.fullmatch(raw)
    if not match:
        raise ValueError(f'Unrecognised TTFund amount: {raw}')
    return match[1].replace(',', ''), match[2]


def _trades(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    body = response
    for key in ('data', 'raw_result', 'body'):
        if isinstance(body, dict) and key in body and 'trade_list_result' not in body:
            body = body[key]
    if not isinstance(body, dict) or body.get('success') is not True or 'trade_list_result' not in body:
        raise ValueError('TTFund CLI response is not a successful trade_list result')
    return list(body['trade_list_result'].get('trades') or [])


def parse_cli_pull(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an export and turn its trades into web-list shaped events."""
    if payload.get('format') != PULL_FORMAT:
        raise ValueError(f'Not a {PULL_FORMAT} export')
    query = payload.get('query') or {}
    start, end = date.fromisoformat(query['start']), date.fromisoformat(query['end'])
    pulled = datetime.fromisoformat(payload['pulled_at']).date()
    if end < start or end > pulled:
        raise ValueError('The queried range must end on or before the pull date')
    responses = payload.get('responses') or []
    if not _REQUIRED_TRADE_TYPES <= {r.get('trade_type') for r in responses}:
        raise ValueError('The export must include the tradeType=all query')
    events, seen = [], set()
    for response in responses:
        for trade in _trades(response.get('result') or {}):
            when = datetime.strptime(trade['tradeTime'], '%Y-%m-%d %H:%M:%S')
            if not start <= when.date() <= end:
                continue
            identity = trade.get('tradeId') or json.dumps(trade, sort_keys=True, ensure_ascii=False)
            if identity in seen:  # 'all' and 'hqb' return the same 活期宝 rows
                continue
            seen.add(identity)
            applied, applied_unit = _count(trade.get('applyCount'))
            confirmed, confirmed_unit = _count(trade.get('confirmCount'))
            events.append({
                'event_date': when.date().isoformat(), 'event_time': when.strftime('%H:%M:%S'),
                'fund_code': trade.get('fundCode') or '', 'fund_name': trade.get('fundName') or '',
                'business_type': trade.get('businessType') or '', 'applied_value': applied,
                'applied_unit': applied_unit, 'confirmed_value': confirmed, 'confirmed_unit': confirmed_unit,
                'account': '', 'status': trade.get('statusText') or '',
            })
    return {'start': start, 'end': end, 'events': events}


def _record(db, *, start: date, end: date, basis: str, event_count=None, imported=None,
            sha=None, note=None) -> int:
    if basis not in BASES or end < start:
        raise ValueError('invalid TTFund coverage record')
    return db.execute(
        'INSERT INTO cn_platform_coverage (covered_from, covered_to, basis, recorded_at, event_count, '
        'imported_events, evidence_sha256, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id',
        [start, end, basis, datetime.now(timezone.utc).replace(tzinfo=None), event_count, imported, sha,
         (note or '')[:500] or None]).fetchone()[0]


def import_cli_pull(db, raw: bytes) -> Dict[str, Any]:
    """Store the events after the web list's last day and record the queried range."""
    parsed = parse_cli_pull(json.loads(raw.decode('utf-8')))
    last_web = db.execute('SELECT MAX(event_date) FROM cn_platform_events').fetchone()[0]
    fresh = [e for e in parsed['events'] if last_web is None or date.fromisoformat(e['event_date']) > last_web]
    db.execute('BEGIN TRANSACTION')
    try:
        imported = persist_events(db, fresh)
        coverage_id = _record(db, start=parsed['start'], end=parsed['end'], basis='cli_pull',
                              event_count=len(parsed['events']), imported=imported,
                              sha=hashlib.sha256(raw).hexdigest(),
                              note=f'ttskill TRADE_QUERY pull, {len(parsed["events"])} trades in range')
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
    return {'coverage_id': coverage_id, 'covered_from': parsed['start'].isoformat(),
            'covered_to': parsed['end'].isoformat(), 'trades_in_range': len(parsed['events']),
            'already_in_web_list': len(parsed['events']) - len(fresh), 'imported_events': imported}


def record_attestation(db, start: date, end: date, note: str) -> Dict[str, Any]:
    if not (note or '').strip():
        raise ValueError('An attestation needs a note saying who confirmed it and how')
    if end >= date.today():
        raise ValueError('An attestation can only cover days that have passed')
    coverage_id = _record(db, start=start, end=end, basis='owner_attestation', event_count=0, imported=0,
                          note=note.strip())
    return {'coverage_id': coverage_id, 'covered_from': start.isoformat(), 'covered_to': end.isoformat()}


def coverage_frontier(db) -> Tuple[Optional[date], List[Dict[str, Any]]]:
    """Last day TTFund activity is known for, joining coverage onto the web list without gaps."""
    frontier = db.execute('SELECT MAX(event_date) FROM cn_platform_events').fetchone()[0]
    try:
        rows = db.execute('SELECT covered_from, covered_to, basis, recorded_at FROM cn_platform_coverage '
                          'ORDER BY covered_from, covered_to').fetchall()
    except Exception:  # table absent before V205
        rows = []
    used = []
    for start, end, basis, recorded in rows:
        if frontier is None or start <= frontier + timedelta(days=1):
            if frontier is None or end > frontier:
                frontier = end
                used.append({'from': start.isoformat(), 'to': end.isoformat(), 'basis': basis,
                             'recorded_at': recorded.isoformat() if recorded else None})
    return frontier, used
