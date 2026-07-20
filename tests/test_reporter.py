"""Tests for ai_spend.reporter."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

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
    format_stats_table,
    format_summary_json,
    format_summary_table,
    format_sync_table,
    import_records,
)


class TestFormatSummaryTable:
    def test_basic(self):
        s = SpendSummary(
            total_usd=Decimal("42.50"),
            record_count=10,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )
        output = format_summary_table(s)
        assert "$42.50" in output
        assert "10" in output

    def test_with_providers(self):
        s = SpendSummary(
            total_usd=Decimal("15"),
            by_provider={"anthropic": Decimal("10"), "openai": Decimal("5")},
        )
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
            DailySpend(date=date(2026, 2, 18), total_usd=Decimal("5"), record_count=3),
            DailySpend(date=date(2026, 2, 19), total_usd=Decimal("10"), record_count=5),
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
            budget=BudgetConfig(total_usd=Decimal("100")),
            spent_usd=Decimal("50"),
            remaining_usd=Decimal("50"),
            utilization=0.5,
        )
        output = format_budget_table(status)
        assert "$100.00" in output
        assert "$50.00" in output
        assert "No" in output

    def test_over_budget(self):
        status = BudgetStatus(
            budget=BudgetConfig(total_usd=Decimal("100")),
            spent_usd=Decimal("110"),
            remaining_usd=Decimal("-10"),
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
                cost_usd=Decimal("1"),
                input_tokens=100,
                output_tokens=50,
            ),
            UsageRecord(
                provider_id="o",
                provider_type=ProviderType.OPENAI,
                date=date(2026, 2, 19),
                model="gpt-4o",
                cost_usd=Decimal("2"),
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
        assert data[0]["cost_usd"] == "1"


class TestFormatSummaryJson:
    def test_basic(self):
        s = SpendSummary(total_usd=Decimal("42.50"), record_count=10)
        output = format_summary_json(s)
        data = json.loads(output)
        assert data["total_usd"] == "42.50"


class TestFormatDailyJson:
    def test_basic(self):
        days = [DailySpend(date=date(2026, 2, 19), total_usd=Decimal("5"))]
        output = format_daily_json(days)
        data = json.loads(output)
        assert len(data) == 1
        assert data[0]["total_usd"] == "5"


class TestImportRecords:
    def _record_dicts(self):
        return [
            {
                "provider_id": "a",
                "provider_type": "anthropic",
                "date": "2026-02-19",
                "model": "claude",
                "input_tokens": 100,
                "output_tokens": 50,
                "cost_usd": "1.00",
            },
            {
                "provider_id": "o",
                "provider_type": "openai",
                "date": "2026-02-19",
                "model": "gpt-4o",
                "input_tokens": 200,
                "output_tokens": 100,
                "cost_usd": "2.50",
            },
        ]

    def test_import_json(self):
        data = json.dumps(self._record_dicts())
        records = import_records(data, ExportFormat.JSON)
        assert len(records) == 2
        assert records[0].provider_id == "a"
        assert records[0].cost_usd == Decimal("1.00")

    def test_import_csv(self):
        rows = [
            "provider_id,provider_type,date,model,input_tokens,output_tokens,cost_usd",
            "a,anthropic,2026-02-19,claude,100,50,1.00",
            "o,openai,2026-02-19,gpt-4o,200,100,2.50",
        ]
        data = "\n".join(rows)
        records = import_records(data, ExportFormat.CSV)
        assert len(records) == 2
        assert records[1].provider_id == "o"
        assert records[1].cost_usd == Decimal("2.50")

    def test_import_json_not_list(self):
        from ai_spend.exceptions import ExportError

        with pytest.raises(ExportError):
            import_records('{"ok": true}', ExportFormat.JSON)

    def test_import_json_bad_record(self):
        from ai_spend.exceptions import ExportError

        with pytest.raises(ExportError):
            import_records('[{"bad": "data"}]', ExportFormat.JSON)

    def test_import_csv_bad_record(self):
        from ai_spend.exceptions import ExportError

        with pytest.raises(ExportError):
            import_records(
                "provider_id,provider_type,date,model,cost_usd\nbad", ExportFormat.CSV
            )


class TestFormatStatsTable:
    def test_basic(self):
        output = format_stats_table(
            commands={"summary": 5, "sync": 2},
            pro_gates={"export": 1},
            total=8,
            first_event="2026-02-01T00:00:00",
            last_event="2026-02-19T00:00:00",
            daily_activity=[("2026-02-18", 3), ("2026-02-19", 5)],
        )
        assert "Telemetry Overview" in output
        assert "summary" in output
        assert "export" in output
        assert "2026-02-18" in output

    def test_empty(self):
        output = format_stats_table({}, {}, 0, None, None, [])
        assert "Telemetry Overview" in output
        assert "0" in output
