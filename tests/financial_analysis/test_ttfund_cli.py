"""TTFund coverage from a ttskill CLI pull or an owner attestation (synthetic data only)."""
import json
from datetime import date, timedelta

import pytest

from src.financial_analysis.flow_coverage import coverage_status, extend_flow_coverage
from src.sources.ttfund_cli import (
    PULL_FORMAT, coverage_frontier, import_cli_pull, parse_cli_pull, record_attestation,
)
from tests.financial_analysis.test_flow_coverage import month


def trade(when, business='红利再投资', apply='--', confirm='312.47份', trade_id=None, code='999999'):
    return {'tradeId': trade_id or f'{code}-{when}', 'tradeTime': when, 'fundCode': code,
            'fundName': 'Synthetic Fund', 'businessType': business, 'applyCount': apply,
            'confirmCount': confirm, 'statusText': '确认成功'}


def pull(start, end, all_trades=(), hqb_trades=(), pulled_at='2026-11-09T10:00:00+08:00', types=('all', 'hqb')):
    body = {'all': all_trades, 'hqb': hqb_trades}
    return {'format': PULL_FORMAT, 'pulled_at': pulled_at, 'query': {'start': start, 'end': end},
            'tool': 'ttskill TRADE_QUERY trade_list',
            'responses': [{'trade_type': t, 'result': {'data': {'raw_result': {'body': {
                'success': True, 'trade_list_result': {'trades': list(body[t])}}}}}} for t in types]}


def raw(payload):
    return json.dumps(payload, ensure_ascii=False).encode()


def test_parse_maps_amounts_dedupes_and_drops_out_of_range():
    hqb = trade('2026-09-20 09:00:00', '活期宝快速取现', apply='12,345.67元', confirm='--', trade_id='h1')
    parsed = parse_cli_pull(pull('2026-09-12', '2026-10-31',
                                 all_trades=[trade('2026-09-11 04:38:00'), hqb, trade('2026-10-02 10:00:00')],
                                 hqb_trades=[hqb]))
    assert [e['event_date'] for e in parsed['events']] == ['2026-09-20', '2026-10-02']
    assert parsed['events'][0]['applied_value'] == '12345.67' and parsed['events'][0]['applied_unit'] == '元'
    assert parsed['events'][0]['confirmed_value'] is None
    assert parsed['events'][1]['confirmed_value'] == '312.47' and parsed['events'][1]['confirmed_unit'] == '份'


@pytest.mark.parametrize('change,message', [
    ({'format': 'other'}, 'Not a'),
    ({'query': {'start': '2026-09-12', 'end': '2026-11-10'}}, 'on or before the pull date'),
    ({'responses': pull('2026-09-12', '2026-10-31', types=('hqb',))['responses']}, 'tradeType=all'),
])
def test_parse_rejects_bad_exports(change, message):
    with pytest.raises(ValueError, match=message):
        parse_cli_pull({**pull('2026-09-12', '2026-10-31'), **change})


def test_parse_rejects_failed_response():
    payload = pull('2026-09-12', '2026-10-31')
    payload['responses'][0]['result']['data']['raw_result']['body']['success'] = False
    with pytest.raises(ValueError, match='not a successful'):
        parse_cli_pull(payload)


def test_empty_pull_unblocks_a_month_without_trades(reviewed_flow_db):
    """No TTFund trades in September: the web list alone can never prove the month."""
    db = reviewed_flow_db
    db.execute("UPDATE cn_platform_events SET event_date = '2026-08-20'")
    month(db, '2026-09-01')
    assert extend_flow_coverage(db)['coverage_end'] == '2026-08-31'
    result = import_cli_pull(db, raw(pull('2026-08-21', '2026-10-01')))
    assert result['trades_in_range'] == 0 and result['imported_events'] == 0
    assert extend_flow_coverage(db)['coverage_end'] == '2026-09-30'
    status = coverage_status(db)
    assert status['cn_coverage']['through'] == '2026-10-01'
    assert status['cn_coverage']['records'][0]['basis'] == 'cli_pull'


def test_pull_skips_events_already_in_the_web_list(reviewed_flow_db):
    db = reviewed_flow_db  # fixture's last web event: 2026-10-31
    result = import_cli_pull(db, raw(pull('2026-10-20', '2026-11-05', all_trades=[
        trade('2026-10-25 09:00:00', '活期宝互转', apply='10.00元', confirm='--'),
        trade('2026-11-03 09:00:00', '活期宝互转', apply='20.00元', confirm='--')])))
    assert (result['already_in_web_list'], result['imported_events']) == (1, 1)
    assert db.execute('SELECT MAX(event_date) FROM cn_platform_events').fetchone()[0] == date(2026, 11, 3)


def test_coverage_with_a_gap_does_not_count(reviewed_flow_db):
    db = reviewed_flow_db
    db.execute("UPDATE cn_platform_events SET event_date = '2026-08-20'")
    import_cli_pull(db, raw(pull('2026-09-05', '2026-10-01')))
    frontier, used = coverage_frontier(db)
    assert frontier == date(2026, 8, 20) and used == []


def test_attestation_needs_a_note_and_past_days(reviewed_flow_db):
    db = reviewed_flow_db
    with pytest.raises(ValueError, match='note'):
        record_attestation(db, date(2026, 9, 12), date(2026, 10, 31), ' ')
    with pytest.raises(ValueError, match='passed'):
        record_attestation(db, date(2026, 9, 12), date.today(), 'owner')


def test_attestation_unblocks_and_is_marked_attested(reviewed_flow_db):
    db = reviewed_flow_db
    db.execute("UPDATE cn_platform_events SET event_date = '2026-08-20'")
    month(db, '2026-09-01')
    record_attestation(db, date(2026, 8, 21), date(2026, 9, 30),
                       'No TTFund transactions 2026-08-21 → 2026-09-30, confirmed by owner')
    assert extend_flow_coverage(db)['coverage_end'] == '2026-09-30'
    assert coverage_status(db)['cn_coverage']['records'][0]['basis'] == 'owner_attestation'
    assert date.today() - timedelta(days=1) >= date(2026, 9, 30)
