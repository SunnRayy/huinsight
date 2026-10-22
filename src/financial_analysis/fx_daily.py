"""Dated USDCNY observations. Derivation reads the cache; only sync fetches."""
import logging
import math
import os
from datetime import timedelta

from src.financial_analysis.twr import _to_date
from src.utils.http_client import http_get

logger = logging.getLogger(__name__)


def lookup_fx(db, event_date):
    day = _to_date(event_date)
    row = db.execute(
        "SELECT date, rate FROM fx_daily WHERE pair = 'USDCNY' AND date <= ? "
        "AND date >= ? AND rate > 0 ORDER BY date DESC LIMIT 1",
        [day, day - timedelta(days=5)],
    ).fetchone()
    return (row[0], float(row[1])) if row else None


def cache_fred_fx(db, start, end):
    """Cache every published observation; absent/error observations stay unavailable."""
    key = os.environ.get('FRED_API_KEY')
    if not key:
        logger.warning('Dated FX unavailable: FRED_API_KEY is not configured')
        return 0
    try:
        # DEXCHUS units are Chinese yuan per one US dollar; no inversion.
        # see docs/architecture/data-sources.md Change Log
        response = http_get('https://api.stlouisfed.org/fred/series/observations', params={
            'series_id': 'DEXCHUS', 'api_key': key, 'file_type': 'json',
            'observation_start': str(_to_date(start) - timedelta(days=5)),
            'observation_end': str(_to_date(end)),
        }, timeout=15)
        response.raise_for_status()
        observations = response.json()['observations']
        rows = []
        for item in observations:
            if item['value'] == '.':
                continue
            day, rate = _to_date(item['date']), float(item['value'])
            if math.isfinite(rate) and rate > 0 and _to_date(start) - timedelta(days=5) <= day <= _to_date(end):
                rows.append((day, rate))
    except Exception:
        logger.exception('FRED dated FX fetch failed; no current-rate fallback')
        return 0
    for day, rate in rows:
        db.execute("INSERT INTO fx_daily VALUES (?, 'USDCNY', ?, 'FRED:DEXCHUS') "
                   "ON CONFLICT(date, pair) DO NOTHING", [day, rate])
    return len(rows)
