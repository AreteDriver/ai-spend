-- Initial schema: base tables for ai-spend v0.1

CREATE TABLE IF NOT EXISTS providers (
    name TEXT PRIMARY KEY,
    provider_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS usage_records (
    record_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    date TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (provider_id) REFERENCES providers(name)
);

CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_records(date);
CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage_records(provider_id);
CREATE INDEX IF NOT EXISTS idx_usage_date_provider ON usage_records(date, provider_id);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    total_usd REAL NOT NULL,
    period TEXT NOT NULL DEFAULT 'month',
    alert_thresholds TEXT NOT NULL DEFAULT '[0.8, 0.9, 1.0]'
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    status TEXT NOT NULL,
    records_synced INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (provider_id) REFERENCES providers(name)
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
