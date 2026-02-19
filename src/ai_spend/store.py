"""SQLite WAL storage for ai-spend usage data."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from ai_spend.exceptions import StoreError
from ai_spend.models import (
    BucketWidth,
    BudgetConfig,
    DailySpend,
    ProviderType,
    SpendSummary,
    SyncResult,
    SyncStatus,
    UsageRecord,
)

_SCHEMA = """
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
"""


class SpendStore:
    """SQLite WAL store for usage data."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        except sqlite3.Error as e:
            raise StoreError(f"Failed to initialize database: {e}") from e

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # --- Provider CRUD ---

    def add_provider(self, name: str, provider_type: ProviderType) -> None:
        """Register a provider."""
        try:
            self._conn.execute(
                "INSERT INTO providers (name, provider_type) VALUES (?, ?)",
                (name, provider_type.value),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise StoreError(f"Provider '{name}' already exists") from e

    def remove_provider(self, name: str) -> None:
        """Remove a provider and its usage records."""
        self._conn.execute("DELETE FROM usage_records WHERE provider_id = ?", (name,))
        self._conn.execute("DELETE FROM sync_log WHERE provider_id = ?", (name,))
        cur = self._conn.execute("DELETE FROM providers WHERE name = ?", (name,))
        self._conn.commit()
        if cur.rowcount == 0:
            raise StoreError(f"Provider '{name}' not found")

    def list_providers(self) -> list[tuple[str, ProviderType]]:
        """List all registered providers."""
        rows = self._conn.execute(
            "SELECT name, provider_type FROM providers ORDER BY name"
        ).fetchall()
        return [(r["name"], ProviderType(r["provider_type"])) for r in rows]

    def get_provider(self, name: str) -> tuple[str, ProviderType] | None:
        """Get a single provider by name."""
        row = self._conn.execute(
            "SELECT name, provider_type FROM providers WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return (row["name"], ProviderType(row["provider_type"]))

    # --- Usage Records ---

    def add_usage_records(self, records: list[UsageRecord]) -> int:
        """Batch upsert usage records. Returns count inserted/updated."""
        if not records:
            return 0
        try:
            self._conn.executemany(
                """INSERT OR REPLACE INTO usage_records
                   (record_id, provider_id, provider_type, date, model,
                    input_tokens, output_tokens, cost_usd, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        r.record_id,
                        r.provider_id,
                        r.provider_type.value,
                        r.date.isoformat(),
                        r.model,
                        r.input_tokens,
                        r.output_tokens,
                        r.cost_usd,
                        json.dumps(r.metadata),
                    )
                    for r in records
                ],
            )
            self._conn.commit()
            return len(records)
        except sqlite3.Error as e:
            raise StoreError(f"Failed to insert usage records: {e}") from e

    def get_usage_by_date_range(
        self,
        start: date,
        end: date,
        provider_id: str | None = None,
    ) -> list[UsageRecord]:
        """Get usage records in a date range, optionally filtered by provider."""
        if provider_id:
            rows = self._conn.execute(
                """SELECT * FROM usage_records
                   WHERE date >= ? AND date <= ? AND provider_id = ?
                   ORDER BY date""",
                (start.isoformat(), end.isoformat(), provider_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM usage_records
                   WHERE date >= ? AND date <= ?
                   ORDER BY date""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_daily_totals(
        self,
        start: date,
        end: date,
    ) -> list[DailySpend]:
        """Get daily spend totals in a date range."""
        rows = self._conn.execute(
            """SELECT date, SUM(cost_usd) as total, COUNT(*) as cnt,
                      provider_id, model
               FROM usage_records
               WHERE date >= ? AND date <= ?
               GROUP BY date, provider_id, model
               ORDER BY date""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

        days: dict[str, DailySpend] = {}
        for r in rows:
            d = r["date"]
            if d not in days:
                days[d] = DailySpend(date=date.fromisoformat(d))
            ds = days[d]
            ds.total_usd += r["total"]
            ds.record_count += r["cnt"]
            prov = r["provider_id"]
            ds.by_provider[prov] = ds.by_provider.get(prov, 0.0) + r["total"]
            model = r["model"]
            ds.by_model[model] = ds.by_model.get(model, 0.0) + r["total"]

        return list(days.values())

    def get_monthly_summary(
        self,
        start: date,
        end: date,
    ) -> SpendSummary:
        """Get aggregated spend summary for a date range."""
        records = self.get_usage_by_date_range(start, end)
        summary = SpendSummary(start_date=start, end_date=end)
        for r in records:
            summary.total_usd += r.cost_usd
            summary.record_count += 1
            summary.by_provider[r.provider_id] = (
                summary.by_provider.get(r.provider_id, 0.0) + r.cost_usd
            )
            summary.by_model[r.model] = summary.by_model.get(r.model, 0.0) + r.cost_usd
        # Round to avoid float drift
        summary.total_usd = round(summary.total_usd, 6)
        for k in summary.by_provider:
            summary.by_provider[k] = round(summary.by_provider[k], 6)
        for k in summary.by_model:
            summary.by_model[k] = round(summary.by_model[k], 6)
        return summary

    # --- Budget ---

    def set_budget(self, budget: BudgetConfig) -> None:
        """Set or update the budget (singleton row)."""
        self._conn.execute(
            """INSERT OR REPLACE INTO budgets (id, total_usd, period, alert_thresholds)
               VALUES (1, ?, ?, ?)""",
            (
                budget.total_usd,
                budget.period.value,
                json.dumps(budget.alert_thresholds),
            ),
        )
        self._conn.commit()

    def get_budget(self) -> BudgetConfig | None:
        """Get the current budget config."""
        row = self._conn.execute("SELECT * FROM budgets WHERE id = 1").fetchone()
        if row is None:
            return None
        return BudgetConfig(
            total_usd=row["total_usd"],
            period=BucketWidth(row["period"]),
            alert_thresholds=json.loads(row["alert_thresholds"]),
        )

    # --- Sync Log ---

    def log_sync(self, result: SyncResult) -> None:
        """Record a sync operation result."""
        self._conn.execute(
            """INSERT INTO sync_log
               (provider_id, status, records_synced,
                error_message, synced_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                result.provider_id,
                result.status.value,
                result.records_synced,
                result.error_message,
                (result.synced_at or datetime.now(timezone.utc)).isoformat(),
            ),
        )
        self._conn.commit()

    def get_last_sync(self, provider_id: str) -> SyncResult | None:
        """Get the most recent sync result for a provider."""
        row = self._conn.execute(
            """SELECT * FROM sync_log WHERE provider_id = ?
               ORDER BY synced_at DESC LIMIT 1""",
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        return SyncResult(
            provider_id=row["provider_id"],
            status=SyncStatus(row["status"]),
            records_synced=row["records_synced"],
            error_message=row["error_message"],
            synced_at=datetime.fromisoformat(row["synced_at"]),
        )

    def get_all_syncs(self) -> list[SyncResult]:
        """Get all sync log entries, most recent first."""
        rows = self._conn.execute(
            "SELECT * FROM sync_log ORDER BY synced_at DESC"
        ).fetchall()
        return [
            SyncResult(
                provider_id=r["provider_id"],
                status=SyncStatus(r["status"]),
                records_synced=r["records_synced"],
                error_message=r["error_message"],
                synced_at=datetime.fromisoformat(r["synced_at"]),
            )
            for r in rows
        ]

    # --- Utilities ---

    def get_total_spend_current_period(self, period: BucketWidth) -> float:
        """Get total spend for the current period (month/week/day)."""
        now = date.today()
        if period == BucketWidth.MONTH:
            start = now.replace(day=1)
        elif period == BucketWidth.WEEK:
            start = date.fromordinal(now.toordinal() - now.weekday())
        else:
            start = now
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) as total"
            " FROM usage_records WHERE date >= ?",
            (start.isoformat(),),
        ).fetchone()
        return row["total"] if row else 0.0

    def get_record_count(self) -> int:
        """Get total number of usage records."""
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM usage_records").fetchone()
        return row["cnt"]

    def reset(self) -> None:
        """Delete all data (for testing)."""
        self._conn.executescript(
            """
            DELETE FROM sync_log;
            DELETE FROM usage_records;
            DELETE FROM budgets;
            DELETE FROM providers;
            """
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> UsageRecord:
        return UsageRecord(
            provider_id=row["provider_id"],
            provider_type=ProviderType(row["provider_type"]),
            date=date.fromisoformat(row["date"]),
            model=row["model"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cost_usd=row["cost_usd"],
            metadata=json.loads(row["metadata"]),
        )
