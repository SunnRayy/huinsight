"""Distinct fund orders can have the same date, fund, and amount."""

import pandas as pd

from src.sync.phases._ingest import _normalize_transactions_df


def test_cn_fund_same_day_equal_orders_keep_distinct_source_ids():
    rows = pd.DataFrame(
        [
            {
                "transaction_date": "2026-01-12",
                "asset_id": "CN_FUND_900001",
                "transaction_type": "buy",
                "quantity": 8000.0,
                "amount": 10000,
                "fees": 10.0,
                "memo": f"TTFund event {event_id}",
            }
            for event_id in ("order-1", "order-2", "order-2")
        ]
    )

    normalized = _normalize_transactions_df(rows, "CN_Fund_Excel")

    assert len(normalized) == 2
    assert set(normalized["memo"]) == {
        "TTFund event order-1",
        "TTFund event order-2",
    }


def test_cn_fund_same_amount_memo_but_different_shares_or_account_survive():
    common = {
        "transaction_date": "2026-01-12", "asset_id": "CN_FUND_900001",
        "transaction_type": "buy", "amount": 10000, "fees": 0,
        "memo": "same provider description",
    }
    rows = pd.DataFrame([
        {**common, "quantity": 8000.0, "account": "account-a"},
        {**common, "quantity": 8001.0, "account": "account-b"},
    ])

    normalized = _normalize_transactions_df(rows, "CN_Fund_Excel")

    assert len(normalized) == 2
