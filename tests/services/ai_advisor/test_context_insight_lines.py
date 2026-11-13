"""AI insight lines in the LLM context: the update day, not the raw DB
timestamp, and the status in the context language, not the raw status code."""
from datetime import datetime

from src.services.ai_advisor.context_builder import ContextBuilder, _resolve_context_language


def _make_builder(language):
    cb = ContextBuilder.__new__(ContextBuilder)
    cb._db = None
    cb._aia = {}
    cb._language = _resolve_context_language(language)
    return cb


def test_ai_insight_lines_show_a_day_and_a_localized_status():
    """An insight line carries the update day (not the raw DB timestamp) and
    the status in the context language, never the raw status code."""
    rows = [
        ("Rule A", "Body A", "principle", datetime(2026, 10, 25, 11, 0, 42, 155538)),
        ("Rule B", "Body B", "validated", "2026-03-19 12:00:00"),
    ]
    zh = _make_builder(language="zh-CN")._format_ai_insights_section(rows, "summary")
    en = _make_builder(language="en")._format_ai_insights_section(rows, "summary")

    assert "- [原则] Rule A (2026-10-25): Body A" in zh
    assert "- [已验证] Rule B (2026-03-19): Body B" in zh
    assert "- [Principle] Rule A (2026-10-25): Body A" in en
    assert "- [Validated] Rule B (2026-03-19): Body B" in en
    for text in (zh, en):
        assert "11:00:42" not in text and "[principle]" not in text
