-- V205: owner records for the Returns coverage (2026-11-09 follow-up to the P&L audit).
-- cn_platform_coverage: a period whose TTFund activity was checked, either by a ttskill CLI
-- pull (basis 'cli_pull', sourced) or by the owner (basis 'owner_attestation', attested).
-- A month with no TTFund trades has no web event, so this is what lets it pass the CN gate.
CREATE SEQUENCE IF NOT EXISTS seq_cn_platform_coverage_id START 1;
CREATE TABLE IF NOT EXISTS cn_platform_coverage (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_cn_platform_coverage_id'),
    covered_from DATE NOT NULL,
    covered_to DATE NOT NULL,
    basis VARCHAR(30) NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    event_count INTEGER,
    imported_events INTEGER,
    evidence_sha256 VARCHAR(64),
    note VARCHAR(500)
);
-- Frozen-window flows replaced by an owner re-review are kept here, never deleted.
CREATE TABLE IF NOT EXISTS investment_external_flows_archive (
    flow_id VARCHAR(80) NOT NULL,
    event_date DATE NOT NULL,
    amount_cny DECIMAL(20,2) NOT NULL,
    original_amount DECIMAL(20,2) NOT NULL,
    original_currency VARCHAR(10) NOT NULL,
    fx_date DATE NOT NULL,
    fx_cny_per_native DECIMAL(20,10) NOT NULL,
    source VARCHAR(30) NOT NULL,
    kind VARCHAR(80) NOT NULL,
    evidence_status VARCHAR(100) NOT NULL,
    evidence VARCHAR(200),
    date_basis VARCHAR(200),
    archived_at TIMESTAMP NOT NULL,
    archive_reason VARCHAR(200) NOT NULL
);
ALTER TABLE sync_metrics_log ADD COLUMN IF NOT EXISTS note VARCHAR
