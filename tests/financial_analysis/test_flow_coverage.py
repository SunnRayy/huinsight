"""Forward coverage gates on synthetic monthly inputs only."""
import json

import pytest

from tests.financial_analysis.test_flow_rules import tx, web
from src.financial_analysis.flow_coverage import extend_flow_coverage
from src.financial_analysis.twr import (
    INVESTMENT_VALUE_COLUMNS, load_investment_return_inputs,
)


def month(flow_db, label, missing=False):
    # Distinct per month: identical month-over-month values trip the fs_value_unchanged check.
    payload = dict.fromkeys(INVESTMENT_VALUE_COLUMNS, 100 + int(label[5:7]))
    if missing:
        payload.pop(INVESTMENT_VALUE_COLUMNS[0])
    flow_db.execute('INSERT INTO balance_sheet_monthly(record_key, snapshot_date, payload, source_system) '
               "VALUES (?, ?, ?, 'synthetic')", [label, label, json.dumps(payload)])



def test_idempotency_frozen_rows_and_loader(reviewed_flow_db):
    con = reviewed_flow_db
    frozen = con.execute("SELECT * FROM investment_external_flows WHERE flow_id = 'reviewed'").fetchall()
    web(con)
    month(con, '2026-09-01')
    assert extend_flow_coverage(con)['coverage_end'] == '2026-09-30'
    assert extend_flow_coverage(con)['coverage_end'] == '2026-09-30'
    assert con.execute('SELECT COUNT(*) FROM investment_external_flows').fetchone()[0] == 2
    assert con.execute("SELECT * FROM investment_external_flows WHERE flow_id = 'reviewed'").fetchall() == frozen
    inputs = load_investment_return_inputs(con)
    assert inputs['as_of'] == '2026-09-30'
    assert not inputs['history_changed_since_review']


@pytest.mark.parametrize('blocker', ['missing_fs', 'partial_fs', 'review', 'fx', 'source_stale', 'gap'])
def test_coverage_stops(reviewed_flow_db, blocker):
    con = reviewed_flow_db
    if blocker == 'gap':
        month(con, '2026-10-01')
    elif blocker != 'missing_fs':
        month(con, '2026-09-01', missing=blocker == 'partial_fs')
    if blocker == 'review':
        web(con, 'unknown')
    elif blocker == 'fx':
        tx(con, 'Schwab_CSV', raw_business_type='MoneyLink Transfer', transaction_type='other')
    elif blocker == 'source_stale':
        con.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-08-30', 'SYNTHETIC', 'Gold_Excel', 1)")
    assert extend_flow_coverage(con)['coverage_end'] == '2026-08-31'


def test_source_fresh_snapshot_unblocks(reviewed_flow_db):
    month(reviewed_flow_db, '2026-09-01')
    reviewed_flow_db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-09-30', 'SYNTHETIC', 'Gold_Excel', 1)")
    assert extend_flow_coverage(reviewed_flow_db)['coverage_end'] == '2026-09-30'


def test_valuation_edit_keeps_serving_and_missing_still_fails(reviewed_flow_db):
    extend_flow_coverage(reviewed_flow_db)
    reviewed_flow_db.execute("UPDATE balance_sheet_monthly SET payload = ? WHERE snapshot_date = '2026-08-01'",
                     [json.dumps(dict.fromkeys(INVESTMENT_VALUE_COLUMNS, 110))])
    assert load_investment_return_inputs(reviewed_flow_db)['history_changed_since_review']
    assert extend_flow_coverage(reviewed_flow_db)['history_changed_since_review']
    assert load_investment_return_inputs(reviewed_flow_db)['history_changed_since_review']
    reviewed_flow_db.execute("UPDATE balance_sheet_monthly SET payload = '{}' WHERE snapshot_date = '2026-08-01'")
    assert load_investment_return_inputs(reviewed_flow_db) is None


def test_raw_flows_edit_remains_fail_closed(reviewed_flow_db):
    reviewed_flow_db.execute("UPDATE investment_external_flows SET amount_cny = 11 WHERE flow_id = 'reviewed'")
    assert load_investment_return_inputs(reviewed_flow_db) is None


def test_frozen_transaction_is_not_rederived(reviewed_flow_db):
    tx(reviewed_flow_db, transaction_date='2026-08-10', raw_business_type=None)
    extend_flow_coverage(reviewed_flow_db)
    assert reviewed_flow_db.execute('SELECT COUNT(*) FROM investment_external_flows').fetchone()[0] == 1


def test_sync_does_not_rebless_tampered_reviewed_flow(reviewed_flow_db):
    extend_flow_coverage(reviewed_flow_db)
    reviewed_flow_db.execute("UPDATE investment_external_flows SET amount_cny = 11 WHERE flow_id = 'reviewed'")
    with pytest.raises(ValueError, match='boundary evidence changed'):
        extend_flow_coverage(reviewed_flow_db)
    assert load_investment_return_inputs(reviewed_flow_db) is None


def test_carried_ibkr_requires_ctrn_for_each_month(reviewed_flow_db, monkeypatch):
    from datetime import date

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 1)

    monkeypatch.setattr('src.financial_analysis.flow_coverage.date', FixedDate)
    monkeypatch.setattr('src.financial_analysis.flow_rules.date', FixedDate)
    month(reviewed_flow_db, '2026-09-01')
    month(reviewed_flow_db, '2026-10-01')
    reviewed_flow_db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-08-31', 'SYNTHETIC', 'Broker_IBKR', 1), ('2026-10-31', 'SYNTHETIC', 'Broker_IBKR', 1)")
    reviewed_flow_db.execute("INSERT INTO flow_source_coverage VALUES ('Broker_IBKR', '2026-10-31', '2026-10-01', TRUE)")
    assert extend_flow_coverage(reviewed_flow_db)['coverage_end'] == '2026-08-31'
    reviewed_flow_db.execute("INSERT INTO flow_source_coverage VALUES ('Broker_IBKR', '2026-09-30', '2026-09-01', TRUE)")
    assert extend_flow_coverage(reviewed_flow_db)['coverage_end'] == '2026-10-31'


def test_frozen_valuation_provenance_still_fails_closed(reviewed_flow_db):
    extend_flow_coverage(reviewed_flow_db)
    reviewed_flow_db.execute("UPDATE balance_sheet_monthly SET source_system = 'unknown' WHERE snapshot_date = '2026-08-01'")
    assert load_investment_return_inputs(reviewed_flow_db) is None
    with pytest.raises(ValueError, match='provenance changed'):
        extend_flow_coverage(reviewed_flow_db)


def test_oracle_script_on_readonly_synthetic_copy(tmp_path):
    import duckdb
    import subprocess
    import sys
    from pathlib import Path
    path = tmp_path / 'synthetic-copy.duckdb'
    with duckdb.connect(str(path)) as con:
        con.execute(Path('src/database/schema.sql').read_text())
        month(con, '2026-08-01')
        month(con, '2026-09-01')
        con.execute("INSERT INTO investment_external_flows VALUES ('oracle', '2026-09-10', 120, 120, 'CNY', '2026-09-10', 1, 'TTFund', 'in', 'confirmed', 'synthetic', 'posted')")
    csv_path = tmp_path / 'web.csv'
    csv_path.write_text('event_date,event_time,fund_code,fund_name,business_type,status,application_amount_value,application_amount_unit,confirmed_amount_value,confirmed_amount_unit,associated_account_raw\n'
                        '2026-09-10,12:00:00,999999,Synthetic Fund,银行卡支付买入,成功,120,元,60,份,测试银行 | 0000\n')
    before = path.read_bytes()
    result = subprocess.run([sys.executable, 'scripts/flow_rules_oracle_check.py', str(path),
                             '--start', '2026-08-31', '--end', '2026-09-30', '--cn-web-csv', str(csv_path)],
                            capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report['sources']['TTFund']['matched']['count'] == 1
    assert report['metrics']['oracle'] == report['metrics']['rules']
    assert path.read_bytes() == before
