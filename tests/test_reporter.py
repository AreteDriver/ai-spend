"""Tests for ai_spend.reporter."""

from __future__ import annotations

import json
from datetime import date

from ai_spend.models import (
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
from ai_spend.reporter import (
    export_records,
    format_budget_table,
    format_daily_json,
    format_daily_table,
    format_providers_table,
    format_summary_json,
    format_summary_table,
    format_sync_table,
)


class TestFormatSummaryTable:
    def test_basic(self):
        s = SpendSummary(
            total_usd=42.50,
            record_count=10,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )
        output = format_summary_table(s)
        assert "$42.50" in output
        assert "10" in output

    def test_with_providers(self):
        s = SpendSummary(total_usd=15.0, by_provider={"anthropic": 10.0, "openai": 5.0})
        output = format_summary_table(s)
        assert "anthropic" in output
        assert "openai" in output

    def test_empty_summary(self):
        s = SpendSummary()
        output = format_summary_table(s)
        assert "$0.00" in output


class TestFormatDailyTable:
    def test_basic(self):
        days = [
            DailySpend(date=date(2026, 2, 18), total_usd=5.0, record_count=3),
            DailySpend(date=date(2026, 2, 19), total_usd=10.0, record_count=5),
        ]
        output = format_daily_table(days)
        assert "2026-02-18" in output
        assert "$5.00" in output
        assert "$10.00" in output

    def test_empty(self):
        output = format_daily_table([])
        assert "Daily Spend" in output


class TestFormatBudgetTable:
    def test_under_budget(self):
        status = BudgetStatus(
            budget=BudgetConfig(total_usd=100.0),
            spent_usd=50.0,
            remaining_usd=50.0,
            utilization=0.5,
        )
        output = format_budget_table(status)
        assert "$100.00" in output
        assert "$50.00" in output
        assert "No" in output

    def test_over_budget(self):
        status = BudgetStatus(
            budget=BudgetConfig(total_usd=100.0),
            spent_usd=110.0,
            remaining_usd=-10.0,
            utilization=1.1,
            is_over_budget=True,
            exceeded_thresholds=[0.8, 0.9, 1.0],
        )
        output = format_budget_table(status)
        assert "YES" in output
        assert "80%" in output


class TestFormatProvidersTable:
    def test_basic(self):
        providers = [
            ProviderConfig(
                name="my-claude",
                provider_type=ProviderType.ANTHROPIC,
                api_key="test-key-anthropic-12345678",
            ),
            ProviderConfig(
                name="my-openai",
                provider_type=ProviderType.OPENAI,
                api_key="test-key-openai-abcdefgh",
            ),
        ]
        output = format_providers_table(providers)
        assert "my-claude" in output
        assert "anthropic" in output
        assert "5678" in output  # Last 4 chars of key visible

    def test_empty(self):
        output = format_providers_table([])
        assert "Configured Providers" in output


class TestFormatSyncTable:
    def test_basic(self):
        syncs = [
            SyncResult(provider_id="a", status=SyncStatus.SUCCESS, records_synced=10),
            SyncResult(
                provider_id="b",
                status=SyncStatus.FAILED,
                error_message="timeout",
            ),
        ]
        output = format_sync_table(syncs)
        assert "success" in output
        assert "timeout" in output


class TestExportRecords:
    def _records(self):
        return [
            UsageRecord(
                provider_id="a",
                provider_type=ProviderType.ANTHROPIC,
                date=date(2026, 2, 19),
                model="claude",
                cost_usd=1.0,
                input_tokens=100,
                output_tokens=50,
            ),
            UsageRecord(
                provider_id="o",
                provider_type=ProviderType.OPENAI,
                date=date(2026, 2, 19),
                model="gpt-4o",
                cost_usd=2.0,
                input_tokens=200,
                output_tokens=100,
            ),
        ]

    def test_json_export(self):
        output = export_records(self._records(), ExportFormat.JSON)
        data = json.loads(output)
        assert len(data) == 2
        assert data[0]["provider_id"] == "a"

    def test_csv_export(self):
        output = export_records(self._records(), ExportFormat.CSV)
        lines = output.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows
        assert "record_id" in lines[0]
        assert "claude" in lines[1]

    def test_json_roundtrip(self):
        records = self._records()
        output = export_records(records, ExportFormat.JSON)
        data = json.loads(output)
        assert data[0]["cost_usd"] == 1.0


class TestFormatSummaryJson:
    def test_basic(self):
        s = SpendSummary(total_usd=42.50, record_count=10)
        output = format_summary_json(s)
        data = json.loads(output)
        assert data["total_usd"] == 42.50


class TestFormatDailyJson:
    def test_basic(self):
        days = [DailySpend(date=date(2026, 2, 19), total_usd=5.0)]
        output = format_daily_json(days)
        data = json.loads(output)
        assert len(data) == 1
        assert data[0]["total_usd"] == 5.0
