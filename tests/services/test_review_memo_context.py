"""Review gets the strategy memos in force and each trade's plan context (2026-11-08).

Before this, review questions asked why memo-directed trades were made: the
question step saw only date/asset/qty/price, and the written review got memos
only when the strategy tier was on, counted back from today.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema
from src.services.ai_advisor.context_builder import format_review_memos, format_review_trades


@pytest.fixture
def db():
    conn = DatabaseConnector(":memory:")
    initialize_schema(conn)
    conn.run_migrations()
    memos = [
        (1, "2026-03-01", "Old memo", "too old, not in force"),
        (2, "2026-05-10", "VOO DCA switched to BRK-B", "Buy BRK-B every two weeks."),
        (3, "2026-06-28", "Q3/H2 playbook", "Finish the RSU sell-down by Q4."),
        (4, "2026-11-20", "After the period", "Not in the period."),
    ]
    for memo_id, memo_date, title, content in memos:
        conn.execute(
            "INSERT INTO strategy_memos (id, memo_date, title, content) VALUES (?, ?, ?, ?)",
            [memo_id, memo_date, title, content],
        )
    conn.execute(
        """INSERT INTO trade_logs (log_date, asset_id, action, quantity, price,
                                   suggestion_source, linked_memo_id, decision_reason)
           VALUES ('2026-10-12', 'RSU_AMZN', 'Sell', 27, 200.5, 'manual', 3, '按减持计划完成RSU清仓'),
                  ('2026-08-21', 'CN_FUND_000198', 'Buy', 9908, 1.0, 'imported', NULL, '余额宝转入'),
                  ('2026-07-01', 'US_STK_BRK-B', 'Buy', 5, 480, 'manual', 1, NULL)"""
    )
    return conn


def test_memos_in_force_are_period_scoped(db):
    text = format_review_memos(db, "2026-06-01", "2026-10-30", "en")
    # In force at start (#2), issued in period (#3), older memo a trade links to (#1).
    assert "#2 · 2026-05-10 · VOO DCA switched to BRK-B" in text
    assert "(in force at period start)" in text
    assert "#3 · 2026-06-28 · Q3/H2 playbook" in text and "(issued in period)" in text
    assert "#1 · 2026-03-01 · Old memo" in text and "(linked by a trade)" in text
    assert "After the period" not in text
    assert "Finish the RSU sell-down by Q4." in text  # full memo body, not just the title


def test_trade_lines_carry_source_memo_and_reason(db):
    text = format_review_trades(db, "2026-06-01", "2026-10-30")
    amzn = next(line for line in text.splitlines() if "AMZN" in line)
    assert "source=manual" in amzn
    assert "memo=#3 2026-06-28 Q3/H2 playbook" in amzn
    assert "reason=按减持计划完成RSU清仓" in amzn
    fund = next(line for line in text.splitlines() if "000198" in line)
    assert "source=imported" in fund and "reason=余额宝转入" in fund and "memo=" not in fund


def test_questions_prompt_gets_memos_and_plan_guidance(monkeypatch):
    from src.services.ai_advisor import review_generator as rg

    monkeypatch.setattr(rg, "_load_trades_text", lambda *a, **k: "2026-10-12 | AMZN | Sell | memo=#3 ...")
    monkeypatch.setattr(rg, "_load_memos_text", lambda *a, **k: "## Strategy memos in force\n### #3 · Q3/H2 playbook")
    llm = MagicMock()
    llm.complete.return_value = MagicMock(
        content_json={"questions": [{"id": 1, "question": "q", "context": "c"}]}
    )
    with patch.object(rg, "LLMClient", return_value=llm):
        rg.ReviewGenerator().generate_questions("2026-06-01", "2026-10-30", language="en")

    prompt = llm.complete.call_args.kwargs["user_prompt"]
    assert prompt.index("### #3 · Q3/H2 playbook") < prompt.index("Trade records for")
    assert "do not ask why it was made" in prompt


def test_review_context_config_turns_off_strategy_tier_without_mutating_input():
    from src.services.ai_advisor.review_generator import review_context_config

    cfg = {"tiers": {"strategy": {"enabled": True, "timeframe": "30d"}, "market": {"enabled": True}}}
    out = review_context_config(cfg)
    assert out["tiers"]["strategy"]["enabled"] is False
    assert out["tiers"]["market"]["enabled"] is True
    assert cfg["tiers"]["strategy"]["enabled"] is True
