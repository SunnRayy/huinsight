"""Import explicit investment-boundary flows from the fund source workbook."""

import calendar
import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

from src.financial_analysis.twr import _input_fingerprint, _valuation_fingerprint

FLOW_TAB = 'TWR外部现金流'
META_TAB = 'TWR估算口径'
FLOW_COLUMNS = (
    'flow_id', 'event_date', 'amount_cny_signed', 'original_amount_signed',
    'original_currency', 'fx_date', 'fx_cny_per_native', 'source', 'kind',
    'evidence_status', 'evidence', 'date_basis',
)
SOURCES = {'Schwab', 'IBKR', 'TTFund', 'Gold', 'RSU'}


def _ensure_source_table(db) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS investment_twr_source (
            id INTEGER PRIMARY KEY, coverage_start DATE NOT NULL,
            coverage_end DATE NOT NULL, quality VARCHAR(20) NOT NULL,
            source_sha256 VARCHAR(64) NOT NULL,
            valuation_sha256 VARCHAR(64), input_fingerprint VARCHAR(64),
            invalid_reason VARCHAR(100),
            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    db.execute('ALTER TABLE investment_twr_source ADD COLUMN IF NOT EXISTS valuation_sha256 VARCHAR(64)')
    db.execute('ALTER TABLE investment_twr_source ADD COLUMN IF NOT EXISTS input_fingerprint VARCHAR(64)')
    db.execute('ALTER TABLE investment_twr_source ADD COLUMN IF NOT EXISTS invalid_reason VARCHAR(100)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS investment_twr_reviews (
            input_fingerprint VARCHAR(64) PRIMARY KEY,
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewer VARCHAR(100) NOT NULL,
            evidence_ref VARCHAR(500) NOT NULL
        )
    ''')


def mark_investment_twr_unavailable(db, reason: str) -> None:
    """Preserve last imported flows but stop presenting them as current TWR."""
    db.execute('BEGIN TRANSACTION')
    try:
        _ensure_source_table(db)
        db.execute(
            "UPDATE investment_twr_source SET quality = 'unavailable', invalid_reason = ?",
            [reason],
        )
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise


def _date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f'invalid TWR date: {value!r}') from exc


def _decimal(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f'invalid {field}') from exc
    if not result.is_finite():
        raise ValueError(f'invalid {field}')
    return result


def _month_end(day: date) -> bool:
    return day.day == calendar.monthrange(day.year, day.month)[1]


def _read_source(path: Path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    present = {FLOW_TAB, META_TAB} & set(workbook.sheetnames)
    if not present:
        return None
    if present != {FLOW_TAB, META_TAB}:
        raise ValueError('TWR flow and coverage tabs must be supplied together')

    metadata = dict(workbook[META_TAB].iter_rows(min_row=2, max_col=2, values_only=True))
    coverage_start = _date(metadata.get('coverage_start'))
    coverage_end = _date(metadata.get('coverage_end'))
    if (coverage_end <= coverage_start or not _month_end(coverage_start)
            or not _month_end(coverage_end)):
        raise ValueError('TWR coverage must use increasing month-end dates')
    if not str(metadata.get('quality') or '').startswith('estimated'):
        raise ValueError('TWR quality must explicitly be estimated')

    sheet = workbook[FLOW_TAB]
    values = sheet.iter_rows(values_only=True)
    header = next(values)
    if tuple(header[:len(FLOW_COLUMNS)]) != FLOW_COLUMNS:
        raise ValueError('TWR flow columns do not match the import contract')
    flows = []
    seen = set()
    for line_no, row in enumerate(values, 2):
        if all(value is None for value in row):
            continue
        record = dict(zip(FLOW_COLUMNS, row))
        flow_id = str(record['flow_id'] or '').strip()
        if not flow_id or flow_id in seen:
            raise ValueError(f'duplicate or missing TWR flow ID at row {line_no}')
        seen.add(flow_id)
        event = _date(record['event_date'])
        fx_date = _date(record['fx_date'])
        if (event < coverage_start.replace(day=1) or event > coverage_end
                or not 0 <= (event - fx_date).days <= 5):
            raise ValueError(f'TWR event/FX date outside coverage at row {line_no}')
        currency = str(record['original_currency'] or '').strip()
        source = str(record['source'] or '').strip()
        if currency not in {'CNY', 'USD'} or source not in SOURCES:
            raise ValueError(f'unsupported TWR currency or source at row {line_no}')
        amount = _decimal(record['amount_cny_signed'], 'amount_cny_signed')
        native = _decimal(record['original_amount_signed'], 'original_amount_signed')
        rate = _decimal(record['fx_cny_per_native'], 'fx_cny_per_native')
        if (amount == 0 or native == 0 or rate <= 0 or (amount > 0) != (native > 0)
                or abs(amount - (native * rate).quantize(Decimal('0.01'))) > Decimal('0.02')):
            raise ValueError(f'inconsistent TWR amount/FX at row {line_no}')
        if currency == 'CNY' and (rate != 1 or fx_date != event):
            raise ValueError(f'CNY TWR flow must have same-day FX 1 at row {line_no}')
        kind = str(record['kind'] or '').strip()
        status = str(record['evidence_status'] or '').strip()
        if not kind or not status or status.startswith('internal_'):
            raise ValueError(f'invalid TWR boundary classification at row {line_no}')
        flows.append((flow_id, event, amount, native, currency, fx_date, rate,
                      source, kind, status, str(record['evidence'] or ''),
                      str(record['date_basis'] or '')))
    if not flows:
        raise ValueError('TWR flow tab is empty')
    return coverage_start, coverage_end, flows


def replace_investment_twr_source(db, workbook_path) -> int:
    """Validate first, then atomically replace one workbook's TWR source rows."""
    present = db.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'investment_twr_source'").fetchone()
    columns = {r[1] for r in db.execute("PRAGMA table_info('investment_twr_source')").fetchall()} if present else set()
    if 'frozen_coverage_end' in columns:
        from src.financial_analysis.flow_coverage import freeze_reviewed_history
        if freeze_reviewed_history(db):
            return 0
    path = Path(workbook_path)
    try:
        parsed = _read_source(path)
    except Exception:
        mark_investment_twr_unavailable(db, 'invalid_twr_tabs')
        raise
    if parsed is None:
        mark_investment_twr_unavailable(db, 'missing_twr_tabs')
        return 0
    coverage_start, coverage_end, rows = parsed
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        valuation_digest = _valuation_fingerprint(db, coverage_start, coverage_end)
    except Exception:
        mark_investment_twr_unavailable(db, 'valuation_source_unavailable')
        raise
    db.execute('BEGIN TRANSACTION')
    try:
        _ensure_source_table(db)
        db.execute('''
            CREATE TABLE IF NOT EXISTS investment_external_flows (
                flow_id VARCHAR(80) PRIMARY KEY, event_date DATE NOT NULL,
                amount_cny DECIMAL(20,2) NOT NULL,
                original_amount DECIMAL(20,2) NOT NULL,
                original_currency VARCHAR(10) NOT NULL, fx_date DATE NOT NULL,
                fx_cny_per_native DECIMAL(20,10) NOT NULL,
                source VARCHAR(30) NOT NULL, kind VARCHAR(80) NOT NULL,
                evidence_status VARCHAR(100) NOT NULL, evidence VARCHAR(200),
                date_basis VARCHAR(200)
            )
        ''')
        db.execute('DELETE FROM investment_external_flows')
        db.executemany(
            'INSERT INTO investment_external_flows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            rows,
        )
        input_digest = _input_fingerprint(db, coverage_start, coverage_end)
        db.execute('DELETE FROM investment_twr_source')
        db.execute(
            'INSERT INTO investment_twr_source '
            '(id, coverage_start, coverage_end, quality, source_sha256, '
            'valuation_sha256, input_fingerprint) '
            "VALUES (1, ?, ?, 'estimated', ?, ?, ?)",
            [coverage_start, coverage_end, digest, valuation_digest, input_digest],
        )
        actual = db.execute('SELECT COUNT(*) FROM investment_external_flows').fetchone()[0]
        if actual != len(rows):
            raise RuntimeError(f'TWR flow import mismatch: {actual} != {len(rows)}')
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        mark_investment_twr_unavailable(db, 'import_failed')
        raise
    return len(rows)
