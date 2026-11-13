"""Tests for tools/demo_data/seed_ai_reports.py (Phase 3b sample reports).

Tests for sample brief and review writing to ai_reports with demo-sample marker.
"""
from __future__ import annotations

import json

from src.database.connector import DatabaseConnector
from src.services.ai_advisor.section_ids import (
    BRIEF_SECTION_IDS,
    REVIEW_SECTION_IDS,
    adapt_stored_content_json,
)
from tools.demo_data.seed_ai import DEMO_SAMPLE_MODEL_MARKER, run
from tests.tools.conftest import _make_db, _insert_demo_marker_holding


class TestSampleReports:
    """Phase 3b: ONE sample daily Brief and ONE sample completed Review,
    written to ai_reports with model_used = DEMO_SAMPLE_MODEL_MARKER so the
    frontend can badge them as samples without any API change."""

    def test_writes_exactly_one_sample_brief_and_one_sample_review(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            rows = verify.execute(
                "SELECT report_type, title, model_used, content_json, content_markdown, "
                "period_start, period_end FROM ai_reports WHERE model_used = ?",
                [DEMO_SAMPLE_MODEL_MARKER],
            ).fetchall()
        finally:
            verify.close()

        by_type = {r[0]: r for r in rows}
        assert set(by_type.keys()) == {"brief", "review"}

        brief_row = by_type["brief"]
        assert brief_row[1]  # title
        assert brief_row[4]  # content_markdown non-empty
        brief_content = json.loads(brief_row[3])
        assert set(brief_content.keys()) == set(BRIEF_SECTION_IDS)

        review_row = by_type["review"]
        assert review_row[1]  # title
        assert review_row[5] and review_row[6]  # period_start / period_end
        review_content = json.loads(review_row[3])
        assert set(review_content.keys()) == set(REVIEW_SECTION_IDS)

    def test_sample_content_json_passes_the_api_read_time_adapter(self, tmp_path):
        """The API's read sites (GET /brief/latest, /review/latest, etc.) run
        every stored content_json through adapt_stored_content_json before
        returning it. A seeded row must survive that adapter with every
        section key and enum value intact — this is what actually makes the
        existing UI render every section, not just the raw dict shape."""
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            rows = verify.execute(
                "SELECT report_type, content_json FROM ai_reports WHERE model_used = ?",
                [DEMO_SAMPLE_MODEL_MARKER],
            ).fetchall()
        finally:
            verify.close()

        by_type = {r[0]: json.loads(r[1]) for r in rows}

        adapted_brief = adapt_stored_content_json(by_type["brief"])
        assert set(adapted_brief.keys()) == set(BRIEF_SECTION_IDS)
        for status in (p["status"] for p in adapted_brief["holdings_risk"]["positions"]):
            assert status in ("hold", "watch", "alert")
        for action in (a["action"] for a in adapted_brief["action_items"]["actions"]):
            assert action in ("buy", "sell", "hold")

        adapted_review = adapt_stored_content_json(by_type["review"])
        assert set(adapted_review.keys()) == set(REVIEW_SECTION_IDS)
        for tier in (s["accuracy_tier"] for s in adapted_review["advice_accuracy"]["scorecard"]):
            assert tier in ("high", "medium", "low")

    def test_idempotent_rerun_same_ai_reports_row_ids(self, tmp_path):
        """Re-running must UPDATE the same two rows, not insert duplicates —
        ai_reports has no unique constraint, so this is the only thing
        stopping every reseed from growing the table."""
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0
        verify1 = DatabaseConnector(db_path, read_only=True)
        try:
            ids_first = verify1.execute(
                "SELECT report_type, id FROM ai_reports WHERE model_used = ? ORDER BY report_type",
                [DEMO_SAMPLE_MODEL_MARKER],
            ).fetchall()
            total_first = verify1.execute("SELECT COUNT(*) FROM ai_reports").fetchone()[0]
        finally:
            verify1.close()

        assert run(db_path, dry_run=False) == 0
        verify2 = DatabaseConnector(db_path, read_only=True)
        try:
            ids_second = verify2.execute(
                "SELECT report_type, id FROM ai_reports WHERE model_used = ? ORDER BY report_type",
                [DEMO_SAMPLE_MODEL_MARKER],
            ).fetchall()
            total_second = verify2.execute("SELECT COUNT(*) FROM ai_reports").fetchone()[0]
        finally:
            verify2.close()

        assert ids_first == ids_second
        assert len(ids_first) == 2
        assert total_first == total_second == 2

    def test_does_not_touch_a_real_generated_report(self, tmp_path):
        """A real (non-sample) ai_reports row must be untouched by reseeding —
        the marker is model_used = 'demo-sample', which a real LLM call never
        writes."""
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.execute(
            """
            INSERT INTO ai_reports (report_type, title, content_json, model_used)
            VALUES ('brief', 'Real generated brief', '{"macro_outlook": {"narrative": "real"}}',
                    'gemini/gemini-2.5-flash')
            """
        )
        real_id = connector.execute(
            "SELECT id FROM ai_reports WHERE model_used = 'gemini/gemini-2.5-flash'"
        ).fetchone()[0]
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            real_row = verify.execute(
                "SELECT title, model_used FROM ai_reports WHERE id = ?", [real_id]
            ).fetchone()
            total = verify.execute("SELECT COUNT(*) FROM ai_reports").fetchone()[0]
        finally:
            verify.close()

        assert real_row == ("Real generated brief", "gemini/gemini-2.5-flash")
        assert total == 3  # the real row + the 2 seeded sample rows
