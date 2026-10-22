"""Paper-gold cost comes from the same FIFO replay as its realized P&L.

docs/known-issues.md §gold-cost-method-mix: the workbook's bank average cost
paired with FIFO realized P&L overstated lifetime P&L. With one method, lifetime
P&L equals the cash result (value − purchases + sales), and in-kind 结息 grams
are zero-cost lots.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.financial_analysis.cost_basis import CostBasisCalculator
from src.services.pnl.models import Treatment
from tests.services.pnl.test_manual_pnl_overlay import _by_id, _hold, _register, db  # noqa: F401

pytestmark = pytest.mark.critical

GOLD = "ALTS_Test_Gold"


def _txn(db, ttype, day, qty, price, amount):  # noqa: F811
    db.execute(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, 'CNY', ?, 'Gold_Excel', FALSE)",
        [GOLD, GOLD, ttype, qty, price, amount, f"2026-0{day}-01"],
    )


def _ledger(db):  # noqa: F811
    db.execute("INSERT INTO taxonomy_classes VALUES (7,'Commodity','商品',NULL,TRUE), (8,'Gold','黄金',7,TRUE)")
    _register(db, GOLD, "Paper gold", "Gold")
    _txn(db, "buy", 1, 10.0, 100.0, 1000.0)
    _txn(db, "buy", 2, 10.0, 200.0, 2000.0)
    _txn(db, "interest", 3, 1.0, 190.0, 190.0)   # grams, not cash; amount is their value
    _txn(db, "sell", 4, 5.0, 150.0, 750.0)


def test_gold_cost_is_fifo_remaining_cost_and_lifetime_matches_cash(db):  # noqa: F811
    _ledger(db)
    _hold(db, GOLD, mv=16 * 180.0, qty=16.0, cost_unit=160.0, price_unit=180.0, source="Gold_Excel")

    gold = _by_id(db)[0][GOLD]
    assert gold.treatment is Treatment.traded
    assert gold.cost_basis_cny == pytest.approx(2500.0)       # 5×100 + 10×200 + 1×0
    assert gold.realized_cny == pytest.approx(250.0)          # 750 − 5×100
    assert gold.lifetime_cny == pytest.approx(16 * 180.0 - 3000.0 + 750.0)


def test_gold_cost_is_unavailable_when_ledger_does_not_explain_holding(db):  # noqa: F811
    _ledger(db)
    _hold(db, GOLD, mv=17 * 180.0, qty=17.0, cost_unit=160.0, price_unit=180.0, source="Gold_Excel")

    gold = _by_id(db)[0][GOLD]
    # Not the workbook cost: pairing it with FIFO realized P&L is the defect.
    assert gold.treatment is Treatment.balance_only
    assert gold.cost_basis_cny is None
    assert gold.unrealized_cny is None
    assert gold.lifetime_cny is None
    assert "does not match" in gold.cost_unavailable_reason


def test_gold_cost_is_unavailable_when_ledger_oversells(db):  # noqa: F811
    _ledger(db)
    _txn(db, "sell", 5, 20.0, 150.0, 3000.0)     # 16 g open, 20 g sold
    _txn(db, "buy", 6, 20.0, 150.0, 3000.0)      # final quantity back to 16 g
    _hold(db, GOLD, mv=16 * 180.0, qty=16.0, cost_unit=160.0, price_unit=180.0, source="Gold_Excel")

    gold = _by_id(db)[0][GOLD]
    assert gold.cost_basis_cny is None
    assert "incomplete" in gold.cost_unavailable_reason


def test_gold_lots_replay_to_the_holding_snapshot_date(db):  # noqa: F811
    _ledger(db)
    # After the 2026-08-01 snapshot: sell 16 g, buy 16 g at another price.
    db.execute(
        "INSERT INTO transactions VALUES (?, ?, 'sell', 16, 300, 4800, 'CNY', '2026-09-01', 'Gold_Excel', FALSE),"
        " (?, ?, 'buy', 16, 300, 4800, 'CNY', '2026-09-02', 'Gold_Excel', FALSE)",
        [GOLD, GOLD, GOLD, GOLD],
    )
    _hold(db, GOLD, mv=16 * 180.0, qty=16.0, cost_unit=160.0, price_unit=180.0, source="Gold_Excel")

    gold = _by_id(db)[0][GOLD]
    assert gold.cost_basis_cny == pytest.approx(2500.0)       # the snapshot's lots, not the 09-02 buy


def test_interest_with_quantity_from_other_sources_adds_no_lot():
    calc = CostBasisCalculator("CN_FUND_X")
    calc.process_transactions(pd.DataFrame(
        {"transaction_type": ["buy", "interest"], "quantity": [2.0, 1.0],
         "price_unit": [100.0, 1.0], "amount_net": [200.0, 1.0], "currency": ["CNY"] * 2,
         "source_system": ["CN_Fund_Excel"] * 2},
        index=pd.to_datetime(["2026-01-01", "2026-02-01"]),
    ))
    assert calc.remaining_position() == pytest.approx((2.0, 200.0))


def test_in_kind_interest_is_a_zero_cost_lot_and_cash_interest_adds_none():
    calc = CostBasisCalculator(GOLD)
    calc.process_transactions(pd.DataFrame(
        {"transaction_type": ["buy", "interest", "interest", "sell"],
         "quantity": [2.0, 1.0, 0.0, 2.5], "price_unit": [100.0, 120.0, 0.0, 150.0],
         "amount_net": [200.0, 120.0, 5.0, 375.0], "currency": ["CNY"] * 4,
         "source_system": ["Gold_Excel"] * 4},
        index=pd.to_datetime(["2026-01-01", "2026-02-01", "2026-02-15", "2026-03-01"]),
    ))
    # Sell 2.5 g: 2 g from the buy (cost 200) + 0.5 g from the interest lot (cost 0).
    assert calc.realized_pnl == pytest.approx(175.0)
    assert calc.remaining_position() == pytest.approx((0.5, 0.0))
