"""Synthetic workbook/Flex retention checks through the ingest boundary."""

import pandas as pd
from openpyxl import Workbook, load_workbook

from src.sources.cn_fund_raw_processor import process_raw_transactions
from src.sources.hooks.cn_fund import cn_fund_transactions_from_sheet
from src.sources.config_driven_reader import _parse_flex_sections
from src.sources.hooks.ibkr import ibkr_transactions_from_flex
from src.sync.phases._ingest import _normalize_transactions_df, _replace_transactions


def test_cn_append_preserves_old_rows_and_raw_fields(tmp_path, flow_db):
    book = Workbook()
    processed = book.active
    processed.title = '基金交易记录'
    processed.append(['交易日期', '基金代码', '基金名称', '操作类型', '交易金额', '交易份额', '交易时基金单位净值', '手续费', '交易原因'])
    from datetime import datetime
    old = [datetime(2026, 8, 3), '999999', 'Synthetic Fund', '申购', 10, 5, 2, 0, 'existing']
    processed.append(old)
    raw = book.create_sheet('raw_transactions_paste')
    raw.append(['确认日期', '基金代码', '基金简称', '业务类型', '确认状态', '确认份额', '确认金额', '手续费', '确认净值', '关联银行卡'])
    raw.append([datetime(2026, 9, 10), '999999', 'Synthetic Fund', '银行卡支付买入', '成功', 50, 101, 1, 2, '测试银行卡'])
    path = tmp_path / 'synthetic.xlsx'
    book.save(path)
    assert process_raw_transactions(path).new_count == 1
    assert process_raw_transactions(path).new_count == 0
    rows = list(load_workbook(path)['基金交易记录'].values)
    assert list(rows[1][:9]) == old
    assert list(rows[2][-4:]) == ['银行卡支付买入', '成功', '测试银行卡', 101]
    frame = cn_fund_transactions_from_sheet(pd.DataFrame(rows[1:], columns=rows[0]), {})
    normalized = _normalize_transactions_df(frame, 'CN_Fund_Excel')
    _replace_transactions(flow_db, normalized)
    _replace_transactions(flow_db, normalized)
    stored = flow_db.execute("SELECT raw_business_type, counterparty, amount_gross, source_event_key FROM transactions WHERE transaction_date='2026-09-10'").fetchall()
    assert len(stored) == 1
    assert stored[0][:3] == ('银行卡支付买入', '测试银行卡', 101)
    assert len(stored[0][3]) == 64


def test_cn_keyed_reimport_over_keyless_ledger_does_not_duplicate(tmp_path, flow_db):
    """2026-10-19: the first keyed import re-inserted every key-less row."""
    from datetime import datetime
    book = Workbook()
    processed = book.active
    processed.title = '基金交易记录'
    processed.append(['交易日期', '基金代码', '基金名称', '操作类型', '交易金额', '交易份额', '交易时基金单位净值', '手续费', '交易原因'])
    processed.append([datetime(2026, 8, 3), '999999', 'Synthetic Fund', '申购', 100, 50, 2, 0, 'order-1'])
    processed.append([datetime(2026, 8, 3), '999999', 'Synthetic Fund', '申购', 100, 50, 2, 0, 'order-2'])
    processed.append([datetime(2026, 8, 5), '999999', 'Synthetic Fund', '赎回', 40, 20, 2, 0, 'sale'])
    raw = book.create_sheet('raw_transactions_paste')
    raw.append(['确认日期', '基金代码', '基金简称', '业务类型', '确认状态', '确认份额', '确认金额', '手续费', '确认净值', '关联银行卡'])
    raw.append([datetime(2026, 9, 10), '999999', 'Synthetic Fund', '银行卡支付买入', '成功', 50, 101, 1, 2, '测试银行卡'])
    path = tmp_path / 'synthetic.xlsx'
    book.save(path)
    process_raw_transactions(path)
    rows = list(load_workbook(path)['基金交易记录'].values)
    keyed = _normalize_transactions_df(
        cn_fund_transactions_from_sheet(pd.DataFrame(rows[1:], columns=rows[0]), {}), 'CN_Fund_Excel')
    assert keyed['source_event_key'].notna().all()

    _replace_transactions(flow_db, keyed.assign(source_event_key=None))  # pre-key import
    for _ in range(2):
        _replace_transactions(flow_db, keyed)
        stored = flow_db.execute(
            "SELECT memo, source_event_key FROM transactions WHERE source_system='CN_Fund_Excel' ORDER BY id"
        ).fetchall()
        assert len(stored) == len(keyed) == 4
        assert all(key is not None for _, key in stored)
        assert sorted(m for m, _ in stored if m and m.startswith('order-')) == ['order-1', 'order-2']

    # A run whose pre-read hook did not extend the sheet has no key or provenance:
    # the keyed ledger is left as it is, including a genuinely new order in that run.
    hookless = keyed.assign(source_event_key=None, raw_business_type=None,
                            confirmation_status=None, counterparty=None)
    new_order = hookless.iloc[[0]].assign(memo='order-3')
    for _ in range(2):
        _replace_transactions(flow_db, pd.concat([hookless, new_order], ignore_index=True))
        assert flow_db.execute(
            "SELECT COUNT(*), COUNT(source_event_key) FROM transactions WHERE source_system='CN_Fund_Excel'"
        ).fetchone() == (4, 4)
    # The next run with keys imports the new order normally.
    with_new = pd.concat([keyed, keyed.iloc[[0]].assign(memo='order-3', source_event_key='k-new')],
                         ignore_index=True)
    _replace_transactions(flow_db, with_new)
    assert flow_db.execute(
        "SELECT COUNT(*) FROM transactions WHERE source_system='CN_Fund_Excel'"
    ).fetchone()[0] == 5


def test_cn_keyless_batch_still_imports_into_a_keyless_ledger(flow_db):
    """Without any keyed rows the old behaviour holds (e.g. an older workbook layout)."""
    from datetime import datetime
    header = ['交易日期', '基金代码', '基金名称', '操作类型', '交易金额', '交易份额', '交易时基金单位净值', '手续费', '交易原因']
    rows = [[datetime(2026, 8, 3), '999999', 'Synthetic Fund', '申购', 100, 50, 2, 0, 'order-1']]
    frame = _normalize_transactions_df(
        cn_fund_transactions_from_sheet(pd.DataFrame(rows, columns=header), {}), 'CN_Fund_Excel')
    assert frame['source_event_key'].isna().all()
    _replace_transactions(flow_db, frame)
    assert flow_db.execute(
        "SELECT COUNT(*) FROM transactions WHERE source_system='CN_Fund_Excel'").fetchone()[0] == 1


def test_paste_processor_keeps_same_day_orders_in_different_accounts(tmp_path):
    """Three 红利再投资 rows (amount 0) on one day, one per card, stay three rows."""
    from datetime import datetime
    book = Workbook()
    processed = book.active
    processed.title = '基金交易记录'
    processed.append(['交易日期', '基金代码', '基金名称', '操作类型', '交易金额', '交易份额', '交易时基金单位净值', '手续费', '交易原因'])
    raw = book.create_sheet('raw_transactions_paste')
    raw.append(['确认日期', '基金代码', '基金简称', '业务类型', '确认状态', '确认份额', '确认金额', '手续费', '确认净值', '关联银行卡'])
    for card, shares in (('测试卡A', 512.3), ('测试卡B', 498.75), ('测试卡C', 512.3)):
        raw.append([datetime(2026, 9, 15), '999999', 'Synthetic Fund', '红利再投资', '成功', shares, 0, 0, 1.1, card])
    path = tmp_path / 'reinvest.xlsx'
    book.save(path)
    assert process_raw_transactions(path).new_count == 3
    assert process_raw_transactions(path).new_count == 0
    assert len(list(load_workbook(path)['基金交易记录'].values)) == 4


def test_cn_equal_orders_on_different_cards_both_survive(flow_db):
    """Ingest keeps ledger rows that differ only by card (the paste processor is separate)."""
    from datetime import datetime
    header = ['交易日期', '基金代码', '基金名称', '操作类型', '交易金额', '交易份额', '交易时基金单位净值',
              '手续费', '交易原因', '原始业务类型', '确认状态', '关联银行卡', '确认金额']
    rows = [
        [datetime(2026, 9, 10), '999999', 'Synthetic Fund', '红利再投资', 0, 50, 2, 0,
         'Dividend Reinvestment', '红利再投资', '成功', card, 0]
        for card in ('测试银行卡A', '测试银行卡B')
    ]
    frame = _normalize_transactions_df(
        cn_fund_transactions_from_sheet(pd.DataFrame(rows, columns=header), {}), 'CN_Fund_Excel')

    for _ in range(2):
        _replace_transactions(flow_db, frame)
        cards = flow_db.execute(
            "SELECT counterparty FROM transactions WHERE source_system='CN_Fund_Excel' ORDER BY counterparty"
        ).fetchall()
        assert [c[0] for c in cards] == ['测试银行卡A', '测试银行卡B']


def test_fee_reduces_proceeds_of_a_negative_gross_sell():
    frame = pd.DataFrame([
        {'asset_id': 'RSU_TEST', 'transaction_date': '2026-06-15', 'transaction_type': 'sell',
         'quantity': -20, 'amount_gross': -5000.0, 'commission_fee': 5.0},
        {'asset_id': 'RSU_TEST', 'transaction_date': '2026-06-15', 'transaction_type': 'vest',
         'quantity': 20, 'amount_gross': 5000.0, 'commission_fee': 0.0},
    ])
    out = _normalize_transactions_df(frame, 'RSU_Excel').set_index('transaction_type')
    assert float(out.loc['sell', 'amount_net']) == -4995.0
    assert float(out.loc['vest', 'amount_net']) == 5000.0


def test_flex_ctrn_parser_fixture(tmp_path, flow_db):
    path = tmp_path / 'cash.csv'
    path.write_text('BOS,CTRN,Cash Transactions\nClientAccountID,DateTime,Type,CurrencyPrimary,Amount,TransactionID,Description\nTEST,2026-09-10;120000,Deposits/Withdrawals,USD,-30,event-1,synthetic withdrawal\nEOS,CTRN\n')
    sections = _parse_flex_sections(path)
    frame = ibkr_transactions_from_flex(pd.DataFrame(), {'flex_sections': sections})
    normalized = _normalize_transactions_df(frame, 'Broker_IBKR')
    _replace_transactions(flow_db, normalized)
    _replace_transactions(flow_db, normalized)
    rows = flow_db.execute('SELECT amount_net, raw_business_type, source_event_key FROM transactions').fetchall()
    assert len(rows) == 1
    assert rows[0][0] == -30
    assert rows[0][1] == 'Deposits/Withdrawals'
    assert len(rows[0][2]) == 64


def test_flex_ctrn_real_column_names_dividends_and_withholding(tmp_path, flow_db):
    """Real Flex exports name the column "Date/Time"; dividends and withholding book on the security."""
    path = tmp_path / 'cash.csv'
    path.write_text(
        'BOS,CTRN,Cash Transactions\n'
        'ClientAccountID,CurrencyPrimary,Symbol,Date/Time,SettleDate,Amount,Type,TransactionID,Description\n'
        'TEST,USD,,2026-06-01;120000,2026-06-01,1000,Deposits/Withdrawals,d-1,synthetic deposit\n'
        'TEST,USD,TESTETF,2026-06-30;202000,2026-06-30,50.00,Dividends,v-1,synthetic dividend\n'
        'TEST,USD,TESTETF,2026-06-30;202000,2026-06-30,-15.00,Withholding Tax,w-1,30% rate\n'
        'TEST,USD,TESTETF,2026-06-30;202000,2026-06-30,15.00,Withholding Tax,w-2,reversal\n'
        'TEST,USD,TESTETF,2026-06-30;202000,2026-06-30,-5.00,Withholding Tax,w-3,10% treaty rate\n'
        'TEST,USD,TESTETF,2026-07-01;100000,2026-07-01,9.99,Other Fees,f-1,not booked\n'
        'EOS,CTRN\n')
    frame = ibkr_transactions_from_flex(pd.DataFrame(), {'flex_sections': _parse_flex_sections(path)})
    _replace_transactions(flow_db, _normalize_transactions_df(frame, 'Broker_IBKR'))
    rows = flow_db.execute(
        "SELECT transaction_date, asset_id, transaction_type, amount_gross FROM transactions "
        "ORDER BY asset_id, amount_gross").fetchall()
    assert [(str(d), a, t, float(x)) for d, a, t, x in rows] == [
        ('2026-06-01', 'CASH_USD', 'other', 1000.0),
        ('2026-06-30', 'US_STK_TESTETF', 'tax_adjustment', -15.0),
        ('2026-06-30', 'US_STK_TESTETF', 'tax_adjustment', -5.0),
        ('2026-06-30', 'US_STK_TESTETF', 'dividend', 15.0),
        ('2026-06-30', 'US_STK_TESTETF', 'dividend', 50.0),
    ]
    # Net income = dividend − net withholding.
    from src.services.portfolio_helpers import calculate_realized_pnl
    assert round(calculate_realized_pnl(flow_db, 'US_STK_TESTETF')[0], 2) == 45.0


def test_optional_rsu_receipt_column(tmp_path):
    from src.sources.config_driven_reader import ConfigDrivenReader
    from src.sources.reader_config import load_reader_config
    from unittest.mock import patch
    book = Workbook()
    sheet = book.active
    sheet.title = 'Transactions'
    sheet.append(['交易日期', '资产名称', '交易类型', '单位', '数量', '单位价格_USD', '总金额_USD', '手续费_USD', '备注', 'Bank receipt'])
    sheet.append(['2026-09-10', 'Synthetic RSU', 'Sell', 'share', -2, 20, -40, 1, 'sale', 35])
    path = tmp_path / 'RSU_transactions.xlsx'
    book.save(path)
    reader = ConfigDrivenReader(load_reader_config('config/readers/rsu.yaml'))
    with patch('src.data_manager.currency_converter.get_default_usd_cny_rate', return_value=7):
        data = reader.read(path)
        _, transactions = reader.transform(data)
    assert transactions.iloc[0]['bank_receipt'] == 35


def test_browser_paste_layout_with_continuation_rows():
    """The live 交易查询 page pasted into Excel: each web row becomes a main row plus a
    continuation row (time, numeric fund code without leading zeros, second account line)."""
    from datetime import datetime, time
    from src.sources.cn_platform_events import parse_web_rows
    rows = [
        ('交易发起时间', '产品名称', '业务类型', '申请数额', '确认数额', '关联账户', '状态', '操作'),
        (datetime(2026, 9, 11), '测试红利联接A', '红利再投资', '--', '100.00份', '测试银行 | 0001', '成功', '详情'),
        (time(4, 38, 23), 12345, None, None, None, None, None, None),
        (datetime(2026, 8, 20), '活期宝', '活期宝快速取现', '500.00份', '500.00元', '活期宝', '成功', '详情'),
        (time(10, 13, 39), None, None, None, None, '测试银行 | 0001', None, None),
        (datetime(2026, 8, 19), '活期宝', '活期宝每日分红', '--', '2.33份', None, '成功', '详情'),
    ]
    events = parse_web_rows(rows)
    assert len(events) == 3
    assert events[0]['fund_code'] == '012345' and events[0]['event_time'] == '04:38:23'
    assert events[1]['account'] == '活期宝 测试银行 | 0001'
    assert events[1]['confirmed_unit'] == '元' and float(events[1]['confirmed_value']) == 500
    assert events[2]['fund_code'] == '' and events[2]['event_time'] == ''


def _paste_book(tmp_path, existing, pasted, name='paste.xlsx', with_extra=True):
    """Workbook with processed rows (9 base cols + raw type/status/card/amount) and a paste."""
    book = Workbook()
    processed = book.active
    processed.title = '基金交易记录'
    header = ['交易日期', '基金代码', '基金名称', '操作类型', '交易金额', '交易份额', '交易时基金单位净值',
              '手续费', '交易原因']
    processed.append(header + (['原始业务类型', '确认状态', '关联银行卡', '确认金额'] if with_extra else []))
    for row in existing:
        processed.append(row)
    raw = book.create_sheet('raw_transactions_paste')
    raw.append(['确认日期', '基金代码', '基金简称', '业务类型', '确认状态', '确认份额', '确认金额', '手续费', '确认净值', '关联银行卡'])
    for row in pasted:
        raw.append(row)
    path = tmp_path / name
    book.save(path)
    return path


def _buy(card, day=11):
    from datetime import datetime
    return [datetime(2026, 9, day), '999999', 'Synthetic Fund', '买入', '成功', 100, 100, 0, 1, card]


def _recorded(card, day=11):
    from datetime import datetime
    return [datetime(2026, 9, day), '999999', 'Synthetic Fund', '申购', 100, 100, 1, 0, 'Buy',
            '买入', '成功', card, 100]


def test_paste_fills_in_a_card_the_ledger_did_not_record(tmp_path):
    """A row recorded before its card was known matches the same paste with the card."""
    path = _paste_book(tmp_path, [_recorded(None)], [_buy('测试卡A')])
    assert process_raw_transactions(path).new_count == 0


def test_paste_card_match_ignores_spacing(tmp_path):
    path = _paste_book(tmp_path, [_recorded('测试卡 A')], [_buy('测试卡A')])
    assert process_raw_transactions(path).new_count == 0


def test_paste_keeps_two_equal_orders_on_one_card(tmp_path):
    path = _paste_book(tmp_path, [], [_buy('测试卡A'), _buy('测试卡A')])
    assert process_raw_transactions(path).new_count == 2
    assert process_raw_transactions(path).new_count == 0


def test_paste_adds_only_the_order_the_ledger_is_missing(tmp_path):
    """One recorded, two pasted (e.g. a lost equal-sized second sale): one is new."""
    path = _paste_book(tmp_path, [_recorded('测试卡A')], [_buy('测试卡A'), _buy('测试卡A')])
    assert process_raw_transactions(path).new_count == 1
    assert process_raw_transactions(path).new_count == 0


def test_paste_legacy_row_covers_one_order_not_two(tmp_path):
    """A legacy row (no raw type) stands for one order: a second card's order is new."""
    from datetime import datetime
    legacy = [datetime(2026, 9, 11), '999999', 'Synthetic Fund', '申购', 100, 100, 1, 0, 'Buy']
    path = _paste_book(tmp_path, [legacy], [_buy('测试卡A'), _buy('测试卡B')], with_extra=False)
    assert process_raw_transactions(path).new_count == 1
    assert process_raw_transactions(path).new_count == 0


def test_paste_legacy_row_with_other_shares_is_a_different_order(tmp_path):
    from datetime import datetime
    legacy = [datetime(2026, 9, 11), '999999', 'Synthetic Fund', '申购', 100, 50, 2, 0, 'Buy']
    path = _paste_book(tmp_path, [legacy], [_buy('测试卡B')], with_extra=False)
    assert process_raw_transactions(path).new_count == 1


def test_paste_flags_orders_competing_for_a_row_without_a_card(tmp_path):
    path = _paste_book(tmp_path, [_recorded(None)], [_buy('测试卡A'), _buy('测试卡B')])
    result = process_raw_transactions(path)
    assert (result.new_count, result.ambiguous) == (1, 2)



def test_two_identical_pasted_orders_reach_the_ledger_as_two(tmp_path, flow_db):
    """Equal same-day orders on one card (seen 2026-04-24) survive paste and ingest."""
    path = _paste_book(tmp_path, [], [_buy('测试卡A'), _buy('测试卡A')])
    assert process_raw_transactions(path).new_count == 2
    rows = list(load_workbook(path)['基金交易记录'].values)
    assert rows[2][8].endswith('；同日第2笔')
    sheet = pd.DataFrame(rows[1:], columns=rows[0])
    frame = _normalize_transactions_df(cn_fund_transactions_from_sheet(sheet, {}), 'CN_Fund_Excel')
    for _ in range(2):
        _replace_transactions(flow_db, frame)
        assert flow_db.execute(
            "SELECT COUNT(*) FROM transactions WHERE source_system='CN_Fund_Excel'").fetchone()[0] == 2
    assert process_raw_transactions(path).new_count == 0
