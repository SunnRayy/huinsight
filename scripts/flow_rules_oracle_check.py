#!/usr/bin/env python3
"""Read-only oracle comparison. The caller must supply an isolated DB COPY."""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from src.financial_analysis.flow_rules import derive_flows
from src.sources.cn_platform_events import persist_events
from src.financial_analysis.twr import _investment_value, _month_end, calculate_twr_from_snapshots
from src.financial_analysis.xirr import calculate_xirr


def compare(db, start, end):
    flows, reviews = derive_flows(db, start)
    flows = [f for f in flows if f['event_date'] <= end]
    oracle = db.execute('SELECT flow_id, event_date, amount_cny, source FROM investment_external_flows '
                        "WHERE event_date > ? AND event_date <= ? AND flow_id NOT LIKE 'auto:%'",
                        [start, end]).fetchall()
    web_cn_days = [day for (day,) in db.execute(
        "SELECT event_date FROM cn_platform_events WHERE event_date > ? AND event_date <= ?",
        [start, end]).fetchall()]
    # Missing website evidence cannot establish CN rule parity.
    excluded = [row for row in oracle if row[3] == 'TTFund'
                and not any(abs((row[1] - day).days) <= 3 for day in web_cn_days)]
    oracle = [row for row in oracle if row not in excluded]
    unmatched = set(range(len(oracle)))
    report = defaultdict(lambda: dict(matched=[], missing=[], extra=[]))
    for flow in flows:
        matches = [i for i in unmatched if oracle[i][3] == flow['source']
                   and abs((oracle[i][1] - flow['event_date']).days) <= 3
                   and abs(float(oracle[i][2]) - flow['amount_cny']) <= .02]
        if matches:
            i = min(matches, key=lambda i: abs((oracle[i][1] - flow['event_date']).days))
            unmatched.remove(i)
            report[flow['source']]['matched'].append(flow['amount_cny'])
        else:
            report[flow['source']]['extra'].append(dict(date=str(flow['event_date']), amount=flow['amount_cny']))
    for i in sorted(unmatched):
        _, day, amount, source = oracle[i]
        report[source]['missing'].append(dict(date=str(day), amount=float(amount)))
    snapshots = [{'date': _month_end(day), 'value': _investment_value(payload)} for day, payload in
                 db.execute('SELECT snapshot_date, payload FROM balance_sheet_monthly WHERE snapshot_date >= ? '
                            'AND snapshot_date <= ? ORDER BY snapshot_date', [start.replace(day=1), end]).fetchall()]
    metrics = {}
    if len(snapshots) >= 2 and all(s['value'] is not None for s in snapshots):
        for name, cash in [('oracle', [{'date': d, 'amount': float(a)} for _, d, a, _ in oracle + excluded]),
                           ('rules', [{'date': f['event_date'], 'amount': f['amount_cny']} for f in flows])]:
            if name == 'rules' and (excluded or any(r['event_date'] <= end for r in reviews)):
                metrics[name] = {'twr': None, 'xirr': None, 'unavailable_reason': 'web_evidence_or_classification_incomplete'}
                continue
            cash = [f for f in cash if snapshots[0]['date'] < f['date'] <= snapshots[-1]['date']]
            vector = [(snapshots[0]['date'], -snapshots[0]['value'])]
            vector += [(f['date'], -f['amount']) for f in cash]
            vector += [(snapshots[-1]['date'], snapshots[-1]['value'])]
            metrics[name] = {'twr': calculate_twr_from_snapshots(snapshots, cash),
                             'xirr': calculate_xirr(sorted(vector))}
    totals = {}
    for source, groups in report.items():
        totals[source] = {}
        for kind, events in groups.items():
            amounts = events if kind == 'matched' else [event['amount'] for event in events]
            totals[source][kind] = {'count': len(events), 'amount_cny': round(sum(amounts), 2), 'events': events}
    return {'sources': totals, 'metrics': metrics,
            'excluded_cn_without_web_events': len(excluded),
            'metrics_scope': 'full requested investment window; rule returns unavailable when website evidence is incomplete',
            'review_items': [r for r in reviews if r['event_date'] <= end]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('db_copy', type=Path)
    parser.add_argument('--start', type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument('--end', type=date.fromisoformat, default=date(2026, 8, 31))
    parser.add_argument('--cn-web-csv', type=Path, help='TTFund historical website events; loaded in memory only')
    args = parser.parse_args()
    with duckdb.connect(':memory:') as db:
        path = str(args.db_copy.resolve()).replace("'", "''")
        db.execute(f"ATTACH '{path}' AS oracle (READ_ONLY)")
        tables = db.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog='oracle' AND table_schema='main'").fetchall()
        db.execute((Path(__file__).resolve().parents[1] / 'src/database/migrations/198_cn_platform_events.sql').read_text())
        for (table,) in tables:
            name = '"' + table.replace('"', '""') + '"'
            if table == 'cn_platform_events':
                db.execute(f'INSERT INTO cn_platform_events SELECT * FROM oracle.main.{name}')
            else:
                db.execute(f'CREATE VIEW {name} AS SELECT * FROM oracle.main.{name}')
        if args.cn_web_csv:
            with args.cn_web_csv.open(newline='', encoding='utf-8-sig') as stream:
                rows = []
                for row in csv.DictReader(stream):
                    rows.append(dict(event_date=row['event_date'], event_time=row['event_time'],
                                     fund_code=row['fund_code'], fund_name=row['fund_name'],
                                     business_type=row['business_type'], status=row['status'],
                                     applied_value=row['application_amount_value'], applied_unit=row['application_amount_unit'],
                                     confirmed_value=row['confirmed_amount_value'], confirmed_unit=row['confirmed_amount_unit'],
                                     account=row['associated_account_raw']))
                persist_events(db, rows)
        print(json.dumps(compare(db, args.start, args.end), ensure_ascii=False, default=str, indent=2))


if __name__ == '__main__':
    main()
