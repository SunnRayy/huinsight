"""Round 6 #3: the investor-profile Target Allocation line, against a real
bootstrapped DB whose active risk profile is the seeded 'Balanced' one
(src/database/risk_profile_seeds.py). It used to read Chinese sub-class names
in an English context and list only the top 4 sub-classes (69% of 100)."""
from __future__ import annotations

import re

import pytest

from src.services.ai_advisor.context_builder import ContextBuilder, _resolve_context_language

_CJK_RE = re.compile(r"[一-鿿]")


def _make_builder(db, language):
    cb = ContextBuilder.__new__(ContextBuilder)
    cb._db = db
    cb._aia = {}
    cb._language = _resolve_context_language(language)
    return cb


class TestTargetAllocationAgainstSeededRiskProfile:
    @pytest.fixture
    def seeded_db(self, tmp_path):
        from src.database.connector import DatabaseConnector
        from src.database.schema import bootstrap_database

        db = DatabaseConnector(str(tmp_path / "ctx.duckdb"))
        bootstrap_database(db)
        yield db
        db.close()

    @staticmethod
    def _allocation_line(text: str, prefix: str) -> str:
        return next(line for line in text.splitlines() if line.startswith(prefix))

    @staticmethod
    def _pct_sum(line: str) -> int:
        return sum(int(p) for p in re.findall(r"(\d+)%", line))

    def test_english_summary_lists_every_class_in_english(self, seeded_db):
        out = _make_builder(seeded_db, "en").build_identity_context("summary")
        line = self._allocation_line(out, "- Target Allocation:")
        assert not _CJK_RE.search(line), line
        assert "Equity 55%" in line and "Fixed Income 20%" in line
        assert self._pct_sum(line) == 100, line

    def test_english_detailed_lists_every_sub_class_in_english(self, seeded_db):
        out = _make_builder(seeded_db, "en").build_identity_context("detailed")
        line = self._allocation_line(out, "- Target Allocation:")
        assert not _CJK_RE.search(line), line
        assert "US Equity 27%" in line
        assert self._pct_sum(line) == 100, line

    def test_chinese_summary_uses_chinese_class_names(self, seeded_db):
        out = _make_builder(seeded_db, "zh-CN").build_identity_context("summary")
        line = self._allocation_line(out, "- 目标配置：")
        assert "股票 55%" in line and "固定收益 20%" in line
        assert self._pct_sum(line) == 100, line
