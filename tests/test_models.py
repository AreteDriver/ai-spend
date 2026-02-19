"""Tests for ai_spend.models."""

from __future__ import annotations

from datetime import date

from ai_spend.models import (
    BucketWidth,
    BudgetConfig,
    BudgetStatus,
    DailySpend,
    ExportFormat,
    ProviderConfig,
    ProviderType,
    SpendSummary,
    SyncResult,
    SyncStatus,
    UsageRecord,
)

# --- Enums ---


class TestProviderType:
    def test_values(self):
        assert ProviderType.ANTHROPIC == "anthropic"
        assert ProviderType.OPENAI == "openai"
        assert ProviderType.MANUAL == "manual"

    def test_from_string(self):
        assert ProviderType("anthropic") is ProviderType.ANTHROPIC

    def test_all_members(self):
        assert len(ProviderType) == 3


class TestBucketWidth:
    def test_values(self):
        assert BucketWidth.DAY == "day"
        assert BucketWidth.WEEK == "week"
        assert BucketWidth.MONTH == "month"

    def test_all_members(self):
        assert len(BucketWidth) == 3


class TestExportFormat:
    def test_values(self):
        assert ExportFormat.JSON == "json"
        assert ExportFormat.CSV == "csv"

    def test_all_members(self):
        assert len(ExportFormat) == 2


class TestSyncStatus:
    def test_values(self):
        assert SyncStatus.SUCCESS == "success"
        assert SyncStatus.PARTIAL == "partial"
        assert SyncStatus.FAILED == "failed"

    def test_all_members(self):
        assert len(SyncStatus) == 3


# --- UsageRecord ---


class TestUsageRecord:
    def test_create(self, sample_usage_record: UsageRecord):
        assert sample_usage_record.provider_id == "my-anthropic"
        assert sample_usage_record.provider_type == ProviderType.ANTHROPIC
        assert sample_usage_record.date == date(2026, 2, 19)
        assert sample_usage_record.model == "claude-sonnet-4-20250514"
        assert sample_usage_record.input_tokens == 1000
        assert sample_usage_record.output_tokens == 500
        assert sample_usage_record.cost_usd == 0.015

    def test_record_id_deterministic(self, sample_usage_record: UsageRecord):
        rid = sample_usage_record.record_id
        assert len(rid) == 16
        # Same inputs -> same ID
        r2 = UsageRecord(
            provider_id="my-anthropic",
            provider_type=ProviderType.ANTHROPIC,
            date=date(2026, 2, 19),
            model="claude-sonnet-4-20250514",
        )
        assert r2.record_id == rid

    def test_record_id_varies(self, sample_usage_record: UsageRecord):
        r2 = UsageRecord(
            provider_id="other",
            provider_type=ProviderType.OPENAI,
            date=date(2026, 2, 19),
            model="gpt-4o",
        )
        assert r2.record_id != sample_usage_record.record_id

    def test_defaults(self):
        r = UsageRecord(
            provider_id="x",
            provider_type=ProviderType.MANUAL,
            date=date(2026, 1, 1),
            model="misc",
        )
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.cost_usd == 0.0
        assert r.metadata == {}

    def test_metadata(self):
        r = UsageRecord(
            provider_id="x",
            provider_type=ProviderType.MANUAL,
            date=date(2026, 1, 1),
            model="misc",
            metadata={"note": "test"},
        )
        assert r.metadata == {"note": "test"}

    def test_serialization(self, sample_usage_record: UsageRecord):
        data = sample_usage_record.model_dump()
        assert "record_id" in data
        assert data["provider_type"] == "anthropic"
        restored = UsageRecord.model_validate(data)
        assert restored.record_id == sample_usage_record.record_id


# --- ProviderConfig ---


class TestProviderConfig:
    def test_create(self, sample_provider_config: ProviderConfig):
        assert sample_provider_config.name == "my-anthropic"
        assert sample_provider_config.provider_type == ProviderType.ANTHROPIC
        assert sample_provider_config.api_key == "test-admin-key-1234567890"

    def test_masked_key_long(self, sample_provider_config: ProviderConfig):
        masked = sample_provider_config.masked_key
        assert masked.endswith("7890")
        assert masked.startswith("*")
        assert "sk-ant" not in masked

    def test_masked_key_short(self):
        pc = ProviderConfig(name="x", provider_type=ProviderType.MANUAL, api_key="abc")
        assert pc.masked_key == "****"

    def test_masked_key_empty(self):
        pc = ProviderConfig(name="x", provider_type=ProviderType.MANUAL, api_key="")
        assert pc.masked_key == "****"

    def test_masked_key_exactly_four(self):
        pc = ProviderConfig(name="x", provider_type=ProviderType.MANUAL, api_key="abcd")
        assert pc.masked_key == "****"

    def test_masked_key_five(self):
        pc = ProviderConfig(
            name="x", provider_type=ProviderType.MANUAL, api_key="abcde"
        )
        assert pc.masked_key == "*bcde"

    def test_default_empty_key(self):
        pc = ProviderConfig(name="x", provider_type=ProviderType.MANUAL)
        assert pc.api_key == ""


# --- BudgetConfig ---


class TestBudgetConfig:
    def test_create(self, sample_budget: BudgetConfig):
        assert sample_budget.total_usd == 100.0
        assert sample_budget.period == BucketWidth.MONTH
        assert sample_budget.alert_thresholds == [0.8, 0.9, 1.0]

    def test_custom_thresholds(self):
        b = BudgetConfig(total_usd=50.0, alert_thresholds=[0.5, 0.75])
        assert b.alert_thresholds == [0.5, 0.75]


# --- SyncResult ---


class TestSyncResult:
    def test_create(self, sample_sync_result: SyncResult):
        assert sample_sync_result.provider_id == "my-anthropic"
        assert sample_sync_result.status == SyncStatus.SUCCESS
        assert sample_sync_result.records_synced == 42
        assert sample_sync_result.synced_at is not None

    def test_failed(self):
        sr = SyncResult(
            provider_id="x",
            status=SyncStatus.FAILED,
            error_message="connection timeout",
        )
        assert sr.error_message == "connection timeout"
        assert sr.records_synced == 0

    def test_defaults(self):
        sr = SyncResult(provider_id="x", status=SyncStatus.SUCCESS)
        assert sr.error_message == ""
        assert sr.synced_at is None


# --- SpendSummary ---


class TestSpendSummary:
    def test_defaults(self):
        s = SpendSummary()
        assert s.total_usd == 0.0
        assert s.by_provider == {}
        assert s.by_model == {}
        assert s.record_count == 0
        assert s.start_date is None
        assert s.end_date is None

    def test_populated(self):
        s = SpendSummary(
            total_usd=42.50,
            by_provider={"anthropic": 30.0, "openai": 12.50},
            by_model={"claude-sonnet-4-20250514": 30.0, "gpt-4o": 12.50},
            record_count=100,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 19),
        )
        assert s.total_usd == 42.50
        assert len(s.by_provider) == 2


# --- DailySpend ---


class TestDailySpend:
    def test_create(self):
        d = DailySpend(date=date(2026, 2, 19), total_usd=5.0, record_count=10)
        assert d.total_usd == 5.0
        assert d.record_count == 10

    def test_defaults(self):
        d = DailySpend(date=date(2026, 2, 19))
        assert d.total_usd == 0.0
        assert d.by_provider == {}
        assert d.by_model == {}


# --- BudgetStatus ---


class TestBudgetStatus:
    def test_under_budget(self, sample_budget: BudgetConfig):
        bs = BudgetStatus(
            budget=sample_budget,
            spent_usd=50.0,
            remaining_usd=50.0,
            utilization=0.5,
        )
        assert not bs.is_over_budget
        assert bs.exceeded_thresholds == []

    def test_over_budget(self, sample_budget: BudgetConfig):
        bs = BudgetStatus(
            budget=sample_budget,
            spent_usd=110.0,
            remaining_usd=-10.0,
            utilization=1.1,
            exceeded_thresholds=[0.8, 0.9, 1.0],
            is_over_budget=True,
        )
        assert bs.is_over_budget
        assert len(bs.exceeded_thresholds) == 3
