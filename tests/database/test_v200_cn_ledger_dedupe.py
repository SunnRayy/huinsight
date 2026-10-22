"""V200: the second copy of the CN ledger is folded into the key-less originals."""
from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema


def _tx(conn, day, asset, kind, qty, amount, key=None, memo=None):
    return conn.execute(
        """INSERT INTO transactions (transaction_date, asset_id, asset_name, transaction_type,
               quantity, price_unit, amount_gross, amount_net, commission_fee, currency,
               account, memo, source_system, source_event_key)
           VALUES (?, ?, ?, ?, ?, 1.0, ?, ?, 0, 'CNY', 'CN Fund', ?, 'CN_Fund_Excel', ?)
           RETURNING id""",
        [day, asset, asset, kind, qty, amount, amount, memo, key],
    ).fetchone()[0]


def _log(conn, tx_id, source):
    return conn.execute(
        """INSERT INTO trade_logs (log_date, asset_id, action, linked_transaction_id, suggestion_source)
           VALUES ('2026-01-02', 'CN_FUND_A', 'Buy', ?, ?) RETURNING id""",
        [tx_id, source],
    ).fetchone()[0]


def _ledger(conn):
    return [
        (r[0], r[1], float(r[2]), r[3])
        for r in conn.execute(
            """SELECT id, asset_id, amount_gross, source_event_key FROM transactions
               WHERE source_system = 'CN_Fund_Excel' ORDER BY id"""
        ).fetchall()
    ]


def test_v200_folds_copies_keeps_originals_and_trade_logs(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "v200.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()

    # Original import (no keys): two independent equal orders, one other buy, one stale row.
    a1 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100)
    a2 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100)
    b1 = _tx(conn, "2026-01-03", "CN_FUND_B", "sell", 5, 60)
    stale = _tx(conn, "2026-01-04", "CN_FUND_C", "other", 0.27, 0.27, memo="份额调增")
    # Keyed re-import: the same three orders plus one genuinely new order.
    k1 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100, key="key-a1")
    k2 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100, key="key-a2")
    kb = _tx(conn, "2026-01-03", "CN_FUND_B", "sell", 5, 60, key="key-b1")
    new = _tx(conn, "2026-02-01", "CN_FUND_D", "buy", 1, 10, key="key-new")
    unrelated = conn.execute(
        """INSERT INTO transactions (transaction_date, asset_id, transaction_type, quantity,
               amount_gross, currency, source_system)
           VALUES ('2026-01-02', 'US_STK_X', 'buy', 10, 100, 'USD', 'Schwab_CSV') RETURNING id"""
    ).fetchone()[0]

    manual_on_original = _log(conn, a1, "manual")
    imported_dup = _log(conn, k1, "imported")      # duplicates manual_on_original
    manual_on_copy = _log(conn, kb, "manual")      # its original has no log: must move

    conn.execute("DELETE FROM schema_version WHERE version = 200")
    conn.run_migrations()

    assert conn._migration_failures == []
    assert _ledger(conn) == [
        (a1, "CN_FUND_A", 100, "key-a1"),
        (a2, "CN_FUND_A", 100, "key-a2"),
        (b1, "CN_FUND_B", 60, "key-b1"),
        (stale, "CN_FUND_C", 0.27, None),
        (new, "CN_FUND_D", 10, "key-new"),
    ]
    assert conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE id = ?", [unrelated]
    ).fetchone()[0] == 1

    logs = dict(conn.execute("SELECT id, linked_transaction_id FROM trade_logs").fetchall())
    assert logs == {manual_on_original: a1, manual_on_copy: b1}

    archived = conn.execute(
        """SELECT id, kept_transaction_id FROM migration_v200_cn_duplicate_transactions
           ORDER BY id"""
    ).fetchall()
    assert archived == [(k1, a1), (k2, a2), (kb, b1)]
    assert conn.execute(
        "SELECT id, kept_transaction_id FROM migration_v200_cn_duplicate_trade_logs"
    ).fetchall() == [(imported_dup, a1)]

    # Re-running finds no pairs and changes nothing.
    conn.execute("DELETE FROM schema_version WHERE version = 200")
    conn.run_migrations()
    assert conn._migration_failures == []
    assert len(_ledger(conn)) == 5
    conn.close()


def _fresh(tmp_path, name):
    conn = DatabaseConnector(str(tmp_path / f"{name}.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    conn.execute("DELETE FROM schema_version WHERE version = 200")
    return conn


def test_v200_fails_closed_on_unequal_groups_and_differing_metadata(tmp_path):
    conn = _fresh(tmp_path, "v200_closed")
    # Two key-less orders but one keyed row: which pair is the copy is unknowable.
    u1 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100)
    u2 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100)
    u3 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100, key="key-a")
    # Same economics, different bank card: not the same order.
    c1 = _tx(conn, "2026-01-03", "CN_FUND_B", "buy", 5, 50)
    c2 = _tx(conn, "2026-01-03", "CN_FUND_B", "buy", 5, 50, key="key-b")
    conn.execute("UPDATE transactions SET counterparty = 'card-1' WHERE id = ?", [c1])
    conn.execute("UPDATE transactions SET counterparty = 'card-2' WHERE id = ?", [c2])

    conn.run_migrations()

    assert conn._migration_failures == []
    assert [r[0] for r in _ledger(conn)] == [u1, u2, u3, c1, c2]
    assert conn.execute("SELECT COUNT(*) FROM schema_version WHERE version = 200").fetchone()[0] == 1
    # Recorded, so a later start cannot reinterpret the same rows.
    conn.run_migrations()
    assert [r[0] for r in _ledger(conn)] == [u1, u2, u3, c1, c2]
    conn.close()


def test_v200_keeps_and_repoints_imported_logs_that_carry_anything(tmp_path):
    conn = _fresh(tmp_path, "v200_logs")
    a1 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100)
    k1 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100, key="key-a")
    b1 = _tx(conn, "2026-01-03", "CN_FUND_B", "buy", 5, 50)
    kb = _tx(conn, "2026-01-03", "CN_FUND_B", "buy", 5, 50, key="key-b")
    _log(conn, a1, "manual")
    _log(conn, b1, "manual")
    noted = _log(conn, k1, "imported")
    conn.execute("UPDATE trade_logs SET user_notes = 'checked' WHERE id = ?", [noted])
    linked = _log(conn, kb, "imported")
    conn.execute("INSERT INTO insight_trade_links (insight_id, trade_id, link_type) VALUES (1, ?, 'auto_source')",
                 [linked])

    conn.run_migrations()

    assert conn._migration_failures == []
    logs = dict(conn.execute("SELECT id, linked_transaction_id FROM trade_logs").fetchall())
    assert logs[noted] == a1 and logs[linked] == b1
    assert conn.execute("SELECT COUNT(*) FROM migration_v200_cn_duplicate_trade_logs").fetchone()[0] == 0
    assert [r[0] for r in _ledger(conn)] == [a1, b1]
    conn.close()


def test_v200_resumes_after_a_crash_between_relink_and_fold(tmp_path):
    conn = _fresh(tmp_path, "v200_crash")
    a1 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100)
    a2 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100)
    k1 = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100, key="key-1")
    _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100, key="key-2")
    moved = _log(conn, k1, "manual")

    real_execute = conn.execute

    def crash_on_fold(query, params=()):
        if query.startswith("DELETE FROM transactions WHERE id IN (SELECT keyed_id"):
            raise RuntimeError("simulated crash")
        return real_execute(query, params)

    conn.execute = crash_on_fold
    conn.run_migrations()
    conn.execute = real_execute

    assert conn._migration_failures and "simulated crash" in conn._migration_failures[0]
    assert conn.execute("SELECT COUNT(*) FROM schema_version WHERE version = 200").fetchone()[0] == 0
    assert len(_ledger(conn)) == 4  # fold rolled back; nothing deleted
    assert dict(conn.execute("SELECT id, linked_transaction_id FROM trade_logs").fetchall()) == {moved: a1}

    conn._migration_failures.clear()
    conn.run_migrations()

    assert conn._migration_failures == []
    assert _ledger(conn) == [(a1, "CN_FUND_A", 100.0, "key-1"), (a2, "CN_FUND_A", 100.0, "key-2")]
    conn.close()


def test_v200_is_a_no_op_without_copies(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "v200_clean.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    only = _tx(conn, "2026-01-02", "CN_FUND_A", "buy", 10, 100)

    conn.execute("DELETE FROM schema_version WHERE version = 200")
    conn.run_migrations()

    assert conn._migration_failures == []
    assert _ledger(conn) == [(only, "CN_FUND_A", 100, None)]
    archive_tables = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name LIKE 'migration_v200%'"
    ).fetchone()[0]
    assert archive_tables == 0
    conn.close()
