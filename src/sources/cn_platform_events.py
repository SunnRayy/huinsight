"""Read-only TTFund web-paste ingestion; amounts retain their displayed 元/份 units."""
import hashlib
import json
import re
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal

from openpyxl import load_workbook

COLUMNS = ('event_key', 'event_date', 'event_time', 'fund_code', 'fund_name',
           'business_type', 'applied_value', 'applied_unit', 'confirmed_value',
           'confirmed_unit', 'account', 'status')
HEADERS = ('申请时间', '基金名称', '业务类型', '申请数额', '确认数额', '关联账户', '状态', '操作')


def _text(value):
    if isinstance(value, datetime) and value.time() == datetime.min.time():
        value = value.date()
    return ' '.join(str(value if value is not None else '').split())


def _amount(value):
    text = _text(value).replace(',', '')
    if text in {'', '--', '-'}:
        return None, None
    match = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*(元|份)', text)
    if not match:
        raise ValueError(f'Invalid TTFund web amount: {text}')
    return Decimal(match[1]), match[2]


def normalize_event(row):
    """Normalize workbook and oracle CSV values to the same stable event identity."""
    values = {key: _text(row.get(key)) for key in COLUMNS[1:]}
    values['event_date'] = date.fromisoformat(values['event_date']).isoformat()
    if values['event_time']:
        values['event_time'] = datetime.strptime(values['event_time'], '%H:%M:%S' if values['event_time'].count(':') == 2 else '%H:%M').strftime('%H:%M:%S')
    values['fund_code'] = values['fund_code'].zfill(6) if values['fund_code'] else ''
    for key in ('applied_value', 'confirmed_value'):
        value = values[key]
        values[key] = format(Decimal(value).normalize(), 'f') if value else None
    identity = json.dumps(values, ensure_ascii=False, sort_keys=True)
    values['event_key'] = hashlib.sha256(identity.encode()).hexdigest()
    return values


def persist_events(db, rows):
    count = 0
    for row in rows:
        event = normalize_event(row)
        inserted = db.execute(f"INSERT INTO cn_platform_events ({','.join(COLUMNS)}) "
                              f"VALUES ({','.join('?' for _ in COLUMNS)}) "
                              'ON CONFLICT(event_key) DO NOTHING RETURNING event_key',
                              [event[key] for key in COLUMNS]).fetchone()
        count += bool(inserted)
    return count


# Header aliases: the live 交易查询 page shows 交易发起时间 / 产品名称 (2026-10 paste).
_ALIASES = {
    '申请时间': ('交易发起时间', '申请时间'), '基金名称': ('产品名称', '基金名称'),
    '业务类型': ('业务类型',), '申请数额': ('申请数额',), '确认数额': ('确认数额',),
    '关联账户': ('关联账户',), '状态': ('状态',),
}
_DATE = re.compile(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?')
_TIME = re.compile(r'\d{1,2}:\d{2}(?::\d{2})?')


def _date_and_time(cell):
    """Return (date, time-text) for a date cell, (None, time-text) for a time-only cell."""
    if isinstance(cell, datetime):
        return cell.date(), (cell.strftime('%H:%M:%S') if cell.time() != datetime.min.time() else '')
    if isinstance(cell, date):
        return cell, ''
    if isinstance(cell, dt_time):
        return None, cell.strftime('%H:%M:%S')
    text = _text(cell)
    match = _DATE.fullmatch(text)
    if match:
        return datetime.strptime(match[1].replace('/', '-'), '%Y-%m-%d').date(), match[2] or ''
    if _TIME.fullmatch(text):
        return None, text
    return None, None


def _code(cell):
    """A fund code cell: Excel turns '012345' into the number 12345."""
    if isinstance(cell, (int, float)) and not isinstance(cell, bool) and float(cell).is_integer():
        return str(int(cell)).zfill(6)
    text = _text(cell)
    return text.zfill(6) if re.fullmatch(r'\d{1,6}', text) else None


def parse_web_rows(rows):
    """Parse the pasted TTFund web list.

    Two layouts are accepted: one Excel row per web row (newline cells), or the browser paste
    where each web row becomes a main row plus a continuation row holding the time, the fund
    code and a second account line. A continuation row is merged into the event above it.
    """
    positions = None
    events = []
    for cells in rows:
        cells = list(cells)
        texts = [_text(cell) for cell in cells]
        found = {}
        for name, aliases in _ALIASES.items():
            for i, text in enumerate(texts):
                # "基金名称\n代码" style headers normalize to "基金名称 代码".
                if text in aliases or any(text.startswith(a + ' ') for a in aliases):
                    found[name] = i
        if len(found) == len(_ALIASES):
            positions = found
            continue
        if not positions or not any(texts):
            continue

        def cell(name):
            i = positions[name]
            return cells[i] if i < len(cells) else None

        def text(name):
            return _text(cell(name))

        def span_text(name):
            # A header may span unlabeled columns (e.g. 基金名称 + 代码, 申请时间 + time).
            first = positions[name]
            nxt = min((i for i in positions.values() if i > first), default=len(cells))
            return ' '.join(t for t in texts[first:nxt] if t).strip()

        day, clock = _date_and_time(cell('申请时间'))
        if day is None and text('状态') and events:
            # A merged date cell: a full row (own status) on the same day as the row above.
            day = events[-1]['event_date']
        if day is not None and not clock:
            # A merged time header may span a separate time column next to the date.
            first = positions['申请时间']
            nxt = min((i for i in positions.values() if i > first), default=len(cells))
            for extra in cells[first + 1:nxt]:
                _, maybe = _date_and_time(extra)
                if maybe:
                    clock = maybe
                    break
        if day is None:
            # Continuation row: time, fund code / wrapped name, second account line.
            if not events or text('状态'):
                continue
            event = events[-1]
            if clock and not event['event_time']:
                event['event_time'] = clock
            code = _code(cell('基金名称'))
            if code and not event['fund_code']:
                event['fund_code'] = code
            elif text('基金名称') and not code:
                event['fund_name'] = (event['fund_name'] + text('基金名称')).strip()
            if text('关联账户'):
                event['account'] = (event['account'] + ' ' + text('关联账户')).strip()
            continue
        fund = span_text('基金名称')
        found_code = re.search(r'(?<!\d)(\d{6})(?!\d)', fund)
        code = found_code[1] if found_code else ''
        name = (fund[:found_code.start()] + fund[found_code.end():]).strip(' ()（）') if found_code else fund
        applied, applied_unit = _amount(cell('申请数额'))
        confirmed, confirmed_unit = _amount(cell('确认数额'))
        events.append(dict(event_date=day, event_time=clock or '', fund_code=code, fund_name=name,
                           business_type=text('业务类型'), applied_value=applied,
                           applied_unit=applied_unit, confirmed_value=confirmed,
                           confirmed_unit=confirmed_unit, account=text('关联账户'), status=text('状态')))
    if positions is None:
        raise ValueError('TTFund raw_web_transactions header missing')
    return events


def import_web_workbook(db, path):
    # see docs/architecture/data-sources.md Change Log
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        if 'raw_web_transactions' not in book.sheetnames:
            return 0
        return persist_events(db, parse_web_rows(book['raw_web_transactions'].values))
    finally:
        book.close()
