"""Tests for the Chinese demo AI content (`seed_ai.py --lang zh-CN`).

The Chinese file must be the English file in another language, never a second
persona: same keys, same list lengths, and the same numbers, dates, ids, enum
values and tags. All tests use tmp_path, never the production DB.
"""
from __future__ import annotations

import json
import re

import pytest

from src.database.connector import DatabaseConnector
from src.services.ai_advisor.section_ids import BRIEF_SECTION_IDS, REVIEW_SECTION_IDS
from tests.tools.conftest import _insert_demo_marker_holding, _make_db, _table_counts
from tools.demo_data.seed_ai import (
    GOAL_NOTES_MARKER,
    SOURCE_MARKER,
    holds_other_language,
    load_seed,
    run,
)

# A string with no whitespace and only ASCII is an id, a date, an enum value or
# a tag; it must be identical in both files. Prose always has spaces or CJK.
_TOKEN = re.compile(r"^[\x21-\x7e]+$")
# Keys whose values differ by language by design.
_LANG_KEYS = {"language", "display_name"}


def _walk_parity(en, zh, path="$"):
    assert type(en) is type(zh), f"{path}: {type(en).__name__} vs {type(zh).__name__}"
    if isinstance(en, dict):
        assert set(en) == set(zh), f"{path}: keys differ {set(en) ^ set(zh)}"
        for k in en:
            if k not in _LANG_KEYS:
                _walk_parity(en[k], zh[k], f"{path}.{k}")
    elif isinstance(en, list):
        assert len(en) == len(zh), f"{path}: {len(en)} vs {len(zh)} items"
        for i, (a, b) in enumerate(zip(en, zh)):
            _walk_parity(a, b, f"{path}[{i}]")
    elif isinstance(en, str):
        if _TOKEN.match(en):
            assert en == zh, f"{path}: {en!r} vs {zh!r}"
    else:
        assert en == zh, f"{path}: {en!r} vs {zh!r}"


def _counts(db_path: str) -> dict:
    db = DatabaseConnector(db_path, read_only=True)
    try:
        return _table_counts(db)
    finally:
        db.close()


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


class TestZhContentFile:
    def test_same_structure_ids_numbers_and_enums_as_english(self):
        _walk_parity(load_seed("en"), load_seed("zh-CN"))

    def test_language_and_persona(self):
        zh = load_seed("zh-CN")
        assert zh["investor_profile"]["language"] == "zh-CN"
        assert zh["investor_profile"]["display_name"] == "王小明"

    def test_every_number_in_the_prose_also_appears_in_english(self):
        """Translation must not invent a figure: each number in a Chinese
        paragraph appears somewhere in the English file too (the English
        writes 5M where the Chinese writes 500 万, so 500 is allowed)."""
        en_numbers = _numbers(json.dumps(load_seed("en"), ensure_ascii=False)) | {"500", "350", "185", "12"}
        # "6 月" is June: English spells month names out
        zh_text = re.sub(r"\d{1,2} 月", "", json.dumps(load_seed("zh-CN"), ensure_ascii=False))
        zh_numbers = _numbers(zh_text)
        assert zh_numbers <= en_numbers, sorted(zh_numbers - en_numbers)

    def test_no_folded_spaces_inside_chinese_sentences(self):
        """YAML folding joins wrapped lines with a space; a space between two
        CJK characters means a paragraph was wrapped."""
        dumped = json.dumps(load_seed("zh-CN"), ensure_ascii=False)
        assert not re.search(r"[一-鿿，。；：、] [一-鿿，。；：、]", dumped)

    def test_contract_sections_and_hedges(self):
        zh = load_seed("zh-CN")
        assert set(zh["sample_brief"]["content_json"]) == set(BRIEF_SECTION_IDS)
        assert set(zh["sample_review"]["content_json"]) == set(REVIEW_SECTION_IDS)
        assert "截至演示快照" in zh["sample_brief"]["content_json"]["holdings_risk"]["narrative"]

    def test_goal_names_the_seeded_target(self):
        zh = load_seed("zh-CN")
        goal_text = zh["investor_profile"]["philosophy"]["goal"]
        assert f"{zh['retirement_goal']['target_amount'] // 10_000} 万元" in goal_text
        assert zh["retirement_goal"]["target_date"][:4] in goal_text

    def test_samples_reconcile_the_risk_profile_drift(self):
        """Same doctrine as the English test: the samples must name the drift
        against the risk profile (风险档位), never claim nothing drifted."""
        zh = load_seed("zh-CN")
        brief = zh["sample_brief"]["content_json"]
        review = zh["sample_review"]["content_json"]
        assert any("风险档位" in item["description"] for item in brief["risk_alerts"]["items"])
        assert "风险档位" in brief["action_items"]["actions"][0]["reasoning"]
        grade = review["advice_accuracy"]["scorecard"][0]
        assert grade["accuracy_tier"] != "high"
        assert "风险档位" in grade["verdict"]

    def test_adoptions_name_existing_insights(self):
        zh = load_seed("zh-CN")
        titles = {i["title"] for i in zh["insights_lifecycle"]}
        assert all(a["title"] in titles for a in zh["insight_adoptions"])

    def test_unknown_language_is_rejected(self):
        with pytest.raises(ValueError):
            load_seed("fr")


class TestZhSeeding:
    def test_seeds_chinese_content(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()

        assert run(db_path, dry_run=False, lang="zh-CN") == 0

        db = DatabaseConnector(db_path, read_only=True)
        try:
            name, language = db.execute(
                "SELECT display_name, language FROM user_profile WHERE id = 1"
            ).fetchone()
            assert (name, language) == ("王小明", "zh-CN")
            titles = {r[0] for r in db.execute(
                "SELECT title FROM strategy_memos WHERE source_file = ?", [SOURCE_MARKER]
            ).fetchall()}
            assert titles == {m["title"] for m in load_seed("zh-CN")["strategy_memos"]}
            md = db.execute(
                "SELECT content_markdown FROM ai_reports WHERE report_type = 'brief'"
            ).fetchone()[0]
            assert "## 宏观形势" in md
            notes = db.execute(
                "SELECT notes FROM goals WHERE strpos(notes, ?) > 0", [GOAL_NOTES_MARKER]
            ).fetchone()[0]
            assert notes.startswith("演示角色")
        finally:
            db.close()

    def test_rerun_is_idempotent(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()
        assert run(db_path, dry_run=False, lang="zh-CN") == 0
        first = _counts(db_path)
        assert run(db_path, dry_run=False, lang="zh-CN") == 0
        assert _counts(db_path) == first

    @pytest.mark.parametrize("first,second", [("en", "zh-CN"), ("zh-CN", "en")])
    def test_refuses_to_mix_languages_in_one_db(self, tmp_path, first, second):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()
        assert run(db_path, dry_run=False, lang=first) == 0
        before = _counts(db_path)

        assert holds_other_language(db_path, load_seed(second))
        assert run(db_path, dry_run=False, lang=second) == 1
        assert _counts(db_path) == before

    def test_fresh_db_is_not_flagged(self, tmp_path):
        connector, db_path = _make_db(tmp_path)
        _insert_demo_marker_holding(connector)
        connector.close()
        assert not holds_other_language(db_path, load_seed("zh-CN"))
