"""V201 and the cost backfill: a CN conversion leaves cost as it leaves realized P&L."""
from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema
from src.services.portfolio_helpers import calculate_realized_pnl
from src.sync.phases._post_reader import fifo_remaining_unit_cost


def _db(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "v201.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    return conn


def _tx(conn, day, kind, qty, amount, asset="CN_FUND_A"):
    conn.execute(
        """INSERT INTO transactions (transaction_date, asset_id, transaction_type, quantity,
               price_unit, amount_gross, amount_net, currency, source_system)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'CNY', 'CN_Fund_Excel')""",
        [day, asset, kind, qty, amount / qty, amount, amount],
    )


def _two_lots_then_convert_oldest(conn):
    _tx(conn, "2025-01-01", "buy", 100, 1000.0)
    _tx(conn, "2025-02-01", "buy", 100, 2000.0)
    _tx(conn, "2025-03-01", "transfer_out", 100, 1500.0)


def test_backfill_cost_and_realized_consume_the_same_lots(tmp_path):
    conn = _db(tmp_path)
    _two_lots_then_convert_oldest(conn)
    assert fifo_remaining_unit_cost(conn, "CN_FUND_A") == 20.0  # the ¥2,000 lot remains
    assert round(calculate_realized_pnl(conn, "CN_FUND_A")[0], 2) == 500.0
    conn.close()


def test_v201_recomputes_stale_cost_once_and_archives_it(tmp_path):
    conn = _db(tmp_path)
    _two_lots_then_convert_oldest(conn)
    conn.execute(
        """INSERT INTO holdings (snapshot_date, asset_id, quantity, cost_price_unit,
               market_price_unit, market_value, currency, source_system, is_shadow)
           VALUES ('2025-04-01', 'CN_FUND_A', 100, 15.0, 20.0, 2000.0, 'CNY', 'CN_Fund_Excel', FALSE)"""
    )
    conn.execute("DELETE FROM schema_version WHERE version = 201")
    conn.run_migrations()

    cost = conn.execute(
        "SELECT cost_price_unit FROM holdings WHERE asset_id = 'CN_FUND_A'").fetchone()[0]
    assert float(cost) == 20.0
    archived = conn.execute(
        "SELECT old_cost_price_unit, new_cost_price_unit FROM migration_v201_cn_conversion_cost"
    ).fetchall()
    assert [(float(a), float(b)) for a, b in archived] == [(15.0, 20.0)]
    # Lifetime = value + money out − money in = 2000 + 1500 − 3000.
    realized = calculate_realized_pnl(conn, "CN_FUND_A")[0]
    assert round(realized + 2000.0 - float(cost) * 100, 2) == 500.0

    conn.run_migrations()  # recorded: never re-run
    assert conn.execute(
        "SELECT COUNT(*) FROM migration_v201_cn_conversion_cost").fetchone()[0] == 1
    conn.close()


def test_v201_fills_a_null_cost_too(tmp_path):
    """Startup alone must not leave a converted position at cost 0 until the next sync."""
    conn = _db(tmp_path)
    _two_lots_then_convert_oldest(conn)
    conn.execute(
        """INSERT INTO holdings (snapshot_date, asset_id, quantity, cost_price_unit,
               market_price_unit, market_value, currency, source_system, is_shadow)
           VALUES ('2025-04-01', 'CN_FUND_A', 100, NULL, 20.0, 2000.0, 'CNY', 'CN_Fund_Excel', FALSE)"""
    )
    conn.execute("DELETE FROM schema_version WHERE version = 201")
    conn.run_migrations()
    cost = conn.execute(
        "SELECT cost_price_unit FROM holdings WHERE asset_id = 'CN_FUND_A'").fetchone()[0]
    assert float(cost) == 20.0
    conn.close()
