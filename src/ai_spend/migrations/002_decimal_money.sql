-- Convert money columns from REAL to TEXT for exact Decimal storage
-- Applied after the Decimal migration in v0.3

-- SQLite doesn't support ALTER COLUMN TYPE, so we recreate the tables

BEGIN;

-- Migrate usage_records cost_usd
CREATE TABLE usage_records_new (
    record_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    date TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd TEXT NOT NULL DEFAULT '0.00',
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (provider_id) REFERENCES providers(name)
);

INSERT INTO usage_records_new
SELECT
    record_id,
    provider_id,
    provider_type,
    date,
    model,
    input_tokens,
    output_tokens,
    printf('%.2f', cost_usd),
    metadata
FROM usage_records;

DROP TABLE usage_records;
ALTER TABLE usage_records_new RENAME TO usage_records;

CREATE INDEX idx_usage_date ON usage_records(date);
CREATE INDEX idx_usage_provider ON usage_records(provider_id);
CREATE INDEX idx_usage_date_provider ON usage_records(date, provider_id);

-- Migrate budgets total_usd
CREATE TABLE budgets_new (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    total_usd TEXT NOT NULL,
    period TEXT NOT NULL DEFAULT 'month',
    alert_thresholds TEXT NOT NULL DEFAULT '[0.8, 0.9, 1.0]'
);

INSERT INTO budgets_new
SELECT
    id,
    printf('%.2f', total_usd),
    period,
    alert_thresholds
FROM budgets;

DROP TABLE budgets;
ALTER TABLE budgets_new RENAME TO budgets;

COMMIT;
