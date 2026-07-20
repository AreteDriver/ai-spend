"""SQLite WAL storage for ai-spend usage data."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
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

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _get_migration_files() -> list[tuple[int, Path]]:
    """Discover migration files, returning sorted (version, path) tuples."""
    if not _MIGRATIONS_DIR.exists():
        return []
    files: list[tuple[int, Path]] = []
    for path in _MIGRATIONS_DIR.iterdir():
        if path.suffix == ".sql" and path.stem[:3].isdigit():
            version = int(path.stem[:3])
            files.append((version, path))
    files.sort(key=lambda x: x[0])
    return files


def _get_current_version(conn: sqlite3.Connection) -> int:
    """Get the current schema version from the database."""
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row["version"] if row else 0
    except sqlite3.OperationalError:
        # schema_version table doesn't exist yet
        return 0


def _backup_db(db_path: Path) -> Path:
    """Copy the database to a timestamped backup before migrations."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.name}.backup.{timestamp}"
    import shutil

    shutil.copy2(db_path, backup_path)
    return backup_path


def _apply_migration(conn: sqlite3.Connection, version: int, sql: str) -> None:
    """Apply a single migration script within a transaction."""
    conn.execute("BEGIN")
    try:
        conn.executescript(sql)
        conn.execute(
            "INSERT OR REPLACE INTO schema_version"
            " (version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


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
            self._run_migrations()
        except sqlite3.Error as e:
            raise StoreError(f"Failed to initialize database: {e}") from e

    def _run_migrations(self) -> None:
        """Run any pending schema migrations."""
        current = _get_current_version(self._conn)
        migrations = _get_migration_files()
        pending = [(v, p) for v, p in migrations if v > current]
        if pending and self._db_path.exists():
            _backup_db(self._db_path)
        for version, path in pending:
            sql = path.read_text()
            try:
                _apply_migration(self._conn, version, sql)
            except sqlite3.Error as e:
                raise StoreError(
                    f"Migration {version:03d} ({path.name}) failed: {e}"
                ) from e

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Run a block of SQL inside a transaction.

        Commits on success, rolls back on any exception.
        """
        try:
            self._conn.execute("BEGIN")
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

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
                        str(r.cost_usd),
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
        provider_id: str | None = None,
    ) -> list[DailySpend]:
        """Get daily spend totals in a date range, optionally filtered by provider."""
        records = self.get_usage_by_date_range(start, end, provider_id=provider_id)
        days: dict[str, DailySpend] = {}
        for r in records:
            d = r.date.isoformat()
            if d not in days:
                days[d] = DailySpend(date=r.date)
            ds = days[d]
            ds.total_usd += r.cost_usd
            ds.record_count += 1
            prov = r.provider_id
            ds.by_provider[prov] = ds.by_provider.get(prov, Decimal("0")) + r.cost_usd
            model = r.model
            ds.by_model[model] = ds.by_model.get(model, Decimal("0")) + r.cost_usd

        return list(days.values())

    def get_monthly_summary(
        self,
        start: date,
        end: date,
        provider_id: str | None = None,
    ) -> SpendSummary:
        """Get aggregated spend summary, optionally filtered by provider."""
        records = self.get_usage_by_date_range(start, end, provider_id=provider_id)
        summary = SpendSummary(start_date=start, end_date=end)
        for r in records:
            summary.total_usd += r.cost_usd
            summary.record_count += 1
            summary.by_provider[r.provider_id] = (
                summary.by_provider.get(r.provider_id, Decimal("0")) + r.cost_usd
            )
            summary.by_model[r.model] = (
                summary.by_model.get(r.model, Decimal("0")) + r.cost_usd
            )
        return summary

    # --- Budget ---

    def set_budget(self, budget: BudgetConfig) -> None:
        """Set or update the budget (singleton row)."""
        self._conn.execute(
            """INSERT OR REPLACE INTO budgets (id, total_usd, period, alert_thresholds)
               VALUES (1, ?, ?, ?)""",
            (
                str(budget.total_usd),
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
            total_usd=Decimal(row["total_usd"]),
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

    def prune_records(self, cutoff: date, dry_run: bool = False) -> int:
        """Delete usage records older than cutoff. Returns count deleted."""
        if dry_run:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM usage_records WHERE date < ?",
                (cutoff.isoformat(),),
            ).fetchone()
            return int(row["cnt"])
        cur = self._conn.execute(
            "DELETE FROM usage_records WHERE date < ?",
            (cutoff.isoformat(),),
        )
        self._conn.execute(
            "DELETE FROM sync_log WHERE synced_at < ?",
            (datetime.combine(cutoff, datetime.min.time()).isoformat(),),
        )
        self._conn.commit()
        return cur.rowcount

    def get_total_spend_current_period(self, period: BucketWidth) -> Decimal:
        """Get total spend for the current period (month/week/day)."""
        now = date.today()
        if period == BucketWidth.MONTH:
            start = now.replace(day=1)
        elif period == BucketWidth.WEEK:
            start = date.fromordinal(now.toordinal() - now.weekday())
        else:
            start = now
        records = self.get_usage_by_date_range(start, now)
        return sum((r.cost_usd for r in records), Decimal("0"))

    def get_record_count(self) -> int:
        """Get total number of usage records."""
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM usage_records").fetchone()
        return int(row["cnt"])

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
            cost_usd=Decimal(row["cost_usd"]),
            metadata=json.loads(row["metadata"]),
        )
