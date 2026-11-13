"""Holding cost from the FIFO replay of an asset's own ledger (paper gold).

Split out of ``engine.py``: the engine asks this module for a FIFO-cost source's
unit cost and either gets one (optionally with a tolerance warning) or a reason
the cost cannot be measured.
"""
from __future__ import annotations

import logging

from src.services.portfolio_helpers import fifo_remaining_position

logger = logging.getLogger("src.services.pnl.engine")

# Sources whose holding cost comes from the FIFO replay of their own ledger,
# not the workbook's unit cost. Paper gold's 平均成本价 is the bank's average
# cost; pairing it with FIFO realized P&L overstated lifetime P&L (two cost
# methods in one figure).
FIFO_COST_SOURCES = frozenset({"Gold_Excel"})
_FIFO_QTY_TOLERANCE = 1e-3
# A replay within this gap of the holding still prices the position (FIFO unit
# cost × the reported quantity) but carries a warning, rather than dropping the
# whole cost over a rounding-sized ledger gap (2026-11-08: 0.0036 g of 305 g
# hid a ¥289K cost). Owner rule: under 0.01 g or 0.01% of the holding.
_FIFO_QTY_WARN_ABS = 0.01
_FIFO_QTY_WARN_REL = 1e-4


def fifo_cost_price_unit(db, asset_id, quantity, source_system):
    """(unit cost, None, warning) from the open FIFO lots, or (None, reason, None).

    The ledger is replayed to the holding's snapshot date, so a later trade
    cannot swap in other lots. The cost is unavailable when the replay is
    missing, oversells (incomplete ledger) or leaves a quantity clearly different
    from the holding. A small gap (within max(0.01, 0.01% of the holding)) keeps
    the FIFO unit cost and returns a warning naming the gap. The workbook's own
    cost is not a fallback: pairing it with FIFO realized P&L is the defect this
    replaces.
    """
    snap = db.execute(
        "SELECT MAX(snapshot_date) FROM holdings "
        "WHERE asset_id = ? AND source_system = ? AND NOT is_shadow",
        [asset_id, source_system],
    ).fetchone()
    end_date = str(snap[0]) if snap and snap[0] is not None else None
    pos = fifo_remaining_position(db, asset_id, end_date=end_date)
    if pos is not None and pos[0] > 0:
        gap = abs(pos[0] - quantity)
        if gap <= _FIFO_QTY_TOLERANCE:
            return pos[1] / pos[0], None, None
        if gap <= max(_FIFO_QTY_WARN_ABS, _FIFO_QTY_WARN_REL * abs(quantity)):
            warning = (
                f"ledger quantity {pos[0]:.4f} differs from holding {quantity:.4f} "
                f"by {gap:.4f}; cost uses the FIFO unit cost"
            )
            logger.warning("FIFO cost for %s within tolerance: %s", asset_id, warning)
            return pos[1] / pos[0], None, warning
    reason = (
        "ledger incomplete (replay failed or oversold)" if pos is None
        else f"ledger quantity {pos[0]:.4f} does not match holding {quantity:.4f}"
    )
    logger.warning("FIFO cost unavailable for %s: %s", asset_id, reason)
    return None, reason, None
