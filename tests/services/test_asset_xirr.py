"""Per-asset XIRR: only histories that explain the holding produce a figure."""
from src.database.connector import DatabaseConnector
from src.database.schema import initialize_schema
from src.services.asset_xirr import build_asset_xirr, xirr


def _db(tmp_path):
    conn = DatabaseConnector(str(tmp_path / "xirr.duckdb"))
    initialize_schema(conn)
    conn.run_migrations()
    return conn


def _tx(conn, day, asset, kind, qty, net, source, currency="CNY"):
    conn.execute(
        """INSERT INTO transactions (transaction_date, asset_id, transaction_type, quantity,
               amount_gross, amount_net, currency, source_system)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [day, asset, kind, qty, net, net, currency, source],
    )


def _hold(conn, day, asset, qty, price, value, source, currency="CNY"):
    conn.execute(
        """INSERT INTO holdings (snapshot_date, asset_id, quantity, market_price_unit,
               market_value, currency, source_system, is_shadow)
           VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)""",
        [day, asset, qty, price, value, currency, source],
    )


def test_xirr_solves_a_simple_year():
    from datetime import date
    assert round(xirr([(date(2025, 1, 1), -100.0), (date(2026, 1, 1), 110.0)]), 4) == 0.10


def test_asset_xirr_measures_complete_histories_and_flags_gaps(tmp_path):
    conn = _db(tmp_path)
    # Complete: 100 shares bought for 100, worth 110 a year later.
    _tx(conn, "2025-01-01", "CN_FUND_A", "buy", 100, 100.0, "CN_Fund_Excel")
    _hold(conn, "2026-01-01", "CN_FUND_A", 100, 1.10, 110.0, "CN_Fund_Excel")
    # Gap: transactions give 100 shares, the holding is 60.
    _tx(conn, "2025-01-01", "CN_FUND_B", "buy", 100, 100.0, "CN_Fund_Excel")
    _hold(conn, "2026-01-01", "CN_FUND_B", 60, 1.0, 60.0, "CN_Fund_Excel")
    # US asset moved Schwab → IBKR: the transfer is not a flow; value = qty × USD price.
    _tx(conn, "2025-01-01", "US_STK_X", "buy", 10, -1000.0, "Schwab_CSV", "USD")
    _tx(conn, "2025-06-01", "US_STK_X", "transfer_out", -10, 0.0, "Schwab_CSV", "USD")
    _tx(conn, "2025-06-01", "US_STK_X", "transfer_in", 10, 0.0, "Broker_IBKR", "USD")
    _hold(conn, "2026-01-01", "US_STK_X", 10, 110.0, 7700.0, "Broker_IBKR", "USD")

    result = build_asset_xirr(conn, 7.0)
    by_id = {a["asset_id"]: a for a in result["assets"]}

    assert round(by_id["CN_FUND_A"]["xirr"], 3) == 0.100
    assert by_id["CN_FUND_B"]["xirr"] is None and not by_id["CN_FUND_B"]["measurable"]
    assert "100.00 shares, holding is 60.00" in by_id["CN_FUND_B"]["reason"]
    assert by_id["US_STK_X"]["currency"] == "USD"
    assert round(by_id["US_STK_X"]["xirr"], 3) == 0.100
    cn = result["by_account"]["CN mutual funds"]
    assert round(cn["xirr"], 3) == 0.100 and round(cn["covered_pct"], 1) == 50.0
    conn.close()


def test_asset_xirr_dates_a_repriced_stale_holding_at_its_price_date(tmp_path):
    # Holdings from 2025-07-01, repriced on 2026-01-01: the 110 is a 2026-01-01 value.
    conn = _db(tmp_path)
    _tx(conn, "2025-01-01", "CN_FUND_A", "buy", 100, 100.0, "CN_Fund_Excel")
    _hold(conn, "2025-07-01", "CN_FUND_A", 100, 1.10, 110.0, "CN_Fund_Excel")
    conn.execute("UPDATE holdings SET price_updated_at = TIMESTAMP '2026-01-01 00:00:00'")

    by_id = {a["asset_id"]: a for a in build_asset_xirr(conn, 7.0)["assets"]}

    assert round(by_id["CN_FUND_A"]["xirr"], 3) == 0.100  # not ~21%, the snapshot-dated figure
    conn.close()


def test_paper_gold_interest_adds_grams_without_cash(tmp_path):
    # 结息 credits grams; its 金额 is their value, not cash received.
    conn = _db(tmp_path)
    _tx(conn, "2025-01-01", "ALTS_GOLD_X", "buy", 100, 100.0, "Gold_Excel")
    _tx(conn, "2025-06-01", "ALTS_GOLD_X", "interest", 2, 2.0, "Gold_Excel")
    _hold(conn, "2026-01-01", "ALTS_GOLD_X", 102, 1.078431, 110.0, "Gold_Excel")

    gold = {a["asset_id"]: a for a in build_asset_xirr(conn, 7.0)["assets"]}["ALTS_GOLD_X"]

    assert gold["measurable"]
    assert round(gold["xirr"], 3) == 0.100  # 100 in, 110 out; the interest is not cash
    conn.close()
