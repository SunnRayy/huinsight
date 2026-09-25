"""Tests for process-local market-data refresh de-duplication."""

from threading import Event, Thread

import pytest

from src.market_data import refresh_guard


@pytest.fixture(autouse=True)
def reset_guard(monkeypatch):
    monkeypatch.setenv("UIS_MARKET_DATA_REFRESH_COOLDOWN_SECONDS", "300")
    refresh_guard.reset_for_tests()
    yield
    refresh_guard.reset_for_tests()


def test_recent_completed_refresh_is_reused():
    calls = 0

    def refresh():
        nonlocal calls
        calls += 1
        return {"refreshed": 141, "errors": 1}

    first = refresh_guard.run_guarded_refresh(refresh)
    second = refresh_guard.run_guarded_refresh(refresh)

    assert calls == 1
    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert second["deduplication_reason"] == "recent_refresh"
    assert second["refreshed"] == 141


def test_concurrent_refresh_is_rejected_while_work_is_in_flight():
    started = Event()
    release = Event()
    first_result = []

    def refresh():
        started.set()
        release.wait(timeout=2)
        return {"refreshed": 1}

    worker = Thread(target=lambda: first_result.append(refresh_guard.run_guarded_refresh(refresh)))
    worker.start()
    assert started.wait(timeout=2)

    with pytest.raises(refresh_guard.RefreshInProgress):
        refresh_guard.run_guarded_refresh(refresh)

    release.set()
    worker.join(timeout=2)
    assert first_result == [{"refreshed": 1, "deduplicated": False}]
