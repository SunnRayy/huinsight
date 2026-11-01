"""Workbook import to explicit flows to estimated return, with a saved proof."""

import json
import os
import asyncio
from datetime import date
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from src.financial_analysis.twr import calculate_portfolio_twr, investment_twr_unavailable_reason
from src.financial_analysis.twr_import import replace_investment_twr_source
from src.api.routes.performance import get_performance_returns


@pytest.fixture(autouse=True)
def isolate_flow_visibility(monkeypatch):
    # Metric-only fixtures predate flow tables; full coverage contracts have their own synthetic schema.
    monkeypatch.setattr('src.financial_analysis.flow_coverage.coverage_status', lambda db: {
        'frozen_end': None, 'coverage_end': None, 'next_month': None, 'blockers': [],
    })


def test_estimated_twr_workbook_roundtrip(tmp_path):
    """Reject duplicate IDs, invalid dates/amounts, missing tabs and partial DB writes."""
    workbook = Workbook()
    flows = workbook.active
    flows.title = 'TWR外部现金流'
    flows.append(['flow_id', 'event_date', 'amount_cny_signed', 'original_amount_signed',
                  'original_currency', 'fx_date', 'fx_cny_per_native', 'source',
                  'kind', 'evidence_status', 'evidence', 'date_basis'])
    flows.append(['abc123', '2025-02-15', '100.00', '100.00', 'CNY', '2025-02-15',
                  '1', 'TTFund', 'external_deposit', 'confirmed', 'synthetic', 'posted'])
    metadata = workbook.create_sheet('TWR估算口径')
    metadata.append(['key', 'value'])
    for item in [('coverage_start', '2025-01-31'), ('coverage_end', '2025-03-31'),
                 ('quality', 'estimated')]:
        metadata.append(item)
    source = tmp_path / 'funding_transactions.xlsx'
    workbook.save(source)

    db = duckdb.connect(str(tmp_path / 'twr.duckdb'))
    db.execute('CREATE TABLE balance_sheet_monthly '
               '(snapshot_date DATE, payload JSON, record_key VARCHAR, source_system VARCHAR)')
    columns = ['投资资产_股票基金_A股基金', '投资资产_股票基金_美股基金_Schwab',
               '投资资产_股票基金_美股基金_IBKR', '投资资产_公司RSU_Amazon Stock',
               '投资资产_公司RSU_Google Stock', '投资资产_黄金_纸黄金(元)']
    for month, value in [('2025-01-01', 1000), ('2025-02-01', 1210), ('2025-03-01', 1331)]:
        db.execute('INSERT INTO balance_sheet_monthly VALUES (?, ?, ?, ?)',
                   [month, json.dumps({**{key: 0 for key in columns}, columns[0]: value}),
                    month, 'Financial_Summary_Excel'])

    assert replace_investment_twr_source(db, source) == 1
    first = calculate_portfolio_twr(db)
    assert first is not None and first['estimated'] is True
    assert first['review_state'] == 'candidate'
    assert first['period_start'] == date(2025, 1, 31).isoformat()
    assert first['as_of'] == date(2025, 3, 31).isoformat()
    assert first['cumulative'] == pytest.approx((1 + 110 / (1000 + 100 * 13 / 28)) * 1.1 - 1)
    response = asyncio.run(get_performance_returns(
        period='all_time', exclude_non_balanceable=False,
        include_non_rebalanceable=True, db=db,
    ))
    assert response['investment_bridge'] == {
        'period_start': '2025-01-31', 'period_end': '2025-03-31',
        'opening_value_cny': 1000.0, 'net_external_flow_cny': 100.0,
        'investment_gain_cny': 231.0, 'closing_value_cny': 1331.0,
    }
    assert response['twr_review_state'] == 'candidate'
    assert response['mwr_review_state'] == 'candidate'
    assert response['mwr_period_start'] == first['period_start']
    assert response['mwr_as_of'] == first['as_of']
    assert response['mwr_scope'] == 'investment_accounts'
    assert response['mwr_xirr'] is not None
    rate = response['mwr_xirr'] / 100
    assert -1000 - 100 / (1 + rate)**(15/365) + 1331 / (1 + rate)**(59/365) == pytest.approx(0, abs=0.01)
    assert response['twr_ytd'] is None
    assert replace_investment_twr_source(db, source) == 1
    assert db.execute('SELECT COUNT(*) FROM investment_external_flows').fetchone()[0] == 1

    january = json.loads(db.execute(
        "SELECT payload FROM balance_sheet_monthly WHERE snapshot_date = '2025-01-01'"
    ).fetchone()[0])
    january[columns[4]] = None
    db.execute("UPDATE balance_sheet_monthly SET payload = ? WHERE snapshot_date = '2025-01-01'", [json.dumps(january)])
    assert replace_investment_twr_source(db, source) == 1
    assert calculate_portfolio_twr(db) is None  # leading blank has no opening evidence
    prior = {**{key: 0 for key in columns}, columns[4]: 20}
    db.execute("INSERT INTO balance_sheet_monthly VALUES ('2024-12-01', ?, ?, ?)",
               [json.dumps(prior), '2024-12-01', 'Financial_Summary_Excel'])
    assert calculate_portfolio_twr(db) is None  # prior funded account cannot vanish
    assert investment_twr_unavailable_reason(db) == 'valuation_changed_or_incomplete'
    db.execute("DELETE FROM balance_sheet_monthly WHERE snapshot_date = '2024-12-01'")
    assert calculate_portfolio_twr(db) is None
    january[columns[4]] = 0
    db.execute("UPDATE balance_sheet_monthly SET payload = ? WHERE snapshot_date = '2025-01-01'", [json.dumps(january)])
    assert replace_investment_twr_source(db, source) == 1
    assert calculate_portfolio_twr(db) is not None

    march = json.loads(db.execute(
        "SELECT payload FROM balance_sheet_monthly WHERE snapshot_date = '2025-03-01'"
    ).fetchone()[0])
    march[columns[0]] = None
    march[columns[1]] = 100
    db.execute("UPDATE balance_sheet_monthly SET payload = ? WHERE snapshot_date = '2025-03-01'", [json.dumps(march)])
    assert calculate_portfolio_twr(db) is None  # funded account missing, not zero
    assert investment_twr_unavailable_reason(db) == 'valuation_changed_or_incomplete'
    march[columns[0]] = 1331
    march[columns[1]] = 0
    db.execute("UPDATE balance_sheet_monthly SET payload = ? WHERE snapshot_date = '2025-03-01'", [json.dumps(march)])
    assert calculate_portfolio_twr(db)['cumulative'] == pytest.approx(first['cumulative'])

    fingerprint = db.execute(
        'SELECT input_fingerprint FROM investment_twr_source'
    ).fetchone()[0]
    assert len(fingerprint) == 64
    db.execute(
        'INSERT INTO investment_twr_reviews '
        '(input_fingerprint, reviewer, evidence_ref) VALUES (?, ?, ?)',
        [fingerprint, 'synthetic-reviewer', 'synthetic-evidence'],
    )
    assert calculate_portfolio_twr(db)['review_state'] == 'reviewed'
    db.execute("UPDATE balance_sheet_monthly SET source_system = 'Unknown' "
               "WHERE snapshot_date = '2025-02-01'")
    assert calculate_portfolio_twr(db) is None  # same numbers, different provenance
    db.execute("UPDATE balance_sheet_monthly SET source_system = 'Financial_Summary_Excel' "
               "WHERE snapshot_date = '2025-02-01'")
    db.execute("UPDATE balance_sheet_monthly SET record_key = 'replacement' "
               "WHERE snapshot_date = '2025-02-01'")
    assert calculate_portfolio_twr(db) is None
    db.execute("UPDATE balance_sheet_monthly SET record_key = '2025-02-01' "
               "WHERE snapshot_date = '2025-02-01'")
    assert calculate_portfolio_twr(db)['review_state'] == 'reviewed'
    db.execute("UPDATE investment_external_flows SET amount_cny = 110 WHERE flow_id = 'abc123'")
    assert calculate_portfolio_twr(db) is None
    db.execute("UPDATE investment_external_flows SET amount_cny = 100 WHERE flow_id = 'abc123'")

    february = json.loads(db.execute(
        "SELECT payload FROM balance_sheet_monthly WHERE snapshot_date = '2025-02-01'"
    ).fetchone()[0])
    february[columns[0]] = 1211
    db.execute("UPDATE balance_sheet_monthly SET payload = ? WHERE snapshot_date = '2025-02-01'", [json.dumps(february)])
    assert calculate_portfolio_twr(db) is None  # valuation changed after flow import
    assert investment_twr_unavailable_reason(db) == 'valuation_changed_or_incomplete'
    assert replace_investment_twr_source(db, source) == 1
    assert calculate_portfolio_twr(db)['review_state'] == 'candidate'
    assert calculate_portfolio_twr(db)['cumulative'] != pytest.approx(first['cumulative'])
    february[columns[0]] = 1210
    february[columns[4]] = 0  # evidenced zero, not a missing observation
    db.execute("UPDATE balance_sheet_monthly SET payload = ? WHERE snapshot_date = '2025-02-01'", [json.dumps(february)])
    assert replace_investment_twr_source(db, source) == 1
    assert calculate_portfolio_twr(db)['cumulative'] == pytest.approx(first['cumulative'])

    flows.append(['abc123', '2025-03-01', '100.00', '100.00', 'CNY', '2025-03-01',
                  '1', 'TTFund', 'external_deposit', 'confirmed', 'duplicate', 'posted'])
    workbook.save(source)
    with pytest.raises(ValueError, match='duplicate'):
        replace_investment_twr_source(db, source)
    assert db.execute('SELECT COUNT(*) FROM investment_external_flows').fetchone()[0] == 1
    assert calculate_portfolio_twr(db) is None
    assert investment_twr_unavailable_reason(db) == 'invalid_twr_tabs'
    assert db.execute('SELECT quality FROM investment_twr_source').fetchone()[0] == 'unavailable'

    flows.delete_rows(3)
    workbook.save(source)
    assert replace_investment_twr_source(db, source) == 1
    assert calculate_portfolio_twr(db) is not None
    del workbook['TWR估算口径']
    workbook.save(source)
    with pytest.raises(ValueError, match='together'):
        replace_investment_twr_source(db, source)
    assert calculate_portfolio_twr(db) is None
    assert investment_twr_unavailable_reason(db) == 'invalid_twr_tabs'
    metadata = workbook.create_sheet('TWR估算口径')
    metadata.append(['key', 'value'])
    for item in [('coverage_start', '2025-01-31'), ('coverage_end', '2025-03-31'),
                 ('quality', 'estimated')]:
        metadata.append(item)
    workbook.save(source)
    assert replace_investment_twr_source(db, source) == 1
    workbook.create_sheet('基金交易记录')
    del workbook['TWR估算口径']
    del workbook['TWR外部现金流']
    workbook.save(source)
    assert replace_investment_twr_source(db, source) == 0
    assert db.execute('SELECT COUNT(*) FROM investment_external_flows').fetchone()[0] == 1
    assert calculate_portfolio_twr(db) is None
    assert investment_twr_unavailable_reason(db) == 'missing_twr_tabs'

    proof = {'valid_flow_count': 1, 'import_twice_count': 1,
             'duplicate_rejected_and_marked_unavailable': True,
             'missing_tabs_preserved_flows_and_marked_unavailable': True,
             'valuation_change_rejected_until_rebound': True,
             'funded_missing_value_rejected': True,
             'leading_blank_without_opening_evidence_rejected': True,
             'estimated_twr_pct': round(first['cumulative'] * 100, 6),
             'period_start': first['period_start'], 'as_of': first['as_of']}
    artifact_dir = os.environ.get('TWR_E2E_ARTIFACT_DIR')
    if artifact_dir:
        path = Path(artifact_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / 'synthetic_workbook_to_twr.json').write_text(
            json.dumps(proof, indent=2) + '\n', encoding='utf-8'
        )
    db.close()


@pytest.mark.parametrize('period, expected_start', [
    ('all_time', None), ('last_12m', '2025-08-31'), ('last_36m', '2023-08-31'),
])
def test_returns_xirr_independent_of_monthly_twr_and_anchors_to_coverage(monkeypatch, period, expected_start):
    from src.api.routes import performance
    from src.services import investment_returns

    starts = []

    def xirr(_db, start_date=None):
        starts.append(start_date)
        return {'annualized': 0.052, 'scope': 'investment_accounts',
                'period_start': start_date or '2020-01-31', 'as_of': '2026-08-31',
                'review_state': 'candidate', 'solver_status': 'solved'}

    monkeypatch.setattr(investment_returns, 'calculate_portfolio_twr', lambda *args, **kwargs: None)
    monkeypatch.setattr(investment_returns, 'calculate_investment_account_xirr', xirr)
    monkeypatch.setattr(investment_returns, 'investment_twr_unavailable_reason',
                        lambda db: 'coverage_or_valuation_incomplete')
    result = asyncio.run(performance.get_performance_returns(
        period=period, exclude_non_balanceable=False,
        include_non_rebalanceable=True, db=None,
    ))
    assert result['twr_cumulative'] is None
    assert result['mwr_xirr'] == 5.2
    assert starts[-1] == expected_start
    assert result['mwr_period_start'] == (expected_start or '2020-01-31')
    assert result['mwr_as_of'] == '2026-08-31'
    assert {k: v for k, v in result.items() if k != 'coverage_status'} == investment_returns.build_investment_returns(None, period=period)
    assert result['scope'] == 'investment_accounts'
    assert result['currency'] == 'CNY'
    assert result['mwr_method'] == 'dated_external_flow_xirr'
    assert result['twr_unavailable_reason'] == 'coverage_or_valuation_incomplete'
