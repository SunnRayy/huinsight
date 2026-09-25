"""Process-local single-flight guard for full market-data refreshes."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable


class RefreshInProgress(RuntimeError):
    """Raised when another full portfolio refresh is already running."""


_DEFAULT_COOLDOWN_SECONDS = 300.0
_refresh_lock = threading.Lock()
_last_completed_at: float | None = None
_last_result: dict[str, Any] | None = None


def _cooldown_seconds() -> float:
    raw = os.getenv("UIS_MARKET_DATA_REFRESH_COOLDOWN_SECONDS")
    if raw is None:
        return _DEFAULT_COOLDOWN_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_COOLDOWN_SECONDS


def _recent_result(now: float) -> dict[str, Any] | None:
    if _last_result is None or _last_completed_at is None:
        return None
    if now - _last_completed_at >= _cooldown_seconds():
        return None
    result = dict(_last_result)
    result["deduplicated"] = True
    result["deduplication_reason"] = "recent_refresh"
    return result


def run_guarded_refresh(
    refresh_fn: Callable[[], dict[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Run one full refresh, or return a recent result without fetching again.

    The lock is held for the entire synchronous refresh. Callers that cannot
    acquire it immediately receive ``RefreshInProgress`` instead of waiting on
    the quote providers and tying up request or scheduler capacity.
    """
    global _last_completed_at, _last_result

    recent = None if force else _recent_result(time.monotonic())
    if recent is not None:
        return recent

    if not _refresh_lock.acquire(blocking=False):
        raise RefreshInProgress("market data refresh already in progress")

    try:
        # A caller may have waited only long enough for the previous holder to
        # release the lock. Re-check the cooldown after acquiring it.
        recent = None if force else _recent_result(time.monotonic())
        if recent is not None:
            return recent

        result = dict(refresh_fn())
        result["deduplicated"] = False
        _last_result = dict(result)
        _last_completed_at = time.monotonic()
        return result
    finally:
        _refresh_lock.release()


def reset_for_tests() -> None:
    """Reset process-local state for isolated tests."""
    global _last_completed_at, _last_result
    with _refresh_lock:
        _last_completed_at = None
        _last_result = None
