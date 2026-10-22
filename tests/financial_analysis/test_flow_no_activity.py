"""No-activity evidence gates, using only synthetic in-memory data."""
import asyncio
from datetime import date

import pytest

from src.financial_analysis.flow_coverage import coverage_status, extend_flow_coverage
from src.financial_analysis.flow_rules import derive_flows
from tests.financial_analysis.test_flow_coverage import month


@pytest.mark.parametrize('evidence', ['date', 'upload', 'decision', 'none', 'invalid', 'same_day'])
@pytest.mark.parametrize('fs_present', [True, False])
def test_source_completeness(reviewed_flow_db, evidence, fs_present):
    db = reviewed_flow_db
    if fs_present:
        month(db, '2026-09-01')
    day = '2026-09-30' if evidence == 'date' else '2026-08-29'
    db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES (?, 'GOLD', 'Gold_Excel', 1)", [day])
    if evidence in {'upload', 'invalid', 'same_day'}:
        db.execute("INSERT INTO source_upload_history(reader, filename, uploaded_at, is_valid) VALUES ('gold', 'synthetic', ?, ?)",
                   ['2026-09-30 23:59:59' if evidence == 'same_day' else '2026-10-01', evidence != 'invalid'])
    key = 'no-activity:Gold_Excel:2026-09'
    if evidence == 'decision':
        db.execute("INSERT INTO external_flow_decisions(event_key, decision) VALUES (?, 'internal')", [key])
    complete = evidence in {'date', 'upload', 'decision'}
    blockers = coverage_status(db)['blockers']
    assert any(b['code'] == 'source_data_behind' for b in blockers) is not complete
    reviews = derive_flows(db, date(2026, 8, 31))[1]
    assert any(r['event_key'] == key and r['reason'] == 'no_activity_unconfirmed' for r in reviews) is not complete
    if not complete:
        assert {'code': 'open_reviews', 'count': 1} in blockers
        assert next(b for b in blockers if b['code'] == 'source_data_behind')['action_hint']
    assert extend_flow_coverage(db)['coverage_end'] == ('2026-09-30' if complete and fs_present else '2026-08-31')


def test_no_activity_api_confirmation(reviewed_flow_db, monkeypatch):
    from src.api.routes.performance import FlowReviewDecision, get_flow_review, put_flow_review
    monkeypatch.setattr('src.api.routes.performance.mark_dirty', lambda: None)
    db = reviewed_flow_db
    month(db, '2026-09-01')
    db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-08-29', 'GOLD', 'Gold_Excel', 1)")
    key = 'no-activity:Gold_Excel:2026-09'
    assert any(r['event_key'] == key for r in asyncio.run(get_flow_review(db))['items'])
    assert asyncio.run(put_flow_review(key, FlowReviewDecision(decision='internal'), db)) == {'event_key': key, 'decision': 'internal'}
    assert coverage_status(db)['blockers'] == []
    assert extend_flow_coverage(db)['coverage_end'] == '2026-09-30'


@pytest.mark.parametrize('source, reader', [('Gold_Excel', 'gold'), ('Schwab_CSV', 'schwab'),
    ('RSU_Excel', 'rsu'), ('CN_Fund_Excel', 'cn_fund'), ('Broker_IBKR', 'ibkr')])
def test_successful_upload_mapping(flow_db, source, reader):
    from src.financial_analysis.flow_rules import source_completeness
    db = flow_db
    end = date(2026, 9, 30)
    from src.api.routes.settings import _ensure_upload_history_table
    _ensure_upload_history_table(db)
    db.execute("INSERT INTO source_upload_history(reader, filename, uploaded_at, is_valid, origin) VALUES (?, 'synthetic', '2026-10-01', TRUE, 'fetch')", [reader])
    assert source_completeness(db, source, end) == (None, None)
    assert source_completeness(db, source, date(2026, 10, 31))[0] is not None


def test_no_activity_decisions_are_source_month_scoped(flow_db):
    from src.financial_analysis.flow_rules import source_completeness
    db = flow_db
    db.execute("INSERT INTO external_flow_decisions(event_key, decision) VALUES ('no-activity:Gold_Excel:2026-09', 'internal'), ('no-activity:RSU_Excel:2026-09', 'external_in')")
    assert source_completeness(db, 'Gold_Excel', date(2026, 9, 30)) == (None, None)
    assert source_completeness(db, 'Gold_Excel', date(2026, 10, 31))[0]
    assert source_completeness(db, 'RSU_Excel', date(2026, 9, 30))[0]


def test_latest_transaction_unblocks_carried_source(reviewed_flow_db):
    from tests.financial_analysis.test_flow_rules import tx
    db = reviewed_flow_db
    month(db, '2026-09-01')
    db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-08-29', 'GOLD', 'Gold_Excel', 1)")
    tx(db, 'Gold_Excel', transaction_date='2026-09-30', transaction_type='interest')
    assert coverage_status(db)['blockers'] == []
    assert extend_flow_coverage(db)['coverage_end'] == '2026-09-30'


def test_no_activity_rejects_external_decision(reviewed_flow_db):
    from src.api.routes.performance import FlowReviewDecision, put_flow_review
    response = asyncio.run(put_flow_review('no-activity:Gold_Excel:2026-09',
        FlowReviewDecision(decision='external_in'), reviewed_flow_db))
    assert response.status_code == 422
    assert reviewed_flow_db.execute('SELECT COUNT(*) FROM external_flow_decisions').fetchone()[0] == 0


@pytest.mark.parametrize('today, expected', [('2026-10-19', []), ('2026-10-31', []),
                                            ('2026-11-01', ['2026-10-31'])])
def test_monthly_reviews_wait_until_after_month_end(reviewed_flow_db, monkeypatch, today, expected):
    import src.financial_analysis.flow_rules as rules
    import src.financial_analysis.flow_coverage as coverage

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(today)

    monkeypatch.setattr(rules, 'date', FixedDate)
    monkeypatch.setattr(coverage, 'date', FixedDate, raising=False)
    db = reviewed_flow_db
    db.execute("UPDATE investment_twr_source SET coverage_end = '2026-09-30'")
    db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) "
               "VALUES ('2026-09-29', 'GOLD', 'Gold_Excel', 1)")
    # A future FS label must not make an unfinished month actionable.
    month(db, '2026-10-01')
    items = rules.derive_flows(db, date(2026, 9, 30))[1]
    assert [i['event_date'].isoformat() for i in items] == expected
    status = coverage.coverage_status(db)
    assert status.get('in_progress', False) == (not expected)
    if not expected:
        assert status['blockers'] == []
    else:
        assert {'code': 'open_reviews', 'count': len(items)} in status['blockers']


def test_card_and_chip_share_only_the_next_finished_month(reviewed_flow_db, monkeypatch):
    import src.financial_analysis.flow_rules as rules
    import src.financial_analysis.flow_coverage as coverage
    from src.api.routes.performance import get_flow_review
    from tests.financial_analysis.test_flow_rules import web

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 12, 1)

    monkeypatch.setattr(rules, 'date', FixedDate)
    monkeypatch.setattr(coverage, 'date', FixedDate)
    web(reviewed_flow_db, 'unknown', event_key='september-review', event_date='2026-09-15')
    web(reviewed_flow_db, 'unknown', event_key='october-review', event_date='2026-10-15')
    items = asyncio.run(get_flow_review(reviewed_flow_db))['items']
    assert [i['event_key'] for i in items] == ['september-review']
    assert {'code': 'open_reviews', 'count': len(items)} in coverage.coverage_status(reviewed_flow_db)['blockers']


@pytest.mark.parametrize('today, count', [('2026-09-30', 0), ('2026-10-01', 1)])
def test_transaction_review_waits_until_month_is_finished(reviewed_flow_db, monkeypatch, today, count):
    import src.financial_analysis.flow_rules as rules
    from tests.financial_analysis.test_flow_rules import web

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(today)

    monkeypatch.setattr(rules, 'date', FixedDate)
    web(reviewed_flow_db, 'unknown', event_key='pending', event_date='2026-09-10')
    assert len(rules.derive_flows(reviewed_flow_db, date(2026, 8, 31))[1]) == count


def test_complete_inputs_do_not_advance_into_an_unfinished_month(reviewed_flow_db, monkeypatch):
    import src.financial_analysis.flow_rules as rules
    import src.financial_analysis.flow_coverage as coverage

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 19)

    monkeypatch.setattr(rules, 'date', FixedDate)
    monkeypatch.setattr(coverage, 'date', FixedDate)
    month(reviewed_flow_db, '2026-09-01')
    month(reviewed_flow_db, '2026-10-01')
    assert coverage.extend_flow_coverage(reviewed_flow_db)['coverage_end'] == '2026-09-30'
