"""Tests for ai_spend.store."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ai_spend.exceptions import StoreError
from ai_spend.models import (
    BucketWidth,
    BudgetConfig,
    ProviderType,
    SyncResult,
    SyncStatus,
    UsageRecord,
)
from ai_spend.store import SpendStore


@pytest.fixture
def store(tmp_db_path: Path) -> SpendStore:
    s = SpendStore(tmp_db_path)
    yield s
    s.close()


class TestStoreInit:
    def test_creates_db_file(self, tmp_db_path: Path):
        s = SpendStore(tmp_db_path)
        assert tmp_db_path.exists()
        s.close()

    def test_creates_parent_dirs(self, tmp_path: Path):
        deep = tmp_path / "a" / "b" / "spend.db"
        s = SpendStore(deep)
        assert deep.exists()
        s.close()

    def test_wal_mode(self, tmp_db_path: Path):
        s = SpendStore(tmp_db_path)
        # WAL pragma should not error; file may or may not exist yet
        assert tmp_db_path.exists()
        s.close()


class TestProviderCRUD:
    def test_add_and_list(self, store: SpendStore):
        store.add_provider("my-claude", ProviderType.ANTHROPIC)
        providers = store.list_providers()
        assert len(providers) == 1
        assert providers[0] == ("my-claude", ProviderType.ANTHROPIC)

    def test_add_duplicate_raises(self, store: SpendStore):
        store.add_provider("x", ProviderType.OPENAI)
        with pytest.raises(StoreError, match="already exists"):
            store.add_provider("x", ProviderType.OPENAI)

    def test_remove(self, store: SpendStore):
        store.add_provider("x", ProviderType.MANUAL)
        store.remove_provider("x")
        assert store.list_providers() == []

    def test_remove_nonexistent_is_noop(self, store: SpendStore):
        """Removing a missing provider is idempotent."""
        store.remove_provider("nope")
        assert store.list_providers() == []

    def test_get_provider(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        result = store.get_provider("a")
        assert result == ("a", ProviderType.ANTHROPIC)

    def test_get_provider_missing(self, store: SpendStore):
        assert store.get_provider("nope") is None

    def test_multiple_providers(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_provider("o", ProviderType.OPENAI)
        store.add_provider("m", ProviderType.MANUAL)
        assert len(store.list_providers()) == 3

    def test_remove_cascades_records(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 19),
                    model="claude",
                    cost_usd=Decimal("1.0"),
                )
            ]
        )
        store.remove_provider("a")
        records = store.get_usage_by_date_range(date(2026, 1, 1), date(2026, 12, 31))
        assert len(records) == 0


class TestUsageRecords:
    def test_add_and_retrieve(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        records = [
            UsageRecord(
                provider_id="a",
                provider_type=ProviderType.ANTHROPIC,
                date=date(2026, 2, 19),
                model="claude-sonnet",
                input_tokens=1000,
                output_tokens=500,
                cost_usd=Decimal("0.015"),
            )
        ]
        count = store.add_usage_records(records)
        assert count == 1
        got = store.get_usage_by_date_range(date(2026, 2, 1), date(2026, 2, 28))
        assert len(got) == 1
        assert got[0].cost_usd == Decimal("0.015")

    def test_empty_list(self, store: SpendStore):
        assert store.add_usage_records([]) == 0

    def test_upsert_dedup(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        r = UsageRecord(
            provider_id="a",
            provider_type=ProviderType.ANTHROPIC,
            date=date(2026, 2, 19),
            model="claude",
            cost_usd=Decimal("1.0"),
        )
        store.add_usage_records([r])
        # Insert same record again with different cost — should update
        r2 = UsageRecord(
            provider_id="a",
            provider_type=ProviderType.ANTHROPIC,
            date=date(2026, 2, 19),
            model="claude",
            cost_usd=Decimal("2.0"),
        )
        store.add_usage_records([r2])
        got = store.get_usage_by_date_range(date(2026, 2, 1), date(2026, 2, 28))
        assert len(got) == 1
        assert got[0].cost_usd == Decimal("2.0")

    def test_filter_by_provider(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_provider("o", ProviderType.OPENAI)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 19),
                    model="claude",
                    cost_usd=Decimal("1.0"),
                ),
                UsageRecord(
                    provider_id="o",
                    provider_type=ProviderType.OPENAI,
                    date=date(2026, 2, 19),
                    model="gpt-4o",
                    cost_usd=Decimal("2.0"),
                ),
            ]
        )
        got = store.get_usage_by_date_range(
            date(2026, 2, 1), date(2026, 2, 28), provider_id="a"
        )
        assert len(got) == 1
        assert got[0].provider_id == "a"

    def test_get_record_count(self, store: SpendStore):
        assert store.get_record_count() == 0
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 19),
                    model="claude",
                    cost_usd=Decimal("1.0"),
                ),
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 18),
                    model="claude",
                    cost_usd=Decimal("2.0"),
                ),
            ]
        )
        assert store.get_record_count() == 2


class TestDailyTotals:
    def test_daily_totals(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 18),
                    model="claude",
                    cost_usd=Decimal("1.0"),
                ),
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 18),
                    model="haiku",
                    cost_usd=Decimal("0.5"),
                ),
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 19),
                    model="claude",
                    cost_usd=Decimal("2.0"),
                ),
            ]
        )
        days = store.get_daily_totals(date(2026, 2, 1), date(2026, 2, 28))
        assert len(days) == 2
        assert days[0].date == date(2026, 2, 18)
        assert days[0].total_usd == Decimal("1.5")
        assert days[1].date == date(2026, 2, 19)

    def test_empty_range(self, store: SpendStore):
        days = store.get_daily_totals(date(2026, 1, 1), date(2026, 1, 31))
        assert days == []


class TestMonthlySummary:
    def test_summary(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_provider("o", ProviderType.OPENAI)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 18),
                    model="claude",
                    cost_usd=Decimal("10.0"),
                ),
                UsageRecord(
                    provider_id="o",
                    provider_type=ProviderType.OPENAI,
                    date=date(2026, 2, 19),
                    model="gpt-4o",
                    cost_usd=Decimal("5.0"),
                ),
            ]
        )
        s = store.get_monthly_summary(date(2026, 2, 1), date(2026, 2, 28))
        assert s.total_usd == Decimal("15")
        assert s.record_count == 2
        assert s.by_provider["a"] == Decimal("10")
        assert s.by_provider["o"] == Decimal("5")
        assert s.by_model["claude"] == Decimal("10")

    def test_empty_summary(self, store: SpendStore):
        s = store.get_monthly_summary(date(2026, 1, 1), date(2026, 1, 31))
        assert s.total_usd == Decimal("0")
        assert s.record_count == 0


class TestBudget:
    def test_set_and_get(self, store: SpendStore):
        b = BudgetConfig(total_usd=Decimal("100"), period=BucketWidth.MONTH)
        store.set_budget(b)
        got = store.get_budget()
        assert got is not None
        assert got.total_usd == Decimal("100")
        assert got.period == BucketWidth.MONTH
        assert got.alert_thresholds == [0.8, 0.9, 1.0]

    def test_get_no_budget(self, store: SpendStore):
        assert store.get_budget() is None

    def test_update_budget(self, store: SpendStore):
        store.set_budget(BudgetConfig(total_usd=Decimal("50")))
        store.set_budget(
            BudgetConfig(total_usd=Decimal("200"), period=BucketWidth.WEEK)
        )
        got = store.get_budget()
        assert got is not None
        assert got.total_usd == Decimal("200")
        assert got.period == BucketWidth.WEEK


class TestSyncLog:
    def test_log_and_get_last(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        sr = SyncResult(
            provider_id="a",
            status=SyncStatus.SUCCESS,
            records_synced=10,
            synced_at=datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc),
        )
        store.log_sync(sr)
        last = store.get_last_sync("a")
        assert last is not None
        assert last.status == SyncStatus.SUCCESS
        assert last.records_synced == 10

    def test_get_last_sync_none(self, store: SpendStore):
        assert store.get_last_sync("nope") is None

    def test_multiple_syncs(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.log_sync(
            SyncResult(
                provider_id="a",
                status=SyncStatus.SUCCESS,
                records_synced=5,
                synced_at=datetime(2026, 2, 18, tzinfo=timezone.utc),
            )
        )
        store.log_sync(
            SyncResult(
                provider_id="a",
                status=SyncStatus.FAILED,
                error_message="timeout",
                synced_at=datetime(2026, 2, 19, tzinfo=timezone.utc),
            )
        )
        last = store.get_last_sync("a")
        assert last is not None
        assert last.status == SyncStatus.FAILED

    def test_get_all_syncs(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.log_sync(
            SyncResult(
                provider_id="a",
                status=SyncStatus.SUCCESS,
                synced_at=datetime(2026, 2, 18, tzinfo=timezone.utc),
            )
        )
        store.log_sync(
            SyncResult(
                provider_id="a",
                status=SyncStatus.SUCCESS,
                synced_at=datetime(2026, 2, 19, tzinfo=timezone.utc),
            )
        )
        all_syncs = store.get_all_syncs()
        assert len(all_syncs) == 2


class TestTransaction:
    def test_transaction_commit(self, store: SpendStore):
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO providers (name, provider_type) VALUES (?, ?)",
                ("tx", "anthropic"),
            )
        assert store.get_provider("tx") is not None

    def test_transaction_rollback(self, store: SpendStore):
        with pytest.raises(RuntimeError):
            with store.transaction() as conn:
                conn.execute(
                    "INSERT INTO providers (name, provider_type) VALUES (?, ?)",
                    ("tx-rollback", "anthropic"),
                )
                raise RuntimeError("abort")
        assert store.get_provider("tx-rollback") is None


class TestUtilities:
    def test_get_total_spend_current_period(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date.today(),
                    model="claude",
                    cost_usd=Decimal("5.0"),
                ),
            ]
        )
        total = store.get_total_spend_current_period(BucketWidth.MONTH)
        assert total == Decimal("5")

    def test_get_total_spend_day(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date.today(),
                    model="claude",
                    cost_usd=Decimal("3.0"),
                ),
            ]
        )
        total = store.get_total_spend_current_period(BucketWidth.DAY)
        assert total == Decimal("3")

    def test_reset(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 19),
                    model="claude",
                    cost_usd=Decimal("1.0"),
                ),
            ]
        )
        store.set_budget(BudgetConfig(total_usd=Decimal("100")))
        store.reset()
        assert store.list_providers() == []
        assert store.get_record_count() == 0
        assert store.get_budget() is None


class TestGetTotalSpendWeek:
    def test_week_branch(self, tmp_db_path: Path):
        s = SpendStore(tmp_db_path)
        s.add_provider("a", ProviderType.ANTHROPIC)
        s.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date.today(),
                    model="claude",
                    cost_usd=Decimal("5.0"),
                ),
            ]
        )
        total = s.get_total_spend_current_period(BucketWidth.WEEK)
        assert total == Decimal("5")
        s.close()


class TestMigrationEdgeCases:
    def test_migration_with_missing_dir(self, tmp_path: Path, monkeypatch):
        """Cover store.py line 31: missing migrations dir returns []."""
        from ai_spend import store as store_mod

        monkeypatch.setattr(store_mod, "_MIGRATIONS_DIR", tmp_path / "nope")
        db = tmp_path / "spend.db"
        s = SpendStore(db)
        s.close()
        assert db.exists()

    def test_migration_rollback_on_bad_sql(self, tmp_path: Path, monkeypatch):
        """Cover store.py lines 74-76: ROLLBACK on invalid SQL."""
        from ai_spend import store as store_mod

        bad_migration = tmp_path / "999_bad.sql"
        bad_migration.write_text("INVALID SYNTAX HERE;;;")
        monkeypatch.setattr(store_mod, "_MIGRATIONS_DIR", tmp_path)
        db = tmp_path / "spend.db"
        # Pre-create a valid db with schema_version so it tries to run migration
        conn = __import__("sqlite3").connect(str(db))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        conn.execute("INSERT INTO schema_version VALUES (0, 'now')")
        conn.commit()
        conn.close()
        with pytest.raises(StoreError, match="Migration 999"):
            SpendStore(db)

    def test_db_init_failure(self, tmp_path: Path):
        """Cover store.py lines 124-131: garbage bytes trigger auto-healing."""
        db = tmp_path / "spend.db"
        db.write_bytes(b"NOT A SQLITE FILE")
        # Should heal corrupted DB instead of raising StoreError
        store = SpendStore(db)
        assert db.exists()
        # Verify the healed DB is functional
        store.add_provider("manual", ProviderType.MANUAL)
        store.add_usage_records([
            UsageRecord(
                provider_id="manual",
                provider_type=ProviderType.MANUAL,
                date=date.today(),
                model="test-model",
                input_tokens=1,
                output_tokens=1,
                cost_usd=Decimal("0"),
                metadata={},
            )
        ])
        store.close()
