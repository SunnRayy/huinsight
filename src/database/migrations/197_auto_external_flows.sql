-- V197: additive provenance, dated FX and owner decisions for forward flows.
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS raw_business_type VARCHAR;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS confirmation_status VARCHAR;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS counterparty VARCHAR;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS source_event_key VARCHAR;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS bank_receipt DECIMAL(20,2);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS tax_withheld_shares DECIMAL(20,8);
ALTER TABLE investment_twr_source ADD COLUMN IF NOT EXISTS frozen_coverage_end DATE;
ALTER TABLE investment_twr_source ADD COLUMN IF NOT EXISTS frozen_valuation_sha256 VARCHAR;
ALTER TABLE investment_twr_source ADD COLUMN IF NOT EXISTS valuation_identity_sha256 VARCHAR;
ALTER TABLE investment_twr_source ADD COLUMN IF NOT EXISTS history_changed_since_review BOOLEAN DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS fx_daily (
    date DATE, pair VARCHAR, rate DECIMAL(20,10) NOT NULL, source VARCHAR NOT NULL,
    PRIMARY KEY(date, pair)
);
CREATE TABLE IF NOT EXISTS external_flow_decisions (
    event_key VARCHAR PRIMARY KEY,
    decision VARCHAR NOT NULL CHECK (decision IN ('external_in','external_out','internal','manual')),
    amount_cny DECIMAL(20,2), note VARCHAR, decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS flow_source_coverage (
    source VARCHAR, period_end DATE, period_start DATE, cash_transactions_present BOOLEAN NOT NULL,
    PRIMARY KEY(source, period_end)
);
