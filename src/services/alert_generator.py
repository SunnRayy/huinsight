"""
Alert generator — produces strategy-aware action items for the Action Inbox.
Runs on-demand (not every sync — keeps it lightweight).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List, Dict

from src.database.connector import DatabaseConnector

logger = logging.getLogger(__name__)


def generate_alerts(db: DatabaseConnector) -> List[Dict]:
    """
    Generate strategy-aware alerts.
    Returns list of {category, priority, title, message, data} dicts.
    Categories: drift | strategy | verification | trading
    Priorities: high | medium | low
    """
    alerts = []
    today = date.today()

    # 1. Allocation drift: drifted >5% from strategic target, falling back to the
    # active risk profile scope when there are no Strategic_Profile targets.
    #
    # Round 5 finding #8: migration V193 seeds `risk_profile_allocations` (the
    # active risk profile) on every install, but `target_allocations WHERE
    # source='Strategic_Profile'` only has rows in the owner's hand-curated DB.
    # Reading only `target_scope_alignment` therefore made every non-owner
    # install report zero drift alerts structurally -- not because nothing had
    # drifted, but because there was nothing to compare against. Fall back to
    # `uis_scope_alignment` (the risk-profile scope) so a fresh install can
    # still detect real drift, and be honest in the title about which basis
    # produced the number. See `drift_basis()` for the scope-selection logic
    # exposed to callers (GET /decisions/stats) so a truly targetless DB can
    # say so instead of silently showing 0.
    try:
        from src.services.strategy_reviewer import review_allocation_alignment
        alignment = review_allocation_alignment(db)
        strategic_scope = alignment.get("target_scope_alignment", {})
        risk_profile_scope = alignment.get("uis_scope_alignment", {})

        if strategic_scope:
            scope, basis, basis_phrase = strategic_scope, "strategic", "strategic target"
        elif risk_profile_scope:
            scope, basis, basis_phrase = risk_profile_scope, "risk_profile", "your risk-profile target"
        else:
            scope, basis, basis_phrase = {}, None, None

        if basis:
            for cls, data in scope.items():
                if data.get('status') == 'drifting' and data.get('drift_pct') is not None:
                    drift = abs(data['drift_pct'])
                    if drift > 5:
                        alerts.append({
                            "category": "drift",
                            "priority": "high" if drift > 10 else "medium",
                            "title": f"{cls} allocation drifted {drift:.1f}% from {basis_phrase}",
                            "message": f"Current: {data['actual_pct']:.1f}% | Target: {data['target_pct']:.1f}%",
                            "data": {"asset_class": cls, "drift_pct": drift, "basis": basis},
                        })
    except Exception as e:
        logger.warning(f"Alert generation: allocation drift check failed: {e}")

    # 2. Verification deadlines approaching (within 7 days)
    try:
        upcoming = db.execute("""
            SELECT asset_id, asset_name, log_date, verification_date, action
            FROM trade_logs
            WHERE verification_date IS NOT NULL
              AND verification_result IS NULL
              AND verification_date BETWEEN ? AND ?
            ORDER BY verification_date ASC
        """, (today, today + timedelta(days=7))).fetchall()

        for row in upcoming:
            days_left = (row[3] - today).days
            alerts.append({
                "category": "verification",
                "priority": "high" if days_left <= 3 else "medium",
                "title": f"Verification due in {days_left}d: {row[4]} {row[0]}",
                "message": f"Trade on {row[2]} needs verification by {row[3]}",
                "data": {"asset_id": row[0], "verification_date": str(row[3])},
            })
    except Exception as e:
        logger.warning(f"Alert generation: verification deadline check failed: {e}")

    # 3. High trading frequency alert
    try:
        cutoff_30d = today - timedelta(days=30)
        count_30d = db.execute(
            "SELECT COUNT(*) FROM trade_logs WHERE log_date >= ?", (cutoff_30d,)
        ).fetchone()[0]
        if count_30d > 8:
            alerts.append({
                "category": "trading",
                "priority": "medium",
                "title": f"High trading frequency: {count_30d} trades in 30 days",
                "message": "Long-term hold philosophy suggests <4 trades/month. Review if momentum trading is creeping in.",
                "data": {"count_30d": count_30d},
            })
    except Exception as e:
        logger.warning(f"Alert generation: trading frequency check failed: {e}")

    # 4. Strategy memos with pending directives (last 30 days)
    try:
        recent_memos = db.execute("""
            SELECT id, memo_date, title, key_directives
            FROM strategy_memos
            WHERE memo_date >= ?
            ORDER BY memo_date DESC LIMIT 3
        """, (today - timedelta(days=30),)).fetchall()

        import json
        for memo in recent_memos:
            directives = json.loads(memo[3]) if memo[3] else []
            if directives:
                alerts.append({
                    "category": "strategy",
                    "priority": "low",
                    "title": f"Strategy memo: {memo[2][:60]}",
                    "message": f"Key directive: {directives[0][:120]}" if directives else "Review strategy memo",
                    "data": {"memo_id": memo[0], "date": str(memo[1])},
                })
    except Exception as e:
        logger.warning(f"Alert generation: strategy memo check failed: {e}")

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda x: priority_order.get(x["priority"], 3))

    return alerts


def drift_basis(db: DatabaseConnector) -> str | None:
    """Which allocation-target scope `generate_alerts()` used (or would use) for
    its drift section: 'strategic' (target_allocations WHERE source=
    'Strategic_Profile' has rows -- the owner's DB), 'risk_profile' (no
    strategic targets, but the active risk profile has them -- every fresh
    install after V193), or None when neither scope has any targets, meaning
    drift is not measurable at all.

    Exists so callers (GET /decisions/stats) can tell a genuine "0 drift
    alerts, checked against your risk-profile targets" apart from "0 because
    there is nothing to compare against" -- generate_alerts() itself can't
    express that distinction through its list-of-alerts return type.
    """
    try:
        from src.services.strategy_reviewer import review_allocation_alignment
        alignment = review_allocation_alignment(db)
        if alignment.get("target_scope_alignment"):
            return "strategic"
        if alignment.get("uis_scope_alignment"):
            return "risk_profile"
        return None
    except Exception as e:
        logger.warning(f"drift_basis check failed: {e}")
        return None
