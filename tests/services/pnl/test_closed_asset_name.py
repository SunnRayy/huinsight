"""Closed positions show the registry's display name, not the bare id.

The transaction ledger stores asset_name = asset_id for most closed assets (no
holdings row is left to carry a name), so WealthOS listed closed funds as
CN_FUND_xxxxxx. closed_asset_meta now falls back to asset_registry.display_name.
"""
import duckdb

from src.services.pnl.snapshot import closed_asset_meta


def _db():
    db = duckdb.connect(":memory:")
    db.execute("CREATE TABLE taxonomy_classes (id INTEGER, name VARCHAR, parent_id INTEGER)")
    db.execute(
        "CREATE TABLE asset_registry (canonical_id VARCHAR, display_name VARCHAR, asset_class VARCHAR)"
    )
    db.execute("CREATE TABLE transactions (asset_id VARCHAR, asset_name VARCHAR)")
    db.execute("INSERT INTO taxonomy_classes VALUES (1, 'Equity', NULL), (2, 'CN Equity', 1)")
    db.execute(
        "INSERT INTO asset_registry VALUES "
        "('CN_FUND_000001', '示例指数基金A', 'CN Equity'), "
        "('CN_FUND_000002', '示例混合A', 'CN Equity'), "
        "('CN_FUND_900001', '', 'CN Equity')"
    )
    db.execute(
        "INSERT INTO transactions VALUES "
        "('CN_FUND_000001', 'CN_FUND_000001'), "    # ledger name is just the id
        "('CN_FUND_000002', '账本里的名称'), "         # ledger has a real name
        "('CN_FUND_900001', 'CN_FUND_900001'), "    # registry name blank
        "('CN_FUND_900002', NULL)"                  # no registry row, no name
    )
    return db


def test_id_only_ledger_name_falls_back_to_registry_display_name():
    meta = closed_asset_meta(_db(), ["CN_FUND_000001"])
    assert meta["CN_FUND_000001"]["name"] == "示例指数基金A"


def test_real_ledger_name_is_kept():
    meta = closed_asset_meta(_db(), ["CN_FUND_000002"])
    assert meta["CN_FUND_000002"]["name"] == "账本里的名称"


def test_blank_registry_name_keeps_the_ledger_value():
    meta = closed_asset_meta(_db(), ["CN_FUND_900001"])
    assert meta["CN_FUND_900001"]["name"] == "CN_FUND_900001"


def test_no_registry_row_and_no_name_stays_none():
    meta = closed_asset_meta(_db(), ["CN_FUND_900002"])
    assert meta["CN_FUND_900002"]["name"] is None
