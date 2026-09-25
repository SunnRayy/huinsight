"""Phase 3c: AI insights lifecycle, Decision Hub bridge, trade_logs, links.

These functions are called by seed_ai.py's seed_all() to write ai_insights
rows spanning every lifecycle stage, bridge them to the Decision Hub (insights
table), apply adoptions, seed trade_logs with owner verdicts, and create
insight_trade_links.
"""
from __future__ import annotations

import json
from typing import Any

from src.database.connector import DatabaseConnector
from src.services.ai_advisor.insight_manager import (
    bridge_ai_insights_to_decision_hub,
    check_promotion_gate,
)
from src.services.decision_links import recompute_auto_links

# Phase 3c ownership marker appended to ai_insights.tags (that table has no
# dedicated source-file column like strategy_memos does) — lets a future
# cleanup tool find "insights this script owns" without relying on title
# text alone, same intent as SOURCE_MARKER.
INSIGHT_TAG_MARKER = "demo-seed:tools/demo_data/seed_ai.py"

# Ownership marker written to strategy_memos.source_file and trade_logs.user_notes
# for every row this script writes/updates.
SOURCE_MARKER = "tools/demo_data/seed_ai.py"


def seed_insights_lifecycle(db: DatabaseConnector, insights: list[dict[str, Any]]) -> dict[str, int]:
    """Idempotent upsert of ai_insights rows spanning every lifecycle stage.

    ai_insights has no natural UNIQUE constraint (id is a bare sequence,
    unlike strategy_memos' (memo_date, title)), so — same approach as
    _seed_sample_report's ai_reports marker lookup — this script's own
    `title` values (fixed, chosen by this file, never overlapping a real
    user's own insight text) ARE the natural key: look up by title, UPDATE
    if found, INSERT if not. INSIGHT_TAG_MARKER is additionally appended to
    `tags` on every write as an explicit ownership marker (ai_insights has no
    source_file-style column to carry one).

    Every row beyond 'raw' is written to already satisfy
    insight_manager.check_promotion_gate(confidence, validated_cases) at its
    OWN current values — the gate is stateless (evaluated fresh on every
    promote_insight() call), so this is what "the UI's own logic agrees with
    the seeded state" means here: calling promote_insight() again on any of
    these rows would succeed for the next step, exactly as it would have to
    have succeeded to reach the current status. Raises AssertionError (never
    silently seeds an inconsistent row) if a non-raw row's fields would fail
    the real gate function.

    Returns {title: ai_insights.id} for every row, so callers can bridge /
    link against the exact ids just written without re-querying.
    """
    ids: dict[str, int] = {}
    for insight in insights:
        status = insight["status"]
        confidence = insight.get("confidence")
        validated_cases = insight.get("validated_cases", 0)
        if status != "raw":
            # Never seed a status the real promote gate would reject at these
            # values — see check_promotion_gate's docstring for the exact
            # raise text this would surface as a 422 via the real API route.
            check_promotion_gate(confidence, validated_cases)

        tags = ",".join(list(insight.get("tags", [])) + [INSIGHT_TAG_MARKER])
        entity_refs = ",".join(insight.get("entity_refs", []))
        validated_case_links = json.dumps(insight.get("validated_case_links", []), ensure_ascii=False)
        created_at = insight["created_at"]
        params = [
            insight.get("source_report_id"),
            insight["category"],
            insight["title"],
            insight["body"],
            tags,
            confidence,
            status,
            insight.get("recurrence_count", 1),
            entity_refs,
            created_at,
            validated_cases,
            validated_case_links,
            insight.get("rule_layer"),
        ]

        existing = db.execute(
            "SELECT id FROM ai_insights WHERE title = ?", [insight["title"]]
        ).fetchone()
        if existing:
            db.execute(
                """
                UPDATE ai_insights
                SET source_report_id = ?, category = ?, body = ?, tags = ?,
                    confidence = ?, status = ?, recurrence_count = ?,
                    entity_refs = ?, created_at = ?, updated_at = CURRENT_TIMESTAMP,
                    validated_cases = ?, validated_case_links = ?, rule_layer = ?
                WHERE id = ?
                """,
                [
                    params[0], params[1], params[3], params[4],
                    params[5], params[6], params[7],
                    params[8], params[9],
                    params[10], params[11], params[12],
                    existing[0],
                ],
            )
            ids[insight["title"]] = existing[0]
        else:
            db.execute(
                """
                INSERT INTO ai_insights (
                    source_report_id, category, title, body, tags, confidence,
                    status, recurrence_count, entity_refs, created_at,
                    updated_at, validated_cases, validated_case_links, rule_layer
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                """,
                params,
            )
            new_id = db.execute(
                "SELECT id FROM ai_insights WHERE title = ?", [insight["title"]]
            ).fetchone()[0]
            ids[insight["title"]] = new_id

    return ids


def apply_insight_adoptions(
    db: DatabaseConnector, adoptions: list[dict[str, Any]], insight_ids: dict[str, int]
) -> int:
    """Set insights.adopted on the Decision Hub bridge row for each named insight.

    Must run AFTER bridge_ai_insights_to_decision_hub — the bridge row is
    keyed on observation_source = 'ai_insights:<id>' (see insight_manager.py
    _upsert_bridge_row). Silently no-ops for a title whose insight never
    qualified for bridging (e.g. category != 'recommendation' and status not
    in recurring/principle) — this script only ever seeds adoptions for
    'recommendation' insights, which always bridge regardless of status, but
    the guard keeps this safe if that changes.
    """
    updated = 0
    for adoption in adoptions:
        insight_id = insight_ids.get(adoption["title"])
        if insight_id is None:
            continue
        observation_source = f"ai_insights:{insight_id}"
        db.execute(
            "UPDATE insights SET adopted = ?, adoption_date = CURRENT_DATE "
            "WHERE observation_source = ?",
            [bool(adoption["adopted"]), observation_source],
        )
        updated += 1
    return updated


def seed_trade_logs(db: DatabaseConnector, trades: list[dict[str, Any]]) -> None:
    """Idempotent upsert of owner-recorded trade_logs rows.

    trade_logs has no natural UNIQUE constraint either — this script's own
    marker (user_notes = SOURCE_MARKER, the same constant strategy_memos uses
    for source_file) combined with (asset_id, log_date, action) is the
    lookup key, matching exactly the rows this script owns without touching
    the 240+ reader-imported rows already in this table (those all carry
    suggestion_source='imported', never this marker).

    outcome_pct is intentionally never written (see ai_seed.yaml trade_logs
    module comment) — every row here sets BOTH verdict and
    verification_result (never verdict alone, satisfying check #19 Rule A)
    and always sets verdict when verification_status='verified' with a
    non-generic suggestion_source (satisfying check #19 Rule B). Leaving
    outcome_pct NULL also keeps every row fully out of score_all_trades'
    rescoring scope is NOT relied upon here (that scope is `verdict IS NULL
    OR outcome_pct IS NULL`, so an outcome_pct-less row COULD be reconsidered
    by a later sync) — but score_all_trades never overwrites an
    already-set verdict (see decision_scorer.py "Never overwrite" guards),
    so re-scoring is a safe no-op either way.
    """
    for trade in trades:
        existing = db.execute(
            """
            SELECT id FROM trade_logs
            WHERE asset_id = ? AND log_date = ? AND action = ? AND user_notes = ?
            """,
            [trade["asset_id"], trade["log_date"], trade["action"], SOURCE_MARKER],
        ).fetchone()

        params = [
            trade["log_date"],
            trade["asset_id"],
            trade.get("asset_name"),
            trade["action"],
            trade.get("price"),
            trade.get("quantity"),
            trade.get("amount"),
            trade.get("decision_reason"),
            trade.get("ai_suggestion"),
            trade.get("suggestion_source"),
            trade.get("verification_date"),
            trade.get("verification_result"),
            trade.get("verdict"),
            trade.get("order_origin"),
            SOURCE_MARKER,
        ]
        # verification_status defaults to 'pending' at the column level;
        # every seeded row here is already owner-verified.
        verification_status = trade.get("verification_status", "verified")

        if existing:
            db.execute(
                """
                UPDATE trade_logs
                SET asset_name = ?, price = ?, quantity = ?, amount = ?,
                    decision_reason = ?, ai_suggestion = ?, suggestion_source = ?,
                    verification_date = ?, verification_result = ?, verdict = ?,
                    order_origin = ?, verification_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [
                    params[2], params[4], params[5], params[6],
                    params[7], params[8], params[9],
                    params[10], params[11], params[12],
                    params[13], verification_status,
                    existing[0],
                ],
            )
        else:
            db.execute(
                """
                INSERT INTO trade_logs (
                    log_date, asset_id, asset_name, action, price, quantity, amount,
                    decision_reason, ai_suggestion, suggestion_source,
                    verification_date, verification_result, verdict, order_origin,
                    user_notes, verification_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params + [verification_status],
            )


def seed_insights_and_trades(db: DatabaseConnector, seed: dict[str, Any]) -> None:
    """Phase 3c orchestration: ai_insights -> Decision Hub bridge -> adoptions
    -> trade_logs -> insight_trade_links.

    Order matters: the bridge must run after ai_insights exist (it reads
    ai_insights), adoptions must run after the bridge (it updates the
    bridged `insights` row), and recompute_auto_links must run after BOTH
    the bridge and trade_logs exist (it joins insights x trade_logs). Every
    step here calls the app's own real function — this script never computes
    a score, a link, or a promotion decision itself.
    """
    insight_ids = seed_insights_lifecycle(db, seed.get("insights_lifecycle", []))
    bridge_ai_insights_to_decision_hub(db)
    apply_insight_adoptions(db, seed.get("insight_adoptions", []), insight_ids)
    seed_trade_logs(db, seed.get("trade_logs", []))
    recompute_auto_links(db)
