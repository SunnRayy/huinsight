from datetime import datetime, timedelta, timezone

from src.storage import backup_history as history


NOW = datetime(2026, 1, 5, 20, tzinfo=timezone.utc)


def item(age, name=None):
    ts = NOW - timedelta(days=age)
    return (name or f'backups/{ts:%Y%m%dT%H%M%SZ}_unified.duckdb.gz', ts, 100)


def test_busy_day_and_daily_window():
    items = [item(d) for d in range(7)]
    items += [(f'backups/duplicate-{h}.duckdb', NOW.replace(hour=h), 1) for h in range(12)]
    keep, delete = history.plan_retention(items, NOW)
    assert len(keep) == 7
    assert len(delete) == 12
    assert item(0) in keep


def test_iso_year_boundary_and_gaps():
    items = [item(d) for d in (0, 7, 8, 14, 28, 35, 49, 50, 200, 210)]
    keep, delete = history.plan_retention(items, NOW)
    assert item(7) in keep  # ISO 2026 week 1 starts in 2025
    assert item(8) in keep  # previous ISO week
    assert item(14) in keep  # inside the 30-day daily window
    assert item(49) in keep
    assert item(50) in delete
    assert item(200) in keep  # monthly representative, gaps do not consume slots
    assert item(210) in delete


def test_month_window_named_floor_and_keep():
    items = [item(900 + d) for d in range(9)]
    named = [item(300 + d, f'backups/named/{d}.duckdb.gz') for d in range(5)]
    recent = item(179, 'local_named_recent.duckdb')
    protected = item(1000, 'old_KEEP.duckdb.gz')
    keep, delete = history.plan_retention(items + named + [recent, protected], NOW)
    assert protected in keep and recent in keep
    assert all(n in keep for n in named[:2])  # recent is the newest named; newest three total
    assert all(n in delete for n in named[2:])
    assert all(i in delete for i in items)
    assert history.plan_retention(items[:8], NOW)[1] == []


def test_calendar_month_boundary():
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    dates = [datetime(2024, 11, 1, tzinfo=timezone.utc), datetime(2024, 10, 31, tzinfo=timezone.utc)]
    items = [(f'{i}.duckdb', t, 1) for i, t in enumerate(dates)]
    items += [(f'busy{i}.duckdb.gz', now + timedelta(seconds=i), 1) for i in range(9)]
    keep, delete = history.plan_retention(items, now + timedelta(seconds=10))
    assert items[0] in keep and items[1] in delete


def test_named_180_day_boundary_and_permanent_preservation():
    items = [item(900 + d) for d in range(9)]
    named = [item(d, f'backups/named/{d}.duckdb.gz') for d in (0, 1, 2, 180, 181)]
    keep, delete = history.plan_retention(items + named, NOW)
    assert named[3] in keep and named[4] in delete
    protected = item(1000, 'backups/ancient_KEEP.duckdb')
    keep, _ = history.plan_retention(items + [protected], NOW)
    assert protected in keep


def test_preserves_timestamps_after_conversion():
    assert history.backup_timestamp('backups/20251231T235959123456Z_unified.duckdb.gz', NOW) == datetime(
        2025, 12, 31, 23, 59, 59, 123456, tzinfo=timezone.utc)
    assert history.backup_timestamp('pre-pull-20251231_235959.duckdb.gz', NOW).date().isoformat() == '2025-12-31'
    assert history.backup_timestamp('20251231T235959Z_unified.duckdb.gz', NOW).second == 59


def test_daily_window_is_30_days():
    items = [item(d) for d in range(0, 40)]
    keep, delete = history.plan_retention(items, NOW)
    assert all(item(d) in keep for d in range(30))
    assert item(31) in keep or item(31) in delete  # older days fall to the weekly tier


def test_original_and_gz_sibling_are_one_backup():
    base = [item(d, f'backups/2025{d:02d}_unified.duckdb') for d in range(1, 12)]
    old_orig = item(800, 'backups/20231001T000000Z_unified.duckdb')
    old_gz = (old_orig[0] + '.gz', old_orig[1], 5)
    new_orig = item(0, 'backups/20260105T000000Z_unified.duckdb')
    new_gz = (new_orig[0] + '.gz', new_orig[1], 5)
    keep, delete = history.plan_retention(base + [old_orig, old_gz, new_orig, new_gz], NOW)
    # kept together: pruning never removes only the original of a kept backup
    assert new_orig in keep and new_gz in keep
    # deleted together when the backup itself falls out of every window
    assert old_orig in delete and old_gz in delete
