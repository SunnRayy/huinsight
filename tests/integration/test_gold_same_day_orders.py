"""Distinct gold orders can share a bank, date, and cash amount."""

from pathlib import Path

import duckdb
import pandas as pd

from src.sync.phases._ingest import _normalize_transactions_df, _replace_transactions


def test_same_day_same_bank_amount_with_different_gold_quantity_survives_reimport():
    raw = pd.DataFrame(
        [
            {
                "asset_id": "GOLD_PAPER_CMB",
                "transaction_date": "2025-11-03",
                "transaction_type": "buy",
                "quantity": 12.5,
                "price": 800.0,
                "amount": 10000,
                "account": "测试银行",
            },
            {
                "asset_id": "GOLD_PAPER_CMB",
                "transaction_date": "2025-11-03",
                "transaction_type": "buy",
                "quantity": 12.8,
                "price": 781.25,
                "amount": 10000,
                "account": "测试银行",
            },
        ]
    )
    normalized = _normalize_transactions_df(raw, "Gold_Excel")
    assert len(normalized) == 2

    conn = duckdb.connect(":memory:")
    conn.execute(Path("src/database/schema.sql").read_text(encoding="utf-8"))

    class Connector:
        def execute(self, sql, params=()):
            return conn.execute(sql, params)

        def executemany(self, sql, rows):
            conn.executemany(sql, rows)

    db = Connector()
    _replace_transactions(db, normalized)
    _replace_transactions(db, normalized)
    rows = conn.execute(
        "SELECT quantity, amount_gross FROM transactions WHERE source_system='Gold_Excel' ORDER BY quantity"
    ).fetchall()
    assert len(rows) == 2
    assert [float(row[0]) for row in rows] == [12.5, 12.8]
    assert sum(float(row[1]) for row in rows) == 20000.0
