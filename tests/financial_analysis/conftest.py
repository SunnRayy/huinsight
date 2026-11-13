"""In-memory fixtures for automatic boundary flows."""
from pathlib import Path
import duckdb
import pytest
from src.financial_analysis.twr import _input_fingerprint, _valuation_fingerprint

@pytest.fixture
def flow_db():
    con = duckdb.connect(':memory:')
    con.execute(Path('src/database/schema.sql').read_text())
    con.execute(Path('src/database/migrations/197_auto_external_flows.sql').read_text())
    yield con
    con.close()


@pytest.fixture
def reviewed_flow_db(flow_db):
    from tests.financial_analysis.test_flow_coverage import month
    month(flow_db, '2026-07-01')
    month(flow_db, '2026-08-01')
    flow_db.execute("INSERT INTO investment_external_flows VALUES ('reviewed', '2026-08-10', 10, 10, 'CNY', '2026-08-10', 1, 'TTFund', 'in', 'confirmed', 'synthetic', 'posted')")
    valuation = _valuation_fingerprint(flow_db, '2026-07-31', '2026-08-31')
    fingerprint = _input_fingerprint(flow_db, '2026-07-31', '2026-08-31')
    flow_db.execute("INSERT INTO investment_twr_source(id, coverage_start, coverage_end, quality, source_sha256, valuation_sha256, input_fingerprint) VALUES (1, '2026-07-31', '2026-08-31', 'estimated', 'synthetic', ?, ?)", [valuation, fingerprint])
    flow_db.execute("INSERT INTO investment_twr_reviews(input_fingerprint, reviewer, evidence_ref) VALUES (?, 'synthetic', 'fixture')", [fingerprint])
    from tests.financial_analysis.test_flow_rules import web
    web(flow_db, '活期宝互转', event_key='cn-coverage', event_date='2026-10-31')
    return flow_db

