"""Rich table and export formatters for ai-spend."""

from __future__ import annotations

import csv
import io
import json

from rich.console import Console
from rich.table import Table

from ai_spend.exceptions import ExportError
from ai_spend.models import (
    BudgetStatus,
    DailySpend,
    ExportFormat,
    ProviderConfig,
    SpendSummary,
    SyncResult,
    UsageRecord,
)


def format_summary_table(summary: SpendSummary, console: Console | None = None) -> str:
    """Render spend summary as a Rich table."""
    c = console or Console(file=io.StringIO(), force_terminal=False)
    table = Table(title="Spend Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Spend", f"${summary.total_usd:.2f}")
    table.add_row("Records", str(summary.record_count))
    if summary.start_date:
        table.add_row("Period", f"{summary.start_date} to {summary.end_date}")

    if summary.by_provider:
        table.add_section()
        for name, cost in sorted(summary.by_provider.items()):
            table.add_row(f"  {name}", f"${cost:.2f}")

    if summary.by_model:
        table.add_section()
        for model, cost in sorted(summary.by_model.items()):
            table.add_row(f"  {model}", f"${cost:.2f}")

    with c.capture() as capture:
        c.print(table)
    return capture.get()


def format_daily_table(days: list[DailySpend], console: Console | None = None) -> str:
    """Render daily spend as a Rich table."""
    c = console or Console(file=io.StringIO(), force_terminal=False)
    table = Table(title="Daily Spend")
    table.add_column("Date", style="cyan")
    table.add_column("Total", style="green", justify="right")
    table.add_column("Records", justify="right")

    for d in days:
        table.add_row(str(d.date), f"${d.total_usd:.2f}", str(d.record_count))

    with c.capture() as capture:
        c.print(table)
    return capture.get()


def format_budget_table(status: BudgetStatus, console: Console | None = None) -> str:
    """Render budget status as a Rich table."""
    c = console or Console(file=io.StringIO(), force_terminal=False)
    table = Table(title="Budget Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Budget", f"${status.budget.total_usd:.2f}")
    table.add_row("Spent", f"${status.spent_usd:.2f}")
    table.add_row("Remaining", f"${status.remaining_usd:.2f}")
    table.add_row("Utilization", f"{status.utilization:.1%}")
    table.add_row("Over Budget", "YES" if status.is_over_budget else "No")

    if status.exceeded_thresholds:
        alerts = ", ".join(f"{t:.0%}" for t in status.exceeded_thresholds)
        table.add_row("Alerts Triggered", alerts)

    with c.capture() as capture:
        c.print(table)
    return capture.get()


def format_providers_table(
    providers: list[ProviderConfig], console: Console | None = None
) -> str:
    """Render providers list as a Rich table."""
    c = console or Console(file=io.StringIO(), force_terminal=False)
    table = Table(title="Configured Providers")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("API Key", style="dim")

    for p in providers:
        table.add_row(p.name, p.provider_type.value, p.masked_key)

    with c.capture() as capture:
        c.print(table)
    return capture.get()


def format_sync_table(syncs: list[SyncResult], console: Console | None = None) -> str:
    """Render sync log as a Rich table."""
    c = console or Console(file=io.StringIO(), force_terminal=False)
    table = Table(title="Sync History")
    table.add_column("Provider", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Records")
    table.add_column("Time")
    table.add_column("Error", style="red")

    for s in syncs:
        table.add_row(
            s.provider_id,
            s.status.value,
            str(s.records_synced),
            str(s.synced_at or ""),
            s.error_message or "",
        )

    with c.capture() as capture:
        c.print(table)
    return capture.get()


def export_records(
    records: list[UsageRecord],
    fmt: ExportFormat,
) -> str:
    """Export usage records to JSON or CSV string."""
    if fmt == ExportFormat.JSON:
        return _export_json(records)
    elif fmt == ExportFormat.CSV:
        return _export_csv(records)
    else:
        raise ExportError(f"Unsupported export format: {fmt}")


def format_summary_json(summary: SpendSummary) -> str:
    """Export summary as JSON string."""
    return json.dumps(summary.model_dump(mode="json"), indent=2, default=str)


def format_daily_json(days: list[DailySpend]) -> str:
    """Export daily data as JSON string."""
    return json.dumps([d.model_dump(mode="json") for d in days], indent=2, default=str)


def _export_json(records: list[UsageRecord]) -> str:
    data = [r.model_dump(mode="json") for r in records]
    return json.dumps(data, indent=2, default=str)


def _export_csv(records: list[UsageRecord]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "record_id",
            "provider_id",
            "provider_type",
            "date",
            "model",
            "input_tokens",
            "output_tokens",
            "cost_usd",
        ]
    )
    for r in records:
        writer.writerow(
            [
                r.record_id,
                r.provider_id,
                r.provider_type.value,
                r.date.isoformat(),
                r.model,
                r.input_tokens,
                r.output_tokens,
                r.cost_usd,
            ]
        )
    return output.getvalue()
