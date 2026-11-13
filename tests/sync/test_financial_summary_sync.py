"""Tests for Financial Summary sync."""
import pytest

pytestmark = pytest.mark.pipeline

import openpyxl
import pandas as pd
from datetime import datetime
from src.sync.financial_summary_sync import sync_financial_summary
from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema
from src.sync.phases._ingest import _upsert_holdings

@pytest.fixture
def fs_config(tmp_path):
    wb = openpyxl.Workbook()
    ws_bs = wb.active
    ws_bs.title = "资产负债"
    ws_bs.append(["", "", ""])
    ws_bs.append(["", "", ""])
    ws_bs.append(["", "", ""])
    ws_bs.append(["Date", "Total Assets", "Total Liabilities", "Net Worth"])
    ws_bs.append([datetime(2025, 1, 1), 100000, 20000, 80000])
    
    ws_ie = wb.create_sheet("月度收支")
    ws_ie.append(["", "", ""])
    ws_ie.append(["", "", ""])
    ws_ie.append(["", "", ""])
    ws_ie.append(["Month", "Income", "Expense", "Savings"])
    ws_ie.append([datetime(2025, 1, 1), 5000, 2000, 3000])
    
    wb.save(tmp_path / "Financial Summary_new.xlsx")
    return {"source_registry": {"financial_summary": {
        "enabled": True, "file_patterns": {"workbook": "Financial Summary_new.xlsx"},
        "data_dir": str(tmp_path)}}}

class TestFinancialSummarySync:
    def test_sync_returns_dfs(self, fs_config):
        result = sync_financial_summary(fs_config)
        assert len(result["holdings"]) == 1
        assert len(result["transactions"]) == 1
        assert "Total Assets" in result["holdings"].columns

    def test_disabled(self):
        result = sync_financial_summary({"source_registry": {"financial_summary": {"enabled": False}}})
        assert result["holdings"].empty

    def test_file_not_found(self):
         result = sync_financial_summary({"source_registry": {"financial_summary": {
            "enabled": True, "data_dir": "/nonexistent"}}})
         assert result["holdings"].empty

    def test_uses_top_level_finance_dir_when_data_dir_null(self, fs_config):
        finance_dir = fs_config["source_registry"]["financial_summary"]["data_dir"]
        fs_config["source_registry"]["financial_summary"]["data_dir"] = None
        fs_config["finance_dir"] = finance_dir

        result = sync_financial_summary(fs_config)

        assert len(result["holdings"]) == 1


def test_financial_summary_reimport_preserves_only_existing_active_cost():
    with DatabaseConnector(':memory:') as db:
        initialize_schema(db)

        def row(asset, source, quantity, cost):
            return pd.DataFrame([{
                'snapshot_date': '2026-08-01', 'asset_id': asset,
                'asset_name': asset, 'asset_type': 'property', 'quantity': quantity,
                'unit': 'unit', 'cost_price_unit': cost,
                'market_price_unit': 2600000, 'market_value': 2600000,
                'currency': 'CNY', 'account': 'Financial_Summary',
                'source_system': source,
            }])

        def cost(asset, source):
            return db.execute(
                'SELECT cost_price_unit FROM holdings WHERE asset_id=? AND source_system=?',
                [asset, source],
            ).fetchone()[0]

        fs = 'Financial_Summary_Excel'
        _upsert_holdings(db, row('Property_TEST', fs, 1, 2820000))
        _upsert_holdings(db, row('Property_TEST', fs, 1, None))
        assert cost('Property_TEST', fs) == 2820000
        _upsert_holdings(db, row('Property_TEST', fs, 1, 2800000))
        assert cost('Property_TEST', fs) == 2800000
        _upsert_holdings(db, row('Property_TEST', fs, 0, None))
        assert cost('Property_TEST', fs) is None

        _upsert_holdings(db, row('Property_NEW', fs, 1, None))
        assert cost('Property_NEW', fs) is None
        other = 'CN_Fund_Excel'
        _upsert_holdings(db, row('CN_FUND_TEST', other, 1, 100))
        _upsert_holdings(db, row('CN_FUND_TEST', other, 1, None))
        assert cost('CN_FUND_TEST', other) is None
