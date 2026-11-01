"""Synthetic investment-boundary examples; never open a portfolio DB."""
from datetime import date

import pytest

from src.financial_analysis.flow_rules import derive_flows



def tx(flow_db, source='CN_Fund_Excel', **kwargs):
    row = dict(transaction_date='2026-09-10', asset_id='SYNTHETIC',
               transaction_type='buy', source_system=source, amount_gross=120,
               amount_net=119, raw_business_type='银行卡支付买入',
               confirmation_status='成功', counterparty='测试银行卡')
    row.update(kwargs)
    flow_db.execute(f"INSERT INTO transactions ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
               list(row.values()))


def web(db, business='银行卡支付买入', **changes):
    row = dict(event_key='web-1', event_date='2026-09-10', event_time='12:00:00',
               fund_code='999999', fund_name='Synthetic Fund', business_type=business,
               applied_value=120, applied_unit='元', confirmed_value=60,
               confirmed_unit='份', account='测试银行 | 0000', status='成功')
    row.update(changes)
    db.execute(f"INSERT INTO cn_platform_events ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))


@pytest.mark.parametrize('raw', ['银行卡定投', '银行卡支付买入', '活期宝充值'])
@pytest.mark.parametrize('status', ['成功', '确认成功', '充值成功'])
def test_cn_in(flow_db, raw, status):
    web(flow_db, raw, status=status)
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert not reviews
    assert flows[0]['amount_cny'] == 120


@pytest.mark.parametrize('raw', ['卖出回银行卡', '活期宝快速取现', '活期宝普通取现'])
def test_cn_cash_out(flow_db, raw):
    web(flow_db, raw, confirmed_value=119, confirmed_unit='元')
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert not reviews
    assert flows[0]['amount_cny'] == -119


@pytest.mark.parametrize('raw', ['卖出回活期宝', '卖出回活期宝(普通)', '活期宝互转', '超级转换', '红利再投资', '份额调增', '份额调减', '活期宝每日分红'])
def test_cn_internal(flow_db, raw):
    web(flow_db, raw)
    assert derive_flows(flow_db, '2026-08-31') == ([], [])


@pytest.mark.parametrize('status', ['受理失败', '受理失败(退款中)', '无效申请', '已撤单'])
def test_cn_failed(flow_db, status):
    web(flow_db, status=status)
    assert derive_flows(flow_db, '2026-08-31') == ([], [])


@pytest.mark.parametrize('raw,account,status', [
    ('unknown', '测试银行', '成功'),
    ('银行卡定投', None, '成功'), ('银行卡定投', '活期宝 北京银行 | 0000', '成功'),
    ('银行卡定投', '测试银行', '已撤单(已支付)'), ('银行卡定投', '测试银行', '处理中'),
])
def test_cn_review(flow_db, raw, account, status):
    web(flow_db, raw, account=account, status=status)
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert not flows
    assert len(reviews) == 1


def fx(flow_db, day='2026-09-09', rate=7.1):
    flow_db.execute("INSERT INTO fx_daily VALUES (?, 'USDCNY', ?, 'synthetic')", [day, rate])


@pytest.mark.parametrize('source,kind,raw,gross,net,expected', [
    ('Schwab_CSV', 'other', 'MoneyLink Transfer', 120, 120, 120),
    ('Schwab_CSV', 'other', 'MoneyLink Transfer', -120, -120, -120),
    ('Broker_IBKR', 'other', 'Deposits/Withdrawals', -120, -120, -120),
    ('Gold_Excel', 'buy', None, 120, 119, 120),
    ('Gold_Excel', 'sell', None, 120, 119, -119),
    ('RSU_Excel', 'sell', None, -120, -121, -119),
])
def test_source_rules(flow_db, source, kind, raw, gross, net, expected):
    fx(flow_db)
    tx(flow_db, source, transaction_type=kind, raw_business_type=raw,
       amount_gross=gross, amount_net=net, commission_fee=1)
    flows, reviews = derive_flows(flow_db, date(2026, 8, 31))
    assert not reviews
    assert flows[0]['amount_cny'] == pytest.approx(expected * (1 if source == 'Gold_Excel' else 7.1))
    if source == 'RSU_Excel':
        assert flows[0]['evidence_status'] == 'auto_rule'
        assert flows[0]['date_basis'] == 'transaction_date'


def test_rsu_net_vest_and_receipt(flow_db):
    fx(flow_db)
    tx(flow_db, 'RSU_Excel', transaction_type='vest', raw_business_type=None,
       quantity=10, tax_withheld_shares=3, price_unit=20)
    tx(flow_db, 'RSU_Excel', transaction_type='sell', raw_business_type=None, bank_receipt=80)
    tx(flow_db, 'RSU_Excel', transaction_type='sell', raw_business_type=None, memo='sell to cover')
    flows, reviews = derive_flows(flow_db, date(2026, 8, 31))
    assert not reviews
    assert [f['amount_cny'] for f in flows] == [994, -852, -852]


@pytest.mark.parametrize('source,kind', [('Schwab_CSV', 'transfer_out'), ('Broker_IBKR', 'transfer_in'), ('Gold_Excel', 'interest')])
def test_internal_source_rules(flow_db, source, kind):
    tx(flow_db, source, transaction_type=kind, raw_business_type=None)
    assert derive_flows(flow_db, date(2026, 8, 31)) == ([], [])


def test_fx_five_day_window_and_no_future_rate(flow_db):
    from src.financial_analysis.fx_daily import lookup_fx
    fx(flow_db, '2026-09-05')
    fx(flow_db, '2026-09-11', 8)
    assert lookup_fx(flow_db, date(2026, 9, 10)) == (date(2026, 9, 5), 7.1)
    assert lookup_fx(flow_db, date(2026, 9, 4)) is None
    flow_db.execute("DELETE FROM fx_daily WHERE date = '2026-09-11'")
    assert lookup_fx(flow_db, date(2026, 9, 11)) is None


def test_decision_reused_and_manual(flow_db):
    web(flow_db, 'unknown')
    _, reviews = derive_flows(flow_db, date(2026, 8, 31))
    key = reviews[0]['event_key']
    flow_db.execute("INSERT INTO external_flow_decisions(event_key, decision, amount_cny) VALUES (?, 'external_out', 50)", [key])
    flow_db.execute("INSERT INTO external_flow_decisions(event_key, decision, amount_cny) VALUES ('manual:2026-09-12:test', 'manual', 60)")
    flows, reviews = derive_flows(flow_db, date(2026, 8, 31))
    assert not reviews
    assert [f['amount_cny'] for f in flows] == [-50, 60]
    assert all(f['evidence_status'] == 'owner_decision' for f in flows)
    assert derive_flows(flow_db, date(2026, 8, 31)) == (flows, reviews)


def test_ibkr_missing_ctrn_month_and_internal_decision(flow_db):
    flow_db.execute("INSERT INTO holdings(snapshot_date, asset_id, source_system, quantity) VALUES ('2026-09-30', 'SYNTHETIC', 'Broker_IBKR', 1)")
    _, reviews = derive_flows(flow_db, date(2026, 8, 31))
    assert reviews[0]['reason'] == 'IBKR deposits unknown'
    flow_db.execute("INSERT INTO flow_source_coverage VALUES ('Broker_IBKR', '2026-10-31', '2026-10-01', TRUE)")
    assert derive_flows(flow_db, date(2026, 8, 31))[1]
    flow_db.execute("INSERT INTO external_flow_decisions(event_key, decision) VALUES (?, 'internal')", [reviews[0]['event_key']])
    assert not derive_flows(flow_db, date(2026, 8, 31))[1]


def test_cn_huoqibao_transfer_into_fund_is_internal(flow_db):
    # 活期宝转入 pays for a fund from the 活期宝 balance; the linked card on the row is not a source.
    web(flow_db, '活期宝转入')
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert flows == [] and reviews == []


@pytest.mark.parametrize('raw', ['超级转换\n(有充值)', '超级转换（有充值）', '超级转换'])
def test_cn_super_conversion_is_internal(flow_db, raw):
    web(flow_db, raw)
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert flows == [] and reviews == []


@pytest.mark.parametrize('status', ['已撤单(无需支付)', '已撤单', '受理失败(支付失败)', '无效申请'])
def test_cn_unpaid_or_failed_is_ignored(flow_db, status):
    web(flow_db, '银行卡支付买入', status=status)
    flows, reviews = derive_flows(flow_db, '2026-08-31')
    assert flows == [] and reviews == []
