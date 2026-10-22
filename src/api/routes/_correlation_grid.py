"""Common-period grid for GET /risk/correlation (issue #34).

Why this module exists
----------------------
Each reader stamps its own ``snapshot_date`` from its own source file, and
``src/services/freshness.py`` documents two cadence tiers: 'fast' classes with a
daily price feed (stocks, ETFs, CN funds, gold) and 'slow' snapshot-only classes
(insurance, pension, property, Financial-Summary balance-sheet items) that are
refreshed on an infrequent cadence.

The endpoint used to compute returns with ``pivot.pct_change(fill_method=None)``
directly on those raw snapshot dates. ``pct_change`` shifts by one row of the
*union* index, so a class produced a usable return only when it happened to be
stamped on two **adjacent** union dates. Put one daily class in the portfolio and
the union index becomes daily; every coarser class then has a daily row sitting
between each of its own observations, and yields *zero* returns — not "too few",
zero. Measured on a realistic mixed-cadence portfolio: a class with 57 snapshots
produced 0 usable returns, and widening the window from 180 days to 10 years did
not change that (still 0). It is a structural defect, not a tuning problem.

What this module does
---------------------
It aligns every class onto one common period grid before differencing, choosing
the grid from the data: the finest period the *slowest* class can actually
populate. Both sides of a pair are then measured over the same horizon, which is
the only way the resulting Pearson r means what the UI says it means.

What it deliberately does NOT do
--------------------------------
It does not forward-fill a slow class onto a finer grid. That is the tempting
fix and it is a fabrication: carrying a monthly value across weekly bins emits
three zero-returns for every real one, which drags the correlation toward zero.
Measured against a known ground truth (rho = 0.65 by construction), weekly bins
with carried values reported **+0.08** — a confident, wrong number where the
honest answer was an en-dash. Resampling both classes to the period the slower
one supports recovered **+0.650**, exact to three decimals, across 40 seeds.

This project has already paid for fabricated confidence once (commit c085931
removed hard zeros that ``/risk/metrics`` returned but never computed). Trading
an honest "–" for a plausible number is a regression here, not a fix.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Grid selection: the slowest class's median inter-snapshot gap picks the period.
GRID_DAILY_MAX_GAP_DAYS = 3.0
GRID_WEEKLY_MAX_GAP_DAYS = 10.0

# Nominal length of one bin, used to scale the window and the jump thresholds.
PERIOD_DAYS: Dict[str, float] = {"D": 1.0, "W-FRI": 7.0, "ME": 30.44}

# Human-facing labels (translated in the UI via riskMatrix.grid.*).
GRID_LABELS: Dict[str, str] = {"D": "daily", "W-FRI": "weekly", "ME": "monthly"}

# A coarser grid needs a longer lookback to reach a usable number of periods.
TARGET_PERIODS = 24
MAX_WINDOW_DAYS = 1100          # ~3 years — the ceiling on any auto-widened window

# A carry may bridge at most this many consecutive empty bins.
MAX_CARRY_BINS = 1

# sqrt(period) scaling of the jump thresholds, capped so a monthly grid does not
# stop flagging genuine structural breaks.
JUMP_PERIOD_SCALE_CAP = 3.0


def detect_grid_frequency(raw: pd.DataFrame) -> Tuple[str, float]:
    """Pick the finest grid the slowest class can still populate.

    Uses each class's *median* inter-observation gap (robust to a single long
    outage) and takes the maximum across classes: the grid has to work for the
    slowest series in the matrix, or that series contributes nothing.

    Returns ``(pandas_freq, median_gap_days_of_slowest_class)``.
    """
    gaps: List[float] = []
    for col in raw.columns:
        obs_index = raw[col].dropna().index
        if len(obs_index) < 2:
            continue
        deltas = np.diff(obs_index.values).astype("timedelta64[D]").astype(float)
        deltas = deltas[deltas > 0]
        if deltas.size:
            gaps.append(float(np.median(deltas)))
    if not gaps:
        return "D", 1.0
    slowest = max(gaps)
    if slowest <= GRID_DAILY_MAX_GAP_DAYS:
        return "D", slowest
    if slowest <= GRID_WEEKLY_MAX_GAP_DAYS:
        return "W-FRI", slowest
    return "ME", slowest


def window_days_for(freq: str, floor_days: int) -> int:
    """Scale the lookback so the chosen grid yields a usable number of periods.

    A monthly grid cannot produce 8 return periods out of 180 days — six
    snapshots is five returns, and no amount of data inside that window changes
    it. The window is therefore a floor, not a fixed span.
    """
    period_days = PERIOD_DAYS.get(freq, 1.0)
    needed = math.ceil(TARGET_PERIODS * period_days * 1.15)
    return int(min(max(floor_days, needed), MAX_WINDOW_DAYS))


def jump_scale_for(freq: str) -> float:
    """Rescale the daily-calibrated jump thresholds to the grid period.

    ``CORR_JUMP_ABS_FLOOR = 0.30`` means "a 30% move in one period". On a monthly
    grid that flags ordinary behaviour — a cash balance routinely swings more
    than 30% between month-end valuations as salary lands and spending clears —
    so the floor is scaled by sqrt(period) under a random-walk assumption.
    """
    return float(min(math.sqrt(PERIOD_DAYS.get(freq, 1.0)), JUMP_PERIOD_SCALE_CAP))


def build_grid(
    raw: pd.DataFrame, freq: str, carry_bins: int = MAX_CARRY_BINS
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Bin the raw class levels onto ``freq``.

    Returns ``(levels, real_mask, obs_dates)``:

    * ``levels``    — last **real** observation inside each bin, then carried
      forward across at most ``carry_bins`` empty bins. ``ffill`` leaves leading
      NaN untouched, so no value is ever invented before a class's first real
      snapshot; that guarantee is structural, not a special case.
    * ``real_mask`` — True where the class had at least one raw snapshot in the bin.
    * ``obs_dates`` — the calendar date behind each level, for the timing-lag metric.
    """
    binned = raw.resample(freq).last()
    real_mask = raw.notna().resample(freq).sum() > 0
    stamped = pd.DataFrame(
        {
            col: np.where(raw[col].notna(), raw.index.values, np.datetime64("NaT"))
            for col in raw.columns
        },
        index=raw.index,
    )
    obs_dates = stamped.resample(freq).last()
    levels = binned.ffill(limit=carry_bins) if carry_bins > 0 else binned
    return levels, real_mask, obs_dates


def classify_returns(
    levels: pd.DataFrame, real_mask: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame, int]:
    """Difference the gridded levels, keeping only returns backed by an observation.

    Three cases, and only the first two are emitted:

    * **real**       — both endpoints observed in their own bin.
    * **bridged**    — the numerator is a real observation, the denominator is a
      carried value. This is a legitimate return *from* the last known level *to*
      a new one; it is emitted, counted, and disclosed.
    * **fabricated** — the numerator itself is a carry, so the "return" is
      identically 0.0. Never emitted. This is the rule that stops a class which
      stopped reporting three months ago from manufacturing twelve zero-returns,
      sailing past the min-overlap gate, and printing a confident 0.00 built from
      nothing at all.

    Returns ``(returns, is_bridged, fabricated_count)``.
    """
    raw_returns = levels.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    prev_real = real_mask.shift(1, fill_value=False)
    prev_level_known = levels.shift(1).notna()

    is_real = real_mask & prev_real
    is_bridged = real_mask & (~prev_real) & prev_level_known

    fabricated = int(((~real_mask) & raw_returns.notna()).to_numpy().sum())
    returns = raw_returns.where(is_real | is_bridged)
    return returns, (is_bridged & returns.notna()), fabricated


def intra_period_lag_days(obs_dates: pd.DataFrame) -> Tuple[int, float]:
    """How far apart two classes' observations sit *inside* one bin.

    A monthly bin holding an equity value from the 2nd and a pension value from
    the 30th is comparing returns measured over materially different sub-spans.
    Reported so the UI can say so rather than implying perfect synchronisation.
    """
    if obs_dates.empty or obs_dates.shape[1] < 2:
        return 0, 0.0
    spread = (obs_dates.max(axis=1) - obs_dates.min(axis=1)).dt.days.dropna()
    if spread.empty:
        return 0, 0.0
    return int(spread.max()), float(spread.mean())


def class_evidence(raw: pd.DataFrame) -> Dict[str, Dict[str, Optional[str]]]:
    """Per-class cadence and recency, so staleness is visible per class.

    ``window_end`` is the newest snapshot across *all* classes, which on a mixed
    portfolio is always a daily class's date. Without this, a class whose newest
    real observation is five months old looks as current as the broker feed.
    """
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for col in raw.columns:
        obs_index = raw[col].dropna().index
        if len(obs_index) == 0:
            out[str(col)] = {
                "observations": 0,
                "median_gap_days": None,
                "first_observed": None,
                "last_observed": None,
            }
            continue
        if len(obs_index) >= 2:
            deltas = np.diff(obs_index.values).astype("timedelta64[D]").astype(float)
            deltas = deltas[deltas > 0]
            median_gap = float(np.median(deltas)) if deltas.size else None
        else:
            median_gap = None
        out[str(col)] = {
            "observations": int(len(obs_index)),
            "median_gap_days": round(median_gap, 1) if median_gap is not None else None,
            "first_observed": obs_index.min().date().isoformat(),
            "last_observed": obs_index.max().date().isoformat(),
        }
    return out
