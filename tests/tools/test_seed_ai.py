"""Tests for tools/demo_data/seed_ai.py (Round 5 finding #3, Phase 3a only).

Tests for module docstring, constants/markers, load_seed, has_demo_marker,
describe_seed, dry-run plumbing, and profile + strategy memo + memo_registry
writers. Also validates YAML structure checks (Phase 3b/3c keys present).

All tests use tmp_path — never the production DB (AGENTS.md / CLAUDE.md DB
Safety rules). Each test builds a minimal schema + a synthetic
`holdings.account = 'IBKR_U0000123'` row to stand in for a real demo sync,
since running the full generator/sync pipeline is out of scope for a unit
test here (that's covered separately by the end-to-end dry check against the
scratch demo DB).
"""
from __future__ import annotations

import json

from src.database.connector import DatabaseConnector
from src.services.ai_advisor.section_ids import (
    BRIEF_SECTION_IDS,
    REVIEW_SECTION_IDS,
)
from tools.demo_data.seed_ai import (
    SOURCE_MARKER,
    has_demo_marker,
    load_seed,
    run,
)
from tests.tools.conftest import _make_db, _insert_demo_marker_holding, _table_counts


class TestSeedFileLoads:
    def test_ai_seed_yaml_loads_and_has_required_shape(self):
        seed = load_seed()
        assert "goal" in seed["investor_profile"]["philosophy"]
        assert "horizon" in seed["investor_profile"]["philosophy"]
        assert "risk_tolerance" in seed["investor_profile"]["philosophy"]
        assert "core_weakness" in seed["investor_profile"]["philosophy"]
        assert "portfolio_structure" in seed["investor_profile"]["philosophy"]
        assert len(seed["strategy_memos"]) in (2, 3)
        for memo in seed["strategy_memos"]:
            assert memo["memo_date"]
            assert memo["title"]
            assert memo["strategic_bias"] in ("defensive", "offensive", "neutral")

    def test_sample_brief_and_review_present_with_all_contract_sections(self):
        """Phase 3b: sample_brief/sample_review must be present and their
        content_json must carry every stable section ID the real generator's
        JSON contract requires (src/services/ai_advisor/prompts.py), so the
        existing UI (BriefSection.tsx / ReviewFlow.tsx) renders every section
        with no code change."""
        seed = load_seed()
        assert seed["sample_brief"]["title"]
        assert set(seed["sample_brief"]["content_json"].keys()) == set(BRIEF_SECTION_IDS)

        assert seed["sample_review"]["title"]
        assert seed["sample_review"]["period_start"]
        assert seed["sample_review"]["period_end"]
        assert set(seed["sample_review"]["content_json"].keys()) == set(REVIEW_SECTION_IDS)

    def test_sample_content_avoids_specific_live_market_numbers(self):
        """Doctrine check (AGENTS.md Core Doctrine): a sample must never
        present a fabricated value as a real measurement. The brief's
        holdings/risk narrative should hedge with "as of the demo snapshot"
        rather than assert a live reading."""
        seed = load_seed()
        holdings_risk_narrative = seed["sample_brief"]["content_json"]["holdings_risk"]["narrative"]
        assert "as of the demo snapshot" in holdings_risk_narrative.lower()


class TestSafetyGuard:
    def test_refuses_without_marker(self, tmp_path):
        """No demo marker present -> refuses, exit non-zero, writes nothing."""
        connector, db_path = _make_db(tmp_path)
        connector.close()

        exit_code = run(db_path, dry_run=False)
        assert exit_code != 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            profile_rows = verify.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0]
            memo_rows = verify.execute("SELECT COUNT(*) FROM strategy_memos").fetchone()[0]
        finally:
            verify.close()
        assert profile_rows == 0
        assert memo_rows == 0

    def test_refuses_on_missing_db(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.duckdb")
        assert has_demo_marker(missing) is False

    def test_has_demo_marker_true_when_present(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()
        assert has_demo_marker(db_path) is True

    def test_dry_run_writes_nothing_even_with_marker(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        exit_code = run(db_path, dry_run=True)
        assert exit_code == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            profile_rows = verify.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0]
            memo_rows = verify.execute("SELECT COUNT(*) FROM strategy_memos").fetchone()[0]
        finally:
            verify.close()
        assert profile_rows == 0
        assert memo_rows == 0


class TestSeeding:
    def test_seed_all_writes_profile_and_memos(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()  # run() opens its own connections; DuckDB forbids mixed-mode concurrent opens

        exit_code = run(db_path, dry_run=False)
        assert exit_code == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            profile = verify.execute(
                "SELECT display_name, philosophy, language FROM user_profile WHERE id = 1"
            ).fetchone()
            assert profile is not None
            display_name, philosophy_json, language = profile
            assert display_name
            assert language == "en"
            philosophy = json.loads(philosophy_json)
            for key in ("goal", "horizon", "risk_tolerance", "core_weakness", "portfolio_structure"):
                assert philosophy.get(key), f"philosophy.{key} must be non-empty"

            memos = verify.execute(
                "SELECT title, content, key_directives, source_file FROM strategy_memos"
            ).fetchall()
            assert len(memos) >= 2
            for title, content, key_directives, source_file in memos:
                assert content
                assert source_file == SOURCE_MARKER
                assert json.loads(key_directives)

            registry_count = verify.execute("SELECT COUNT(*) FROM memo_registry").fetchone()[0]
            map_count = verify.execute("SELECT COUNT(*) FROM memo_asset_map").fetchone()[0]
            assert registry_count >= 1
            assert map_count >= 1
        finally:
            verify.close()

    def test_falsification_memo_exists(self, tmp_path):
        """One memo must contain explicit falsification conditions the
        Value-Trap Review feature could cite (src/api/routes/value_trap.py)."""
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()
        run(db_path, dry_run=False)

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            rows = verify.execute(
                "SELECT content, key_directives FROM strategy_memos WHERE content ILIKE '%falsif%'"
            ).fetchall()
            assert rows, "expected at least one strategy memo with explicit falsification conditions"
            content, key_directives_json = rows[0]
            directives = json.loads(key_directives_json)
            assert any("falsif" in d.lower() for d in directives)
            # Falsification-evidence discipline mirrored from value_trap.py:
            # price decline / unrealized loss must be explicitly ruled out.
            assert "price decline" in content.lower() or "unrealized loss" in content.lower()

            registry_row = verify.execute(
                "SELECT falsification_summary FROM memo_registry "
                "WHERE falsification_summary ILIKE '%falsif%' OR falsification_summary IS NOT NULL "
                "ORDER BY memo_id LIMIT 1"
            ).fetchone()
            assert registry_row is not None and registry_row[0]
        finally:
            verify.close()

    def test_idempotent_rerun_same_row_counts(self, tmp_path):
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
        assert counts_first["user_profile"] == 1
        assert counts_first["strategy_memos"] >= 2

    def test_seed_all_never_touches_unrelated_holdings_rows(self, tmp_path):
        """Sanity: seeding profile/memos must not mutate the holdings table
        used only for the marker check."""
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        before = connector.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
        connector.close()

        run(db_path, dry_run=False)

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            after = verify.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
        finally:
            verify.close()
        assert before == after == 1




class TestRound6PersonaConsistency:
    """Round 6: the demo persona has to agree with itself on screen."""

    def test_seeds_one_active_retirement_goal_the_forecast_resolves(self, tmp_path):
        """#2: Your Path read a ¥20M config fallback because the demo had no
        active retirement goal; the seeded one must be what the resolver picks."""
        from src.services.goal_resolver import resolve_north_star_goal

        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False) == 0
        assert run(db_path, dry_run=False) == 0  # idempotent: still one row

        seed_goal = load_seed()["retirement_goal"]
        verify = DatabaseConnector(db_path, read_only=True)
        try:
            rows = verify.execute(
                "SELECT name, goal_type, status FROM goals"
            ).fetchall()
            resolved = resolve_north_star_goal(verify)
        finally:
            verify.close()
        assert rows == [(seed_goal["name"], "retirement", "active")]
        assert resolved["source"] == "goals"
        assert resolved["fallback_reason"] is None
        assert resolved["target_amount"] == float(seed_goal["target_amount"])
        assert resolved["target_date"] == seed_goal["target_date"]

    def test_never_touches_a_goal_the_user_created(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.execute(
            """
            INSERT INTO goals (name, target_amount, target_date, goal_type, status, notes)
            VALUES ('My own goal', 123456, DATE '2031-01-01', 'retirement', 'active', 'mine')
            """
        )
        connector.close()

        assert run(db_path, dry_run=False) == 0

        verify = DatabaseConnector(db_path, read_only=True)
        try:
            mine = verify.execute(
                "SELECT target_amount, target_date, notes FROM goals WHERE name = 'My own goal'"
            ).fetchall()
            total = verify.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
        finally:
            verify.close()
        assert [(float(a), str(d), n) for a, d, n in mine] == [(123456.0, "2031-01-01", "mine")]
        assert total == 2

    def test_profile_goal_names_the_seeded_target(self):
        seed = load_seed()
        goal_text = seed["investor_profile"]["philosophy"]["goal"]
        target_m = seed["retirement_goal"]["target_amount"] / 1_000_000
        assert f"CNY {target_m:g}M" in goal_text
        assert seed["retirement_goal"]["target_date"][:4] in goal_text

    def test_samples_reconcile_the_risk_profile_drift(self):
        """#1: on a fresh demo the drift alerts flag Equity HIGH against the
        active risk profile. The samples must say so and explain the call,
        never claim that nothing has drifted."""
        seed = load_seed()
        brief = seed["sample_brief"]["content_json"]
        review = seed["sample_review"]["content_json"]

        assert any("risk profile" in item["description"] for item in brief["risk_alerts"]["items"])
        us_core_action = next(a for a in brief["action_items"]["actions"] if a["asset"] == "US core index sleeve")
        assert "risk profile" in us_core_action["reasoning"]

        us_core_grade = next(
            s for s in review["advice_accuracy"]["scorecard"] if s["decision"].startswith("Hold the US core sleeve")
        )
        assert us_core_grade["accuracy_tier"] != "high"
        assert "risk profile" in us_core_grade["verdict"]

        dumped = json.dumps([brief, review]).lower()
        for claim in ("no position has drifted", "no core position drifted", "rule did not trigger"):
            assert claim not in dumped, claim
