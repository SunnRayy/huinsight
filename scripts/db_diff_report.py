#!/usr/bin/env python3
"""Read-only before/after database report. No bootstrap, migrations or audit writes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.connector import DatabaseConnector
from src.services.pnl.snapshot import _latest_holdings_cte
from src.validation.data_integrity_gate import is_blocking, run_integrity_checks


def inspect_database(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    with DatabaseConnector(str(path.resolve()), read_only=True) as db:
        tables = db.execute("""
            SELECT table_schema, table_name FROM information_schema.tables
            WHERE table_type = 'BASE TABLE' ORDER BY table_schema, table_name
        """).fetchall()
        counts = {}
        for schema, table in tables:
            quoted = '.'.join('"' + part.replace('"', '""') + '"' for part in (schema, table))
            counts[f'{schema}.{table}'] = db.execute(f'SELECT COUNT(*) FROM {quoted}').fetchone()[0]
        # Reuse the P&L service's current per-asset snapshot selection. market_value is CNY.
        cte, params = _latest_holdings_cte(None)
        net_worth = db.execute(cte + """
            SELECT SUM(h.market_value) FROM holdings h
            JOIN latest_per_asset lpa ON h.asset_id = lpa.asset_id AND h.snapshot_date = lpa.latest_date
            WHERE h.is_shadow = FALSE
        """, params).fetchone()[0]
        report = run_integrity_checks(db, log_audit=False)
    return {'counts': counts, 'net_worth': float(net_worth or 0), 'integrity': report}


def integrity_summary(report) -> str:
    blocking = sum(is_blocking(c.name) for c in report.failed_checks)
    return (f'{report.passed_count}/{len(report.checks)} passed, {report.skipped_count} skipped, '
            f'{blocking} blocking failures, {len(report.failed_checks) - blocking} advisory failures')


def _cell(value) -> str:
    return str(value).replace('|', '\\|').replace('\n', ' ')


def diff_report(old: Path, new: Path) -> int:
    before, after = inspect_database(old), inspect_database(new)
    print('# Database change report\n')
    print('| Table (changed only) | OLD rows | NEW rows | Delta |')
    print('| --- | ---: | ---: | ---: |')
    for table in sorted(before['counts'].keys() | after['counts'].keys()):
        a, b = before['counts'].get(table, 0), after['counts'].get(table, 0)
        if a != b or table not in before['counts'] or table not in after['counts']:
            print(f'| {_cell(table)} | {a} | {b} | {b-a:+d} |')
    a, b = sum(before['counts'].values()), sum(after['counts'].values())
    print(f'| **Total** | {a} | {b} | {b-a:+d} |')
    print(f'\nActive net worth (CNY): {before["net_worth"]:,.2f} → {after["net_worth"]:,.2f}')
    print('\n| Integrity check | OLD | NEW | NEW details |\n| --- | --- | --- | --- |')
    for a, b in zip(before['integrity'].checks, after['integrity'].checks):
        def status(c):
            return 'SKIP' if c.skipped else ('PASS' if c.passed else 'FAIL')
        print(f'| {b.name} | {status(a)} | {status(b)} | {_cell(b.details)} |')
    print(f'\nOLD: {integrity_summary(before["integrity"])}')
    print(f'\nNEW: {integrity_summary(after["integrity"])}')
    return int(any(is_blocking(c.name) for c in after['integrity'].failed_checks))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('old', type=Path)
    parser.add_argument('new', type=Path)
    args = parser.parse_args()
    return diff_report(args.old, args.new)


if __name__ == '__main__':
    sys.exit(main())
