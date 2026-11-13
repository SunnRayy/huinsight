-- V204: append-only sync log (audit 2026-11-08 issue 7). One row per sync:
-- the hashes of the ledger input files the readers used and the headline
-- figures, so a closed period whose numbers change can be traced to the
-- input that changed. Rows are never updated or deleted by the app.
CREATE SEQUENCE IF NOT EXISTS seq_sync_metrics_log_id START 1;
CREATE TABLE IF NOT EXISTS sync_metrics_log (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_sync_metrics_log_id'),
    recorded_at TIMESTAMP NOT NULL,
    trigger VARCHAR(40) NOT NULL,
    app_version VARCHAR(40),
    input_fingerprint VARCHAR(64),
    funding_source_sha256 VARCHAR(64),
    ledger_hashes JSON NOT NULL,
    metrics JSON NOT NULL,
    note VARCHAR
)
