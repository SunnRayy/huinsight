"""Tests for tools/demo_data/seed_ai_insights.py (Phase 3c insights/trades/links).

Tests for AI insights lifecycle, Decision Hub bridge, trade logs, and insight_trade_links.
"""
from __future__ import annotations

import re

from src.database.connector import DatabaseConnector
from src.services.ai_advisor.insight_manager import (
    PROMOTE_MIN_CONFIDENCE,
    PROMOTE_MIN_VALIDATED_CASES,
    STATUS_ORDER,
    check_promotion_gate,
)
from src.validation.data_integrity_gate import (
    _check_insight_trade_links_no_orphans,
    _check_trade_log_verdict_consistency,
)
from tools.demo_data.seed_ai import (
    INSIGHT_TAG_MARKER,
    SOURCE_MARKER,
    load_seed,
    run,
)
from tests.tools.conftest import _make_db, _insert_demo_marker_holding, _table_counts


class TestSeedFileHasPhase3cShape:
    """Phase 3c: ai_seed.yaml must carry insights_lifecycle / insight_adoptions /
    trade_logs alongside the Phase 3a/3b keys already covered above."""

    def test_insights_lifecycle_spans_every_stage(self):
        seed = load_seed()
        insights = seed["insights_lifecycle"]
        assert 6 <= len(insights) <= 8
        statuses = {i["status"] for i in insights}
        assert statuses == set(STATUS_ORDER), (
            f"expected every lifecycle stage {STATUS_ORDER}, got {sorted(statuses)}"
        )
        for insight in insights:
            assert insight["title"]
            assert insight["body"]
            assert insight["category"]
            assert insight["entity_refs"], "every seeded insight must reference a real asset"

    def test_non_raw_insights_satisfy_the_real_promotion_gate(self):
        """Every insight beyond 'raw' must already clear
        insight_manager.check_promotion_gate at its own seeded
        confidence/validated_cases — otherwise the seeded status would be
        something promote_insight() itself could never have produced."""
        seed = load_seed()
        for insight in seed["insights_lifecycle"]:
            if insight["status"] == "raw":
                continue
            # Must not raise.
            check_promotion_gate(insight.get("confidence"), insight.get("validated_cases", 0))
            passes_confidence = (insight.get("confidence") or 0) >= PROMOTE_MIN_CONFIDENCE
            passes_cases = (insight.get("validated_cases") or 0) >= PROMOTE_MIN_VALIDATED_CASES
            assert passes_confidence or passes_cases

    def test_trade_logs_verification_result_has_no_percent_literal(self):
        """decision_scorer.compute_outcome_pct_from_text greedily extracts the
        first r'([+-]?\\d+\\.?\\d*)%' match from verification_result as a
        real numeric outcome (its narrative-fallback path, run automatically
        by score_all_trades on every GET /decisions/scorecard). A seeded
        narrative that happens to mention an unrelated percentage (e.g. "back
        inside the 20% cap") would silently get outcome_pct=20.0 written by
        the app's own scorer — a real side effect, not fabricated by this
        seeder, but still a nonsense number this seeder can trivially avoid
        by never writing a bare N% token into verification_result."""
        seed = load_seed()
        for trade in seed["trade_logs"]:
            result = trade.get("verification_result") or ""
            assert not re.search(r"[+-]?\d+\.?\d*%", result), (
                f"{trade['asset_id']}/{trade['log_date']} verification_result "
                f"contains a percent literal that score_all_trades would "
                f"misread as a real outcome_pct: {result!r}"
            )

    def test_trade_logs_never_pair_bare_verdict_without_verification_result(self):
        """Doctrine/Rule-A pre-check at the source-of-truth level: catches a
        content mistake in the yaml before it ever reaches the DB."""
        seed = load_seed()
        for trade in seed["trade_logs"]:
            if trade.get("verdict"):
                assert trade.get("verification_result"), (
                    f"trade {trade['asset_id']}/{trade['log_date']} has a verdict "
                    "but no verification_result (would violate check #19 Rule A)"
                )


class TestInsightLifecycleSeeding:
    def test_seeds_insights_at_every_lifecycle_stage(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            rows = verify.execute(
                "SELECT status, confidence, validated_cases, tags FROM ai_insights"
            ).fetchall()
        finally:
            verify.close()

        assert len(rows) >= 6
        statuses = {r[0] for r in rows}
        assert statuses == set(STATUS_ORDER)
        for status, confidence, validated_cases, tags in rows:
            assert INSIGHT_TAG_MARKER in tags
            if status != "raw":
                check_promotion_gate(confidence, validated_cases)  # must not raise

    def test_bridges_recommendation_and_governed_insights_into_decision_hub(self, tmp_path):
        """category='recommendation' bridges regardless of status (raw included);
        recurring/principle non-recommendations bridge as category='lesson'."""
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            bridged = verify.execute(
                "SELECT observation_source, category, adopted FROM insights ORDER BY id"
            ).fetchall()
        finally:
            verify.close()

        assert len(bridged) >= 4
        categories = {row[1] for row in bridged}
        assert "recommendation" in categories
        # At least one adopted, at least one still pending (adopted IS NULL) —
        # a real funnel, not an all-or-nothing demo.
        adopted_flags = [row[2] for row in bridged]
        assert True in adopted_flags
        assert any(flag is None for flag in adopted_flags)

    def test_idempotent_rerun_same_ai_insights_ids_and_bridge_rows(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0
        verify1 = DatabaseConnector(db_path, read_only=True)
        try:
            ids_first = verify1.execute(
                "SELECT id, title FROM ai_insights ORDER BY title"
            ).fetchall()
            counts_first = _table_counts(verify1)
        finally:
            verify1.close()

        assert run(db_path, dry_run=False) == 0
        verify2 = DatabaseConnector(db_path, read_only=True)
        try:
            ids_second = verify2.execute(
                "SELECT id, title FROM ai_insights ORDER BY title"
            ).fetchall()
            counts_second = _table_counts(verify2)
        finally:
            verify2.close()

        assert ids_first == ids_second
        assert counts_first == counts_second


class TestTradeLogsAndLinks:
    def test_seeds_owner_recorded_trades_with_verdicts(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            rows = verify.execute(
                """
                SELECT asset_id, verdict, verification_result, verification_status,
                       suggestion_source, user_notes
                FROM trade_logs WHERE user_notes = ?
                """,
                [SOURCE_MARKER],
            ).fetchall()
        finally:
            verify.close()

        assert len(rows) >= 3
        for asset_id, verdict, verification_result, status, source, user_notes in rows:
            assert verdict, f"{asset_id} row must carry a verdict"
            assert verification_result, f"{asset_id} row must carry verification_result (Rule A)"
            assert status == "verified"
            assert source not in (None, "", "imported"), "must be owner-recorded, not reader-imported"

    def test_never_touches_the_reader_imported_trade_logs(self, tmp_path):
        """Sanity: seeding must not perturb pre-existing reader-imported rows
        (suggestion_source='imported', verdict=NULL by design — Rule B carve-out)."""
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.execute(
            """
            INSERT INTO trade_logs (log_date, asset_id, action, suggestion_source, verification_status)
            VALUES (DATE '2026-05-01', 'US_STK_VOO', 'Buy', 'imported', 'verified')
            """
        )
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            imported_row = verify.execute(
                "SELECT verdict, verification_status FROM trade_logs WHERE suggestion_source = 'imported'"
            ).fetchone()
        finally:
            verify.close()
        assert imported_row == (None, "verified")

    def test_creates_non_orphaned_insight_trade_links(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            links = verify.execute("SELECT insight_id, trade_id, link_type FROM insight_trade_links").fetchall()
            insight_ids = {row[0] for row in verify.execute("SELECT id FROM insights").fetchall()}
            trade_ids = {row[0] for row in verify.execute("SELECT id FROM trade_logs").fetchall()}
        finally:
            verify.close()

        assert len(links) >= 1
        for insight_id, trade_id, link_type in links:
            assert insight_id in insight_ids
            assert trade_id in trade_ids
            assert link_type == "auto_source"

    def test_idempotent_rerun_same_trade_logs_and_link_counts(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0
        verify1 = DatabaseConnector(db_path, read_only=True)
        try:
            counts_first = _table_counts(verify1)
        finally:
            verify1.close()

        assert run(db_path, dry_run=False) == 0
        verify2 = DatabaseConnector(db_path, read_only=True)
        try:
            counts_second = _table_counts(verify2)
        finally:
            verify2.close()

        assert counts_first == counts_second
        assert counts_first["trade_logs"] >= 3
        assert counts_first["insight_trade_links"] >= 1


class TestIntegrityGateAgreesWithSeededState:
    """Phase 3c must never trip check #19 (trade_log_verdict_consistency) or
    check #20 (insight_trade_links_no_orphans) — run the REAL check functions
    from src/validation/data_integrity_gate.py against the seeded temp DB,
    not a reimplementation of their rules."""

    def test_trade_log_verdict_consistency_passes(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()
        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            result = _check_trade_log_verdict_consistency(verify)
        finally:
            verify.close()
        assert result.passed, result.details

    def test_insight_trade_links_no_orphans_passes(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()
        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            result = _check_insight_trade_links_no_orphans(verify)
        finally:
            verify.close()
        assert result.passed, result.details

    def test_integrity_checks_still_pass_after_a_second_seed_run(self, tmp_path):
        """Rerunning must not accumulate violations (e.g. duplicate bridge
        rows, duplicate links, or a second copy of a trade_logs row)."""
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()
        assert run(db_path, dry_run=False) == 0
        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            verdict_result = _check_trade_log_verdict_consistency(verify)
            links_result = _check_insight_trade_links_no_orphans(verify)
        finally:
            verify.close()
        assert verdict_result.passed, verdict_result.details
        assert links_result.passed, links_result.details
