"""Language parity for ContextBuilder's rendered block headers/labels (Round 5 #6).

Before this, every block header and fixed label `ContextBuilder` emits into the
LLM context text was a literal Chinese string with no language handling — an
English-UI "Preview Context" still showed `## 投资者画像`, `- 风险画像：Balanced`,
`## 当前资产配置`, etc. Mirrors the spirit of
``tests/services/test_ai_advisor_prompt_parity.py`` (which guards the bilingual
*prompt* scaffold in prompts.py) but for the *context* scaffold instead:

  - every fixed label has exactly the supported languages, no more, no fewer
  - the English variant never contains a CJK character
  - `language=None` (or an unrecognised code) reproduces the exact
    pre-existing Chinese text — nothing already stored or under test changes
  - rendering the same context in 'en' (with English-only fixture data) never
    emits a CJK character anywhere, not just in the labels
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from src.services.ai_advisor.context_builder import (
    ContextBuilder,
    _DEFAULT_CONTEXT_LANGUAGE,
    _LABELS,
    _format_analysis_age,
    _resolve_context_language,
    render_context,
)
from src.services.ai_advisor.section_ids import SUPPORTED_LANGUAGES

_CJK_RE = re.compile(r"[一-鿿]")


def _make_builder(db_mock=None, language=None):
    """Instantiate ContextBuilder with a mocked DB, bypassing __init__.

    Mirrors the `_make_builder` helper in test_context_builder.py so this
    file stays consistent with the existing test suite's convention.
    """
    cb = ContextBuilder.__new__(ContextBuilder)
    cb._db = db_mock if db_mock is not None else MagicMock()
    cb._aia = {}
    cb._language = _resolve_context_language(language)
    return cb


def _make_db_mock(fetchall_return=None, fetchone_return=None):
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = fetchall_return or []
    result.fetchone.return_value = fetchone_return
    db.execute.return_value = result
    return db


def _assert_label_covers_supported_languages(key: str) -> None:
    variants = _LABELS[key]
    assert set(variants) == set(SUPPORTED_LANGUAGES), (
        f"_LABELS[{key!r}] covers {sorted(variants)}, expected "
        f"{sorted(SUPPORTED_LANGUAGES)} — add the missing language variant "
        f"next to its sibling in the same literal"
    )
    for language, text in variants.items():
        assert text, f"_LABELS[{key!r}][{language!r}] is empty"


def _assert_label_en_has_no_cjk(key: str) -> None:
    text = _LABELS[key]["en"]
    offenders = _CJK_RE.findall(text)
    assert not offenders, f"_LABELS[{key!r}]['en'] contains CJK characters: {offenders} in {text!r}"


# ---------------------------------------------------------------------------
# Structural parity of the _LABELS lookup table
# ---------------------------------------------------------------------------


def test_default_context_language_is_zh_cn():
    """Anchor: the default must stay Chinese so language=None never changes stored output."""
    assert _DEFAULT_CONTEXT_LANGUAGE == "zh-CN"


@pytest.mark.parametrize("key", sorted(_LABELS))
def test_every_label_covers_exactly_the_supported_languages(key):
    _assert_label_covers_supported_languages(key)


@pytest.mark.parametrize("key", sorted(_LABELS))
def test_english_labels_never_contain_cjk(key):
    _assert_label_en_has_no_cjk(key)


def test_parity_checks_are_not_vacuous(monkeypatch):
    """Break each invariant deliberately; the corresponding check must go RED."""
    import src.services.ai_advisor.context_builder as cb_module

    monkeypatch.setitem(cb_module._LABELS, "probe_missing_lang", {"en": "English only"})
    with pytest.raises(AssertionError, match="expected"):
        _assert_label_covers_supported_languages("probe_missing_lang")

    monkeypatch.setitem(
        cb_module._LABELS, "probe_cjk_leak", {"en": "投资者", "zh-CN": "投资者"}
    )
    with pytest.raises(AssertionError, match="CJK"):
        _assert_label_en_has_no_cjk("probe_cjk_leak")


def test_resolve_context_language_defaults_and_falls_back():
    assert _resolve_context_language(None) == "zh-CN"
    assert _resolve_context_language("en") == "en"
    assert _resolve_context_language("zh-CN") == "zh-CN"
    # Unsupported / unrecognised code -> the pre-existing Chinese default,
    # never a guess.
    assert _resolve_context_language("fr") == "zh-CN"
    assert _resolve_context_language("") == "zh-CN"


def test_context_builder_language_defaults_to_zh_cn_when_unset():
    cb = ContextBuilder.__new__(ContextBuilder)  # bypass __init__, as some existing tests do
    assert cb._language == "zh-CN"


def test_context_builder_constructor_resolves_language():
    with patch("src.services.ai_advisor.context_builder.DatabaseConnector"):
        assert ContextBuilder()._language == "zh-CN"
        assert ContextBuilder(language="en")._language == "en"
        assert ContextBuilder(language="zh-CN")._language == "zh-CN"
        assert ContextBuilder(language="fr")._language == "zh-CN"


# ---------------------------------------------------------------------------
# Functional rendering parity: English-only fixtures must render with no CJK
# ---------------------------------------------------------------------------


def _identity_db_side_effect(query, params=()):
    result = MagicMock()
    if "user_profile" in query:
        result.fetchone.return_value = (
            "Test Investor",
            '{"goal": "Financial independence", "horizon": "10-20 years", '
            '"risk_tolerance": "Moderate", "core_weakness": "Chasing rallies", '
            '"portfolio_structure": "60/40 core-satellite"}',
        )
    elif "risk_profiles" in query:
        result.fetchone.return_value = (2, "Balanced", "Balanced", "Balance risk and return")
    elif "risk_profile_allocations" in query:
        result.fetchall.return_value = [("Equity", 60.0), ("Bonds", 40.0)]
    elif "ai_insights" in query:
        result.fetchall.return_value = [
            ("Rebalance trigger", "Trim equity when drift exceeds 5pp", "validated", "2026-01-01"),
        ]
    else:
        result.fetchall.return_value = []
        result.fetchone.return_value = None
    return result


class TestIdentityContextLanguage:
    def test_zh_cn_default_and_english_headers(self):
        db_zh = _make_db_mock()
        db_zh.execute.side_effect = _identity_db_side_effect
        zh = _make_builder(db_mock=db_zh).build_identity_context("detailed")  # None -> zh-CN, unchanged
        assert "## 投资者画像" in zh and "## AI洞见沉淀" in zh
        assert "- 目标：Financial independence" in zh
        assert "- 风险画像：Balanced" in zh

        db_en = _make_db_mock()
        db_en.execute.side_effect = _identity_db_side_effect
        en = _make_builder(db_mock=db_en, language="en").build_identity_context("detailed")
        assert "## Investor Profile" in en and "## AI Insights" in en
        assert "- Goal: Financial independence" in en
        assert "- Risk Profile: Balanced" in en
        assert not _CJK_RE.search(en), f"English identity context leaked CJK: {en!r}"


class TestPortfolioContextLanguage:
    _compass_rows = [
        {
            "asset_class": "Equity",
            "current_value": 500000.0,
            "current_pct": 70.0,
            "target_pct": 65.0,
            "drift_pct": 5.0,
            "is_top_level": True,
        },
    ]
    _holdings_rows = [
        {
            "asset_id": "US_STK_AAPL",
            "name": "Apple Inc.",
            "market_value": 500000.0,
            "cost_basis": 400000.0,
            "lifetime_pl": 100000.0,
            "return_pct": 25.0,
        },
    ]

    def _build(self, language):
        db = _make_db_mock()
        cb = _make_builder(db_mock=db, language=language)
        with patch(
            "src.services.ai_advisor.context_builder.build_compass_allocation",
            return_value=self._compass_rows,
        ), patch(
            "src.services.ai_advisor.context_builder.fetch_wealthos_active_holdings",
            return_value=self._holdings_rows,
        ), patch(
            "src.services.ai_advisor.context_builder.build_portfolio_summary_semantics",
            return_value={
                "net_worth": 500000.0,
                "total_cost_basis": 400000.0,
                "total_unrealized_pl": 100000.0,
                "unrealized_pl_pct": 25.0,
                "total_realized_pl": 0.0,
                "total_lifetime_pl": 100000.0,
            },
        ), patch(
            "src.services.ai_advisor.context_builder.calculate_portfolio_twr",
            return_value={"cumulative": 0.1, "annualized": 0.08},
        ), patch(
            "src.services.ai_advisor.context_builder.calculate_portfolio_xirr",
            return_value=0.09,
        ), patch(
            "src.services.ai_advisor.context_builder.calculate_portfolio_metrics",
            return_value={
                "sharpe_ratio": 1.0,
                "sortino_ratio": 1.2,
                "max_drawdown": 5.0,
                "calmar_ratio": 0.5,
                "volatility_annual": 10.0,
                "total_return": 12.0,
                "data_points": 20,
            },
        ):
            return cb.build_portfolio_context("detailed")

    def test_zh_cn_default_and_english_headers(self):
        zh = self._build(language=None)
        assert "## 当前资产配置" in zh and "### 偏离最大的配置" in zh
        assert "Equity: 当前70.0% vs 目标65.0% (偏离5.0%)" in zh
        assert "### 持仓明细" in zh

        en = self._build(language="en")
        assert "## Current Asset Allocation" in en and "### Largest Allocation Drift" in en
        assert "Equity: current 70.0% vs target 65.0% (drift 5.0%)" in en
        assert "### Holdings Detail" in en
        assert not _CJK_RE.search(en), f"English portfolio context leaked CJK: {en!r}"


class TestMarketAndStrategyAndTransactionsLanguage:
    """One block per method: default (zh-CN) keeps the original header;
    'en' renders the English header and leaks no CJK."""

    def test_market_context(self):
        db = _make_db_mock(fetchall_return=[("equity_macro", "VIX", "18.0", "Neutral")])
        assert "## 市场情绪" in _make_builder(db_mock=db).build_market_context("summary")

        db_en = _make_db_mock(fetchall_return=[("equity_macro", "VIX", "18.0", "Neutral")])
        result_en = _make_builder(db_mock=db_en, language="en").build_market_context("summary")
        assert "## Market Sentiment" in result_en
        assert not _CJK_RE.search(result_en)

    def test_strategy_context(self):
        rows = [("2026-03-01", "Q1 Strategy", "defensive", "[]", "Stay defensive on drawdown risk.")]
        assert "## 策略备忘" in _make_builder(db_mock=_make_db_mock(fetchall_return=rows)).build_strategy_context("30d")

        result_en = _make_builder(
            db_mock=_make_db_mock(fetchall_return=rows), language="en"
        ).build_strategy_context("30d")
        assert "## Strategy Memos" in result_en
        assert not _CJK_RE.search(result_en)

    def test_transactions_context(self):
        rows = [("2026-03-01", "US_STK_AAPL", "Apple Inc.", "USD", "BUY", 10, 150.0, "A")]
        result_zh = _make_builder(db_mock=_make_db_mock(fetchall_return=rows)).build_transactions_context(
            "14d", detail="summary"
        )
        assert "## 近期交易" in result_zh
        assert "| 日期 | 资产 | 操作 | 数量 | 价格 | 评级 |" in result_zh

        result_en = _make_builder(
            db_mock=_make_db_mock(fetchall_return=rows), language="en"
        ).build_transactions_context("14d", detail="summary")
        assert "## Recent Transactions" in result_en
        assert "| Date | Asset | Action | Quantity | Price | Grade |" in result_en
        assert not _CJK_RE.search(result_en)


class TestTechnicalContextLanguage:
    _signals = {
        "trend_status": "BULL",
        "rsi_value": 55.0,
        "rsi_status": "NEUTRAL",
        "macd_status": "BULLISH",
        "volume_status": "NORMAL",
        "signal_score": 70,
        "support_levels": [100.0],
        "resistance_levels": [120.0],
    }

    def _build(self, language):
        import json

        db = MagicMock()

        def side_effect(query, params=()):
            result = MagicMock()
            if "FROM holdings" in query:
                result.fetchall.return_value = [("US_STK_AAPL",)]
            elif "FROM asset_analyses" in query or "asset_analyses" in query:
                result.fetchall.return_value = [
                    ("US_STK_AAPL", "Apple Inc.", json.dumps(self._signals), "2026-03-20 10:00:00"),
                ]
            else:
                result.fetchall.return_value = []
            return result

        db.execute.side_effect = side_effect
        cb = _make_builder(db_mock=db, language=language)
        return cb.build_technical_context(detail="full")

    def test_zh_cn_default_and_english_headers(self):
        zh = self._build(language=None)
        assert zh.startswith("## 近期技术分析")
        assert "评分70/100" in zh and "量能=NORMAL" in zh
        assert "支撑=100.0" in zh and "阻力=120.0" in zh

        en = self._build(language="en")
        assert en.startswith("## Recent Technical Analysis")
        assert "Score 70/100" in en and "Volume=NORMAL" in en
        assert "Support=100.0" in en and "Resistance=120.0" in en
        assert not _CJK_RE.search(en), f"English technical context leaked CJK: {en!r}"


def test_format_analysis_age_language_parity():
    from datetime import datetime, timedelta

    recent = datetime.now() - timedelta(minutes=5)
    older = datetime.now() - timedelta(hours=2)

    assert _format_analysis_age(recent, "zh-CN") == "5分钟前"
    assert _format_analysis_age(recent, "en") == "5 minutes ago"
    assert _format_analysis_age(older, "zh-CN") == "2小时前"
    assert _format_analysis_age(older, "en") == "2 hours ago"
    # Default (no language arg) must stay byte-identical to pre-existing behaviour.
    assert _format_analysis_age(recent) == "5分钟前"


# ---------------------------------------------------------------------------
# render_context: top-level "no data" fallback follows the resolved language
# ---------------------------------------------------------------------------


def _empty_stub():
    cb = MagicMock()
    cb.build_identity_context.return_value = ""
    cb.build_portfolio_context.return_value = ""
    cb.build_market_context.return_value = ""
    cb.build_strategy_context.return_value = ""
    cb.build_transactions_context.return_value = ""
    cb.build_realtime_context.return_value = ""
    cb.build_valuation_context.return_value = ""
    cb.build_technical_context.return_value = ""
    return cb


def _empty_cfg():
    return {
        "tiers": {},
        "include_realtime": False,
        "include_valuation_context": False,
        "include_technical_context": False,
    }


def test_render_context_fallback_zh_cn_default():
    result = render_context(_empty_stub(), _empty_cfg())
    assert result == "（持仓和市场数据暂不可用。请仅说明数据不足，不要编造分析。）"


def test_render_context_fallback_english():
    result = render_context(_empty_stub(), _empty_cfg(), language="en")
    assert "Holdings and market data are currently unavailable" in result
    assert not _CJK_RE.search(result)


def test_render_context_fallback_unsupported_language_keeps_chinese():
    result = render_context(_empty_stub(), _empty_cfg(), language="fr")
    assert result == "（持仓和市场数据暂不可用。请仅说明数据不足，不要编造分析。）"
