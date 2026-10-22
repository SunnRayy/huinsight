-- V198: optional TTFund website transaction evidence, independent of app provenance.
CREATE TABLE IF NOT EXISTS cn_platform_events (
    event_key VARCHAR PRIMARY KEY,
    event_date DATE NOT NULL,
    event_time VARCHAR,
    fund_code VARCHAR,
    fund_name VARCHAR,
    business_type VARCHAR,
    applied_value DECIMAL(20,8),
    applied_unit VARCHAR,
    confirmed_value DECIMAL(20,8),
    confirmed_unit VARCHAR,
    account VARCHAR,
    status VARCHAR
);
