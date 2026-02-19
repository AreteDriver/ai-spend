"""Typer CLI for ai-spend."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

import ai_spend
from ai_spend import config as cfg
from ai_spend.budget import check_budget, set_budget
from ai_spend.exceptions import (
    AiSpendError,
    BudgetError,
    ConfigError,
    LicenseError,
    ProviderError,
)
from ai_spend.gates import require_pro
from ai_spend.licensing import MAX_FREE_PROVIDERS, get_license
from ai_spend.models import ExportFormat, ProviderType, SyncStatus
from ai_spend.providers.manual import ManualProvider
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

app = typer.Typer(name="ai-spend", help="Aggregate AI API costs across providers.")
config_app = typer.Typer(name="config", help="Manage provider configurations.")
budget_app = typer.Typer(name="budget", help="Manage spending budgets.")
manual_app = typer.Typer(name="manual", help="Manual cost entries.")

app.add_typer(config_app)
app.add_typer(budget_app)
app.add_typer(manual_app)

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ai-spend {ai_spend.__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            callback=_version_callback,
            is_eager=True,
            help="Show version.",
        ),
    ] = None,
) -> None:
    """AI spend tracker CLI."""


# --- Config commands ---


@config_app.command("add")
def config_add(
    name: Annotated[str, typer.Argument(help="Provider name")],
    provider_type: Annotated[ProviderType, typer.Argument(help="Provider type")],
    api_key: Annotated[str, typer.Option("--key", "-k", help="API key")] = "",
) -> None:
    """Add a provider configuration."""
    try:
        license_info = get_license()
        if not license_info.is_pro:
            existing = cfg.list_providers()
            if len(existing) >= MAX_FREE_PROVIDERS:
                console.print(
                    f"[red]Free tier limited to {MAX_FREE_PROVIDERS} providers. "
                    "Upgrade to Pro for unlimited.[/red]"
                )
                raise typer.Exit(1)

        pc = cfg.add_provider(name, provider_type, api_key)
        # Also register in the store
        store = cfg.get_store()
        try:
            store.add_provider(name, provider_type)
        except Exception:
            pass  # Already exists in store is fine
        console.print(f"[green]Added provider '{pc.name}' ({pc.provider_type})[/green]")
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


@config_app.command("remove")
def config_remove(
    name: Annotated[str, typer.Argument(help="Provider name to remove")],
) -> None:
    """Remove a provider configuration."""
    try:
        cfg.remove_provider(name)
        store = cfg.get_store()
        try:
            store.remove_provider(name)
        except Exception:
            pass
        console.print(f"[green]Removed provider '{name}'[/green]")
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


@config_app.command("list")
def config_list() -> None:
    """List all configured providers."""
    providers = cfg.list_providers()
    if not providers:
        console.print(
            "[dim]No providers configured. Use 'ai-spend config add' to add one.[/dim]"
        )
        return
    console.print(format_providers_table(providers))


# --- Sync ---


@app.command()
def sync() -> None:
    """Sync usage data from all configured providers."""
    providers = cfg.list_providers()
    if not providers:
        console.print("[dim]No providers configured.[/dim]")
        return

    store = cfg.get_store()
    from ai_spend.models import SyncResult
    from ai_spend.providers.registry import get_provider as get_provider_impl

    for pc in providers:
        if pc.provider_type == ProviderType.MANUAL:
            continue

        try:
            provider = get_provider_impl(pc.provider_type, pc.name, pc.api_key)
            end = date.today()
            start = end - timedelta(days=30)
            records = provider.fetch_usage(start, end)
            count = store.add_usage_records(records)

            result = SyncResult(
                provider_id=pc.name,
                status=SyncStatus.SUCCESS,
                records_synced=count,
                synced_at=datetime.now(timezone.utc),
            )
            store.log_sync(result)
            console.print(f"[green]{pc.name}: synced {count} records[/green]")

        except (ProviderError, AiSpendError) as e:
            result = SyncResult(
                provider_id=pc.name,
                status=SyncStatus.FAILED,
                error_message=str(e),
                synced_at=datetime.now(timezone.utc),
            )
            store.log_sync(result)
            console.print(f"[red]{pc.name}: {e}[/red]")


# --- Summary ---


@app.command()
def summary(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    days: Annotated[
        int,
        typer.Option("--days", "-d", help="Number of days to include"),
    ] = 30,
) -> None:
    """Show spend summary."""
    store = cfg.get_store()
    end = date.today()
    start = end - timedelta(days=days)
    s = store.get_monthly_summary(start, end)
    if json_output:
        console.print(format_summary_json(s))
    else:
        console.print(format_summary_table(s))


# --- Daily ---


@app.command()
def daily(
    last: Annotated[int, typer.Option("--last", "-n", help="Number of days")] = 7,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Show daily spend breakdown."""
    store = cfg.get_store()
    end = date.today()
    start = end - timedelta(days=last)
    days = store.get_daily_totals(start, end)
    if json_output:
        console.print(format_daily_json(days))
    else:
        console.print(format_daily_table(days))


# --- Budget ---


@budget_app.command("set")
def budget_set(
    total: Annotated[
        float,
        typer.Option("--total", "-t", help="Budget amount in USD"),
    ],
    period: Annotated[
        str,
        typer.Option("--period", "-p", help="Budget period"),
    ] = "month",
) -> None:
    """Set a spending budget."""
    try:
        store = cfg.get_store()
        b = set_budget(store, total, period)
        console.print(f"[green]Budget set: ${b.total_usd:.2f}/{b.period}[/green]")
    except BudgetError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


@budget_app.command("check")
def budget_check() -> None:
    """Check current spend against budget."""
    try:
        store = cfg.get_store()
        status = check_budget(store)
        console.print(format_budget_table(status))
    except BudgetError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


# --- Export ---


@app.command()
def export(
    fmt: Annotated[
        ExportFormat,
        typer.Option("--format", "-f", help="Export format"),
    ] = ExportFormat.JSON,
    days: Annotated[int, typer.Option("--days", "-d", help="Number of days")] = 30,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file path"),
    ] = None,
) -> None:
    """Export usage records (Pro feature)."""
    try:
        _do_export(fmt, days, output)
    except LicenseError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None


@require_pro("export")
def _do_export(fmt: ExportFormat, days: int, output: Path | None) -> None:
    store = cfg.get_store()
    end = date.today()
    start = end - timedelta(days=days)
    records = store.get_usage_by_date_range(start, end)
    result = export_records(records, fmt)
    if output:
        output.write_text(result)
        console.print(f"[green]Exported {len(records)} records to {output}[/green]")
    else:
        console.print(result)


# --- Manual ---


@manual_app.command("add")
def manual_add(
    model: Annotated[str, typer.Argument(help="Model or service name")],
    cost: Annotated[float, typer.Argument(help="Cost in USD")],
    entry_date: Annotated[
        str | None,
        typer.Option("--date", "-d", help="Date (YYYY-MM-DD)"),
    ] = None,
    note: Annotated[str, typer.Option("--note", "-n", help="Note")] = "",
    provider_name: Annotated[
        str,
        typer.Option("--provider", "-p", help="Provider name"),
    ] = "manual",
) -> None:
    """Add a manual cost entry."""
    try:
        d = date.fromisoformat(entry_date) if entry_date else date.today()
    except ValueError:
        console.print("[red]Invalid date format. Use YYYY-MM-DD.[/red]")
        raise typer.Exit(1) from None

    store = cfg.get_store()
    # Ensure manual provider exists
    if store.get_provider(provider_name) is None:
        store.add_provider(provider_name, ProviderType.MANUAL)

    mp = ManualProvider(name=provider_name)
    record = mp.create_entry(model, cost, d, note)
    store.add_usage_records([record])
    console.print(f"[green]Added ${cost:.2f} for '{model}' on {d}[/green]")


# --- Status ---


@app.command()
def status() -> None:
    """Show system status and sync history."""
    store = cfg.get_store()
    providers = cfg.list_providers()
    license_info = get_license()

    console.print(f"[bold]ai-spend v{ai_spend.__version__}[/bold]")
    console.print(f"License: [cyan]{license_info.tier}[/cyan]")
    console.print(f"Providers: [cyan]{len(providers)}[/cyan]")
    console.print(f"Records: [cyan]{store.get_record_count()}[/cyan]")

    budget = store.get_budget()
    if budget:
        console.print(f"Budget: [cyan]${budget.total_usd:.2f}/{budget.period}[/cyan]")
    else:
        console.print("Budget: [dim]not set[/dim]")

    syncs = store.get_all_syncs()
    if syncs:
        console.print()
        console.print(format_sync_table(syncs[:5]))
