"""RSU liquidation remains an active zero through the normal shadow phases."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.database.connector import DatabaseConnector
from src.sources.hooks.rsu import derive_rsu_holdings
from src.sync.phases._ingest import _normalize_holdings_df, _upsert_holdings
from src.sync.phases._shadow import _shadow_stale_non_tradable_holdings, _shadow_stale_reader_holdings
from src.validation.data_integrity_gate import _check_reader_rows_not_all_shadowed, _check_shadow_mutual_exclusion


@pytest.mark.parametrize('prior_day', ['2026-10-19', '2026-09-01'])
@pytest.mark.parametrize('residue', [0, 1e-8, -1e-8])
def test_liquidation_overwrites_same_day_and_survives_sweeps(prior_day, residue):
    ledger = pd.DataFrame([
        dict(asset_id='RSU_AMZN', quantity=1.8, price_usd=200, transaction_date=date(2026, 8, 1)),
        dict(asset_id='RSU_AMZN', quantity=-1.8 + residue, price_usd=200, transaction_date=date(2026, 10, 19)),
        dict(asset_id='RSU_GOOG', quantity=2, price_usd=100, transaction_date=date(2026, 8, 1)),
    ])
    with DatabaseConnector(':memory:') as db:
        db.execute(Path('src/database/schema.sql').read_text())
        db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity, market_value) "
                   "VALUES (?, 'RSU_AMZN', 'RSU_Excel', 1.8, 3006)", [prior_day])
        for _ in range(2):
            output = derive_rsu_holdings(ledger, {'snapshot_date': '2026-10-19', 'prior_rsu_assets': {'RSU_AMZN'}})
            _upsert_holdings(db, _normalize_holdings_df(output, 'RSU_Excel'))
            _shadow_stale_reader_holdings(db)
            _shadow_stale_non_tradable_holdings(db)
        rows = db.execute("SELECT quantity, market_value, is_shadow FROM holdings WHERE asset_id='RSU_AMZN' "
                          "AND snapshot_date='2026-10-19'").fetchall()
        assert rows == [(0, 0, False)]
        assert db.execute("SELECT SUM(market_value) FROM holdings WHERE asset_id='RSU_AMZN' "
                          "AND snapshot_date=(SELECT MAX(snapshot_date) FROM holdings WHERE asset_id='RSU_AMZN')").fetchone()[0] == 0
        assert _check_shadow_mutual_exclusion(db).passed
        assert _check_reader_rows_not_all_shadowed(db).passed


def test_zero_without_prior_holdings_and_negative_quantity_are_not_liquidations():
    ledger = pd.DataFrame([
        dict(asset_id='RSU_NEW', quantity=0, price_usd=200, transaction_date=date(2026, 10, 19)),
        dict(asset_id='RSU_BAD', quantity=-1, price_usd=200, transaction_date=date(2026, 10, 19)),
    ])
    assert derive_rsu_holdings(ledger, {'prior_rsu_assets': {'RSU_BAD'}}).empty


def test_rsu_reader_passes_prior_assets_and_emits_zero(tmp_path, monkeypatch):
    import openpyxl
    from datetime import datetime
    from src.sync.orchestrator import SyncResult, _run_rsu_reader

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'Transactions'
    sheet.append(['交易日期', '资产名称', '交易类型', '单位', '数量',
                  '单位价格_USD', '总金额_USD', '手续费_USD', '备注'])
    sheet.append([datetime(2026, 8, 1), 'Amazon RSU', 'RSU Vest', 'Shares', 1.8, 200, 360, 0, 'synthetic'])
    sheet.append([datetime(2026, 10, 19), 'Amazon RSU', 'Sell', 'Shares', -1.8, 200, 360, 0, 'synthetic'])
    book.save(tmp_path / 'RSU_transactions.xlsx')
    config = {'source_registry': {'rsu': {'enabled': True, 'data_dir': str(tmp_path),
                                         'file_patterns': {'workbook': 'RSU_transactions.xlsx'}}}}
    monkeypatch.setattr('src.services.reader_mappings.load_id_field_maps', lambda *args: {'asset_name': {'Amazon RSU': 'AMZN'}})
    with DatabaseConnector(':memory:') as db:
        db.execute(Path('src/database/schema.sql').read_text())
        db.run_migrations()
        db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity, market_value) "
                   "VALUES (CURRENT_DATE, 'RSU_AMZN', 'RSU_Excel', 1.8, 3006)")
        result = SyncResult(success=True)
        assert _run_rsu_reader(db, config, result)[0] == 1, result.warnings
        result = SyncResult(success=True)
        assert _run_rsu_reader(db, config, result)[0] == 1, result.warnings
        _shadow_stale_reader_holdings(db)
        _shadow_stale_non_tradable_holdings(db)
        assert db.execute("SELECT quantity, market_value, is_shadow FROM holdings "
                          "WHERE asset_id='RSU_AMZN'").fetchall() == [(0, 0, False)]
        assert _check_shadow_mutual_exclusion(db).passed
        assert _check_reader_rows_not_all_shadowed(db).passed


def test_revest_resumes_normal_shadow_sweep():
    with DatabaseConnector(':memory:') as db:
        db.execute(Path('src/database/schema.sql').read_text())
        db.execute("INSERT INTO holdings(snapshot_date,asset_id,source_system,quantity,market_value) "
                   "VALUES ('2026-10-19','RSU_AMZN','RSU_Excel',0,0)")
        ledger = pd.DataFrame([dict(asset_id='RSU_AMZN', quantity=3, price_usd=200,
                                    transaction_date=date(2026, 10, 21))])
        output = derive_rsu_holdings(ledger, {'snapshot_date': '2026-10-21', 'prior_rsu_assets': {'RSU_AMZN'}})
        _upsert_holdings(db, _normalize_holdings_df(output, 'RSU_Excel'))
        _shadow_stale_non_tradable_holdings(db)
        assert db.execute("SELECT quantity, is_shadow FROM holdings ORDER BY snapshot_date").fetchall() == [(0, True), (3, False)]
        assert _check_shadow_mutual_exclusion(db).passed


def test_missing_ledger_quantity_does_not_zero_a_prior_position():
    ledger = pd.DataFrame([dict(asset_id='RSU_AMZN', quantity=None, price_usd=None,
                                transaction_date=date(2026, 10, 19))])
    assert derive_rsu_holdings(ledger, {'prior_rsu_assets': {'RSU_AMZN'}}).empty
