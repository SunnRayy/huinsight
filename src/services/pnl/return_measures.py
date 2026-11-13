"""Per-asset return measures (audit 2026-11-08 issue 5, owner decision).

Two percentages replace the single "(realized + unrealized) / remaining cost"
figure, which inflated after partial sells as the remaining cost shrank:

- ``unrealized_pct``      = unrealized / remaining cost. The owner's loss-review
  governance rule (review at −25%) uses this definition.
- ``lifetime_return_pct`` = lifetime P&L / total invested, where total invested
  is every amount ever put into the position (buys, RSU vests, CN fund
  switches in), from the same flows as the per-asset XIRR.

The per-asset XIRR rides along for detail views and tooltips. It stays
annualized when the money has been in for under a year (owner decision
2026-11-09), flagged ``xirr_under_one_year`` so the UI can say so. Money amounts are
CNY at today's FX, like every other aggregate (USD P&L at today's rate).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

ONE_YEAR_DAYS = 365

from src.services.asset_xirr import build_asset_xirr


def invested_and_xirr(db, today_fx: float) -> Dict[str, Tuple[Optional[float], Optional[float], bool]]:
    """{asset_id: (total invested CNY or None, annual XIRR as a fraction or None,
    True when the first money in is under a year before the valuation day)}."""
    try:
        result = build_asset_xirr(db, today_fx)
    except Exception:  # a broken ledger must not take the P&L pages down
        return {}
    out: Dict[str, Tuple[Optional[float], Optional[float], bool]] = {}
    for row in result.get("assets", []):
        invested = float(row.get("invested_native") or 0.0)
        if row.get("currency") == "USD":
            invested *= today_fx
        first, last = row.get("first_flow"), row.get("terminal_day")
        short = bool(first and last and (last - first).days < ONE_YEAR_DAYS)
        out[row["asset_id"]] = (invested if invested > 0 else None, row.get("xirr"), short)
    return out


def pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """numerator / denominator in percent, or None when it is not measurable."""
    if numerator is None or not denominator or abs(denominator) < 1:
        return None
    return round(numerator / denominator * 100.0, 2)


def xirr_pct(rate: Optional[float]) -> Optional[float]:
    return round(rate * 100.0, 2) if rate is not None else None
