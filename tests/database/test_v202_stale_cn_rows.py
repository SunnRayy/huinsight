"""V202 removes the reviewed stale CN rows only while they are exactly what was reviewed."""
import pytest

from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema

# Synthetic reviewed rows; the real list is deployment data (see the connector).
_ROWS = (
    (900101, "2025-02-14", "dividend_reinvest", 120.5),
    (900102, "2025-08-25", "other", 0.25),
)


@pytest.fixture(autouse=True)
def _synthetic_rows(monkeypatch):
    monkeypatch.setattr(DatabaseConnector, "_V202_STALE_CN_ROWS", _ROWS)


def _tx(conn, tx_id, asset, day, kind, qty):
    conn.execute(
        """INSERT INTO transactions (id, transaction_date, asset_id, transaction_type, quantity,
               amount_gross, amount_net, currency, source_system)
           VALUES (?, ?, ?, ?, ?, 0, 0, 'CNY', 'CN_Fund_Excel')""",
        [tx_id, day, asset, kind, qty],
    )


def test_v202_archives_and_removes_only_the_reviewed_rows(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "v202.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    _tx(conn, 900101, "CN_FUND_SYN_A", "2025-02-14", "dividend_reinvest", 120.5)
    _tx(conn, 900102, "CN_FUND_SYN_B", "2025-08-25", "other", 0.31)  # changed: kept
    conn.execute("DELETE FROM schema_version WHERE version = 202")
    conn.run_migrations()

    left = [r[0] for r in conn.execute("SELECT id FROM transactions ORDER BY id").fetchall()]
    archived = [r[0] for r in conn.execute(
        "SELECT id FROM migration_v202_stale_cn_transactions").fetchall()]
    assert left == [900102] and archived == [900101]
    conn.run_migrations()  # recorded: never re-run
    assert conn.execute(
        "SELECT COUNT(*) FROM migration_v202_stale_cn_transactions").fetchone()[0] == 1
    conn.close()


def test_v202_recomputes_the_affected_fund_cost(tmp_path):
    """Removing a reinvestment lot must not leave its cost in the stored average."""
    conn = DatabaseConnector(str(tmp_path / "v202c.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    conn.execute(
        """INSERT INTO transactions (transaction_date, asset_id, transaction_type, quantity,
               price_unit, amount_gross, amount_net, currency, source_system)
           VALUES ('2026-01-02', 'CN_FUND_SYN_A', 'buy', 100, 1.0, 100, 100, 'CNY', 'CN_Fund_Excel')"""
    )
    conn.execute(
        """INSERT INTO transactions (id, transaction_date, asset_id, transaction_type, quantity,
               price_unit, amount_gross, amount_net, currency, source_system)
           VALUES (900101, '2025-02-14', 'CN_FUND_SYN_A', 'dividend_reinvest', 120.5, 1.25,
                   0, 0, 'CNY', 'CN_Fund_Excel')"""
    )
    conn.execute(
        """INSERT INTO holdings (snapshot_date, asset_id, quantity, cost_price_unit,
               market_price_unit, market_value, currency, source_system, is_shadow)
           VALUES ('2026-08-28', 'CN_FUND_SYN_A', 100, 1.2, 1.1, 110, 'CNY', 'CN_Fund_Excel', FALSE)"""
    )
    conn.execute("DELETE FROM schema_version WHERE version = 202")
    conn.run_migrations()
    cost = conn.execute(
        "SELECT cost_price_unit FROM holdings WHERE asset_id = 'CN_FUND_SYN_A'").fetchone()[0]
    assert float(cost) == 1.0
    assert conn.execute(
        "SELECT COUNT(*) FROM migration_v202_cn_cost").fetchone()[0] == 1
    conn.close()


def test_sync_backfill_recomputes_a_stale_cn_cost(tmp_path):
    """The CN workbook has no cost field: each sync recomputes it from the ledger."""
    from src.sync.phases._post_reader import _backfill_fifo_cost_basis
    conn = DatabaseConnector(str(tmp_path / "bf.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    conn.execute(
        """INSERT INTO transactions (transaction_date, asset_id, transaction_type, quantity,
               price_unit, amount_gross, amount_net, currency, source_system)
           VALUES ('2026-01-02', 'CN_FUND_B', 'buy', 100, 2.0, 200, 200, 'CNY', 'CN_Fund_Excel')"""
    )
    conn.execute(
        """INSERT INTO holdings (snapshot_date, asset_id, quantity, cost_price_unit,
               market_price_unit, market_value, currency, source_system, is_shadow)
           VALUES ('2026-08-28', 'CN_FUND_B', 100, 1.5, 2.5, 250, 'CNY', 'CN_Fund_Excel', FALSE)"""
    )
    _backfill_fifo_cost_basis(conn)
    cost = conn.execute(
        "SELECT cost_price_unit FROM holdings WHERE asset_id = 'CN_FUND_B'").fetchone()[0]
    assert float(cost) == 2.0
    conn.close()


def test_v202_with_no_reviewed_rows_records_itself(tmp_path, monkeypatch):
    """The public export ships an empty list: V202 must record itself, not fail."""
    monkeypatch.setattr(DatabaseConnector, "_V202_STALE_CN_ROWS", ())
    conn = DatabaseConnector(str(tmp_path / "v202e.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    conn.execute("DELETE FROM schema_version WHERE version = 202")
    conn.run_migrations()
    assert conn.execute("SELECT 1 FROM schema_version WHERE version = 202").fetchone()
    assert not [f for f in conn._migration_failures if "V202" in f]
    conn.close()
