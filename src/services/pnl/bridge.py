"""Lifetime P&L bridge: Overview lifetime P&L ↔ Returns-page investment gain.

Audit 2026-11-08 issue 6 (owner decision): generate the bridge automatically and
itemise whatever is left, or show it is under ¥5K.

The two figures measure the same thing, value minus net money in, with three
differences, each computed here per Returns source (CN funds, US brokers, RSU, gold):

1. Dates. Returns covers its frozen window (2019-11-30 → coverage end); the
   Overview covers everything to today. After-window lines use Returns' own
   month-end values and flows, then the Overview valuation for the last stretch.
   Before the window, the Overview also counts the gain made before the opening
   value (opening value − ledger money in before it).
2. FX. Returns converts each external flow at its own date's rate; the Overview
   converts every USD amount at today's rate. FX line = Σ USD flows ×
   (dated rate − today's rate), from the flows' own recorded rates.
3. What counts as money in. Returns uses account-level external flows; the
   Overview uses the ledger trades (buys, vests, switches in, minus sells). The
   remainder per source equals, exactly, the gap between those two money-in
   records plus the engine's own income (dividends, interest, fees) — so a source
   whose remainder is ¥5K or more is itemised by month.

Amounts are CNY; a positive line raises the Overview figure above Returns.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

GROUP_LABELS = {
    "cn": "CN funds (TTFund)",
    "us": "US brokers (Schwab + IBKR)",
    "rsu": "RSU",
    "gold": "Gold",
    "outside": "Outside the Returns accounts",
}
# Returns valuation columns (src/financial_analysis/twr.py) → source group.
VALUE_COLUMN_GROUPS = {
    "投资资产_股票基金_A股基金": "cn",
    "投资资产_股票基金_美股基金_Schwab": "us",
    "投资资产_股票基金_美股基金_IBKR": "us",
    "投资资产_公司RSU_Amazon Stock": "rsu",
    "投资资产_公司RSU_Google Stock": "rsu",
    "投资资产_黄金_纸黄金(元)": "gold",
}
FLOW_SOURCE_GROUPS = {"TTFund": "cn", "Schwab": "us", "IBKR": "us", "RSU": "rsu", "Gold": "gold"}
LEDGER_SOURCE_GROUPS = {
    "CN_Fund_Excel": "cn", "Schwab_CSV": "us", "Broker_IBKR": "us", "Consolidated": "us",
    "RSU_Excel": "rsu", "Gold_Excel": "gold",
}
MONEY_IN_TYPES = frozenset({"buy", "vest", "transfer_in", "adjustment_buy"})
MONEY_OUT_TYPES = frozenset({"sell", "transfer_out"})
UNEXPLAINED_THRESHOLD_CNY = 5000.0
ITEM_MIN_CNY = 1000.0


def _month_label(day: date) -> date:
    return day.replace(day=1)


def _month_end(label: date) -> date:
    return (label.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _r(x: float) -> float:
    return round(float(x), 2)


# ── pure arithmetic (unit-tested) ────────────────────────────────────────────

def itemise_months(diffs: Dict[str, float]) -> List[Dict[str, Any]]:
    """Name the months whose money-in records differ by ¥1,000 or more.

    Two adjacent months that cancel out (a flow dated later than its trade) are
    one 'timing' item; everything smaller is pooled into one line.
    """
    months = sorted(diffs)
    items: List[Dict[str, Any]] = []
    small = 0.0
    i = 0
    while i < len(months):
        m, d = months[i], diffs[months[i]]
        nxt = months[i + 1] if i + 1 < len(months) else None
        if abs(d) >= ITEM_MIN_CNY and nxt and abs(diffs[nxt]) >= ITEM_MIN_CNY and abs(d + diffs[nxt]) < ITEM_MIN_CNY:
            small += d + diffs[nxt]
            items.append({"month": f"{m}→{nxt}", "amount_cny": 0.0, "net_cny": _r(d + diffs[nxt]),
                          "kind": "timing", "gross_cny": _r(abs(d))})
            i += 2
            continue
        if abs(d) >= ITEM_MIN_CNY:
            items.append({"month": m, "amount_cny": _r(d), "kind": "money_in_gap"})
        else:
            small += d
        i += 1
    items.append({"month": None, "amount_cny": _r(small), "kind": "smaller_differences"})
    return items


def bridge_group(g: Dict[str, Any]) -> Dict[str, Any]:
    """One source's lines from its raw totals (see module docstring for the identity).

    Keys of ``g``: lifetime, value_now, v_start, v_end, v_last, flows_window,
    flows_post_end, flows_post_last, flows_dated_all, flows_today_all,
    ledger_pre, ledger_all, monthly_flows, monthly_ledger.
    """
    returns_gain = g["v_end"] - g["v_start"] - g["flows_window"]
    after_window = g["v_last"] - g["v_end"] - g["flows_post_end"]
    to_today = g["value_now"] - g["v_last"] - g["flows_post_last"]
    fx = g["flows_dated_all"] - g["flows_today_all"]
    before_window = g["v_start"] - g["ledger_pre"] if (g["v_start"] or g["ledger_pre"]) else 0.0
    remainder = g["lifetime"] - returns_gain - after_window - to_today - fx - before_window
    out = {
        "overview_lifetime_cny": _r(g["lifetime"]),
        "returns_gain_cny": _r(returns_gain),
        "after_window_cny": _r(after_window),
        "to_today_cny": _r(to_today),
        "fx_cny": _r(fx),
        "before_window_cny": _r(before_window),
        "remainder_cny": _r(remainder),
        "items": None,
    }
    if abs(remainder) >= UNEXPLAINED_THRESHOLD_CNY:
        months = sorted(set(g["monthly_flows"]) | set(g["monthly_ledger"]))
        diffs = {m: g["monthly_flows"].get(m, 0.0) - g["monthly_ledger"].get(m, 0.0) for m in months}
        items = itemise_months(diffs)
        engine_income = g["ledger_all"] - (g["value_now"] - g["lifetime"])
        items.append({"month": None, "amount_cny": _r(engine_income), "kind": "engine_income"})
        out["items"] = items
    return out


# ── data gathering ───────────────────────────────────────────────────────────

def usd_flow_fx_effect(db, fx_today: float) -> Optional[float]:
    """The bridge's FX line on its own: Returns money in/out valued at each flow's
    date rate minus the same flows at today's rate (only USD flows differ).

    Cheap enough for the Overview; ``build_lifetime_bridge`` sums the same
    quantity per source group (tests/services/pnl/test_lifetime_bridge.py).
    """
    row = db.execute("SELECT coverage_start FROM investment_twr_source WHERE id = 1").fetchone()
    if not row or row[0] is None:
        return None
    total = db.execute(
        "SELECT COALESCE(SUM(CAST(amount_cny AS DOUBLE) - CAST(original_amount AS DOUBLE) * ?), 0) "
        "FROM investment_external_flows WHERE original_currency = 'USD' AND event_date > ?",
        [float(fx_today), row[0]]).fetchone()[0]
    return _r(total)


def _group_values(db, label: date) -> Optional[Dict[str, float]]:
    row = db.execute("SELECT payload FROM balance_sheet_monthly WHERE snapshot_date = ?", [label]).fetchone()
    if not row:
        return None
    data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    out: Dict[str, float] = defaultdict(float)
    for column, group in VALUE_COLUMN_GROUPS.items():
        try:
            out[group] += float(data[column])
        except (KeyError, TypeError, ValueError):
            return None
    return out


def build_lifetime_bridge(db, *, include_non_rebalanceable: bool = False, today: Optional[date] = None) -> Dict[str, Any]:
    from src.financial_analysis.twr import INVESTMENT_VALUE_COLUMNS, load_investment_return_inputs
    from src.services.pnl import Scope, compute_portfolio_pnl, summary_totals
    from src.services.rebalanceable_filter import fetch_non_rebalanceable_asset_ids

    if set(INVESTMENT_VALUE_COLUMNS) != set(VALUE_COLUMN_GROUPS):
        return {"available": False, "reason": "Returns valuation columns changed; bridge mapping needs an update"}
    inputs = load_investment_return_inputs(db)
    if not inputs:
        return {"available": False, "reason": "Returns inputs unavailable"}
    start, end = date.fromisoformat(inputs["period_start"]), date.fromisoformat(inputs["as_of"])
    today = today or date.today()

    v_start, v_end = _group_values(db, _month_label(start)), _group_values(db, _month_label(end))
    if v_start is None or v_end is None:
        return {"available": False, "reason": "Returns window month-end values missing"}
    last, v_last = end, v_end
    for (label,) in db.execute(
        "SELECT snapshot_date FROM balance_sheet_monthly WHERE snapshot_date > ? ORDER BY snapshot_date",
        [_month_label(end)],
    ).fetchall():
        values = _group_values(db, label)
        if values is None or _month_end(label) > today:
            break
        last, v_last = _month_end(label), values

    portfolio = compute_portfolio_pnl(db, scope=Scope())
    fx_today = float(portfolio.today_fx)
    excluded = frozenset() if include_non_rebalanceable else fetch_non_rebalanceable_asset_ids(db)
    overview = summary_totals(portfolio.assets, excluded_ids=excluded, apply_name_filter=not include_non_rebalanceable)
    # A closed asset has no holding row: take its reader from the ledger (the reader
    # with most rows — imported review trades such as 'AIA' are not a reader).
    ledger_source: Dict[str, str] = {}
    for asset_id, source, _n in db.execute(
        "SELECT asset_id, source_system, COUNT(*) AS n FROM transactions GROUP BY ALL ORDER BY n").fetchall():
        if source in LEDGER_SOURCE_GROUPS:
            ledger_source[asset_id] = source

    G = defaultdict(lambda: {"lifetime": 0.0, "value_now": 0.0, "flows_window": 0.0, "flows_post_end": 0.0,
                             "flows_post_last": 0.0, "flows_dated_all": 0.0, "flows_today_all": 0.0,
                             "ledger_pre": 0.0, "ledger_all": 0.0,
                             "monthly_flows": defaultdict(float), "monthly_ledger": defaultdict(float)})
    for a in portfolio.assets:
        if a.asset_id in excluded:
            continue
        group = LEDGER_SOURCE_GROUPS.get(a.source_system or ledger_source.get(a.asset_id), "outside")
        G[group]["lifetime"] += a.lifetime_cny or 0.0
        if a.is_current and group != "outside":
            G[group]["value_now"] += a.market_value_cny

    for day, source, amount_cny, original, currency in db.execute(
        "SELECT event_date, source, amount_cny, original_amount, original_currency "
        "FROM investment_external_flows WHERE event_date > ?", [start]).fetchall():
        g = G[FLOW_SOURCE_GROUPS.get(source, "outside")]
        dated = float(amount_cny)
        at_today = float(original) * fx_today if currency == "USD" else dated
        bucket = "flows_window" if day <= end else "flows_post_end" if day <= last else "flows_post_last"
        g[bucket] += dated
        g["flows_dated_all"] += dated
        g["flows_today_all"] += at_today
        g["monthly_flows"][day.strftime("%Y-%m")] += at_today

    types = sorted(MONEY_IN_TYPES | MONEY_OUT_TYPES)
    for day, source, ttype, currency, amount in db.execute(
        f"SELECT transaction_date, source_system, transaction_type, currency, ABS(amount_net) FROM transactions "
        f"WHERE transaction_type IN ({','.join('?' * len(types))}) AND amount_net IS NOT NULL",
        types).fetchall():
        group = LEDGER_SOURCE_GROUPS.get(source)
        if group is None:
            continue
        signed = float(amount) * (fx_today if currency == "USD" else 1.0) * (1 if ttype in MONEY_IN_TYPES else -1)
        G[group]["ledger_all"] += signed
        if day <= start:
            G[group]["ledger_pre"] += signed
        else:
            G[group]["monthly_ledger"][day.strftime("%Y-%m")] += signed

    rows, totals = [], defaultdict(float)
    for group in ("cn", "us", "rsu", "gold", "outside"):
        if group not in G and group == "outside":
            continue
        g = G[group]
        g.update(v_start=v_start.get(group, 0.0), v_end=v_end.get(group, 0.0), v_last=v_last.get(group, 0.0))
        if group == "outside":  # no Returns counterpart: the whole figure is scope
            line = {k: 0.0 for k in ("returns_gain_cny", "after_window_cny", "to_today_cny", "fx_cny",
                                     "before_window_cny", "remainder_cny")}
            line.update(overview_lifetime_cny=_r(g["lifetime"]), scope_cny=_r(g["lifetime"]), items=None)
        else:
            line = bridge_group(g)
        rows.append({"group": group, "label": GROUP_LABELS[group], **line})
        for key in ("overview_lifetime_cny", "returns_gain_cny", "after_window_cny", "to_today_cny",
                    "fx_cny", "before_window_cny", "remainder_cny", "scope_cny"):
            totals[key] += line.get(key) or 0.0

    returns_gain = totals["returns_gain_cny"]
    overview_lifetime = float(overview["total_lifetime"])
    lines = [
        {"key": "returns_gain", "label": f"Returns investment gain ({start} → {end})", "amount_cny": _r(returns_gain)},
        {"key": "after_window", "label": f"After the Returns window ({end} → {last}, Returns' month-end values)",
         "amount_cny": _r(totals["after_window_cny"])},
        {"key": "to_today", "label": f"{last} → {today} (Overview valuation)", "amount_cny": _r(totals["to_today_cny"])},
        {"key": "fx", "label": "USD money in at today's rate instead of each flow's date rate",
         "amount_cny": _r(totals["fx_cny"])},
        {"key": "before_window", "label": f"Gain before {start} (opening value − money put in before it)",
         "amount_cny": _r(totals["before_window_cny"])},
        {"key": "scope", "label": "Assets outside the Returns accounts", "amount_cny": _r(totals["scope_cny"])},
        {"key": "remainder", "label": "Money-in records differ (itemised by source)", "amount_cny": _r(totals["remainder_cny"])},
    ]
    closing_error = overview_lifetime - sum(line["amount_cny"] for line in lines)
    unexplained = sum(
        row["remainder_cny"] if row["items"] is None else
        sum(i["amount_cny"] for i in row["items"] if i["kind"] in ("smaller_differences",))
        for row in rows
    ) + closing_error
    return {
        "available": True,
        "period_start": start.isoformat(), "as_of": end.isoformat(),
        "last_month_end": last.isoformat(), "today": today.isoformat(), "usd_cny_today": fx_today,
        "scope": "all_assets" if include_non_rebalanceable else "rebalanceable",
        "overview_lifetime_cny": _r(overview_lifetime),
        "returns_gain_cny": _r(returns_gain),
        "lines": lines,
        "by_source": rows,
        "closing_error_cny": _r(closing_error),
        "unexplained_cny": _r(unexplained),
        "threshold_cny": UNEXPLAINED_THRESHOLD_CNY,
        "within_threshold": abs(unexplained) < UNEXPLAINED_THRESHOLD_CNY,
    }
