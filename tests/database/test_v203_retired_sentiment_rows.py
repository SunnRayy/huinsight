"""V203 removes only the retired Buffett CN/JP/EU sentiment cache rows."""
from src.api.routes.sentiment import ensure_sentiment_table
from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema


def _cache_row(conn, key):
    conn.execute(
        """INSERT INTO market_sentiment_cache
               (indicator_key, section, indicator_name, value, updated_at)
           VALUES (?, 'equity_macro', ?, 1.0, CURRENT_TIMESTAMP)""",
        [key, key],
    )


def test_v203_removes_only_retired_rows(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "v203.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    ensure_sentiment_table(conn)
    for key in ("buffett_us", "buffett_cn", "buffett_jp", "buffett_eu", "vix"):
        _cache_row(conn, key)
    conn.execute("DELETE FROM schema_version WHERE version = 203")
    conn.run_migrations()

    left = [r[0] for r in conn.execute(
        "SELECT indicator_key FROM market_sentiment_cache ORDER BY indicator_key").fetchall()]
    assert left == ["buffett_us", "vix"]
    assert conn.execute("SELECT 1 FROM schema_version WHERE version = 203").fetchone()

    _cache_row(conn, "buffett_cn")  # recorded: never re-run
    conn.run_migrations()
    assert conn.execute(
        "SELECT COUNT(*) FROM market_sentiment_cache WHERE indicator_key = 'buffett_cn'"
    ).fetchone()[0] == 1
    conn.close()


def test_v203_records_on_a_fresh_db_without_the_cache_table(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "v203_fresh.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    assert conn.execute("SELECT 1 FROM schema_version WHERE version = 203").fetchone()
    assert not conn._migration_failures
    conn.close()
