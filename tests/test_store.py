"""Tests for ai_spend.store."""

from __future__ import annotations

from datetime import date, datetime, timezone
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

    def test_remove_nonexistent_raises(self, store: SpendStore):
        with pytest.raises(StoreError, match="not found"):
            store.remove_provider("nope")

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
                    cost_usd=1.0,
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
                cost_usd=0.015,
            )
        ]
        count = store.add_usage_records(records)
        assert count == 1
        got = store.get_usage_by_date_range(date(2026, 2, 1), date(2026, 2, 28))
        assert len(got) == 1
        assert got[0].cost_usd == 0.015

    def test_empty_list(self, store: SpendStore):
        assert store.add_usage_records([]) == 0

    def test_upsert_dedup(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        r = UsageRecord(
            provider_id="a",
            provider_type=ProviderType.ANTHROPIC,
            date=date(2026, 2, 19),
            model="claude",
            cost_usd=1.0,
        )
        store.add_usage_records([r])
        # Insert same record again with different cost — should update
        r2 = UsageRecord(
            provider_id="a",
            provider_type=ProviderType.ANTHROPIC,
            date=date(2026, 2, 19),
            model="claude",
            cost_usd=2.0,
        )
        store.add_usage_records([r2])
        got = store.get_usage_by_date_range(date(2026, 2, 1), date(2026, 2, 28))
        assert len(got) == 1
        assert got[0].cost_usd == 2.0

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
                    cost_usd=1.0,
                ),
                UsageRecord(
                    provider_id="o",
                    provider_type=ProviderType.OPENAI,
                    date=date(2026, 2, 19),
                    model="gpt-4o",
                    cost_usd=2.0,
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
                    cost_usd=1.0,
                ),
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 18),
                    model="claude",
                    cost_usd=2.0,
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
                    cost_usd=1.0,
                ),
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 18),
                    model="haiku",
                    cost_usd=0.5,
                ),
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 19),
                    model="claude",
                    cost_usd=2.0,
                ),
            ]
        )
        days = store.get_daily_totals(date(2026, 2, 1), date(2026, 2, 28))
        assert len(days) == 2
        assert days[0].date == date(2026, 2, 18)
        assert days[0].total_usd == pytest.approx(1.5)
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
                    cost_usd=10.0,
                ),
                UsageRecord(
                    provider_id="o",
                    provider_type=ProviderType.OPENAI,
                    date=date(2026, 2, 19),
                    model="gpt-4o",
                    cost_usd=5.0,
                ),
            ]
        )
        s = store.get_monthly_summary(date(2026, 2, 1), date(2026, 2, 28))
        assert s.total_usd == pytest.approx(15.0)
        assert s.record_count == 2
        assert s.by_provider["a"] == pytest.approx(10.0)
        assert s.by_provider["o"] == pytest.approx(5.0)
        assert s.by_model["claude"] == pytest.approx(10.0)

    def test_empty_summary(self, store: SpendStore):
        s = store.get_monthly_summary(date(2026, 1, 1), date(2026, 1, 31))
        assert s.total_usd == 0.0
        assert s.record_count == 0


class TestBudget:
    def test_set_and_get(self, store: SpendStore):
        b = BudgetConfig(total_usd=100.0, period=BucketWidth.MONTH)
        store.set_budget(b)
        got = store.get_budget()
        assert got is not None
        assert got.total_usd == 100.0
        assert got.period == BucketWidth.MONTH
        assert got.alert_thresholds == [0.8, 0.9, 1.0]

    def test_get_no_budget(self, store: SpendStore):
        assert store.get_budget() is None

    def test_update_budget(self, store: SpendStore):
        store.set_budget(BudgetConfig(total_usd=50.0))
        store.set_budget(BudgetConfig(total_usd=200.0, period=BucketWidth.WEEK))
        got = store.get_budget()
        assert got is not None
        assert got.total_usd == 200.0
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
                    cost_usd=5.0,
                ),
            ]
        )
        total = store.get_total_spend_current_period(BucketWidth.MONTH)
        assert total == pytest.approx(5.0)

    def test_reset(self, store: SpendStore):
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date(2026, 2, 19),
                    model="claude",
                    cost_usd=1.0,
                ),
            ]
        )
        store.set_budget(BudgetConfig(total_usd=100.0))
        store.reset()
        assert store.list_providers() == []
        assert store.get_record_count() == 0
        assert store.get_budget() is None
