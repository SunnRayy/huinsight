"""Money-weighted return (XIRR) per asset, rolled up by asset class and by account.

Built from stored transactions plus the current holding, for the AI context. A figure is
reported only when the asset's transactions explain its current quantity; otherwise the
asset is listed as not measurable, so a broken history never shows up as a return.

Flows: buy / vest / adjustment buy / CN fund conversion in = money out; sell / dividend /
interest / CN conversion out = money in; withholding as recorded. Reinvested dividends and
paper-gold interest add shares, whose value is in the final holding. Transfers between the owner's own brokers
(Schwab ↔ IBKR) are not flows. USD assets are measured in USD; roll-ups convert USD at
today's rate. Cash, money-market, insurance, property and balance-only rows are excluded.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from src.services.transaction_source_selector import select_transaction_sources

_OUT = {"buy", "vest", "adjustment_buy"}
_IN = {"sell", "sell_to_cover", "dividend", "dividend_cash", "interest"}
_ADD_SHARES = {"buy", "vest", "adjustment_buy", "dividend_reinvest", "transfer_in"}
_REMOVE_SHARES = {"sell", "sell_to_cover", "transfer_out"}
_EXCLUDED_CLASSES = {"Cash", "Insurance", "Real Estate"}
_EXCLUDED_SUBCLASSES = {"Money Market", "Cash", "Cash Checking", "Bank Wealth", "Pension"}
_QTY_TOLERANCE = 0.005  # 0.5% of the holding, or 0.01 share


def xirr(flows: List[Tuple[date, float]]) -> Optional[float]:
    flows = [(d, a) for d, a in flows if abs(a) > 1e-9]
    if len(flows) < 2 or all(a > 0 for _, a in flows) or all(a < 0 for _, a in flows):
        return None
    d0 = min(d for d, _ in flows)

    def npv(rate: float) -> float:
        return sum(a / (1 + rate) ** ((d - d0).days / 365.0) for d, a in flows)

    lo, hi = -0.9999, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _in_kind(source: str, kind: str, qty: float) -> bool:
    """Paper-gold 结息 credits grams, not cash: its 金额 is only the grams' value."""
    return source == "Gold_Excel" and kind == "interest" and qty > 0


def _flow(source: str, kind: str, net: float) -> float:
    if kind in _OUT:
        return -abs(net)
    if kind in _IN:
        return abs(net)
    if kind == "tax_adjustment":
        return net
    if source == "CN_Fund_Excel" and kind == "transfer_in":
        return -abs(net)
    if source == "CN_Fund_Excel" and kind == "transfer_out":
        return abs(net)
    return 0.0


def _account(sources: set) -> str:
    if sources & {"Schwab_CSV", "Broker_IBKR"}:
        return "US brokerage (Schwab + IBKR)"
    if "RSU_Excel" in sources:
        return "RSU"
    if "CN_Fund_Excel" in sources:
        return "CN mutual funds"
    if "Gold_Excel" in sources:
        return "Paper gold"
    return "Other"


def build_asset_xirr(db, usd_cny: float) -> Dict[str, Any]:
    """{'assets': [...], 'by_class': {...}, 'by_account': {...}, 'portfolio': float|None}."""
    held = {
        r[0]: r[1:]
        for r in db.execute("""
            WITH latest AS (
                SELECT asset_id, MAX(snapshot_date) AS d FROM holdings
                WHERE is_shadow = FALSE GROUP BY asset_id)
            SELECT h.asset_id, SUM(h.quantity), MAX(h.market_price_unit), SUM(h.market_value),
                   MAX(h.currency), MAX(h.snapshot_date),
                   COALESCE(MAX(parent_tc.name), MAX(tc.name), MAX(r.asset_class), 'Unclassified'),
                   COALESCE(MAX(r.asset_class), 'Unclassified'),
                   MAX(CAST(h.price_updated_at AS DATE))
            FROM holdings h JOIN latest l ON h.asset_id = l.asset_id AND h.snapshot_date = l.d
            LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
            LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
            LEFT JOIN taxonomy_classes parent_tc ON tc.parent_id = parent_tc.id
            WHERE h.is_shadow = FALSE GROUP BY h.asset_id""").fetchall()
    }
    registry = {
        r[0]: (r[1], r[2])
        for r in db.execute("""
            SELECT r.canonical_id,
                   COALESCE(parent_tc.name, tc.name, r.asset_class, 'Unclassified'),
                   COALESCE(r.asset_class, 'Unclassified')
            FROM asset_registry r
            LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
            LEFT JOIN taxonomy_classes parent_tc ON tc.parent_id = parent_tc.id""").fetchall()
    }
    asset_ids = [r[0] for r in db.execute(
        "SELECT DISTINCT asset_id FROM transactions WHERE asset_id IS NOT NULL ORDER BY 1").fetchall()]

    assets: List[Dict[str, Any]] = []
    rollups = {"by_class": defaultdict(list), "by_account": defaultdict(list)}
    coverage = {"by_class": defaultdict(lambda: [0.0, 0.0]), "by_account": defaultdict(lambda: [0.0, 0.0])}
    for aid in asset_ids:
        sources = select_transaction_sources(db, aid)
        if not sources:
            continue
        marks = ", ".join("?" for _ in sources)
        rows = db.execute(
            f"SELECT source_system, LOWER(transaction_type), transaction_date, quantity, amount_net, currency "
            f"FROM transactions WHERE asset_id = ? AND source_system IN ({marks}) ORDER BY transaction_date, id",
            [aid, *sources],
        ).fetchall()
        h = held.get(aid)
        top, sub = (h[5], h[6]) if h else registry.get(aid, ("Unclassified", "Unclassified"))
        if top in _EXCLUDED_CLASSES or sub in _EXCLUDED_SUBCLASSES:
            continue
        usd = any((r[5] or "").upper() == "USD" for r in rows) or (h is not None and (h[3] or "").upper() == "USD")
        flows, shares = [], 0.0
        for source, kind, day, qty, net, _cur in rows:
            q = abs(float(qty or 0))
            if _in_kind(source, kind, q):
                shares += q
                continue
            if kind in _ADD_SHARES:
                shares += q
            elif kind in _REMOVE_SHARES:
                shares -= q
            amount = _flow(source, kind, float(net or 0))
            if amount:
                flows.append((day, amount))
        qty_now = float(h[0] or 0) if h else 0.0
        if usd and h:
            value_native = qty_now * float(h[1] or 0)
        else:
            value_native = float(h[2] or 0) if h else 0.0
        closes = abs(shares - qty_now) <= max(0.01, _QTY_TOLERANCE * abs(qty_now))
        # The value is quantity at the holdings date × the latest price, so it is a value on the
        # price date: a stale CN snapshot repriced today must not be dated back to the snapshot.
        terminal_day = max(d for d in (h[4], h[7]) if d) if h else (max(d for d, _ in flows) if flows else None)
        all_flows = flows + ([(terminal_day, value_native)] if value_native and terminal_day else [])
        rate = xirr(all_flows) if closes else None
        invested = -sum(a for _, a in flows if a < 0)
        account = _account(set(sources))
        scale = usd_cny if usd else 1.0
        assets.append({
            "asset_id": aid, "top_class": top, "account": account, "currency": "USD" if usd else "CNY",
            "invested_native": invested, "value_native": value_native,
            "first_flow": min((d for d, _ in flows), default=None),
            "xirr": rate, "measurable": closes and rate is not None,
            "reason": None if closes else f"transactions give {shares:,.2f} shares, holding is {qty_now:,.2f}",
        })
        for key, bucket in (("by_class", top), ("by_account", account)):
            coverage[key][bucket][0] += invested * scale
            if closes and rate is not None:
                coverage[key][bucket][1] += invested * scale
                rollups[key][bucket] += [(d, a * scale) for d, a in all_flows]

    result: Dict[str, Any] = {"assets": assets, "usd_cny": usd_cny}
    for key in ("by_class", "by_account"):
        result[key] = {
            name: {"xirr": xirr(flows),
                   "covered_pct": (coverage[key][name][1] / coverage[key][name][0] * 100
                                   if coverage[key][name][0] else 0.0)}
            for name, flows in sorted(rollups[key].items())
        }
        for name, (total, _ok) in coverage[key].items():
            result[key].setdefault(name, {"xirr": None, "covered_pct": 0.0})
    everything = [f for flows in rollups["by_account"].values() for f in flows]
    result["portfolio"] = xirr(everything)
    return result
