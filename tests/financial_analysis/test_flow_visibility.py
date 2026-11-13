"""Read-only owner visibility using synthetic inputs."""
import asyncio
from datetime import date

import pytest

from tests.financial_analysis.test_flow_coverage import month
from tests.financial_analysis.test_flow_rules import tx, web


@pytest.mark.parametrize('case, expected', [
    ('fs', {'code': 'fs_month_missing'}),
    ('cn', {'code': 'cn_web_list_missing'}),
    ('source', {'code': 'source_data_behind', 'source': 'Gold', 'latest_date': '2026-08-30', 'action_hint': 'confirm_no_activity_or_upload'}),
    ('ibkr', {'code': 'ibkr_cash_transactions_missing'}),
    ('fx', {'code': 'fx_unavailable'}),
    ('review', {'code': 'open_reviews', 'count': 1}),
])
def test_blockers_readonly_and_match_extension(reviewed_flow_db, case, expected):
    from src.financial_analysis.flow_coverage import coverage_status, extend_flow_coverage
    db = reviewed_flow_db
    if case != 'fs':
        month(db, '2026-09-01')
    if case == 'cn':
        db.execute('DELETE FROM cn_platform_events')
    if case == 'source':
        db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-08-30', 'SYNTHETIC', 'Gold_Excel', 1)")
    if case == 'ibkr':
        db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-09-30', 'SYNTHETIC', 'Broker_IBKR', 1)")
    if case == 'fx':
        tx(db, 'Schwab_CSV', transaction_type='other', raw_business_type='MoneyLink')
    if case == 'review':
        web(db, 'unknown')
    before = db.execute('SELECT * FROM investment_twr_source').fetchall()
    status = coverage_status(db)
    assert expected in status['blockers']
    assert status['next_month'] == '2026-09-01'
    assert status['frozen_end'] == status['coverage_end'] == '2026-08-31'
    assert db.execute('SELECT * FROM investment_twr_source').fetchall() == before
    assert extend_flow_coverage(db)['coverage_end'] == status['coverage_end']


def test_clear_and_only_next_month(reviewed_flow_db):
    from src.financial_analysis.flow_coverage import coverage_status
    month(reviewed_flow_db, '2026-09-01')
    web(reviewed_flow_db, 'unknown', event_date='2026-10-10')
    assert coverage_status(reviewed_flow_db)['blockers'] == []


def test_returns_api_shape(reviewed_flow_db):
    from src.api.routes.performance import get_performance_returns
    result = asyncio.run(get_performance_returns(period='all_time', db=reviewed_flow_db))
    assert result['coverage_status'] == {
        'frozen_end': '2026-08-31', 'coverage_end': '2026-08-31',
        'next_month': '2026-09-01', 'blockers': [{'code': 'fs_month_missing'}],
        'cn_coverage': {'through': '2026-10-31', 'records': []},
    }


def test_ibkr_manual_review_resolves(reviewed_flow_db, monkeypatch):
    from src.api.routes.performance import put_flow_review, FlowReviewDecision
    from src.financial_analysis.flow_rules import derive_flows
    monkeypatch.setattr('src.api.routes.performance.mark_dirty', lambda: None)
    db = reviewed_flow_db
    month(db, '2026-09-01')
    db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-09-30', 'SYNTHETIC', 'Broker_IBKR', 1)")
    key = 'ibkr-unknown:2026-09-30'
    result = asyncio.run(put_flow_review(key, FlowReviewDecision(decision='manual', amount_cny=-120), db))
    assert result == {'event_key': key, 'decision': 'manual'}
    flows, reviews = derive_flows(db, date(2026, 8, 31))
    assert reviews == []
    assert flows[0]['amount_cny'] == -120


def test_non_reader_and_null_sources_are_ignored(reviewed_flow_db):
    from src.financial_analysis.flow_coverage import coverage_status
    month(reviewed_flow_db, '2026-09-01')
    reviewed_flow_db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-09-30', 'SYNTHETIC', NULL, 1), ('2026-09-30', 'GOLD', 'Gold_Excel', 1)")
    assert coverage_status(reviewed_flow_db)['blockers'] == []


def test_no_baseline(flow_db):
    from src.financial_analysis.flow_coverage import coverage_status
    assert coverage_status(flow_db) == dict(frozen_end=None, coverage_end=None, next_month=None, blockers=[])


def test_partial_fs_is_missing(reviewed_flow_db):
    from src.financial_analysis.flow_coverage import coverage_status
    month(reviewed_flow_db, '2026-09-01', missing=True)
    assert coverage_status(reviewed_flow_db)['blockers'] == [{'code': 'fs_month_missing'}]


def test_source_with_activity_in_month_asks_for_upload_not_no_activity(reviewed_flow_db):
    """Schwab-like case: data reaches mid-month, so 'no activity' must not be offered."""
    from datetime import date
    from src.financial_analysis.flow_rules import source_completeness
    reviewed_flow_db.execute("INSERT INTO holdings(snapshot_date,asset_id,source_system,quantity) "
                             "VALUES ('2026-09-18','US_STK_TEST','Schwab_CSV',1)")
    blocker, review = source_completeness(reviewed_flow_db, 'Schwab_CSV', date(2026, 9, 30))
    assert blocker['action_hint'] == 'upload_newer'
    assert review['reason'] == 'upload_needed' and review['latest_date'] == '2026-09-18'


def _fs_month(db, label, **overrides):
    import json
    from src.financial_analysis.twr import INVESTMENT_VALUE_COLUMNS
    payload = dict.fromkeys(INVESTMENT_VALUE_COLUMNS, 100 + int(label[5:7]))
    payload.update(overrides)
    db.execute("INSERT INTO balance_sheet_monthly(record_key, snapshot_date, payload, source_system) "
               "VALUES (?, ?, ?, 'synthetic')", [label, label, json.dumps(payload)])


def test_fs_zero_while_rsu_still_held_blocks_the_month(reviewed_flow_db):
    """A blank/zero FS cell while the ledger still holds shares must not become an investment loss."""
    db = reviewed_flow_db
    db.execute("INSERT INTO fx_daily VALUES ('2026-09-30', 'USDCNY', 7.0, 'synthetic')")
    db.execute("INSERT INTO transactions(id, transaction_date, asset_id, transaction_type, quantity, price_unit, "
               "amount_gross, amount_net, currency, source_system) VALUES "
               "(9001, '2026-01-15', 'RSU_AMZN', 'vest', 100, 200, 20000, 20000, 'USD', 'RSU_Excel')")
    _fs_month(db, '2026-09-01', **{'投资资产_公司RSU_Amazon Stock': 0})
    from src.financial_analysis.flow_rules import fs_value_reviews
    from datetime import date
    items = fs_value_reviews(db, date(2026, 8, 31))
    assert [(i['reason'], i['column']) for i in items] == [('fs_zero_with_position', '投资资产_公司RSU_Amazon Stock')]
    assert items[0]['estimate_cny'] == 140000.0
    from src.financial_analysis.flow_coverage import extend_flow_coverage
    assert extend_flow_coverage(db)["coverage_end"] == "2026-08-31"
    db.execute("INSERT INTO external_flow_decisions(event_key, decision) VALUES (?, 'internal')", [items[0]['event_key']])
    assert fs_value_reviews(db, date(2026, 8, 31)) == []


def test_fs_value_identical_to_previous_month_is_flagged(reviewed_flow_db):
    from src.financial_analysis.flow_rules import fs_value_reviews
    from datetime import date
    _fs_month(reviewed_flow_db, '2026-09-01', **{'投资资产_黄金_纸黄金(元)': 108})  # equals August
    items = fs_value_reviews(reviewed_flow_db, date(2026, 8, 31))
    assert [(i['reason'], i['column']) for i in items] == [('fs_value_unchanged', '投资资产_黄金_纸黄金(元)')]
