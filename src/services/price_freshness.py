"""How much of the headline net worth rests on live prices.

The dashboard's net worth sums the latest holdings rows. For market-priced
sources those rows are repriced by the live refresh; when the refresh fails
(no network, provider outage) they keep the price from the source file, which
can be months old. The total then moves for reasons that have nothing to do
with the portfolio, and nothing on the card says so. This module measures
that dependence so the UI can mark the number degraded (AGENTS.md Rule 22,
staleness obligation).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

# Sources whose holdings are expected to be repriced by the live refresh.
MARKET_PRICED_SOURCES = ("Schwab_CSV", "Broker_IBKR", "CN_Fund_Excel", "Gold_Excel", "RSU_Excel", "Consolidated")

# price_source values that mean "not priced by a live provider".
_NOT_LIVE_PRICE_SOURCES = ("file", "financial_summary", "consolidated")

# Share of market-priced value at non-live prices above which the number is degraded.
UNPRICED_SHARE_THRESHOLD = 0.2

# A live price older than this is stale (covers weekends and QDII T+2 lag).
STALE_AFTER_DAYS = 5


def compute_price_freshness(db: Any, now: Optional[datetime] = None) -> dict[str, Any]:
    """Summarize live-price coverage of current market-priced holdings.

    Returns ``status``:
      - ``"fresh"``: live-priced, newest price within STALE_AFTER_DAYS
      - ``"stale"``: live-priced, but the newest price is older than that
      - ``"unpriced"``: at least UNPRICED_SHARE_THRESHOLD of the value was
        never live-priced (the refresh failed or never ran)
      - ``"none"``: no market-priced holdings to judge
    """
    now = now or datetime.now()
    sources = ", ".join(f"'{s}'" for s in MARKET_PRICED_SOURCES)
    not_live = ", ".join(f"'{s}'" for s in _NOT_LIVE_PRICE_SOURCES)
    row = db.execute(
        f"""
        WITH latest AS (
            SELECT asset_id, source_system, MAX(snapshot_date) AS d
            FROM holdings WHERE is_shadow = FALSE
            GROUP BY asset_id, source_system
        )
        SELECT
            COALESCE(SUM(ABS(h.market_value)), 0),
            COALESCE(SUM(CASE WHEN h.price_source IS NULL OR h.price_source IN ({not_live})
                              THEN ABS(h.market_value) ELSE 0 END), 0),
            SUM(CASE WHEN h.price_source IS NULL OR h.price_source IN ({not_live}) THEN 1 ELSE 0 END),
            COUNT(*),
            MAX(h.price_updated_at)
        FROM holdings h
        JOIN latest l ON h.asset_id = l.asset_id AND h.source_system = l.source_system AND h.snapshot_date = l.d
        WHERE h.is_shadow = FALSE
          AND h.source_system IN ({sources})
          AND COALESCE(h.quantity, 0) <> 0
          -- Consolidated rows inherit their brokers' pricing; count them only when live-priced.
          AND NOT (h.source_system = 'Consolidated' AND COALESCE(h.price_source, '') = 'consolidated')
        """
    ).fetchone()

    total_value = float(row[0] or 0.0)
    unpriced_value = float(row[1] or 0.0)
    unpriced_count = int(row[2] or 0)
    holding_count = int(row[3] or 0)
    last_price_at = row[4]

    if holding_count == 0 or total_value <= 0:
        status = "none"
        unpriced_share = 0.0
    else:
        unpriced_share = unpriced_value / total_value
        if unpriced_share >= UNPRICED_SHARE_THRESHOLD:
            status = "unpriced"
        elif last_price_at is None or last_price_at < now - timedelta(days=STALE_AFTER_DAYS):
            status = "stale"
        else:
            status = "fresh"

    return {
        "status": status,
        "unpriced_share": round(unpriced_share, 4),
        "unpriced_count": unpriced_count,
        "holding_count": holding_count,
        "last_price_at": last_price_at.isoformat() if last_price_at is not None else None,
    }
