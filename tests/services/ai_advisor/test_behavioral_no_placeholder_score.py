"""Structural guard: behavioral metrics never report a placeholder as a score.

A dimension without enough data used to return score=0.5, which the radar
plotted as a real mid-scale measurement — the "fabricated default shown as a
measurement" failure class (AGENTS.md Core Doctrine, Rule 24). Unmeasured
dimensions must carry score=None; only computed values may be numeric.
"""
import ast
from pathlib import Path

import duckdb

from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema
from src.services.ai_advisor.behavioral_metrics import BehavioralMetricsComputer

_SOURCE = Path(__file__).resolve().parents[3] / "src" / "services" / "ai_advisor" / "behavioral_metrics.py"


def _is_numeric_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def test_no_metric_result_is_built_with_a_constant_score():
    """Every MetricResult(score=...) and every `x.score = ...` must be computed or None."""
    tree = ast.parse(_SOURCE.read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "MetricResult":
            for kw in node.keywords:
                if kw.arg == "score" and _is_numeric_constant(kw.value):
                    offenders.append(f"line {node.lineno}: MetricResult(score={kw.value.value})")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "score" and _is_numeric_constant(node.value):
                    offenders.append(f"line {node.lineno}: .score = {node.value.value}")
    assert not offenders, (
        "Behavioral metrics must not emit a constant score — an unmeasured "
        "dimension is score=None, not a plotted placeholder:\n" + "\n".join(offenders)
    )


def test_empty_portfolio_yields_no_numeric_scores(tmp_path):
    """With no trades, targets, insights or memos, nothing is measurable."""
    db_path = tmp_path / "behavioral_empty.duckdb"
    conn = DatabaseConnector(str(db_path))
    initialize_schema(conn)
    conn.run_migrations()
    conn.close()

    raw = duckdb.connect(str(db_path))
    try:
        results = BehavioralMetricsComputer(str(db_path)).compute_all(window_days=90, conn=raw)
    finally:
        raw.close()

    assert len(results) == 8
    scored = {r.dimension: r.score for r in results if r.score is not None}
    assert scored == {}, f"Unmeasurable dimensions reported numeric scores: {scored}"
