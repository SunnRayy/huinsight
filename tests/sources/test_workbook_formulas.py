"""Workbooks saved without formula results are refused (2026-11-09; synthetic data only).

openpyxl writes a formula with an empty result (`<v></v>`), which is what the owner's
ledgers looked like after a scripted edit; Excel writes the result. The readers read results,
so the first kind became RSU amounts of ¥0, blank quantities and a ¥0 gold value.
"""
import io
import re
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pandas as pd
import pytest

from src.sources.config_driven_reader import _assert_quantities_present, sync_config_source
from src.sources.reader_config import load_reader_config
from src.sources.workbook_formulas import UncachedFormulasError, assert_formulas_cached, describe, uncached_formula_cells

HEADER = ['交易日期', '资产名称', '交易类型', '单位', '数量', '单位价格_USD', '总金额_USD', '手续费_USD', '备注']


def rsu_book(path: Path, amount='=E2*F2', quantity=10) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'Transactions'
    sheet.append(HEADER)
    sheet.append([datetime(2026, 8, 1), 'Amazon RSU', 'RSU Vest', 'Shares', quantity, 200, amount, 0, 'synthetic'])
    book.create_sheet('Notes').append(['=1+1'])
    book.save(path)
    return path


def rewrite_cells(path: Path, fn) -> Path:
    """Rewrite every formula cell's XML in every sheet (simulates what Excel would store)."""
    with zipfile.ZipFile(path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    for name, data in items.items():
        if name.startswith('xl/worksheets/sheet'):
            items[name] = re.sub(r'<c ([^>]*)><f>([^<]*)</f><v\s*/?>(</v>)?</c>',
                                 lambda m: fn(m.group(1), m.group(2)), data.decode()).encode()
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in items.items():
            z.writestr(name, data)
    return path


def test_openpyxl_saved_formulas_are_found_per_sheet(tmp_path):
    path = rsu_book(tmp_path / 'RSU_transactions.xlsx')
    assert uncached_formula_cells(path) == {'Transactions': ['G2'], 'Notes': ['A1']}
    assert uncached_formula_cells(path, ['Transactions']) == {'Transactions': ['G2']}
    assert uncached_formula_cells(path, ['Missing']) == {}


def test_excel_saved_results_and_empty_text_results_pass(tmp_path):
    path = rewrite_cells(rsu_book(tmp_path / 'b.xlsx'), lambda attrs, f: f'<c {attrs}><f>{f}</f><v>2000</v></c>')
    assert uncached_formula_cells(path) == {}
    path = rewrite_cells(rsu_book(tmp_path / 'c.xlsx'), lambda attrs, f: f'<c {attrs} t="str"><f>{f}</f><v></v></c>')
    assert uncached_formula_cells(path) == {}  # a formula that really returns ""


def test_not_a_workbook_is_left_to_the_format_check(tmp_path):
    path = tmp_path / 'old.xls'
    path.write_bytes(b'not a zip')
    assert uncached_formula_cells(path) == {}


def test_message_names_file_sheet_cells_and_the_fix(tmp_path):
    found = {'Transactions': [f'G{i}' for i in range(2, 10)]}
    message = describe('RSU_transactions.xlsx', found)
    assert 'RSU_transactions.xlsx: 8 formula cell(s)' in message
    assert 'Transactions: G2, G3, G4, G5, G6 …' in message
    assert 'Open it in Excel' in message
    with pytest.raises(UncachedFormulasError, match='Notes: A1'):
        assert_formulas_cached(rsu_book(tmp_path / 'r.xlsx'))


def rsu_config(tmp_path):
    return {'source_registry': {'rsu': {'enabled': True, 'data_dir': str(tmp_path),
                                        'file_patterns': {'workbook': 'RSU_transactions.xlsx'}}}}


def test_reader_refuses_the_workbook_and_ignores_unread_sheets(tmp_path):
    cfg = load_reader_config(Path('config/readers/rsu.yaml'))
    rsu_book(tmp_path / 'RSU_transactions.xlsx')
    with pytest.raises(UncachedFormulasError, match='Transactions: G2'):
        sync_config_source(rsu_config(tmp_path), cfg)
    # Results stored for the read sheet: the unread Notes formula does not block the sync.
    rewrite_cells(tmp_path / 'RSU_transactions.xlsx',
                  lambda attrs, f: f'<c {attrs}><f>{f}</f><v>2000</v></c>' if 'E2' in f else f'<c {attrs}><f>{f}</f><v></v></c>')
    result = sync_config_source(rsu_config(tmp_path), cfg)
    assert len(result['transactions']) == 1


def test_orchestrator_keeps_rsu_rows_and_reports_the_reason(tmp_path, monkeypatch):
    from src.database.connector import DatabaseConnector
    from src.sync.orchestrator import SyncResult, _run_rsu_reader

    rsu_book(tmp_path / 'RSU_transactions.xlsx')
    monkeypatch.setattr('src.services.reader_mappings.load_id_field_maps', lambda *args: {'asset_name': {'Amazon RSU': 'AMZN'}})
    with DatabaseConnector(':memory:') as db:
        db.execute(Path('src/database/schema.sql').read_text())
        db.run_migrations()
        db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity, market_value) "
                   "VALUES (CURRENT_DATE, 'RSU_AMZN', 'RSU_Excel', 1.8, 3006)")
        result = SyncResult(success=True)
        assert _run_rsu_reader(db, rsu_config(tmp_path), result) == (0, 0)
        assert any('RSU sync error' in w and 'Open it in Excel' in w for w in result.warnings), result.warnings
        assert db.execute("SELECT quantity::DOUBLE, market_value::DOUBLE FROM holdings "
                          "WHERE asset_id='RSU_AMZN'").fetchall() == [(1.8, 3006.0)]


def test_blank_quantity_on_a_unit_moving_row_is_refused():
    rows = pd.DataFrame([
        {'transaction_date': '2025-10-31', 'asset_id': 'RSU_AMZN', 'transaction_type': 'sell', 'quantity': None},
        {'transaction_date': '2025-11-01', 'asset_id': 'X', 'transaction_type': 'dividend', 'quantity': None},
        {'transaction_date': '2025-11-02', 'asset_id': 'Y', 'transaction_type': 'Buy', 'quantity': 0},
    ])
    with pytest.raises(ValueError, match=r'RSU: 1 buy/sell/vest row\(s\) have no quantity \(2025-10-31 RSU_AMZN sell\)'):
        _assert_quantities_present('RSU', rows)
    _assert_quantities_present('RSU', rows.iloc[1:])  # dividends may carry no quantity; zero is not blank


def test_upload_refuses_the_workbook_and_keeps_the_current_file(tmp_path):
    from fastapi.testclient import TestClient
    from src.api.dependencies import get_db, get_writable_db
    from src.api.main import app
    from src.database.connector import DatabaseConnector

    source_dir = tmp_path / 'rsu'
    source_dir.mkdir()
    current = source_dir / 'RSU_transactions.xlsx'
    current.write_bytes(b'current')
    content = rsu_book(tmp_path / 'upload.xlsx').read_bytes()
    settings = {'source_registry': {'rsu': {'data_dir': str(source_dir), 'enabled': True,
                                            'file_patterns': {'workbook': 'RSU_transactions.xlsx'}}},
                'sources': {'pis': {}}, 'subsystems': {}}
    def temp_db():  # never the real DB, even if the endpoint reached it
        with DatabaseConnector(str(tmp_path / 'test.duckdb')) as db:
            yield db
    app.dependency_overrides[get_db] = app.dependency_overrides[get_writable_db] = temp_db
    try:
        with patch('src.api.routes.settings.settings_manager.load_settings', return_value=settings):
            response = TestClient(app).post('/settings/sources/upload/rsu', files={
                'file': ('RSU_transactions.xlsx', io.BytesIO(content),
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_writable_db, None)
    assert response.status_code == 422, response.text
    assert 'Transactions: G2' in response.json()['detail'] and 'Open it in Excel' in response.json()['detail']
    assert current.read_bytes() == b'current'
    assert sorted(p.name for p in source_dir.iterdir()) == ['RSU_transactions.xlsx']  # no temp file left
