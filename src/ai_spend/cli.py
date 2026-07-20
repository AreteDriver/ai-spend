"""Typer CLI for ai-spend."""

from __future__ import annotations

import json
import signal
import stat
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

import ai_spend
from ai_spend import config as cfg
from ai_spend.budget import check_budget, set_budget
from ai_spend.context import AppContext
from ai_spend.exceptions import (
    AiSpendError,
    BudgetError,
    ConfigError,
    LicenseError,
    ProviderError,
)
from ai_spend.gates import require_pro
from ai_spend.licensing import MAX_FREE_PROVIDERS, get_license
from ai_spend.log import configure_logging, get_logger
from ai_spend.models import ExportFormat, ProviderType, SyncStatus
from ai_spend.providers.manual import ManualProvider
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
from ai_spend.store import SpendStore

app = typer.Typer(name="ai-spend", help="Aggregate AI API costs across providers.")
config_app = typer.Typer(name="config", help="Manage provider configurations.")
budget_app = typer.Typer(name="budget", help="Manage spending budgets.")
manual_app = typer.Typer(name="manual", help="Manual cost entries.")

app.add_typer(config_app)
app.add_typer(budget_app)
app.add_typer(manual_app)

console = Console()
logger = get_logger(__name__)


class _GracefulShutdown:
    """Context manager for graceful SIGINT/SIGTERM handling.

    Sets a flag on signal receipt and closes the store connection on exit.
    """

    def __init__(self, store: SpendStore) -> None:
        self.store = store
        self._signaled = False
        self._original_handler: object = None

    def _handler(self, _signum: int, _frame: object) -> None:
        self._signaled = True
        console.print("\n[yellow]Shutting down gracefully...[/yellow]")

    def __enter__(self) -> _GracefulShutdown:
        self._original_handler = signal.signal(signal.SIGINT, self._handler)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._original_handler is not None:
            signal.signal(signal.SIGINT, self._original_handler)  # type: ignore[arg-type]
        if self._signaled:
            try:
                self.store.close()
            except Exception:
                pass

    @property
    def signaled(self) -> bool:
        return self._signaled


def _handle_error(e: Exception, verbose: bool = False) -> None:
    """Print error message and exit. Preserves exception chain for debugging."""
    console.print(f"[red]Error: {e}[/red]")
    if verbose:
        console.print_exception()
    raise typer.Exit(1)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ai-spend {ai_spend.__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
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
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose", "-V", help="Show verbose output including tracebacks"
        ),
    ] = False,
) -> None:
    """AI spend tracker CLI."""
    configure_logging(verbose=verbose)
    ctx.obj = AppContext.from_env(verbose=verbose)


# --- Config commands ---


@config_app.command("add")
def config_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Provider name")],
    provider_type: Annotated[ProviderType, typer.Argument(help="Provider type")],
    api_key: Annotated[str, typer.Option("--key", "-k", help="API key")] = "",
) -> None:
    """Add a provider configuration."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "config.add")
    try:
        license_info = get_license()
        if not license_info.is_pro:
            existing = cfg.list_providers(app_ctx.config_dir)
            if len(existing) >= MAX_FREE_PROVIDERS:
                console.print(
                    f"[red]Free tier limited to {MAX_FREE_PROVIDERS} providers. "
                    "Upgrade to Pro for unlimited.[/red]"
                )
                raise typer.Exit(1)

        pc = cfg.add_provider(name, provider_type, api_key, app_ctx.config_dir)
        # Also register in the store
        try:
            app_ctx.store.add_provider(name, provider_type)
        except Exception:
            pass  # Already exists in store is fine
        console.print(
            f"[green]Added provider '{pc.name}' ({pc.provider_type})[/green]"
        )
    except ConfigError as e:
        _handle_error(e, app_ctx.verbose)


@config_app.command("remove")
def config_remove(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Provider name to remove")],
) -> None:
    """Remove a provider configuration."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "config.remove")
    try:
        cfg.remove_provider(name, app_ctx.config_dir)
        try:
            app_ctx.store.remove_provider(name)
        except Exception:
            pass
        console.print(f"[green]Removed provider '{name}'[/green]")
    except ConfigError as e:
        _handle_error(e, app_ctx.verbose)


@config_app.command("edit")
def config_edit(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Provider name to edit")],
    api_key: Annotated[
        str | None,
        typer.Option("--key", "-k", help="New API key"),
    ] = None,
    provider_type: Annotated[
        ProviderType | None,
        typer.Option("--type", "-t", help="New provider type"),
    ] = None,
) -> None:
    """Edit an existing provider configuration."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "config.edit")
    try:
        if api_key is None and provider_type is None:
            console.print(
                "[yellow]No changes specified. "
                "Use --key or --type to edit.[/yellow]"
            )
            raise typer.Exit(1)
        pc = cfg.edit_provider(
            name, api_key=api_key, provider_type=provider_type,
            config_dir=app_ctx.config_dir,
        )
        # Also update in the store if type changed
        if provider_type is not None:
            try:
                app_ctx.store.remove_provider(name)
                app_ctx.store.add_provider(name, provider_type)
            except Exception:
                pass
        console.print(
            f"[green]Updated provider '{pc.name}' ({pc.provider_type})[/green]"
        )
    except ConfigError as e:
        _handle_error(e, app_ctx.verbose)


@config_app.command("list")
def config_list(ctx: typer.Context) -> None:
    """List all configured providers."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "config.list")
    providers = cfg.list_providers(app_ctx.config_dir)
    if not providers:
        console.print(
            "[dim]No providers configured. "
            "Use 'ai-spend config add' to add one.[/dim]"
        )
        return
    console.print(format_providers_table(providers))


@config_app.command("encrypt")
def config_encrypt(ctx: typer.Context) -> None:
    """Encrypt all API keys at rest."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "config.encrypt")
    try:
        cfg.encrypt_config(app_ctx.config_dir)
        console.print("[green]Config encrypted.[/green]")
    except ConfigError as e:
        _handle_error(e, app_ctx.verbose)


@config_app.command("validate")
def config_validate(ctx: typer.Context) -> None:
    """Validate API credentials for all configured providers."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "config.validate")
    providers = cfg.list_providers(app_ctx.config_dir)
    if not providers:
        console.print("[dim]No providers configured.[/dim]")
        return

    from ai_spend.providers.registry import get_provider as get_provider_impl

    any_failed = False
    for pc in providers:
        if pc.provider_type == ProviderType.MANUAL:
            console.print(f"[dim]{pc.name}: manual provider (skipped)[/dim]")
            continue
        try:
            provider = get_provider_impl(pc.provider_type, pc.name, pc.api_key)
            valid = provider.validate_credentials()
            if valid:
                console.print(f"[green]{pc.name}: credentials valid[/green]")
            else:
                console.print(f"[yellow]{pc.name}: credentials invalid[/yellow]")
                any_failed = True
        except (ProviderError, AiSpendError) as e:
            console.print(f"[red]{pc.name}: {e}[/red]")
            any_failed = True

    if any_failed:
        raise typer.Exit(1)


# --- Sync ---


@app.command()
def sync(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Preview what would be synced"),
    ] = False,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="Sync only this provider"),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option("--since", "-s", help="Sync from date (YYYY-MM-DD)"),
    ] = None,
) -> None:
    """Sync usage data from all configured providers."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "sync")
    providers = cfg.list_providers(app_ctx.config_dir)
    if not providers:
        console.print("[dim]No providers configured.[/dim]")
        return

    if provider is not None:
        providers = [p for p in providers if p.name == provider]
        if not providers:
            console.print(f"[red]Provider '{provider}' not configured.[/red]")
            raise typer.Exit(1)

    end = date.today()
    if since is not None:
        try:
            start = date.fromisoformat(since)
        except ValueError:
            console.print("[red]Invalid --since date. Use YYYY-MM-DD.[/red]")
            raise typer.Exit(1) from None
    else:
        start = end - timedelta(days=30)

    store = app_ctx.store
    from ai_spend.models import SyncResult
    from ai_spend.providers.registry import get_provider as get_provider_impl

    with _GracefulShutdown(store) as shutdown:
        for pc in providers:
            if shutdown.signaled:
                break
            if pc.provider_type == ProviderType.MANUAL:
                continue

            try:
                p = get_provider_impl(pc.provider_type, pc.name, pc.api_key)
                logger.info(
                    "sync_start",
                    extra={
                        "extra_fields": {
                            "provider": pc.name,
                            "date_range": f"{start} to {end}",
                        }
                    },
                )
                records = p.fetch_usage(start, end)

                if dry_run:
                    logger.info(
                        "sync_dry_run",
                        extra={
                            "extra_fields": {
                                "provider": pc.name,
                                "records": len(records),
                            }
                        },
                    )
                    console.print(
                        f"[cyan]{pc.name}:[/cyan] would sync {len(records)} records"
                    )
                    for r in records[:3]:
                        console.print(
                            f"  {r.date} | {r.model} | ${r.cost_usd:.4f}"
                        )
                    if len(records) > 3:
                        console.print(f"  ... and {len(records) - 3} more")
                    continue

                count = store.add_usage_records(records)
                result = SyncResult(
                    provider_id=pc.name,
                    status=SyncStatus.SUCCESS,
                    records_synced=count,
                    synced_at=datetime.now(timezone.utc),
                )
                store.log_sync(result)
                logger.info(
                    "sync_success",
                    extra={
                        "extra_fields": {
                            "provider": pc.name,
                            "records": count,
                        }
                    },
                )
                console.print(f"[green]{pc.name}: synced {count} records[/green]")

            except (ProviderError, AiSpendError) as e:
                result = SyncResult(
                    provider_id=pc.name,
                    status=SyncStatus.FAILED,
                    error_message=str(e),
                    synced_at=datetime.now(timezone.utc),
                )
                store.log_sync(result)
                logger.error(
                    "sync_failure",
                    extra={
                        "extra_fields": {
                            "provider": pc.name,
                            "error": str(e),
                        }
                    },
                )
                console.print(f"[red]{pc.name}: {e}[/red]")


# --- Summary ---


@app.command()
def summary(
    ctx: typer.Context,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    days: Annotated[
        int,
        typer.Option("--days", "-d", help="Number of days to include"),
    ] = 30,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Filter by provider name"),
    ] = None,
) -> None:
    """Show spend summary."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "summary")
    store = app_ctx.store
    end = date.today()
    start = end - timedelta(days=days)
    s = store.get_monthly_summary(start, end, provider_id=provider)
    if json_output:
        console.print(format_summary_json(s))
    else:
        console.print(format_summary_table(s))


# --- Daily ---


@app.command()
def daily(
    ctx: typer.Context,
    last: Annotated[int, typer.Option("--last", "-n", help="Number of days")] = 7,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Filter by provider name"),
    ] = None,
) -> None:
    """Show daily spend breakdown."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "daily")
    store = app_ctx.store
    end = date.today()
    start = end - timedelta(days=last)
    days = store.get_daily_totals(start, end, provider_id=provider)
    if json_output:
        console.print(format_daily_json(days))
    else:
        console.print(format_daily_table(days))


# --- Budget ---


@budget_app.command("set")
def budget_set(
    ctx: typer.Context,
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
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "budget.set")
    try:
        store = app_ctx.store
        total_decimal = Decimal(str(total))
        b = set_budget(store, total_decimal, period)
        console.print(f"[green]Budget set: ${b.total_usd:.2f}/{b.period}[/green]")
    except BudgetError as e:
        _handle_error(e, app_ctx.verbose)


@budget_app.command("check")
def budget_check(ctx: typer.Context) -> None:
    """Check current spend against budget."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "budget.check")
    try:
        store = app_ctx.store
        status = check_budget(store)
        console.print(format_budget_table(status))
    except BudgetError as e:
        _handle_error(e, app_ctx.verbose)


# --- Export ---


@app.command()
def export(
    ctx: typer.Context,
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
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "export")
    try:
        _do_export(ctx, fmt, days, output)
    except LicenseError as e:
        _handle_error(e, app_ctx.verbose)


@require_pro("export")
def _do_export(
    ctx: typer.Context, fmt: ExportFormat, days: int, output: Path | None
) -> None:
    app_ctx: AppContext = ctx.obj
    store = app_ctx.store
    end = date.today()
    start = end - timedelta(days=days)
    records = store.get_usage_by_date_range(start, end)
    result = export_records(records, fmt)
    if output:
        output.write_text(result)
        console.print(
            f"[green]Exported {len(records)} records to {output}[/green]"
        )
    else:
        console.print(result)


@app.command("import")
def import_cmd(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="File to import")],
    fmt: Annotated[
        ExportFormat,
        typer.Option("--format", "-f", help="Import format"),
    ] = ExportFormat.JSON,
) -> None:
    """Import usage records from a JSON or CSV file."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "import")
    if not file.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    try:
        data = file.read_text()
        records = import_records(data, fmt)
        store = app_ctx.store
        # Atomic import: create missing providers + insert records in one tx
        with store.transaction() as conn:
            for pc in records:
                conn.execute(
                    "INSERT OR IGNORE INTO providers"
                    " (name, provider_type) VALUES (?, ?)",
                    (pc.provider_id, pc.provider_type.value),
                )
            conn.executemany(
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
        console.print(f"[green]Imported {len(records)} records from {file}[/green]")
    except (AiSpendError, OSError) as e:
        _handle_error(e, app_ctx.verbose)


# --- Manual ---


@manual_app.command("add")
def manual_add(
    ctx: typer.Context,
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
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "manual.add")
    try:
        d = date.fromisoformat(entry_date) if entry_date else date.today()
    except ValueError:
        console.print("[red]Invalid date format. Use YYYY-MM-DD.[/red]")
        raise typer.Exit(1) from None

    store = app_ctx.store
    # Ensure manual provider exists
    if store.get_provider(provider_name) is None:
        store.add_provider(provider_name, ProviderType.MANUAL)

    mp = ManualProvider(name=provider_name)
    cost_decimal = Decimal(str(cost))
    record = mp.create_entry(model, cost_decimal, d, note)
    store.add_usage_records([record])
    console.print(f"[green]Added ${cost_decimal:.2f} for '{model}' on {d}[/green]")


# --- Prune ---


@app.command()
def prune(
    ctx: typer.Context,
    older_than: Annotated[
        int,
        typer.Option("--older-than", help="Delete records older than N days"),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Preview what would be deleted"),
    ] = False,
) -> None:
    """Delete usage records older than a given number of days."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "prune")
    store = app_ctx.store
    cutoff = date.today() - timedelta(days=older_than)
    count = store.prune_records(cutoff, dry_run=dry_run)
    if dry_run:
        console.print(
            f"[cyan]Would delete {count} records older than {cutoff}[/cyan]"
        )
    else:
        console.print(
            f"[green]Deleted {count} records older than {cutoff}[/green]"
        )


# --- Health ---


@app.command()
def health(ctx: typer.Context) -> None:
    """Run operational health checks."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "health")
    store = app_ctx.store
    config_dir = app_ctx.config_dir
    all_ok = True

    # Database integrity
    try:
        row = store._conn.execute("PRAGMA integrity_check").fetchone()
        if row and row[0] == "ok":
            console.print(
                "[green]✓ Database integrity check passed[/green]"
            )
        else:
            detail = row[0] if row else "unknown"
            console.print(
                f"[red]✗ Database integrity failed: {detail}[/red]"
            )
            all_ok = False
    except Exception as e:
        console.print(f"[red]✗ Database integrity check error: {e}[/red]")
        all_ok = False

    # WAL mode
    try:
        wal_row = store._conn.execute("PRAGMA journal_mode").fetchone()
        if wal_row and wal_row[0].lower() == "wal":
            console.print("[green]✓ WAL mode enabled[/green]")
        else:
            detail = wal_row[0] if wal_row else "unknown"
            console.print(f"[yellow]! WAL mode: {detail}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]! WAL mode check error: {e}[/yellow]")

    # Config directory permissions
    try:
        st = config_dir.stat()
        mode = st.st_mode
        ok = (
            mode & stat.S_IRWXU
            and not (mode & stat.S_IRWXG)
            and not (mode & stat.S_IRWXO)
        )
        if ok:
            console.print(
                "[green]✓ Config directory permissions OK[/green]"
            )
        else:
            console.print(
                f"[yellow]! Config dir permissions: "
                f"{oct(mode)[-3:]} (expected 700)[/yellow]"
            )
            all_ok = False
    except Exception as e:
        console.print(f"[red]✗ Config directory check error: {e}[/red]")
        all_ok = False

    # Config file permissions
    config_path = config_dir / "config.yaml"
    if config_path.exists():
        try:
            st = config_path.stat()
            mode = st.st_mode
            ok = (
                (mode & stat.S_IRUSR)
                and (mode & stat.S_IWUSR)
                and not (mode & stat.S_IRGRP)
                and not (mode & stat.S_IROTH)
            )
            if ok:
                console.print(
                    "[green]✓ Config file permissions OK[/green]"
                )
            else:
                console.print(
                    f"[yellow]! Config file permissions: "
                    f"{oct(mode)[-3:]} (expected 600)[/yellow]"
                )
                all_ok = False
        except Exception as e:
            console.print(f"[red]✗ Config file check error: {e}[/red]")
            all_ok = False
    else:
        console.print("[dim]- Config file not present (OK)[/dim]")

    # Encryption status
    key_file = config_dir / ".key"
    if key_file.exists():
        console.print("[green]✓ Config encryption key present[/green]")
    else:
        console.print(
            "[yellow]! Config encryption key not present "
            "(run `config encrypt`)[/yellow]"
        )

    # Schema version
    try:
        from ai_spend.store import _get_current_version

        version = _get_current_version(store._conn)
        console.print(f"[green]✓ Schema version: {version}[/green]")
    except Exception as e:
        console.print(f"[yellow]! Schema version check error: {e}[/yellow]")

    if all_ok:
        console.print("\n[bold green]All checks passed[/bold green]")
    else:
        console.print(
            "\n[bold yellow]Some checks raised warnings[/bold yellow]"
        )


# --- Status ---


@app.command()
def status(ctx: typer.Context) -> None:
    """Show system status and sync history."""
    app_ctx: AppContext = ctx.obj
    app_ctx.track("command", "status")
    store = app_ctx.store
    providers = cfg.list_providers(app_ctx.config_dir)
    license_info = get_license()

    console.print(f"[bold]ai-spend v{ai_spend.__version__}[/bold]")
    console.print(f"License: [cyan]{license_info.tier}[/cyan]")
    console.print(f"Providers: [cyan]{len(providers)}[/cyan]")
    console.print(f"Records: [cyan]{store.get_record_count()}[/cyan]")

    budget = store.get_budget()
    if budget:
        console.print(
            f"Budget: [cyan]${budget.total_usd:.2f}/{budget.period}[/cyan]"
        )
    else:
        console.print("Budget: [dim]not set[/dim]")

    syncs = store.get_all_syncs()
    if syncs:
        console.print()
        console.print(format_sync_table(syncs[:5]))


# --- Stats ---


@app.command()
def stats(
    ctx: typer.Context,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
) -> None:
    """Show local usage telemetry (requires AI_SPEND_TELEMETRY=1)."""
    app_ctx: AppContext = ctx.obj

    if app_ctx.telemetry is None:
        console.print(
            "[dim]Telemetry is disabled. "
            "Set AI_SPEND_TELEMETRY=1 to enable local usage tracking.[/dim]"
        )
        return

    ts = app_ctx.telemetry
    try:
        commands = ts.get_command_counts()
        pro_gates = ts.get_pro_gate_counts()
        total = ts.get_total_events()
        first = ts.get_first_event_time()
        last = ts.get_last_event_time()
        activity = ts.get_daily_activity()

        if json_output:
            import json

            data = {
                "total_events": total,
                "first_event": first,
                "last_event": last,
                "commands": commands,
                "pro_gate_hits": pro_gates,
                "daily_activity": [{"date": d, "count": c} for d, c in activity],
            }
            console.print(json.dumps(data, indent=2))
        else:
            console.print(
                format_stats_table(
                    commands, pro_gates, total, first, last, activity
                )
            )
    finally:
        ts.close()
