"""Shared allocation and presentation facts for advisor and exported context."""

import logging

logger = logging.getLogger(__name__)

LATEST_PER_ASSET_CTE = """
    latest_per_asset AS (
        SELECT asset_id, MAX(snapshot_date) AS latest_date
        FROM holdings WHERE is_shadow = FALSE GROUP BY asset_id
    )
"""


def build_context_allocation(db):
    """Profile targets and current weights share the rebalanceable denominator."""
    top_targets, sub_targets = {}, {}
    try:
        targets = db.execute('''
            SELECT COALESCE(parent_tc.name, tc.name) as top_class,
                   tc.name as sub_class, rpa.target_pct
            FROM risk_profile_allocations rpa
            JOIN taxonomy_classes tc ON rpa.class_id = tc.id
            LEFT JOIN taxonomy_classes parent_tc ON tc.parent_id = parent_tc.id
            JOIN risk_profiles rp ON rpa.profile_id = rp.id
            WHERE rp.is_active = TRUE
        ''').fetchall()
        for top, sub, pct in targets:
            if pct is not None:
                sub_targets[sub] = float(pct)
                top_targets[top] = top_targets.get(top, 0.0) + float(pct)
    except Exception:
        logger.warning('Context allocation targets unavailable', exc_info=True)
    base = f'''
        WITH {LATEST_PER_ASSET_CTE}
        SELECT {{columns}}, SUM(h.market_value) as val
        FROM holdings h
        JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
        LEFT JOIN asset_registry r ON h.asset_id = r.canonical_id
        LEFT JOIN taxonomy_classes tc ON r.asset_class = tc.name
        LEFT JOIN taxonomy_classes parent_tc ON tc.parent_id = parent_tc.id
        WHERE h.is_shadow = FALSE
          AND COALESCE(tc.is_rebalanceable, r.is_rebalanceable, TRUE) = {{included}}
        GROUP BY {{groups}}
        ORDER BY val DESC
    '''
    top_column = "COALESCE(parent_tc.name, tc.name, r.asset_class, 'Unclassified') as top_class"
    top_rows = db.execute(base.format(columns=top_column, included='TRUE', groups='top_class')).fetchall()
    sub_rows = db.execute(base.format(
        columns=top_column + ", COALESCE(tc.name, r.asset_class, 'Unclassified') as sub_class",
        included='TRUE', groups='top_class, sub_class')).fetchall()
    excluded = db.execute(base.format(columns=top_column, included='FALSE', groups='top_class')).fetchall()
    total = sum(float(value or 0) for _, value in top_rows)

    def fact(cls, value, target):
        value = float(value or 0)
        pct = value / total * 100 if total else 0.0
        return dict(asset_class=cls, current_value=value, current_pct=pct,
                    target_pct=target, drift_pct=pct - target if target is not None else None)

    return {
        'top': [fact(cls, value, top_targets.get(cls)) for cls, value in top_rows],
        'sub': [dict(fact(sub, value, sub_targets.get(sub)), top_class=top) for top, sub, value in sub_rows],
        'excluded': excluded,
    }


def format_account_risk(risk):
    """Risk values use percent units; drawdown is displayed as a loss."""
    lines = [f"- Account Risk: {risk.get('quality', 'unavailable')} "
             f"(scope: {risk.get('scope', 'investment_accounts')}; sampling: monthly; "
             f"{risk.get('period_start') or 'N/A'} to {risk.get('as_of') or 'N/A'})"]
    for label, key, pct in (
        ('Total Return (Historical)', 'total_return', True),
        ('Volatility (Annualized)', 'volatility_annual', True),
        ('Max Drawdown', 'max_drawdown', True),
        ('Sharpe Ratio', 'sharpe_ratio', False),
        ('Sortino Ratio', 'sortino_ratio', False),
        ('Calmar Ratio', 'calmar_ratio', False),
    ):
        value = risk.get(key)
        if key == 'max_drawdown' and value is not None:
            value = -abs(value)
        cell = f"{value:.2f}{'%' if pct else ''}" if value is not None else 'N/A'
        lines.append(f'- {label}: {cell}')
    lines.append(f"- Data Points: {risk.get('data_points', 0)} monthly returns")
    if risk.get('reason'):
        lines.append(f"- Risk availability: {risk['reason']}")
    return '\n'.join(lines)


def short_market_history(payload):
    """Render up to five dated values from the cache's supported feed shapes."""
    history = payload if isinstance(payload, list) else None
    if isinstance(payload, dict):
        historical = payload.get('fear_and_greed_historical')
        sources = [payload, historical] if isinstance(historical, dict) else [payload]
        history = next((source[key] for source in sources
                        for key in ('history', 'observations', 'data')
                        if isinstance(source.get(key), list) and source[key]), None)
    if not isinstance(history, list):
        return ''
    observations = []
    for item in history:
        if isinstance(item, dict):
            value = next((item[key] for key in ('value', 'y', 'close') if key in item), None)
            when = next((item[key] for key in ('date', 'timestamp', 'x') if key in item), '')
            if isinstance(value, (str, int, float)):
                observations.append((str(when), f'{str(when)[:24]}: {str(value)[:24]}'))
        elif isinstance(item, (str, int, float)):
            observations.append(('', str(item)[:48]))
    if any(when for when, _ in observations):
        observations.sort(key=lambda row: row[0])
    return ', '.join(value for _, value in observations[-5:])


# Normalize aliases before ranking; a newer non-estimable snapshot must not
# revive an old valuation. Exact date ties are resolved deterministically.
LATEST_VALUATIONS_CTE = '''
    ranked AS (
        SELECT *, REPLACE(UPPER(TRIM(ticker)), '/', '-') AS normalized_ticker,
               ROW_NUMBER() OVER (
                   PARTITION BY REPLACE(UPPER(TRIM(ticker)), '/', '-')
                   ORDER BY snapshot_date DESC, created_at DESC, id DESC, ticker
               ) AS rn
        FROM valuation_snapshots
    ), latest AS (
        SELECT * FROM ranked
        WHERE rn = 1 AND is_estimable = TRUE
          AND (snapshot_date >= CURRENT_DATE - INTERVAL '60 days'
               OR NOT EXISTS (
                   SELECT 1 FROM ranked fresh
                   WHERE fresh.snapshot_date >= CURRENT_DATE - INTERVAL '60 days'
               ))
    )
'''
