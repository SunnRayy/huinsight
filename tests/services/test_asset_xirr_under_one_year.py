"""Per-asset XIRR stays annualized under a year and is flagged (owner decision 2026-11-09)."""
from datetime import date

import src.services.pnl.return_measures as rm


def _rows(monkeypatch, *assets):
    monkeypatch.setattr(rm, "build_asset_xirr", lambda db, fx: {"assets": list(assets)})


def test_flag_follows_first_money_in_to_valuation_day(monkeypatch):
    _rows(monkeypatch,
          {"asset_id": "NEW", "currency": "USD", "invested_native": 100, "xirr": 0.4,
           "first_flow": date(2026, 3, 1), "terminal_day": date(2026, 11, 9)},
          {"asset_id": "OLD", "currency": "CNY", "invested_native": 100, "xirr": 0.05,
           "first_flow": date(2025, 11, 9), "terminal_day": date(2026, 11, 9)},
          {"asset_id": "NOFLOW", "currency": "CNY", "invested_native": 0, "xirr": None,
           "first_flow": None, "terminal_day": None})
    out = rm.invested_and_xirr(None, 7.0)
    assert out["NEW"] == (700.0, 0.4, True)
    assert out["OLD"] == (100.0, 0.05, False)
    assert out["NOFLOW"] == (None, None, False)
