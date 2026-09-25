"""The grid must recover a correlation that is known by construction.

PR #35 justified choosing a common coarsest-period grid over the obvious
weekly-grid-plus-forward-fill with a benchmark table in its description: forward
fill reported +0.083 against a true 0.650, the shipped method reported 0.650.
The argument is correct and it decided the design — but **no test in that PR
asserted it**, so the single most persuasive piece of evidence could not be
re-run by a reviewer, and a later refactor could silently reintroduce the biased
variant with every existing test still green.

This file makes the claim executable. It deliberately does *not* reproduce the
PR's "mean absolute error 0.000": aggregating ~26 monthly periods from a daily
latent process carries real sampling error, and measuring it independently gives
roughly 0.09. A test asserting 0.000 would be asserting a number that cannot be
true, which is its own kind of fabricated confidence.

What is asserted is the durable part:
  * forward-filling a slow class onto a fine grid is biased hard toward zero
  * the shipped grid recovers the true rho within sampling error
  * the ordering between them is not close
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.api.routes._correlation_grid import (
    build_grid,
    classify_returns,
    detect_grid_frequency,
)

TRUE_RHO = 0.65
SEEDS = 40


def _mixed_cadence_pair(seed: int) -> pd.DataFrame:
    """Two latent daily series with rho fixed by construction.

    `fast` is observed every day (a broker feed); `slow` only at month end (a
    balance-sheet class). The latent correlation is TRUE_RHO regardless of how
    either is observed — which is exactly what a correct method should recover
    and an interpolating one should not.
    """
    rng = np.random.default_rng(seed)
    n = 900
    z1 = rng.standard_normal(n)
    z2 = rng.standard_normal(n)
    r_fast = z1
    r_slow = TRUE_RHO * z1 + np.sqrt(1.0 - TRUE_RHO**2) * z2

    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "fast": 100 * np.exp(np.cumsum(r_fast * 0.01)),
            "slow": 100 * np.exp(np.cumsum(r_slow * 0.01)),
        },
        index=idx,
    )
    month_end = idx[pd.Series(idx).dt.is_month_end.to_numpy()]
    df.loc[~df.index.isin(month_end), "slow"] = np.nan
    return df


def _shipped(df: pd.DataFrame) -> float:
    freq, _ = detect_grid_frequency(df)
    levels, real_mask, _ = build_grid(df, freq)
    returns, _, _ = classify_returns(levels, real_mask)
    return returns["fast"].corr(returns["slow"], min_periods=8)


def _weekly_forward_fill(df: pd.DataFrame) -> float:
    """The rejected alternative, kept here so the rejection stays evidenced."""
    gridded = df.resample("W-FRI").last().ffill()
    returns = gridded.pct_change(fill_method=None)
    return returns["fast"].corr(returns["slow"], min_periods=8)


def _raw_union_pct_change(df: pd.DataFrame) -> float:
    """What the endpoint did before #35 — differencing on the union index."""
    returns = df.pct_change(fill_method=None)
    return returns["fast"].corr(returns["slow"], min_periods=8)


@pytest.fixture(scope="module")
def measured() -> dict[str, list[float]]:
    out: dict[str, list[float]] = {"shipped": [], "weekly_ffill": [], "raw": []}
    for seed in range(SEEDS):
        df = _mixed_cadence_pair(seed)
        out["shipped"].append(_shipped(df))
        out["weekly_ffill"].append(_weekly_forward_fill(df))
        out["raw"].append(_raw_union_pct_change(df))
    return out


def test_the_old_method_produces_nothing_at_all(measured):
    """Anti-vacuity for issue #34 itself: this is not "too few periods", it is
    zero. If this ever starts producing values the fixture no longer reproduces
    the bug and the rest of this file proves nothing."""
    usable = [v for v in measured["raw"] if v == v]  # NaN != NaN
    assert not usable, (
        f"raw union-index pct_change produced {len(usable)}/{SEEDS} values; the "
        "mixed-cadence fixture no longer reproduces issue #34"
    )


def test_the_grid_detects_the_slow_class_cadence():
    freq, gap = detect_grid_frequency(_mixed_cadence_pair(0))
    assert freq == "ME", f"expected a monthly grid for a month-end class, got {freq}"
    assert gap > 10, gap


def test_shipped_grid_recovers_the_true_correlation(measured):
    values = np.array([v for v in measured["shipped"] if v == v])
    assert len(values) == SEEDS, f"only {len(values)}/{SEEDS} seeds produced a value"
    mean_abs_err = float(np.abs(values - TRUE_RHO).mean())
    # Sampling error over ~26 monthly periods is real; measured independently at
    # ~0.09. The bound is loose enough to be stable and far tighter than the
    # bias it is distinguishing from.
    assert mean_abs_err < 0.20, (
        f"grid recovered mean r={values.mean():+.3f} against a true {TRUE_RHO}; "
        f"mean abs error {mean_abs_err:.3f}"
    )


def test_forward_filling_onto_a_finer_grid_is_biased_toward_zero(measured):
    """The rejected design, kept measurable so the rejection cannot rot.

    Carrying a monthly value across weekly bins emits ~3 zero-returns for every
    real one, which drags r toward 0. This is the failure the endpoint must not
    regress into — it would replace an honest en-dash with a confident wrong
    number, the shape `c085931` removed from /risk/metrics.
    """
    values = np.array([v for v in measured["weekly_ffill"] if v == v])
    assert len(values) > 0, "the biased variant produced nothing; test is vacuous"
    assert abs(values.mean()) < 0.30, (
        f"forward-fill mean r={values.mean():+.3f} — expected heavy attenuation "
        "toward zero; if this is no longer true the comparison below is not "
        "measuring what it claims"
    )


def test_the_shipped_grid_beats_forward_fill_and_not_narrowly(measured):
    shipped = np.abs(np.array([v for v in measured["shipped"] if v == v]) - TRUE_RHO).mean()
    ffill = np.abs(np.array([v for v in measured["weekly_ffill"] if v == v]) - TRUE_RHO).mean()
    assert shipped < ffill / 2, (
        f"shipped mean abs error {shipped:.3f} vs forward-fill {ffill:.3f} — the "
        "design decision in PR #35 rests on this gap being large"
    )
