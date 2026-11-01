import json
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from src.database.connector import DatabaseConnector
from src.financial_analysis.regime import assess_portfolio_regime
from src.services.investment_risk import build_investment_risk
from src.services.context_facts import build_context_allocation, format_account_risk, LATEST_VALUATIONS_CTE
from src.services.investment_returns import build_investment_returns, format_account_returns
from src.services.rebalanceable_filter import fetch_non_rebalanceable_asset_ids
from src.services.portfolio_helpers import calculate_realized_pnl
from src.services.currency import (
    get_today_usd_cny_rate,
)
from src.services.pnl.engine import compute_portfolio_pnl
from src.services.asset_xirr import build_asset_xirr
from src.services.pnl.models import Scope

logger = logging.getLogger(__name__)

CASH_CLASS_KEYS = ('cash', '现金', 'money market', 'bank wealth', 'cash checking',
                   'cash deposit', 'time deposit', '货币市场', '银行理财', '活期存款', '定期存款')
_LATEST_PER_ASSET_CTE = """
    latest_per_asset AS (
        SELECT asset_id, MAX(snapshot_date) AS latest_date
        FROM holdings
        WHERE is_shadow = FALSE
        GROUP BY asset_id
    )
"""

_STALE_SOURCE_DAYS = 31
_SOURCE_LABELS = {
    "Schwab_CSV": "Schwab",
    "Broker_IBKR": "IBKR",
    "Consolidated": "Schwab + IBKR (combined positions)",
    "CN_Fund_Excel": "CN mutual funds",
    "Gold_Excel": "Paper gold",
    "Insurance_Excel": "Insurance",
    "RSU_Excel": "RSU",
    "Financial_Summary_Excel": "Financial Summary (deposits, bonds, pension)",
}


_MONTH_LABELLED_SOURCES = {"Financial_Summary_Excel"}
_LIABILITY_PREFIXES = ("短期负债", "长期负债", "其他负债")


def _month_end(day: date) -> date:
    following = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return following - timedelta(days=1)


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _is_cash_like(asset_class: Optional[str]) -> bool:
    if not asset_class:
        return False
    return asset_class.lower() in CASH_CLASS_KEYS


class MarkdownContextGenerator:
    """Generate Personal_Investment_Analysis_Context_*.md from Huinsight DB."""

    def __init__(self, db: DatabaseConnector):
        self.db = db
        self._realized_cache: Dict[str, float] = {}
        self._engine_pnl_map: Optional[Dict[str, Any]] = None

    def format_currency(self, value: Any) -> str:
        if value is None:
            return "¥0"
        try:
            return f"¥{float(value):,.0f}"
        except Exception:
            return "¥0"

    def _engine_pnl_by_id(self) -> Dict[str, Any]:
        """Per-asset :class:`AssetPnL` records from the one P&L engine, keyed by
        ``asset_id`` (memoized for the whole export).

        The engine (``compute_portfolio_pnl``, current scope) is the single source
        of the cost/unrealized/realized math every dashboard already uses. Its
        ``mode=current`` snapshot is the same per-asset latest, ``is_shadow=FALSE``
        universe these markdown sections query, so every current-holding
        ``asset_id`` is present.
        """
        if self._engine_pnl_map is None:
            portfolio = compute_portfolio_pnl(self.db, scope=Scope())
            self._engine_pnl_map = {
                a.asset_id: a for a in portfolio.assets if a.asset_id
            }
        return self._engine_pnl_map

    def _engine_cost(self, aid) -> Optional[float]:
        """Engine-derived cost basis (CNY) for the AI context export.

        Returns ``None`` for a **balance-only** asset (non-cash, no cost, no
        transactions — e.g. an FS bond column): its market value still counts, but
        it contributes 0 cost / 0 unrealized and is EXCLUDED from every cost/return
        denominator — the V7.8.3 rule the dashboards already apply, now reaching the
        LLM export (documented delta, plan §B.3). Cash and traded assets return
        their real FIFO/native-converted cost, identical to the pre-engine value.
        """
        pnl = self._engine_pnl_by_id().get(aid)
        # Keyed on has_known_cost, not the treatment enum (see AssetPnL): the
        # question here is "is there a cost to report?", not "how was this
        # classified?".
        if pnl is None or not pnl.has_known_cost:
            return None
        return pnl.cost_basis_cny

    def format_pct(self, value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.2f}%"
        except Exception:
            return "N/A"

    def format_ratio(self, value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.2f}"
        except Exception:
            return "N/A"

    def _sanitize_cell(self, value: Any) -> str:
        if value is None:
            text = ""
        else:
            text = str(value)
        return (
            text.replace("|", "\\|")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("\t", " ")
        )

    def _get_rebalanceable_asset_ids(self) -> set[str]:
        try:
            excluded = fetch_non_rebalanceable_asset_ids(self.db)
            rows = self.db.execute(f"""
                WITH {_LATEST_PER_ASSET_CTE}
                SELECT h.asset_id
                FROM holdings h
                JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                WHERE h.is_shadow = FALSE
                  AND COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) = TRUE
            """).fetchall()
            ids = {row[0] for row in rows if row and row[0]}
            return ids - set(excluded or set())
        except Exception:
            return set()

    def _get_realized_map(self, asset_ids: List[str]) -> Dict[str, float]:
        realized: Dict[str, float] = {}
        for aid in asset_ids:
            if not aid:
                continue
            if aid not in self._realized_cache:
                try:
                    realized_amount, realized_currency = calculate_realized_pnl(
                        self.db, aid, start_date=None
                    )
                    if realized_currency == "USD":
                        self._realized_cache[aid] = float(realized_amount or 0.0) * get_today_usd_cny_rate()
                    else:
                        self._realized_cache[aid] = float(realized_amount or 0.0)
                except Exception:
                    self._realized_cache[aid] = 0.0
            realized[aid] = self._realized_cache.get(aid, 0.0)
        return realized

    def generate_markdown_table(self, headers: List[str], rows: List[List[Any]]) -> str:
        if not rows:
            return "*No data available*"
        safe_headers = [self._sanitize_cell(h) for h in headers]
        header_row = "| " + " | ".join(safe_headers) + " |"
        separator = "|" + "|".join(["-" * (len(h) + 2) for h in safe_headers]) + "|"
        data_rows = ["| " + " | ".join(self._sanitize_cell(c) for c in r) + " |" for r in rows]
        return "\n".join([header_row, separator] + data_rows)

    def generate(self) -> str:
        """Generate full markdown document."""
        sections = [
            self._header(),
            self._section_1_portfolio_state(),
            self._section_2_performance(),
            self._section_3_market_environment(),
            self._section_4_holdings_detail(),
        ]
        valuation_section = self._section_5_valuation_dashboard()
        if valuation_section:
            sections.append(valuation_section)
        return "\n\n".join(sections)

    def _section_5_valuation_dashboard(self) -> str:
        """Valuation dashboard section for AI context export."""
        try:
            count = self.db.execute("SELECT COUNT(*) FROM valuation_snapshots").fetchone()
            if not count or count[0] == 0:
                return ""
        except Exception:
            return ""
        try:
            rows = self.db.execute(f"""
                WITH {LATEST_VALUATIONS_CTE}
                SELECT normalized_ticker, asset_class, valuation_signal,
                       pe_ttm, pe_forward, pe_ttm_pct, pe_fwd_pct,
                       sec_yield, signal_basis, is_estimable, snapshot_date
                FROM latest ORDER BY asset_class, normalized_ticker
            """).fetchall()
        except Exception:
            return ""
        if not rows:
            return ""
        lines = ["## Section 5: Valuation Dashboard\n"]
        lines.append("| 资产 | 类型 | 指标 | 当前值 | 历史%位 | 信号 | 更新日期 |")
        lines.append("|------|------|------|--------|---------|------|---------|")
        for r in rows:
            ticker, cls, signal, pe_ttm, pe_fwd, ttm_pct, fwd_pct, sec_yld, basis, estimable, snap_date = r
            if cls in ("US_STOCK", "US_ETF"):
                val = f"Fwd PE {pe_fwd:.1f}" if pe_fwd else "n/a"
                pct = f"{fwd_pct:.0f}%" if fwd_pct else "n/a"
            elif cls == "US_BOND_ETF":
                val = f"Yield {sec_yld:.2f}%" if sec_yld else "n/a"
                pct = "n/a"
            else:
                val = f"PE-TTM {pe_ttm:.1f}" if pe_ttm else "n/a"
                pct = f"{ttm_pct:.0f}%" if ttm_pct else "n/a"
            lines.append(f"| {ticker} | {cls} | — | {val} | {pct} | {signal or 'N/A'} | {snap_date} |")
        return "\n".join(lines)

    def _header(self) -> str:
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""# Personal Investment Analysis Context

Generated: {gen_time}

{self._source_freshness()}

---"""

    def _section_2_4_asset_xirr(self) -> str:
        """XIRR by account, asset class and asset (money-weighted, since first purchase)."""
        try:
            result = build_asset_xirr(self.db, get_today_usd_cny_rate())
        except Exception:
            logger.exception("export context asset XIRR failed")
            return "\n### 2.4 Money-Weighted Returns by Account, Class and Asset\n\n*Unavailable.*"

        def pct(value):
            return "—" if value is None else self.format_pct(value * 100)

        lines = [
            "\n### 2.4 Money-Weighted Returns by Account, Class and Asset\n",
            "XIRR from each asset's own buys, sells and dividends since its first purchase, ending at "
            "today's value; USD assets measured in USD. Account and class rows convert every USD "
            "flow at today's rate, so they leave out currency gains and losses. An asset counts only when its transactions "
            "explain its current quantity; \"Covered\" is the share of invested money that qualifies. "
            "Not comparable with the account-level TWR/XIRR in 2.3 (that one includes idle cash and "
            "counts only money moving into or out of the accounts). For positions held under a "
            "year the annualized figure swings widely — read it with the \"Since\" date.\n",
        ]
        for title, key in (("Account", "by_account"), ("Asset Class", "by_class")):
            rows = [[name, pct(v["xirr"]), self.format_pct(v["covered_pct"])]
                    for name, v in result[key].items()]
            if rows:
                lines.append(self.generate_markdown_table([title, "XIRR", "Covered"], rows))
                lines.append("")
        held = [a for a in result["assets"] if a["measurable"] and a["value_native"] > 0]
        held.sort(key=lambda a: (a["account"], -a["invested_native"]))
        if held:
            lines.append("Current holdings:\n")
            lines.append(self.generate_markdown_table(
                ["Asset", "Account", "Class", "Since", "XIRR"],
                [[a["asset_id"], a["account"], a["top_class"], str(a["first_flow"] or "—"), pct(a["xirr"])]
                 for a in held],
            ))
        gaps = [a for a in result["assets"] if not a["measurable"] and a["reason"]]
        if gaps:
            lines.append("\nNot measurable (history does not explain the holding): " + "; ".join(
                f"{a['asset_id']} ({a['reason']})" for a in gaps))
        lines.append(f"\nPortfolio of all measurable positions: {pct(result['portfolio'])}.")
        return "\n".join(lines)

    def _latest_liabilities(self) -> Optional[tuple]:
        """(≈ month-end date, long-term, short-term) from the newest balance-sheet row.

        Sums leaf liability columns only — never the workbook's own total — and
        skips native-currency siblings ("_USD"/"_HKD") of CNY-converted columns,
        the same classification Reader Mappings uses.
        """
        try:
            row = self.db.execute(
                "SELECT snapshot_date, payload FROM balance_sheet_monthly "
                "WHERE snapshot_date IS NOT NULL ORDER BY snapshot_date DESC LIMIT 1"
            ).fetchone()
        except Exception:
            return None
        if not row or not row[1]:
            return None
        payload = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        long_term = short_term = 0.0
        found = False
        for column, value in payload.items():
            name = str(column)
            if name.endswith(("_USD", "_HKD")) or not name.startswith(_LIABILITY_PREFIXES):
                continue
            try:
                amount = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(amount):
                continue
            found = True
            if name.startswith("短期负债"):
                short_term += amount
            else:
                long_term += amount
        if not found:
            return None
        label = _as_date(row[0])
        if label and label.day == 1:
            label = _month_end(label)
        return label, long_term, short_term

    def _source_freshness(self) -> str:
        """Per-source dates for the investable rows (property and insurance excluded).

        One global "as of" date would show the freshest source and hide the
        stale ones, so each source reports its own holdings, price and
        transaction dates.
        """
        try:
            rows = self.db.execute(f"""
                WITH {_LATEST_PER_ASSET_CTE},
                held AS (
                    SELECT h.source_system, h.asset_id, h.snapshot_date,
                           h.market_value, h.price_updated_at
                    FROM holdings h
                    JOIN latest_per_asset lpa
                      ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                    LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                    LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                    WHERE h.is_shadow = FALSE
                      AND COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) = TRUE
                ),
                tx AS (
                    SELECT source_system, MAX(transaction_date) AS last_tx
                    FROM transactions GROUP BY source_system
                )
                SELECT held.source_system, MIN(held.snapshot_date), MAX(held.snapshot_date),
                       MAX(held.price_updated_at), MAX(tx.last_tx),
                       SUM(held.market_value), COUNT(DISTINCT held.asset_id)
                FROM held LEFT JOIN tx ON tx.source_system = held.source_system
                GROUP BY held.source_system
                ORDER BY MIN(held.snapshot_date), held.source_system
            """).fetchall()
        except Exception:
            logger.exception("export context source freshness failed")
            rows = []
        if not rows:
            return "Data freshness by source: unavailable."

        today = date.today()
        table = []
        for source, oldest, newest, priced, last_tx, value, count in rows:
            oldest_d, newest_d = _as_date(oldest), _as_date(newest)
            held_as_of = str(newest_d) if oldest_d == newest_d else f"{oldest_d} – {newest_d}"
            if source in _MONTH_LABELLED_SOURCES and oldest_d == newest_d and newest_d.day == 1:
                # Same policy as returns: a month row holds ~month-end balances.
                oldest_d = _month_end(newest_d)
                held_as_of = f"≈ {oldest_d} ({newest_d:%Y-%m} month row)"
            age = (today - oldest_d).days if oldest_d else None
            if age is not None and age > _STALE_SOURCE_DAYS:
                held_as_of += f" ⚠ {age} days old"
            table.append([
                _SOURCE_LABELS.get(source, source),
                held_as_of,
                str(_as_date(priced)) if priced else "from file",
                str(_as_date(last_tx)) if last_tx else "—",
                self.format_currency(value),
                int(count or 0),
            ])
        return (
            "### Data freshness by source\n\n"
            "Quantities and balances are as of each source's holdings date; listed "
            "securities and funds are then revalued at the latest price date. Trades or "
            f"balance changes after a source's holdings date are not included; ⚠ marks a "
            f"source older than {_STALE_SOURCE_DAYS} days.\n\n"
            + self.generate_markdown_table(
                ["Source", "Holdings as of", "Latest price", "Latest transaction",
                 "Value", "Assets"],
                table,
            )
        )

    def _section_1_portfolio_state(self) -> str:
        lines = ["## 1. Portfolio State\n"]
        lines.append("### 1.1 Current Holdings Overview\n")

        try:
            result = self.db.execute(f'''
                WITH {_LATEST_PER_ASSET_CTE}
                SELECT
                    SUM(h.market_value) as total,
                    SUM(CASE WHEN COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE)
                             THEN h.market_value ELSE 0 END) as reb,
                    SUM(CASE WHEN NOT COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE)
                             THEN h.market_value ELSE 0 END) as non_reb
                FROM holdings h
                JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                WHERE h.is_shadow = FALSE
            ''').fetchone()

            total = float(result[0] or 0.0) if result and result[0] else 0.0
            reb = float(result[1] or 0.0) if result and result[1] else 0.0

            # Property and insurance can't be re-allocated, so the context reports investable
            # assets only; they stay inside net worth, which is a balance-sheet figure.
            lines.append(
                f"- Investable Assets: {self.format_currency(reb)} "
                "(every figure in this context covers these; property and insurance are excluded)"
            )
            liabilities = self._latest_liabilities()
            if liabilities:
                as_of, long_term, short_term = liabilities
                owed = long_term + short_term
                lines.append(
                    f"- Liabilities (Financial Summary ≈ {as_of}): {self.format_currency(owed)} "
                    f"(long-term {self.format_currency(long_term)}, short-term {self.format_currency(short_term)})"
                )
                lines.append(
                    f"- Net Worth (all assets incl. property and insurance, − liabilities): "
                    f"{self.format_currency(total - owed)} — balance-sheet reference only; "
                    "liabilities at the Financial Summary date"
                )

            lines.append("\n### 1.2 Investable Allocation vs Target\n")

            allocation = build_context_allocation(self.db)
            table_rows = []
            for row in allocation['top']:
                drift = row['drift_pct']
                status = ('Increase' if drift < -2 else 'Reduce' if drift > 2 else 'Aligned') if drift is not None else 'No target'
                table_rows.append([
                    row['asset_class'], self.format_currency(row['current_value']),
                    self.format_pct(row['current_pct']), self.format_pct(row['target_pct']),
                    self.format_pct(drift), status,
                ])

            if table_rows:
                lines.append(self.generate_markdown_table(
                    ["Asset Class", "Value", "Current %", "Target %", "Drift", "Status"],
                    table_rows
                ))
            else:
                lines.append("*No allocation data available.*")

            lines.append("\n### 1.3 Sub-Class Breakdown (Rebalanceable Assets Only)\n")
            try:
                subclass_rows = allocation['sub']
                if subclass_rows:
                    sub_table_rows = []
                    for row in subclass_rows:
                        sub_table_rows.append([
                            row['top_class'], row['asset_class'], self.format_currency(row['current_value']),
                            self.format_pct(row['current_pct']), self.format_pct(row['target_pct']),
                            self.format_pct(row['drift_pct']),
                        ])
                    lines.append(self.generate_markdown_table(
                        ["Top Class", "Sub-Class", "Value", "Current %", "Target %", "Drift"],
                        sub_table_rows
                    ))
                else:
                    lines.append("*No sub-class data available.*")
            except Exception as e:
                logger.error(f"Error in section 1.3: {e}")
                lines.append("*Error generating sub-class breakdown.*")

            lines.append("\n### 1.4 Tier Allocation\n")
            try:
                tier_meta_rows = self.db.execute(
                    "SELECT name, target_pct, sort_order FROM asset_tiers ORDER BY sort_order"
                ).fetchall()
                reb_total_row = self.db.execute(f'''
                    WITH {_LATEST_PER_ASSET_CTE}
                    SELECT SUM(h.market_value) as total
                    FROM holdings h
                    JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                    LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                    LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                    WHERE h.is_shadow = FALSE
                      AND COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) = TRUE
                ''').fetchone()
                reb_total = float(reb_total_row[0] or 0.0) if reb_total_row else 0.0
                tier_asset_rows = self.db.execute(f'''
                    WITH {_LATEST_PER_ASSET_CTE}
                    SELECT
                        r.tier,
                        h.asset_id,
                        SUM(h.market_value) as mv,
                        SUM(h.quantity) as quantity,
                        MAX(h.cost_price_unit) as cost_price_unit,
                        MAX(h.currency) as currency,
                        COALESCE(MAX(r.asset_class), 'Unclassified') as sub_class,
                        COALESCE(MAX(parent_tc.name), MAX(tc.name), MAX(r.asset_class), 'Unclassified') as top_class
                    FROM holdings h
                    JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                    LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                    LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                    LEFT JOIN taxonomy_classes parent_tc ON tc.parent_id = parent_tc.id
                    WHERE h.is_shadow = FALSE
                    GROUP BY r.tier, h.asset_id
                ''').fetchall()
                tier_data: Dict[str, Dict[str, Any]] = defaultdict(
                    lambda: {"val": 0.0, "unrealized_pl": 0.0, "asset_count": 0}
                )
                for t_row in tier_asset_rows:
                    t_tier, t_aid, t_mv, t_qty, t_cpu, t_curr, t_sub, t_top = t_row
                    if not t_tier:
                        continue
                    t_mv_f = float(t_mv or 0.0)
                    t_cost = self._engine_cost(t_aid)
                    tier_data[t_tier]["val"] += t_mv_f
                    # Balance-only (t_cost is None): value counts, but 0 unrealized —
                    # excluded from the gain math (was charged at cost=value before).
                    if t_cost is not None:
                        tier_data[t_tier]["unrealized_pl"] += (t_mv_f - t_cost)
                    tier_data[t_tier]["asset_count"] += 1
                if tier_meta_rows or tier_data:
                    tier_table_rows = []
                    for t_name, t_target_pct, _sort in tier_meta_rows:
                        th = tier_data.get(t_name, {"val": 0.0, "unrealized_pl": 0.0, "asset_count": 0})
                        t_val = th["val"]
                        t_cur_pct = t_val / reb_total * 100 if reb_total else 0.0
                        t_drift = t_cur_pct - float(t_target_pct or 0.0)
                        tier_table_rows.append([
                            t_name,
                            self.format_currency(t_val),
                            self.format_pct(t_cur_pct),
                            self.format_pct(t_target_pct),
                            self.format_pct(t_drift),
                            self.format_currency(th["unrealized_pl"]),
                            int(th["asset_count"]),
                        ])
                    lines.append(self.generate_markdown_table(
                        ["Tier", "Value", "Current %", "Target %", "Drift", "Unrealized P&L", "Assets"],
                        tier_table_rows
                    ))
            except Exception as e:
                logger.error(f"Error in section 1.4: {e}")
                lines.append("*Error generating tier data.*")

        except Exception as e:
            logger.error(f"Error evaluating Section 1: {e}")
            lines.append("*Error generating portfolio state*")

        return "\n".join(lines)

    def _section_2_performance(self) -> str:
        lines = ["## 2. Performance Metrics\n"]

        try:
            # 2.1 Overall performance summary — total and rebalanceable breakdown
            perf = self.db.execute(f'''
                WITH {_LATEST_PER_ASSET_CTE}
                SELECT
                    SUM(h.market_value) as net_worth,
                    SUM(CASE WHEN COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE)
                             THEN h.market_value ELSE 0 END) as reb_value,
                    SUM(CASE WHEN NOT COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE)
                             THEN h.market_value ELSE 0 END) as non_reb_value,
                    COUNT(DISTINCT h.asset_id) as asset_count
                FROM holdings h
                JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                WHERE h.is_shadow = FALSE
            ''').fetchone()

            asset_rows = self.db.execute(f'''
                WITH {_LATEST_PER_ASSET_CTE}
                SELECT
                    h.asset_id,
                    COALESCE(parent_tc.name, tc.name, r.asset_class, 'Unclassified') as top_class,
                    SUM(h.market_value) as market_value,
                    SUM(h.quantity) as quantity,
                    MAX(h.cost_price_unit) as cost_price_unit,
                    MAX(h.currency) as currency,
                    COALESCE(MAX(r.asset_class), 'Unclassified') as sub_class,
                    COALESCE(MAX(tc.is_rebalanceable), MAX(r.is_rebalanceable), TRUE) as is_rebalanceable
                FROM holdings h
                JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                LEFT JOIN taxonomy_classes parent_tc ON tc.parent_id = parent_tc.id
                WHERE h.is_shadow = FALSE
                GROUP BY h.asset_id, top_class
            ''').fetchall()
            active_asset_ids = [row[0] for row in asset_rows if row and row[0]]
            active_rebalanceable_ids = {
                row[0]
                for row in asset_rows
                if row and row[0] and bool(row[7])
            } & self._get_rebalanceable_asset_ids()
            tx_asset_rows = self.db.execute("SELECT DISTINCT asset_id FROM transactions").fetchall()
            tx_asset_ids = sorted({row[0] for row in tx_asset_rows if row and row[0]})
            realized_map = self._get_realized_map(tx_asset_ids)

            # Per-asset cost basis from the one P&L engine. Balance-only assets
            # return None (excluded from cost/return denominators — the documented
            # V7.8.3 delta); their market value still counts via measurable_value.
            asset_cost_map: dict[str, Optional[float]] = {}
            total_cost_basis = 0.0
            total_measurable = 0.0
            reb_cost_basis = 0.0
            reb_measurable = 0.0
            for _row in asset_rows:
                if not _row or not _row[0]:
                    continue
                _aid, _top, _mv, _qty, _cpu, _curr, _sub, _ = _row
                _mv_f = float(_mv or 0.0)
                _cost = self._engine_cost(_aid)
                asset_cost_map[_aid] = _cost
                if _cost is not None:
                    total_cost_basis += _cost
                    total_measurable += _mv_f
                    if _aid in active_rebalanceable_ids:
                        reb_cost_basis += _cost
                        reb_measurable += _mv_f

            sold_only_asset_ids = sorted(set(tx_asset_ids) - set(active_asset_ids))
            sold_class_rows: list[tuple[str, str, bool]] = []
            if sold_only_asset_ids:
                placeholders = ",".join(["?"] * len(sold_only_asset_ids))
                sold_class_rows = self.db.execute(
                    f"""
                    SELECT
                        r.canonical_id,
                        COALESCE(parent_tc.name, tc.name, r.asset_class, 'Unclassified') as top_class,
                        COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) as is_rebalanceable
                    FROM asset_registry r
                    LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                    LEFT JOIN taxonomy_classes parent_tc ON tc.parent_id = parent_tc.id
                    WHERE r.canonical_id IN ({placeholders})
                    """,
                    sold_only_asset_ids,
                ).fetchall()
            sold_class_map = {
                row[0]: (row[1], bool(row[2]))
                for row in sold_class_rows
                if row and row[0]
            }
            sold_rebalanceable_ids = {
                aid for aid, (_, is_reb) in sold_class_map.items() if is_reb
            }
            rebalanceable_ids = active_rebalanceable_ids | sold_rebalanceable_ids

            if perf and perf[0] is not None:
                reb_value = float(perf[1] or 0.0)
                cost_basis = total_cost_basis
                reb_cost = reb_cost_basis
                # Unrealized is measurable_value − cost (NOT net_worth − cost): a
                # balance-only asset's value is in net_worth but its unknown cost is
                # not, so it must be excluded from BOTH sides of the gain, else its
                # whole balance would book as phantom profit.
                unrealized_pl = total_measurable - cost_basis
                reb_pl = reb_measurable - reb_cost
                realized_total = sum(realized_map.get(aid, 0.0) for aid in tx_asset_ids)
                realized_reb = sum(realized_map.get(aid, 0.0) for aid in rebalanceable_ids)
                lifetime_total = unrealized_pl + realized_total
                lifetime_reb = reb_pl + realized_reb
                unrealized_ret_reb = reb_pl / reb_cost * 100 if reb_cost > 0 else 0.0
                lifetime_ret = lifetime_total / cost_basis * 100 if cost_basis > 0 else 0.0
                lifetime_ret_reb = lifetime_reb / reb_cost * 100 if reb_cost > 0 else 0.0

                lines.append("### 2.1 Portfolio Performance Summary (investable assets)\n")
                lines.append(self.generate_markdown_table(
                    ["Metric", "Investments", "Notes"],
                    [
                        ["Market Value", self.format_currency(reb_value),
                         "Property and insurance excluded"],
                        ["Cost Basis", self.format_currency(reb_cost), "Acquisition cost (FIFO)"],
                        ["Unrealized P&L", self.format_currency(reb_pl),
                         f"Value of positions with a known cost ({self.format_currency(reb_measurable)}) "
                         "– cost basis; cash and balance-only bonds have no cost and are left out"],
                        ["Realized Gains (incl. sold positions)", self.format_currency(realized_reb),
                         "Closed-lot profits from transactions, including positions since sold"],
                        ["Lifetime P&L", self.format_currency(lifetime_reb), "Unrealized + realized"],
                        ["Unrealized Return", self.format_pct(unrealized_ret_reb), "Unrealized P&L / cost basis"],
                        ["Lifetime Return", self.format_pct(lifetime_ret_reb), "Lifetime P&L / cost basis"],
                    ]
                ))
                lines.append("")

            # 2.2 Per-class performance (rebalanceable-only)
            class_agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
                "market_value": 0.0,
                "cost_basis": 0.0,
                "measurable_value": 0.0,
                "realized": 0.0,
                "count": 0,
            })
            for row in asset_rows:
                if not row or not row[0]:
                    continue
                aid, top_class, mv, _qty, _cpu, _curr, _sub, is_reb = row
                if not is_reb or aid not in rebalanceable_ids:
                    continue
                bucket = class_agg[top_class]
                mv_f = float(mv or 0.0)
                bucket["market_value"] += mv_f
                _cost = asset_cost_map.get(aid)
                # Balance-only (cost None): value shows, but excluded from cost and
                # the unrealized denominator (measurable_value).
                if _cost is not None:
                    bucket["cost_basis"] += _cost
                    bucket["measurable_value"] += mv_f
                bucket["realized"] += float(realized_map.get(aid, 0.0))
                bucket["count"] += 1

            for aid in sold_only_asset_ids:
                top_class, is_reb = sold_class_map.get(aid, ("Unclassified", False))
                if not is_reb:
                    continue
                class_agg[top_class]["realized"] += float(realized_map.get(aid, 0.0))

            if class_agg:
                lines.append("### 2.2 Asset Class Performance\n")
                table_rows = []
                reb_total_mv = sum(v["market_value"] for v in class_agg.values()) or 1.0
                sorted_rows = sorted(
                    class_agg.items(),
                    key=lambda item: item[1]["market_value"],
                    reverse=True,
                )
                for cls, payload in sorted_rows:
                    mv = float(payload["market_value"])
                    cost = float(payload["cost_basis"])
                    measurable = float(payload["measurable_value"])
                    realized = float(payload["realized"])
                    count = int(payload["count"])
                    weight = mv / reb_total_mv * 100
                    # Unrealized over measurable value only (balance-only excluded).
                    unrealized = measurable - cost
                    lifetime = unrealized + realized
                    lifetime_ret = lifetime / cost * 100 if cost > 0 else 0.0
                    table_rows.append([
                        cls,
                        self.format_currency(mv),
                        self.format_pct(weight),
                        self.format_currency(unrealized),
                        self.format_currency(realized),
                        self.format_currency(lifetime),
                        self.format_pct(lifetime_ret),
                        int(count),
                    ])
                lines.append(self.generate_markdown_table(
                    ["Asset Class", "Market Value", "Weight %", "Unrealized P&L",
                     "Realized P&L (incl. sold)", "Lifetime P&L", "Lifetime Return %", "Assets"],
                    table_rows
                ))
                lines.append(
                    "\n*Realized P&L here includes positions since sold. Section 4 shows "
                    "realized P&L for current holdings only, so its class totals are lower.*"
                )

            lines.append("\n### 2.3 Returns & Risk Metrics\n")
            account_returns = build_investment_returns(self.db)
            lines.append(format_account_returns(account_returns))
            try:
                risk = build_investment_risk(self.db, account_result=account_returns)
            except Exception:
                logger.exception("export context risk metrics failed")
                risk = {}
            lines.append(format_account_risk(risk))
            lines.append(self._section_2_4_asset_xirr())

        except Exception as e:
            logger.error(f"Error in section 2: {e}")
            lines.append("*Error generating performance metrics.*")

        return "\n".join(lines)

    def _section_3_market_environment(self) -> str:
        lines = ["## 3. Market Environment\n"]

        lines.append("### 3.0 Market Regime Summary\n")
        try:
            regime = assess_portfolio_regime(self.db)
            if regime:
                lines.append(f"- Trend: {regime.get('trend', 'Unknown')}")
                lines.append(f"- Volatility: {regime.get('volatility_level', 'Unknown')}")
                lines.append(f"- Drawdown: {self.format_pct(regime.get('drawdown_pct'))}")
                lines.append(f"- 3M Momentum: {self.format_pct(regime.get('momentum_3m_pct'))}")
            else:
                lines.append("*Market regime data unavailable — run market data sync.*")
        except Exception as e:
            logger.error(f"Error loading market regime for AI export: {e}")
            lines.append("*Market regime data unavailable — run market data sync.*")

        try:
            rows = self.db.execute(
                "SELECT * FROM market_sentiment_cache ORDER BY section, indicator_key"
            ).fetchall()
            if rows:
                lines.append("\n### 3.1 Market Indicators\n")
                # Columns: indicator_key, section, indicator_name, value, display_value, zone, zone_color, description, raw_json, updated_at
                table_rows = []
                for r in rows:
                    indicator_name = str(r[2])
                    display_value = str(r[4])
                    zone = str(r[5])
                    table_rows.append([indicator_name, display_value, zone])
                lines.append(self.generate_markdown_table(
                    ["Indicator", "Value", "Zone"], table_rows
                ))
                # Last updated
                try:
                    last_updated = str(rows[0][9])[:19] if rows[0][9] else "N/A"
                    lines.append(f"\n*Last refreshed: {last_updated}*")
                except Exception:
                    pass
            else:
                lines.append("*No market sentiment data available. Use the Market Sentiment page to refresh.*")
        except Exception:
            lines.append("*Market sentiment data unavailable.*")

        return "\n".join(lines)

    def _section_4_holdings_detail(self) -> str:
        lines = [
            "## 4. Holdings Details\n",
            "*Realized and Lifetime P&L in this section cover current holdings only; the "
            "Section 2 realized totals also include positions since sold.*\n",
        ]

        try:
            rows = self.db.execute(f'''
                WITH {_LATEST_PER_ASSET_CTE},
                total_mv AS (
                    SELECT SUM(h.market_value) as total
                    FROM holdings h
                    JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                    LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                    LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                    WHERE h.is_shadow = FALSE
                      AND COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) = TRUE
                )
                SELECT
                    COALESCE(h.asset_name, h.asset_id) as name,
                    h.asset_id,
                    COALESCE(parent_tc.name, tc.name, r.asset_class, 'Unclassified') as top_class,
                    COALESCE(tc.name, r.asset_class, 'Unclassified') as sub_class,
                    h.market_value,
                    h.quantity,
                    h.cost_price_unit,
                    h.currency,
                    h.market_value / NULLIF(total_mv.total, 0) * 100 as weight_pct,
                    COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) as is_rebalanceable
                FROM holdings h
                JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
                LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
                LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
                LEFT JOIN taxonomy_classes parent_tc ON tc.parent_id = parent_tc.id
                CROSS JOIN total_mv
                WHERE h.is_shadow = FALSE
                  AND COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) = TRUE
                ORDER BY top_class, sub_class, h.market_value DESC
            ''').fetchall()

            if not rows:
                lines.append("*No holdings data available.*")
                return "\n".join(lines)

            # Group by top_class
            by_class: Dict[str, list] = defaultdict(list)
            for row in rows:
                name, asset_id, top_class, sub_class, mv, qty, cpu, currency, weight, is_rebalanceable = row
                if not bool(is_rebalanceable) or abs(float(mv or 0)) < 1 or qty == 0:
                    continue
                # Engine cost: None for balance-only (excluded from gain math).
                cost = self._engine_cost(asset_id)
                by_class[top_class].append({
                    "name": name,
                    "asset_id": asset_id,
                    "sub_class": sub_class,
                    "mv": float(mv or 0.0),
                    "cost": cost,
                    "weight": float(weight or 0.0),
                })

            total_mv = sum(a["mv"] for assets in by_class.values() for a in assets)
            for assets in by_class.values():
                for asset in assets:
                    asset['weight'] = asset['mv'] / total_mv * 100 if total_mv else 0.0
            all_asset_ids = [a["asset_id"] for assets in by_class.values() for a in assets]
            realized_map = self._get_realized_map(all_asset_ids)

            for top_class, assets in by_class.items():
                class_mv = sum(a["mv"] for a in assets)
                # Balance-only assets (cost None) excluded from cost and the
                # unrealized denominator; their value still counts in class_mv.
                class_cost = sum(a["cost"] for a in assets if a["cost"] is not None)
                class_measurable = sum(a["mv"] for a in assets if a["cost"] is not None)
                class_pl = class_measurable - class_cost
                class_realized = sum(realized_map.get(a["asset_id"], 0.0) for a in assets)
                class_lifetime = class_pl + class_realized
                class_ret = class_lifetime / class_cost * 100 if class_cost >= 1 else None
                class_weight = class_mv / total_mv * 100 if total_mv > 0 else 0.0

                lines.append(f"### {top_class}")
                lines.append(
                    f"*Market Value: {self.format_currency(class_mv)} | "
                    f"Weight: {self.format_pct(class_weight)} | "
                    f"Unrealized: {self.format_currency(class_pl)} | "
                    f"Realized: {self.format_currency(class_realized)} | "
                    f"Lifetime: {self.format_currency(class_lifetime)} ({self.format_pct(class_ret) if class_ret is not None else '—'})*\n"
                )

                table_rows = []
                if _is_cash_like(top_class):
                    cash_realized = sum(realized_map.get(a["asset_id"], 0.0) for a in assets)
                    cash_unrealized = class_mv - class_cost
                    cash_lifetime = cash_unrealized + cash_realized
                    cash_ret = cash_lifetime / class_cost * 100 if class_cost >= 1 else None
                    table_rows.append([
                        "Cash Total",
                        "CASH_TOTAL",
                        "Cash",
                        self.format_currency(class_mv),
                        self.format_currency(class_cost),
                        self.format_currency(cash_unrealized),
                        self.format_currency(cash_realized),
                        self.format_currency(cash_lifetime),
                        self.format_pct(cash_ret) if cash_ret is not None else '—',
                        self.format_pct(class_weight),
                    ])
                else:
                    for a in assets:
                        realized = float(realized_map.get(a["asset_id"], 0.0))
                        if a["cost"] is None:
                            # Balance-only: real value shows, but cost/unrealized/
                            # return are unknown ("—") — no phantom gain. Lifetime needs
                            # unrealized, so it is unknown too, not the realized part.
                            cost_disp = "—"
                            unrealized_disp = "—"
                            lifetime_disp = "—"
                            ret_disp = "—"
                        else:
                            unrealized = a["mv"] - a["cost"]
                            lifetime = unrealized + realized
                            ret_pct = lifetime / a["cost"] * 100 if a["cost"] >= 1 else None
                            cost_disp = self.format_currency(a["cost"])
                            unrealized_disp = self.format_currency(unrealized)
                            lifetime_disp = self.format_currency(lifetime)
                            ret_disp = self.format_pct(ret_pct) if ret_pct is not None else "—"
                        table_rows.append([
                            a["name"] or a["asset_id"],
                            a["asset_id"],
                            a["sub_class"],
                            self.format_currency(a["mv"]),
                            cost_disp,
                            unrealized_disp,
                            self.format_currency(realized),
                            lifetime_disp,
                            ret_disp,
                            self.format_pct(a["weight"]),
                        ])

                if table_rows:
                    lines.append(self.generate_markdown_table(
                        ["Name", "Ticker", "Sub-Class", "Market Value", "Cost Basis",
                         "Unrealized P&L", "Realized P&L", "Lifetime P&L", "Lifetime Return %", "Weight %"],
                        table_rows
                    ))
                lines.append("")

        except Exception as e:
            logger.error(f"Error in section 4: {e}")
            lines.append("*Error generating holdings details.*")

        return "\n".join(lines)
