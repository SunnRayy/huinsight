"""Backup retention and verified gzip conversion; no database connections."""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BackupItem = tuple[str, datetime, int]
RETENTION_FLOOR = 8


def backup_timestamp(name: str, fallback: datetime) -> datetime:
    """Prefer original snapshot time over a compression/upload modification time."""
    patterns = (
        (r'(\d{8}T\d{6}\d*Z)', '%Y%m%dT%H%M%S%fZ'),
        (r'(\d{8}_\d{6})', '%Y%m%d_%H%M%S'),
        (r'(\d{4}-\d{2}-\d{2}_\d{6})', '%Y-%m-%d_%H%M%S'),
    )
    for pattern, fmt in patterns:
        match = re.search(pattern, Path(name).name)
        if match:
            try:
                value = match.group(1)
                if 'T' in value and len(value) == 16:
                    fmt = '%Y%m%dT%H%M%SZ'
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return fallback.astimezone(timezone.utc)


DAILY_DAYS = 30
WEEKLY_WEEKS = 8
MONTHLY_MONTHS = 24


def _base_name(name: str) -> str:
    return name[:-3] if name.endswith('.gz') else name


def plan_retention(items: list[BackupItem], now: datetime) -> tuple[list[BackupItem], list[BackupItem]]:
    """Union of daily/ISO-week/month representatives; named 180d + newest 3.

    Windows include the current calendar period. Small collections (<=8) and
    unknown filenames are preserved. Future timestamps are never pruned.

    An original and its verified `.gz` sibling are ONE backup: they are kept or
    deleted together. Removing only the original is the job of the explicit
    `--compress-existing --execute --delete-originals` path, never of pruning.
    """
    groups: dict[str, list[BackupItem]] = {}
    for it in items:
        groups.setdefault(_base_name(it[0]), []).append(it)
    representatives = [max(group, key=lambda it: it[0].endswith('.gz')) for group in groups.values()]
    keep_rep, delete_rep = _plan_representatives(representatives, now)
    def expand(reps):
        return sorted((m for r in reps for m in groups[_base_name(r[0])]),
                      key=lambda it: (it[1], it[0]), reverse=True)

    return expand(keep_rep), expand(delete_rep)


def _plan_representatives(items: list[BackupItem], now: datetime) -> tuple[list[BackupItem], list[BackupItem]]:
    ranked = sorted(items, key=lambda it: (it[1], it[0]), reverse=True)
    if len(ranked) <= RETENTION_FLOOR:
        return ranked, []
    now = now.astimezone(timezone.utc)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    named = [it for it in ranked if '/named/' in it[0] or '_named_' in Path(it[0]).name]
    protected = {it[0] for it in named[:3]}
    seen_days, seen_weeks, seen_months = set(), set(), set()
    keep, delete = [], []
    for it in ranked:
        name, ts, _ = it
        ts = ts.astimezone(timezone.utc)
        day = ts.date()
        if '_KEEP' in name or ts > now or not name.endswith(('.duckdb', '.duckdb.gz')):
            retain = True
        elif it in named:
            retain = name in protected or ts >= now - timedelta(days=180)
        else:
            week = day - timedelta(days=day.weekday())
            month = (day.year, day.month)
            month_age = (today.year - day.year) * 12 + today.month - day.month
            retain = (
                (0 <= (today - day).days < DAILY_DAYS and day not in seen_days)
                or (0 <= (week_start - week).days < WEEKLY_WEEKS * 7 and week not in seen_weeks)
                or (0 <= month_age < MONTHLY_MONTHS and month not in seen_months)
            )
            seen_days.add(day)
            seen_weeks.add(week)
            seen_months.add(month)
        (keep if retain else delete).append(it)
    return keep, delete


def sha256_file(path: Path, *, compressed: bool = False) -> str:
    digest = hashlib.sha256()
    opener = gzip.open if compressed else open
    with opener(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def gzip_copy(source: Path, destination: Path) -> None:
    """Create a new gzip at level 6. Caller owns temporary-file cleanup."""
    with source.open('rb') as src, gzip.open(destination, 'wb', compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)


def compress_backup(source: Path, *, execute: bool = False, delete_originals: bool = False) -> Path:
    """Create and verify a gzip sibling atomically, without overwriting a sibling."""
    dest = Path(str(source) + '.gz')
    if dest.exists():
        raise FileExistsError(dest)
    if not execute:
        print(f'[DRY-RUN] compress {source} -> {dest}; delete original={delete_originals}')
        return dest
    with tempfile.TemporaryDirectory(prefix='uis-gzip-', dir=source.parent) as work:
        staged = Path(work) / 'backup.gz'
        gzip_copy(source, staged)
        if sha256_file(source) != sha256_file(staged, compressed=True):
            raise ValueError(f'SHA-256 mismatch: {source}')
        shutil.copystat(source, staged)
        os.link(staged, dest)  # exclusive publication: cannot overwrite a concurrent sibling
    print(f'{source}: {source.stat().st_size} -> {dest.stat().st_size} bytes; SHA-256 verified')
    if delete_originals and "_KEEP" not in source.name:
        source.unlink()
    return dest
