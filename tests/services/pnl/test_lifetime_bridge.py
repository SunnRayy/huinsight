"""Lifetime P&L bridge arithmetic (audit 2026-11-08 issue 6)."""
import pytest

from src.services.pnl.bridge import UNEXPLAINED_THRESHOLD_CNY, bridge_group, itemise_months


def _group(**kw):
    g = dict(lifetime=0.0, value_now=0.0, v_start=0.0, v_end=0.0, v_last=0.0, flows_window=0.0,
             flows_post_end=0.0, flows_post_last=0.0, flows_dated_all=0.0, flows_today_all=0.0,
             ledger_pre=0.0, ledger_all=0.0, monthly_flows={}, monthly_ledger={})
    g.update(kw)
    return g


def _lines_sum(out):
    return sum(out[k] for k in ("returns_gain_cny", "after_window_cny", "to_today_cny", "fx_cny",
                                "before_window_cny", "remainder_cny"))


def test_usd_source_fx_line_explains_the_whole_gap():
    # $1,000 deposited at 7.0, worth $1,100 at 6.5 today; no other differences.
    g = _group(lifetime=(1100 - 1000) * 6.5, value_now=1100 * 6.5, v_end=1100 * 6.5, v_last=1100 * 6.5,
               flows_window=7000.0, flows_dated_all=7000.0, flows_today_all=6500.0,
               ledger_all=6500.0, monthly_flows={"2026-01": 6500.0}, monthly_ledger={"2026-01": 6500.0})
    out = bridge_group(g)
    assert out["returns_gain_cny"] == pytest.approx(150.0)    # 7150 − 7000
    assert out["fx_cny"] == pytest.approx(500.0)              # money in counted 500 lower today
    assert out["remainder_cny"] == pytest.approx(0.0)
    assert _lines_sum(out) == pytest.approx(out["overview_lifetime_cny"])
    assert out["items"] is None


def test_before_window_gain_and_after_window_moves():
    g = _group(lifetime=300.0, value_now=1300.0, v_start=1050.0, v_end=1200.0, v_last=1250.0,
               flows_dated_all=0.0, flows_today_all=0.0, ledger_pre=1000.0, ledger_all=1000.0)
    out = bridge_group(g)
    assert out["before_window_cny"] == 50.0
    assert out["returns_gain_cny"] == 150.0
    assert out["after_window_cny"] == 50.0
    assert out["to_today_cny"] == 50.0
    assert out["remainder_cny"] == 0.0


def test_large_remainder_is_itemised_and_items_add_up():
    # Returns books a 5,646 contribution in March the ledger nets to zero (gross vs net vest).
    g = _group(lifetime=1000.0, flows_window=4646.0, flows_dated_all=4646.0, flows_today_all=4646.0,
               ledger_all=-1000.0, monthly_flows={"2026-03": 5646.0, "2026-04": -1000.0},
               monthly_ledger={"2026-03": 0.0, "2026-04": -1000.0})
    out = bridge_group(g)
    assert out["remainder_cny"] == pytest.approx(5646.0)
    assert out["remainder_cny"] >= UNEXPLAINED_THRESHOLD_CNY
    assert {"month": "2026-03", "amount_cny": 5646.0, "kind": "money_in_gap"} in out["items"]
    assert sum(i["amount_cny"] for i in out["items"]) == pytest.approx(out["remainder_cny"])
    assert _lines_sum(out) == pytest.approx(out["overview_lifetime_cny"])


def test_itemise_names_big_months_merges_timing_and_pools_small():
    items = itemise_months({"2026-03": 37633.0, "2026-06": -6900.0, "2026-07": 6890.0, "2026-08": 40.0, "2026-09": -300.0})
    big = [i for i in items if i["kind"] == "money_in_gap"]
    timing = [i for i in items if i["kind"] == "timing"]
    small = [i for i in items if i["kind"] == "smaller_differences"]
    assert big == [{"month": "2026-03", "amount_cny": 37633.0, "kind": "money_in_gap"}]
    assert timing[0]["month"] == "2026-06→2026-07" and timing[0]["net_cny"] == -10.0
    assert small[0]["amount_cny"] == pytest.approx(-10.0 + 40.0 - 300.0)
    assert sum(i["amount_cny"] for i in items) == pytest.approx(37633.0 - 6900 + 6890 + 40 - 300)


def test_overview_fx_effect_is_the_bridge_fx_quantity():
    """usd_flow_fx_effect = Σ (dated CNY − native × today) over flows after the window start,
    the same sum build_lifetime_bridge splits into flows_dated_all − flows_today_all."""
    import duckdb
    from src.services.pnl.bridge import usd_flow_fx_effect
    con = duckdb.connect(":memory:")
    assert usd_flow_fx_effect(con.execute("CREATE TABLE investment_twr_source(id INT, coverage_start DATE)")
                              or con, 6.5) is None
    con.execute("INSERT INTO investment_twr_source VALUES (1, '2019-11-30')")
    con.execute("CREATE TABLE investment_external_flows(event_date DATE, amount_cny DECIMAL(20,2), "
                "original_amount DECIMAL(20,2), original_currency VARCHAR)")
    con.execute("INSERT INTO investment_external_flows VALUES ('2020-01-10', 700, 100, 'USD'), "
                "('2021-01-10', -360, -50, 'USD'), ('2020-01-10', 999, 999, 'CNY'), ('2019-11-30', 70, 10, 'USD')")
    assert usd_flow_fx_effect(con, 6.5) == pytest.approx((700 - 650) + (-360 + 325))
