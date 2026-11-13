"""Shared fixtures and helpers for seed_ai tests."""
from __future__ import annotations

from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema
from tools.demo_data.seed_ai import DEMO_MARKER_ACCOUNT


def _make_db(tmp_path, name="test_seed_ai.duckdb"):
    db_path = tmp_path / name
    connector = DatabaseConnector(str(db_path))
    initialize_schema(connector)
    connector.run_migrations()
    return connector, str(db_path)


def _insert_demo_marker_holding(connector) -> None:
    """Minimal row standing in for a real demo sync's IBKR holdings row."""
    connector.execute(
        """
        INSERT INTO holdings (snapshot_date, asset_id, asset_name, account, source_system, currency)
        VALUES (DATE '2026-05-23', 'US_STK_VOO', 'VANGUARD S&P 500 ETF', ?, 'Broker_IBKR', 'USD')
        """,
        [DEMO_MARKER_ACCOUNT],
    )


def _table_counts(connector) -> dict:
    return {
        "user_profile": connector.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0],
        "goals": connector.execute("SELECT COUNT(*) FROM goals").fetchone()[0],
        "strategy_memos": connector.execute("SELECT COUNT(*) FROM strategy_memos").fetchone()[0],
        "memo_registry": connector.execute("SELECT COUNT(*) FROM memo_registry").fetchone()[0],
        "memo_asset_map": connector.execute("SELECT COUNT(*) FROM memo_asset_map").fetchone()[0],
        "ai_insights": connector.execute("SELECT COUNT(*) FROM ai_insights").fetchone()[0],
        "insights": connector.execute("SELECT COUNT(*) FROM insights").fetchone()[0],
        "trade_logs": connector.execute("SELECT COUNT(*) FROM trade_logs").fetchone()[0],
        "insight_trade_links": connector.execute("SELECT COUNT(*) FROM insight_trade_links").fetchone()[0],
    }
