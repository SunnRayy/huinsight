"""Lead corrections, using synthetic inputs only."""
from datetime import date

import pytest
from openpyxl import Workbook

from src.financial_analysis.flow_coverage import extend_flow_coverage, freeze_reviewed_history
from src.financial_analysis.flow_rules import derive_flows
from tests.financial_analysis.test_flow_rules import tx, fx, web


def test_freeze_without_review(reviewed_flow_db):
    reviewed_flow_db.execute('DELETE FROM investment_twr_reviews')
    assert freeze_reviewed_history(reviewed_flow_db)
    assert reviewed_flow_db.execute('SELECT frozen_coverage_end FROM investment_twr_source').fetchone()[0] == date(2026, 8, 31)


def test_freeze_keeps_fingerprint_guard(reviewed_flow_db):
    reviewed_flow_db.execute('DELETE FROM investment_twr_reviews')
    reviewed_flow_db.execute("UPDATE investment_external_flows SET amount_cny=11")
    with pytest.raises(ValueError, match='baseline changed'):
        freeze_reviewed_history(reviewed_flow_db)


@pytest.mark.parametrize('field,value', [('quality', 'unavailable'), ('coverage_end', '2026-08-30')])
def test_freeze_requires_estimated_month_end(reviewed_flow_db, field, value):
    reviewed_flow_db.execute(f'UPDATE investment_twr_source SET {field}=?', [value])
    assert not freeze_reviewed_history(reviewed_flow_db)


@pytest.mark.parametrize('kind', ['sell', 'tax', 'sell_to_cover', 'tax_cover'])
def test_all_rsu_sales_use_proceeds(flow_db, kind):
    fx(flow_db)
    tx(flow_db, 'RSU_Excel', transaction_type=kind, amount_gross=-120,
       commission_fee=1, bank_receipt=80, memo='sell to cover')
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert not reviews
    assert flows[0]['original_amount'] == -119
    assert flows[0]['evidence_status'] == 'auto_rule'
    assert flows[0]['date_basis'] == 'transaction_date'


def test_cn_ledger_raw_fields_are_not_boundary_evidence(flow_db):
    tx(flow_db)
    assert derive_flows(flow_db, '2026-08-31') == ([], [])


def test_web_paste_is_read_only_normalized_and_idempotent(tmp_path, flow_db):
    from src.sources.cn_platform_events import import_web_workbook
    book = Workbook()
    sheet = book.active
    sheet.title = 'raw_web_transactions'
    sheet.append(['TTFund web paste'])
    header = ['申请时间', None, '基金名称\n代码', '业务类型', '申请数额', '确认数额', '关联账户', '状态', '操作']
    sheet.append(header)
    sheet.merge_cells('A2:B2')
    row = ['2026-09-10', '12:00:00', 'Synthetic Fund\n999999', '银行卡支付买入', '120.00元', '60.00份', '测试银行 | 0000', '成功', '详情']
    sheet.append(row)
    sheet.append([])
    sheet.append(header)
    sheet.append(['2026-09-10\n12:00:00', None, *row[2:]])
    path = tmp_path / 'synthetic-web.xlsx'
    book.save(path)
    before = path.read_bytes()
    assert import_web_workbook(flow_db, path) == 1
    assert import_web_workbook(flow_db, path) == 0
    assert path.read_bytes() == before
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert not reviews
    assert [f['amount_cny'] for f in flows] == [120]


def test_uncovered_flows_regenerated_on_decision_change(reviewed_flow_db):
    web(reviewed_flow_db, 'unknown')
    reviewed_flow_db.execute("INSERT INTO external_flow_decisions(event_key,decision,amount_cny) VALUES ('web-1','external_in',50)")
    extend_flow_coverage(reviewed_flow_db)
    reviewed_flow_db.execute("UPDATE external_flow_decisions SET amount_cny=80")
    extend_flow_coverage(reviewed_flow_db)
    assert reviewed_flow_db.execute("SELECT amount_cny FROM investment_external_flows WHERE flow_id='auto:web-1'").fetchone()[0] == 80
    reviewed_flow_db.execute("UPDATE external_flow_decisions SET decision='internal'")
    extend_flow_coverage(reviewed_flow_db)
    assert reviewed_flow_db.execute("SELECT COUNT(*) FROM investment_external_flows WHERE flow_id='auto:web-1'").fetchone()[0] == 0


@pytest.mark.parametrize('offset,quantity,matches', [(10, 60.01, True), (-10, 59.99, True), (11, 60, False), (0, 60.02, False)])
def test_cn_sell_ledger_matching(flow_db, offset, quantity, matches):
    from datetime import timedelta
    web(flow_db, '卖出回银行卡')
    tx(flow_db, asset_id='CN_FUND_999999', transaction_type='sell', quantity=quantity,
       transaction_date=date(2026, 9, 10) + timedelta(days=offset), amount_net=119)
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert bool(flows) == matches
    assert bool(reviews) != matches
    if matches:
        assert flows[0]['amount_cny'] == -119


def test_cn_sell_consumes_earliest_once(flow_db):
    web(flow_db, '卖出回银行卡')
    web(flow_db, '卖出回银行卡', event_key='web-2', event_time='13:00:00')
    web(flow_db, '卖出回银行卡', event_key='web-3', event_time='14:00:00')
    for day, cash in [('2026-09-12', 90), ('2026-09-11', 80)]:
        tx(flow_db, asset_id='CN_FUND_999999', transaction_type='sell', quantity=60, transaction_date=day, amount_net=cash)
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert [f['amount_cny'] for f in flows] == [-80, -90]
    assert len(reviews) == 1
    assert derive_flows(flow_db, '2026-08-31') == (flows, reviews)


@pytest.mark.parametrize('account,ledger,expected', [('测试银行 | 0000', True, -25), ('活期宝 北京银行 | 0000', False, None), ('测试银行 | 0000', False, 'review')])
def test_cn_cash_dividend_boundary(flow_db, account, ledger, expected):
    web(flow_db, '现金分红', account=account, confirmed_unit='元', confirmed_value=999)
    if ledger:
        tx(flow_db, asset_id='CN_FUND_999999', transaction_type='dividend_cash', amount_net=25)
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    if expected == 'review':
        assert not flows and len(reviews) == 1
    else:
        assert not reviews
        assert [f['amount_cny'] for f in flows] == ([] if expected is None else [expected])


def test_cn_coverage_requires_web_month_not_app_or_snapshot(reviewed_flow_db):
    from tests.financial_analysis.test_flow_coverage import month
    reviewed_flow_db.execute('DELETE FROM cn_platform_events')
    month(reviewed_flow_db, '2026-09-01')
    tx(reviewed_flow_db, transaction_date='2026-09-30')
    reviewed_flow_db.execute("INSERT INTO holdings(snapshot_date,asset_id,source_system,quantity) VALUES ('2026-09-30','CN_FUND_999999','CN_Fund_Excel',1)")
    assert extend_flow_coverage(reviewed_flow_db)['coverage_end'] == '2026-08-31'
    web(reviewed_flow_db, '活期宝互转', event_date='2026-09-01')
    assert extend_flow_coverage(reviewed_flow_db)['coverage_end'] == '2026-09-30'


def test_months_after_frozen_end_are_recomputed_but_frozen_rows_are_not(reviewed_flow_db):
    """0.1.4 policy: only the frozen history is immutable; later months follow corrections."""
    from tests.financial_analysis.test_flow_coverage import month
    web(reviewed_flow_db)
    month(reviewed_flow_db, '2026-09-01')
    assert extend_flow_coverage(reviewed_flow_db)['coverage_end'] == '2026-09-30'
    frozen = reviewed_flow_db.execute("SELECT * FROM investment_external_flows WHERE flow_id='reviewed'").fetchall()
    reviewed_flow_db.execute("INSERT INTO external_flow_decisions(event_key,decision,amount_cny) VALUES ('web-1','external_out',999)")
    extend_flow_coverage(reviewed_flow_db)
    row = reviewed_flow_db.execute("SELECT amount_cny, evidence_status FROM investment_external_flows WHERE flow_id='auto:web-1'").fetchone()
    assert (float(row[0]), row[1]) == (-999.0, 'owner_decision')
    assert reviewed_flow_db.execute("SELECT * FROM investment_external_flows WHERE flow_id='reviewed'").fetchall() == frozen


def test_open_reviews_do_not_degrade_sync(reviewed_flow_db, monkeypatch):
    from src.sync import orchestrator as orch
    from src.sync.phases._common import SyncResult
    web(reviewed_flow_db, 'unknown')
    monkeypatch.setattr(orch, '_PHASE2_READER_ORDER', [])
    from unittest.mock import Mock
    monkeypatch.setattr('src.sources.registry.get_registry', lambda: Mock(reader_keys=lambda: []))
    result = SyncResult(success=True)
    orch._dispatch_phase2_readers(reviewed_flow_db, {}, result)
    assert result.success and not result.degraded
    assert not [step for step in result.steps if step.status == 'failed']
    assert '1 investment-flow items need confirmation' in result.warnings


def test_fs_reader_preserves_baseline_without_review_row(reviewed_flow_db, monkeypatch):
    import pandas as pd
    from unittest.mock import Mock
    from src.sync import orchestrator as orch
    from src.sync.phases._common import SyncResult
    reviewed_flow_db.execute('DELETE FROM investment_twr_reviews')
    monkeypatch.setattr(orch, 'sync_financial_summary', lambda _: {'holdings': pd.DataFrame()})
    monkeypatch.setattr(orch, '_persist_financial_summary', lambda *args: (1, 0))
    monkeypatch.setattr('src.sources.config_driven_reader.sync_config_source', lambda *args, **kwargs: {'holdings': pd.DataFrame()})
    monkeypatch.setattr('src.services.reader_mappings.load_reader_mappings', lambda *args: {})
    monkeypatch.setattr(orch, '_upsert_holdings', lambda *args: 0)
    monkeypatch.setattr(orch, '_log_sync_event', lambda **kwargs: None)
    replacement = Mock(side_effect=AssertionError('must not replace frozen flows'))
    monkeypatch.setattr(orch, 'replace_investment_twr_source', replacement)
    result = SyncResult(success=True)
    assert orch._run_financial_summary_reader(reviewed_flow_db, {'source_registry': {'financial_summary': {'enabled': True}}}, result) == (0, 0)
    assert not replacement.called
    assert reviewed_flow_db.execute('SELECT frozen_coverage_end FROM investment_twr_source').fetchone()[0] == date(2026, 8, 31)


def test_web_header_split_fund_and_merged_date():
    from src.sources.cn_platform_events import parse_web_rows, normalize_event
    rows = [
        ['申请时间', None, '基金名称', '代码', '业务类型', '申请数额', '确认数额', '关联账户', '状态', '操作'],
        ['2026-09-10', '12:00', 'Synthetic Fund', '999999', '卖出回活期宝', '100份', None, '活期宝\n测试银行 | 0000', '确认成功', '详情'],
        [None, '13:00', 'Synthetic Fund', '999999', '活期宝每日分红', '1元', None, '活期宝\n测试银行 | 0000', '成功', '详情'],
    ]
    events = [normalize_event(row) for row in parse_web_rows(rows)]
    assert [row['event_time'] for row in events] == ['12:00:00', '13:00:00']
    assert all(row['event_date'] == '2026-09-10' for row in events)
    assert events[0]['fund_code'] == '999999'
    assert events[0]['confirmed_value'] is None
    assert events[0]['account'] == '活期宝 测试银行 | 0000'


def test_new_paste_regenerates_uncovered_auto_rule(reviewed_flow_db):
    web(reviewed_flow_db, '卖出回银行卡')
    tx(reviewed_flow_db, asset_id='CN_FUND_999999', transaction_type='sell', quantity=60, amount_net=90)
    extend_flow_coverage(reviewed_flow_db)
    assert reviewed_flow_db.execute("SELECT amount_cny FROM investment_external_flows WHERE flow_id='auto:web-1'").fetchone()[0] == -90
    reviewed_flow_db.execute('UPDATE transactions SET amount_net=80')
    extend_flow_coverage(reviewed_flow_db)
    assert reviewed_flow_db.execute("SELECT amount_cny FROM investment_external_flows WHERE flow_id='auto:web-1'").fetchone()[0] == -80


def test_web_migration_is_additive_and_repeatable(flow_db):
    from pathlib import Path
    web(flow_db)
    before = flow_db.execute('SELECT * FROM cn_platform_events').fetchall()
    for _ in range(2):
        flow_db.execute(Path('src/database/migrations/198_cn_platform_events.sql').read_text())
    assert flow_db.execute('SELECT * FROM cn_platform_events').fetchall() == before
