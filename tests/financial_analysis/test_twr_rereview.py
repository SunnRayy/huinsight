"""Owner re-review of the frozen Returns window (synthetic data only)."""
from datetime import date

import pytest
from openpyxl import Workbook

from src.financial_analysis.flow_coverage import extend_flow_coverage
from src.financial_analysis.twr import load_investment_return_inputs
from src.financial_analysis.twr_import import FLOW_COLUMNS, FLOW_TAB, META_TAB
from src.financial_analysis.twr_rereview import apply_rereview, frozen_window_diff

REVIEWED = ['reviewed', date(2026, 8, 10), 10, 10, 'CNY', date(2026, 8, 10), 1, 'TTFund', 'in', 'confirmed',
            'synthetic', 'posted']


def workbook(tmp_path, rows, coverage_end=date(2026, 9, 30)):
    book = Workbook()
    flows = book.active
    flows.title = FLOW_TAB
    flows.append(list(FLOW_COLUMNS))
    for row in rows:
        flows.append(row)
    meta = book.create_sheet(META_TAB)
    meta.append(['key', 'value'])
    for key, value in (('coverage_start', date(2026, 7, 31)), ('coverage_end', coverage_end), ('quality', 'estimated')):
        meta.append([key, value])
    path = tmp_path / 'funding.xlsx'
    book.save(path)
    return path


@pytest.fixture
def frozen_db(reviewed_flow_db):
    extend_flow_coverage(reviewed_flow_db)  # pins frozen_coverage_end = 2026-08-31
    return reviewed_flow_db


def corrected(tmp_path):
    fixed = list(REVIEWED)
    fixed[2:4] = [8, 8]
    fixed[9] = 'owner_confirmed'
    added = ['late', date(2026, 8, 20), -5, -5, 'CNY', date(2026, 8, 20), 1, 'TTFund', 'out', 'confirmed', 'x', 'posted']
    after_window = ['september', date(2026, 9, 5), 3, 3, 'CNY', date(2026, 9, 5), 1, 'TTFund', 'in', 'confirmed', 'x', 'p']
    return workbook(tmp_path, [fixed, added, after_window])


def test_unchanged_workbook_needs_no_review(frozen_db, tmp_path):
    diff = frozen_window_diff(frozen_db, workbook(tmp_path, [REVIEWED]))
    assert diff['available'] and diff['changes'] == [] and not diff['needs_review']


def test_diff_lists_only_frozen_window_changes(frozen_db, tmp_path):
    diff = frozen_window_diff(frozen_db, corrected(tmp_path))
    assert {(c['flow_id'], c['change']) for c in diff['changes']} == {('reviewed', 'changed'), ('late', 'added')}
    changed = next(c for c in diff['changes'] if c['flow_id'] == 'reviewed')
    assert changed['fields'] == ['amount_cny', 'original_amount', 'evidence_status']
    assert diff['net_change_cny'] == -7.0


def test_half_cent_native_amount_is_not_a_change(frozen_db, tmp_path):
    frozen_db.execute("UPDATE investment_external_flows SET original_amount = 10.13, amount_cny = 10.13 "
                      "WHERE flow_id = 'reviewed'")
    frozen_db.execute('UPDATE investment_twr_source SET frozen_flows_sha256 = NULL')
    row = list(REVIEWED)
    row[2:4] = [10.125, 10.125]
    assert frozen_window_diff(frozen_db, workbook(tmp_path, [row]))['changes'] == []


def test_apply_archives_rewrites_and_repins(frozen_db, tmp_path):
    db = frozen_db
    result = apply_rereview(db, corrected(tmp_path), reviewer='owner', evidence_ref='statement 2026-11-09')
    assert result['archived_rows'] == 1 and result['written_rows'] == 2
    archived = db.execute('SELECT flow_id, amount_cny, archive_reason FROM investment_external_flows_archive').fetchall()
    assert archived[0][:2] == ('reviewed', 10) and 'statement 2026-11-09' in archived[0][2]
    stored = dict(db.execute("SELECT flow_id, amount_cny FROM investment_external_flows").fetchall())
    assert stored == {'reviewed': 8, 'late': -5}  # the September workbook row stays with the auto rules
    assert not db.execute('SELECT history_changed_since_review FROM investment_twr_source').fetchone()[0]
    inputs = load_investment_return_inputs(db)
    assert inputs is not None and not inputs['history_changed_since_review']
    assert db.execute('SELECT reviewer FROM investment_twr_reviews WHERE input_fingerprint = ?',
                      [result['input_fingerprint']]).fetchone()[0] == 'owner'
    assert extend_flow_coverage(db)['status'] == 'ok'  # the next sync accepts the new pins


def test_apply_requires_reviewer_evidence_and_frozen_history(reviewed_flow_db, tmp_path):
    path = workbook(tmp_path, [REVIEWED])
    with pytest.raises(ValueError, match='required'):
        apply_rereview(reviewed_flow_db, path, reviewer='owner', evidence_ref=' ')
    with pytest.raises(ValueError, match='not frozen'):
        apply_rereview(reviewed_flow_db, path, reviewer='owner', evidence_ref='x')


def test_failed_write_leaves_the_frozen_rows(frozen_db, tmp_path, monkeypatch):
    import src.financial_analysis.twr_rereview as module
    before = frozen_db.execute('SELECT * FROM investment_external_flows ORDER BY flow_id').fetchall()
    monkeypatch.setattr(module, '_valuation_fingerprint', lambda *a: (_ for _ in ()).throw(RuntimeError('boom')))
    with pytest.raises(RuntimeError):
        apply_rereview(frozen_db, corrected(tmp_path), reviewer='owner', evidence_ref='x')
    assert frozen_db.execute('SELECT * FROM investment_external_flows ORDER BY flow_id').fetchall() == before
    assert frozen_db.execute('SELECT COUNT(*) FROM investment_external_flows_archive').fetchone()[0] == 0


def test_pending_corrections_counts_and_caches(frozen_db, tmp_path, monkeypatch):
    import src.financial_analysis.twr_rereview as module
    path = corrected(tmp_path)
    config = {'source_registry': {'cn_fund': {'data_dir': str(path.parent), 'file_patterns': {'workbook': path.name}}}}
    assert module.pending_corrections(frozen_db, config) == 2
    monkeypatch.setattr(module, 'frozen_window_diff', lambda *a: (_ for _ in ()).throw(AssertionError('not cached')))
    assert module.pending_corrections(frozen_db, config) == 2
    monkeypatch.undo()
    apply_rereview(frozen_db, path, reviewer='owner', evidence_ref='x')
    assert module.pending_corrections(frozen_db, config) == 0  # new pin: recomputed
    assert module.pending_corrections(frozen_db, {'source_registry': {'cn_fund': {'data_dir': str(tmp_path / 'none')}}}) is None
