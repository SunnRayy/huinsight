"""Integration tests for transaction source selection and XIRR deduplication."""
from unittest.mock import MagicMock
from src.financial_analysis.xirr import calculate_portfolio_xirr
from src.services.transaction_source_selector import build_source_filter_clauses

def test_build_source_filter_clauses_empty_assests():
    db = MagicMock()
    # Mock returning no active assets with txs
    db.execute.return_value.fetchall.return_value = []
    
    clause, params = build_source_filter_clauses(db)
    assert clause == "1=0"
    assert params == []

def test_build_source_filter_clauses_with_assets(monkeypatch):
    db = MagicMock()
    
    # Mock select_transaction_sources to return specific sources for our assets.
    # The resolver= kwarg (added in C3.3) must be accepted so build_source_filter_clauses
    # can pass the shared resolver in without the mock raising TypeError.
    def mock_select(db_param, asset_id, resolver=None):
        if asset_id == 'A1':
            return ['PIS_SQLite', 'Other_DB']
        elif asset_id == 'A2':
            return ['Schwab_CSV']
        return []
        
    monkeypatch.setattr('src.services.transaction_source_selector.select_transaction_sources', mock_select)
    
    clause, params = build_source_filter_clauses(db, ['A1', 'A2', 'A3'])
    
    expected_clause = "((asset_id = ? AND source_system IN (?, ?)) OR (asset_id = ? AND source_system IN (?)) OR (asset_id = ?))"
    expected_params = ['A1', 'PIS_SQLite', 'Other_DB', 'A2', 'Schwab_CSV', 'A3']
    
    assert clause == expected_clause
    assert params == expected_params


def test_xirr_calculator_uses_dedup_clause(monkeypatch):
    db = MagicMock()
    
    # Mock the helper to return a predictable clause
    def mock_build_xirr(db_param, asset_ids):
        return "(asset_id = ? AND source_system IN (?))", ['TEST_ASSET', 'TEST_SRC']
        
    monkeypatch.setattr('src.services.transaction_source_selector.build_source_filter_clauses', mock_build_xirr)
    
    # Mock transactions and terminal value
    db.execute.return_value.fetchall.side_effect = [
        [("TEST_ASSET", "2025-01-01", "buy", 1000.0, "CNY")],  # Transactions
        [("TEST_ASSET", "CNY", 0.0, 1100.0)],  # Terminal value
    ]
    
    calculate_portfolio_xirr(db, include_asset_ids=['TEST_ASSET'])
    
    calls = db.execute.call_args_list
    assert len(calls) == 2
    
    # Verify the SQL and params used for transactions
    tx_query_args = calls[0]
    sql, params = tx_query_args[0]
    
    # The transaction query should now contain our injected dedup clause
    assert "(asset_id = ? AND source_system IN (?))" in sql
    assert params == ['TEST_ASSET', 'TEST_SRC']
