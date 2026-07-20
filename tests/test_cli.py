"""Tests for ai_spend.cli."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_spend.cli import app
from ai_spend.context import AppContext
from ai_spend.licensing import generate_key
from ai_spend.models import ProviderType

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate each test with its own config/store directory."""
    config_dir = tmp_path / ".ai-spend"
    config_dir.mkdir()
    monkeypatch.setenv("AI_SPEND_DIR", str(config_dir))
    monkeypatch.delenv("AI_SPEND_LICENSE", raising=False)
    yield


class TestVersion:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.3.0" in result.stdout

    def test_version_short(self):
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "ai-spend" in result.stdout


class TestVerboseError:
    def test_verbose_traceback(self):
        result = runner.invoke(app, ["-V", "budget", "check"])
        assert result.exit_code == 1
        # Verbose mode should include traceback details
        assert "Traceback" in result.stdout or "No budget" in result.stdout


class TestConfigAdd:
    def test_add_provider(self):
        result = runner.invoke(
            app,
            ["config", "add", "my-claude", "anthropic", "--key", "test-key"],
        )
        assert result.exit_code == 0
        assert "Added provider" in result.stdout

    def test_add_duplicate(self):
        runner.invoke(app, ["config", "add", "x", "manual"])
        result = runner.invoke(app, ["config", "add", "x", "manual"])
        assert result.exit_code == 1
        assert "already exists" in result.stdout

    def test_add_openai(self):
        result = runner.invoke(
            app,
            ["config", "add", "my-openai", "openai", "-k", "test-key-openai"],
        )
        assert result.exit_code == 0
        assert "openai" in result.stdout

    def test_free_tier_limit(self):
        runner.invoke(app, ["config", "add", "a", "anthropic"])
        runner.invoke(app, ["config", "add", "b", "openai"])
        runner.invoke(app, ["config", "add", "c", "manual"])
        result = runner.invoke(app, ["config", "add", "d", "manual"])
        assert result.exit_code == 1
        assert "Free tier" in result.stdout

    def test_pro_unlimited(self, monkeypatch: pytest.MonkeyPatch):
        key = generate_key()
        monkeypatch.setenv("AI_SPEND_LICENSE", key)
        for i in range(5):
            runner.invoke(app, ["config", "add", f"p{i}", "manual"])
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "p4" in result.stdout


class TestConfigRemove:
    def test_remove_provider(self):
        runner.invoke(app, ["config", "add", "x", "manual"])
        result = runner.invoke(app, ["config", "remove", "x"])
        assert result.exit_code == 0
        assert "Removed" in result.stdout

    def test_remove_missing(self):
        result = runner.invoke(app, ["config", "remove", "nope"])
        assert result.exit_code == 1
        assert "not found" in result.stdout


class TestConfigEdit:
    def test_edit_api_key(self):
        runner.invoke(app, ["config", "add", "x", "manual", "-k", "old-key"])
        result = runner.invoke(app, ["config", "edit", "x", "--key", "new-key"])
        assert result.exit_code == 0
        assert "Updated" in result.stdout

    def test_edit_type(self):
        runner.invoke(app, ["config", "add", "x", "manual"])
        result = runner.invoke(app, ["config", "edit", "x", "--type", "anthropic"])
        assert result.exit_code == 0
        assert "anthropic" in result.stdout

    def test_edit_no_changes(self):
        runner.invoke(app, ["config", "add", "x", "manual"])
        result = runner.invoke(app, ["config", "edit", "x"])
        assert result.exit_code == 1
        assert "No changes" in result.stdout

    def test_edit_missing(self):
        result = runner.invoke(app, ["config", "edit", "nonexistent", "--key", "k"])
        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_config_encrypt(self):
        runner.invoke(app, ["config", "add", "x", "openai", "--key", "secret123"])
        result = runner.invoke(app, ["config", "encrypt"])
        assert result.exit_code == 0
        assert "encrypted" in result.stdout.lower()


class TestConfigList:
    def test_empty_list(self):
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "No providers" in result.stdout

    def test_list_with_providers(self):
        runner.invoke(app, ["config", "add", "a", "anthropic", "-k", "test-key"])
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "a" in result.stdout
        assert "anthropic" in result.stdout


class TestConfigValidate:
    def test_validate_no_providers(self):
        result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 0
        assert "No providers" in result.stdout

    def test_validate_manual_skipped(self):
        runner.invoke(app, ["config", "add", "m", "manual"])
        result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 0
        assert "skipped" in result.stdout

    def test_validate_api_provider(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "my-openai", "openai", "-k", "test-key"])
        import ai_spend.providers.registry

        def _fake_provider(*args, **kwargs):
            class Fake:
                name = "my-openai"
                api_key = "test-key"
                provider_type = None

                def validate_credentials(self):
                    return True

            return Fake()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _fake_provider, raising=False
        )
        result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 0
        assert "credentials valid" in result.stdout

    def test_validate_invalid_credentials(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "my-openai", "openai", "-k", "test-key"])
        import ai_spend.providers.registry

        def _fake_provider(*args, **kwargs):
            class Fake:
                name = "my-openai"
                api_key = "test-key"
                provider_type = None

                def validate_credentials(self):
                    return False

            return Fake()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _fake_provider, raising=False
        )
        result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 1
        assert "credentials invalid" in result.stdout

    def test_validate_failure(self, monkeypatch: pytest.MonkeyPatch):
        from ai_spend.exceptions import ProviderError

        runner.invoke(app, ["config", "add", "my-openai", "openai", "-k", "test-key"])
        import ai_spend.providers.registry

        def _broken_provider(*args, **kwargs):
            class Broken:
                name = "my-openai"
                api_key = "test-key"
                provider_type = None

                def validate_credentials(self):
                    raise ProviderError("bad key")

            return Broken()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _broken_provider, raising=False
        )
        result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 1
        assert "bad key" in result.stdout


class TestSync:
    def test_sync_no_providers(self):
        result = runner.invoke(app, ["sync"])
        assert result.exit_code == 0
        assert "No providers" in result.stdout

    def test_sync_manual_skipped(self):
        runner.invoke(app, ["config", "add", "m", "manual"])
        result = runner.invoke(app, ["sync"])
        assert result.exit_code == 0
        # Manual providers are skipped — no output about them

    def test_sync_dry_run(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "my-openai", "openai", "-k", "test-key"])
        import ai_spend.providers.registry

        def _fake_provider(*args, **kwargs):
            class Fake:
                name = "my-openai"
                api_key = "test-key"
                provider_type = None

                def fetch_usage(self, start, end):
                    return []

            return Fake()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _fake_provider, raising=False
        )
        result = runner.invoke(app, ["sync", "--dry-run"])
        assert result.exit_code == 0
        assert "would sync" in result.stdout

    def test_sync_dry_run_many_records(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "my-openai", "openai", "-k", "test-key"])
        import ai_spend.providers.registry

        def _fake_provider(*args, **kwargs):
            from datetime import date
            from decimal import Decimal

            from ai_spend.models import UsageRecord

            class Fake:
                name = "my-openai"
                api_key = "test-key"
                provider_type = None

                def fetch_usage(self, start, end):
                    return [
                        UsageRecord(
                            provider_id="my-openai",
                            provider_type=ProviderType.OPENAI,
                            date=date.today(),
                            model=f"gpt-{i}",
                            cost_usd=Decimal("0.01"),
                        )
                        for i in range(5)
                    ]

            return Fake()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _fake_provider, raising=False
        )
        result = runner.invoke(app, ["sync", "--dry-run"])
        assert result.exit_code == 0
        assert "... and 2 more" in result.stdout

    def test_sync_failure(self, monkeypatch: pytest.MonkeyPatch):
        from ai_spend.exceptions import ProviderError

        runner.invoke(app, ["config", "add", "my-openai", "openai", "-k", "test-key"])
        import ai_spend.providers.registry

        def _broken_provider(*args, **kwargs):
            class Broken:
                name = "broken"
                api_key = ""
                provider_type = None

                def fetch_usage(self, start, end):
                    raise ProviderError("network down")

            return Broken()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _broken_provider, raising=False
        )
        result = runner.invoke(app, ["sync"])
        assert result.exit_code == 0
        assert "network down" in result.stdout

    def test_sync_provider_filter(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "p1", "openai", "-k", "k1"])
        runner.invoke(app, ["config", "add", "p2", "anthropic", "-k", "k2"])
        import ai_spend.providers.registry

        def _fake_provider(*args, **kwargs):
            class Fake:
                name = kwargs.get("name", "fake")
                api_key = ""
                provider_type = None

                def fetch_usage(self, start, end):
                    return []

            return Fake()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _fake_provider, raising=False
        )
        result = runner.invoke(app, ["sync", "--provider", "p1"])
        assert result.exit_code == 0
        assert "p1" in result.stdout

    def test_sync_provider_not_found(self):
        runner.invoke(app, ["config", "add", "existing", "manual"])
        result = runner.invoke(app, ["sync", "--provider", "nonexistent"])
        assert result.exit_code == 1
        assert "not configured" in result.stdout

    def test_sync_since(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "my-openai", "openai", "-k", "test-key"])
        import ai_spend.providers.registry

        captured_start = None

        def _fake_provider(*args, **kwargs):
            class Fake:
                name = "my-openai"
                api_key = "test-key"
                provider_type = None

                def fetch_usage(self, start, end):
                    nonlocal captured_start
                    captured_start = start
                    return []

            return Fake()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _fake_provider, raising=False
        )
        result = runner.invoke(app, ["sync", "--since", "2026-01-01"])
        assert result.exit_code == 0
        assert captured_start is not None
        assert captured_start.isoformat() == "2026-01-01"

    def test_sync_since_invalid(self):
        runner.invoke(app, ["config", "add", "existing", "manual"])
        result = runner.invoke(app, ["sync", "--since", "not-a-date"])
        assert result.exit_code == 1
        assert "Invalid --since" in result.stdout


class TestSummary:
    def test_empty_summary(self):
        result = runner.invoke(app, ["summary"])
        assert result.exit_code == 0
        assert "$0.00" in result.stdout

    def test_summary_json(self):
        result = runner.invoke(app, ["summary", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "total_usd" in data

    def test_summary_with_data(self):
        runner.invoke(app, ["manual", "add", "misc", "5.00"])
        result = runner.invoke(app, ["summary"])
        assert result.exit_code == 0
        assert "$5.00" in result.stdout

    def test_summary_provider_filter(self):
        runner.invoke(app, ["manual", "add", "misc", "5.00", "--provider", "p1"])
        runner.invoke(app, ["manual", "add", "misc2", "3.00", "--provider", "p2"])
        result = runner.invoke(app, ["summary", "--provider", "p1"])
        assert result.exit_code == 0
        assert "$5.00" in result.stdout
        assert "$3.00" not in result.stdout


class TestDaily:
    def test_empty_daily(self):
        result = runner.invoke(app, ["daily"])
        assert result.exit_code == 0
        assert "Daily Spend" in result.stdout

    def test_daily_json(self):
        result = runner.invoke(app, ["daily", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_daily_with_data(self):
        runner.invoke(app, ["manual", "add", "misc", "3.50"])
        result = runner.invoke(app, ["daily", "--last", "7"])
        assert result.exit_code == 0

    def test_daily_provider_filter(self):
        runner.invoke(app, ["manual", "add", "misc", "4.00", "--provider", "a"])
        runner.invoke(app, ["manual", "add", "misc2", "2.00", "--provider", "b"])
        result = runner.invoke(app, ["daily", "--provider", "a"])
        assert result.exit_code == 0
        assert "$4.00" in result.stdout
        assert "$2.00" not in result.stdout


class TestBudgetSet:
    def test_set_budget(self):
        result = runner.invoke(app, ["budget", "set", "--total", "100.0"])
        assert result.exit_code == 0
        assert "$100.00" in result.stdout

    def test_set_budget_weekly(self):
        result = runner.invoke(app, ["budget", "set", "-t", "50", "-p", "week"])
        assert result.exit_code == 0
        assert "week" in result.stdout

    def test_set_budget_invalid(self):
        result = runner.invoke(app, ["budget", "set", "-t", "0"])
        assert result.exit_code == 1
        assert "greater than zero" in result.stdout


class TestBudgetCheck:
    def test_check_no_budget(self):
        result = runner.invoke(app, ["budget", "check"])
        assert result.exit_code == 1
        assert "No budget" in result.stdout

    def test_check_under_budget(self):
        runner.invoke(app, ["budget", "set", "-t", "100"])
        result = runner.invoke(app, ["budget", "check"])
        assert result.exit_code == 0
        assert "$100.00" in result.stdout


class TestExport:
    def test_export_free_blocked(self):
        result = runner.invoke(app, ["export"])
        assert result.exit_code == 1
        assert "Pro license" in result.stdout

    def test_export_pro_json(self, monkeypatch: pytest.MonkeyPatch):
        key = generate_key()
        monkeypatch.setenv("AI_SPEND_LICENSE", key)
        runner.invoke(app, ["manual", "add", "misc", "5.0"])
        result = runner.invoke(app, ["export", "--format", "json"])
        assert result.exit_code == 0

    def test_export_pro_csv(self, monkeypatch: pytest.MonkeyPatch):
        key = generate_key()
        monkeypatch.setenv("AI_SPEND_LICENSE", key)
        runner.invoke(app, ["manual", "add", "misc", "5.0"])
        result = runner.invoke(app, ["export", "--format", "csv"])
        assert result.exit_code == 0
        assert "record_id" in result.stdout

    def test_export_to_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        key = generate_key()
        monkeypatch.setenv("AI_SPEND_LICENSE", key)
        runner.invoke(app, ["manual", "add", "misc", "5.0"])
        out = tmp_path / "export.json"
        result = runner.invoke(app, ["export", "-f", "json", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()


class TestPrune:
    def test_prune_dry_run(self):
        runner.invoke(app, ["manual", "add", "misc", "5.00"])
        result = runner.invoke(app, ["prune", "--older-than", "1", "--dry-run"])
        assert result.exit_code == 0
        assert "Would delete" in result.stdout

    def test_prune_actual(self):
        runner.invoke(app, ["manual", "add", "misc", "5.00"])
        result = runner.invoke(app, ["prune", "--older-than", "0"])
        assert result.exit_code == 0
        assert "Deleted" in result.stdout

    def test_prune_no_old_records(self):
        result = runner.invoke(app, ["prune", "--older-than", "9999"])
        assert result.exit_code == 0
        assert "Deleted 0" in result.stdout


class TestImport:
    def test_import_json(self, tmp_path: Path):
        data = json.dumps(
            [
                {
                    "provider_id": "test",
                    "provider_type": "manual",
                    "date": "2026-02-19",
                    "model": "misc",
                    "cost_usd": "5.00",
                }
            ]
        )
        f = tmp_path / "records.json"
        f.write_text(data)
        result = runner.invoke(app, ["import", str(f), "--format", "json"])
        assert result.exit_code == 0
        assert "Imported" in result.stdout

    def test_import_csv(self, tmp_path: Path):
        lines = [
            "provider_id,provider_type,date,model,cost_usd",
            "test,manual,2026-02-19,misc,3.50",
        ]
        f = tmp_path / "records.csv"
        f.write_text("\n".join(lines))
        result = runner.invoke(app, ["import", str(f), "--format", "csv"])
        assert result.exit_code == 0
        assert "Imported" in result.stdout

    def test_import_missing_file(self):
        result = runner.invoke(app, ["import", "/does/not/exist.json"])
        assert result.exit_code == 1
        assert "File not found" in result.stdout

    def test_import_invalid_data(self, tmp_path: Path):
        f = tmp_path / "bad.json"
        f.write_text('[{"not_a_record": true}]')
        result = runner.invoke(app, ["import", str(f), "--format", "json"])
        assert result.exit_code == 1
        assert "Error" in result.stdout


class TestManualAdd:
    def test_add_manual_entry(self):
        result = runner.invoke(app, ["manual", "add", "misc", "5.00"])
        assert result.exit_code == 0
        assert "$5.00" in result.stdout

    def test_add_with_date(self):
        result = runner.invoke(
            app,
            ["manual", "add", "gpt-4o", "10.0", "--date", "2026-02-19"],
        )
        assert result.exit_code == 0
        assert "2026-02-19" in result.stdout

    def test_add_with_note(self):
        result = runner.invoke(
            app,
            ["manual", "add", "misc", "1.0", "-n", "test charge"],
        )
        assert result.exit_code == 0

    def test_add_invalid_date(self):
        result = runner.invoke(
            app,
            ["manual", "add", "misc", "1.0", "--date", "not-a-date"],
        )
        assert result.exit_code == 1
        assert "Invalid date" in result.stdout

    def test_add_custom_provider(self):
        result = runner.invoke(
            app,
            ["manual", "add", "misc", "1.0", "--provider", "custom"],
        )
        assert result.exit_code == 0


class TestStats:
    def test_stats_disabled(self):
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "Telemetry is disabled" in result.stdout

    def test_stats_enabled(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AI_SPEND_TELEMETRY", "1")
        runner.invoke(app, ["summary"])  # record a command event
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "Telemetry Overview" in result.stdout

    def test_stats_json(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AI_SPEND_TELEMETRY", "1")
        runner.invoke(app, ["summary"])
        result = runner.invoke(app, ["stats", "--json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.stdout)
        assert "total_events" in data


class TestStatus:
    def test_status_empty(self):
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "ai-spend" in result.stdout
        assert "License" in result.stdout
        assert "Providers" in result.stdout
        assert "Records" in result.stdout

    def test_status_with_data(self):
        runner.invoke(app, ["config", "add", "x", "manual"])
        runner.invoke(app, ["manual", "add", "misc", "5.0"])
        runner.invoke(app, ["budget", "set", "-t", "100"])
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "$100.00" in result.stdout

    def test_status_pro(self, monkeypatch: pytest.MonkeyPatch):
        key = generate_key()
        monkeypatch.setenv("AI_SPEND_LICENSE", key)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "pro" in result.stdout

    def test_status_with_syncs(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "my-openai", "openai", "-k", "test-key"])
        import ai_spend.providers.registry

        def _fake_provider(*args, **kwargs):
            class Fake:
                name = "my-openai"
                api_key = "test-key"
                provider_type = None

                def fetch_usage(self, start, end):
                    return []

            return Fake()

        monkeypatch.setattr(
            ai_spend.providers.registry, "get_provider", _fake_provider, raising=False
        )
        runner.invoke(app, ["sync"])
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "SUCCESS" in result.stdout or "my-openai" in result.stdout


class TestGracefulShutdown:
    def test_normal_exit_does_not_close_store(self):
        from ai_spend.cli import _GracefulShutdown

        class MockStore:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        store = MockStore()
        with _GracefulShutdown(store) as shutdown:
            assert not shutdown.signaled
        assert not store.closed

    def test_signal_closes_store(self):
        from ai_spend.cli import _GracefulShutdown

        class MockStore:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        store = MockStore()
        with _GracefulShutdown(store) as shutdown:
            shutdown._handler(2, None)
            assert shutdown.signaled
        assert store.closed


class TestHealth:
    def test_health_all_pass(self):
        runner.invoke(app, ["config", "add", "x", "manual"])
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Database integrity" in result.stdout
        assert "All checks passed" in result.stdout

    def test_health_no_config_file(self):
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Config file not present" in result.stdout

    def test_health_encryption_warning(self):
        runner.invoke(app, ["config", "add", "x", "manual"])
        # Remove key file if it exists to trigger warning
        import os

        key_file = Path(os.environ["AI_SPEND_DIR"]) / ".key"
        if key_file.exists():
            key_file.unlink()
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "encryption key not present" in result.stdout

    def test_health_config_dir_stat_error(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "x", "manual"])

        class BadStatDir:
            """Wrapper that raises on stat()."""

            def __init__(self, path: Path) -> None:
                self._path = path

            def __getattr__(self, name: str):
                return getattr(self._path, name)

            def __truediv__(self, other):
                return self._path / other

            def stat(self, *args, **kwargs):
                raise OSError("bad stat")

        original_from_env = AppContext.from_env
        fake_dir = BadStatDir(Path(os.environ["AI_SPEND_DIR"]))

        def _fake_from_env(*, verbose: bool = False):
            ctx = original_from_env(verbose=verbose)
            ctx.config_dir = fake_dir  # type: ignore[assignment]
            return ctx

        monkeypatch.setattr(AppContext, "from_env", _fake_from_env)
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Config directory check error" in result.stdout
        assert "Some checks raised warnings" in result.stdout

    def test_health_integrity_not_ok(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "x", "manual"])
        original_from_env = AppContext.from_env

        class FakeCursor:
            def __init__(self, rows):
                self._rows = rows

            def fetchone(self):
                return self._rows[0] if self._rows else None

        class FakeConn:
            def __init__(self, real_conn):
                self._real = real_conn

            def execute(self, sql, *args):
                if "integrity_check" in sql.lower():

                    class FakeRow:
                        def __getitem__(self, _):
                            return "corrupt"

                    return FakeCursor([FakeRow()])
                return self._real.execute(sql, *args)

            def close(self):
                self._real.close()

        store = AppContext.from_env(verbose=False).store
        fake_conn = FakeConn(store._conn)
        monkeypatch.setattr(store, "_conn", fake_conn)

        def _fake_from_env(*, verbose: bool = False):
            ctx = original_from_env(verbose=verbose)
            ctx.store = store
            return ctx

        monkeypatch.setattr(AppContext, "from_env", _fake_from_env)
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Database integrity failed" in result.stdout
        assert "Some checks raised warnings" in result.stdout

    def test_health_config_dir_permissions_wrong(self, monkeypatch: pytest.MonkeyPatch):
        runner.invoke(app, ["config", "add", "x", "manual"])
        original_from_env = AppContext.from_env
        config_dir = Path(os.environ["AI_SPEND_DIR"])

        class WrongPermsDir:
            """Wrapper that returns mode 755 from stat()."""

            def __init__(self, path: Path) -> None:
                self._path = path

            def __getattr__(self, name: str):
                return getattr(self._path, name)

            def __truediv__(self, other):
                return self._path / other

            def stat(self, *args, **kwargs):
                class FakeStat:
                    st_mode = 0o40755

                return FakeStat()

        fake_dir = WrongPermsDir(config_dir)

        def _fake_from_env(*, verbose: bool = False):
            ctx = original_from_env(verbose=verbose)
            ctx.config_dir = fake_dir  # type: ignore[assignment]
            return ctx

        monkeypatch.setattr(AppContext, "from_env", _fake_from_env)
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Config dir permissions" in result.stdout
        assert "Some checks raised warnings" in result.stdout

    def test_health_config_file_permissions_wrong(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        runner.invoke(app, ["config", "add", "x", "manual"])
        original_from_env = AppContext.from_env
        config_dir = Path(os.environ["AI_SPEND_DIR"])

        class WrongFileStat:
            def __init__(self, path: Path) -> None:
                self._path = path

            def __getattr__(self, name: str):
                return getattr(self._path, name)

            def stat(self, *args, **kwargs):
                class FakeStat:
                    st_mode = 0o100644

                return FakeStat()

        class WrongFilePermsDir:
            """Wrapper that returns mode 644 for config.yaml stat()."""

            def __init__(self, path: Path) -> None:
                self._path = path

            def __getattr__(self, name: str):
                return getattr(self._path, name)

            def __truediv__(self, other):
                result = self._path / other
                if str(result).endswith("config.yaml"):
                    return WrongFileStat(result)
                return result

            def stat(self, *args, **kwargs):
                return self._path.stat(*args, **kwargs)

        fake_dir = WrongFilePermsDir(config_dir)

        def _fake_from_env(*, verbose: bool = False):
            ctx = original_from_env(verbose=verbose)
            ctx.config_dir = fake_dir  # type: ignore[assignment]
            return ctx

        monkeypatch.setattr(AppContext, "from_env", _fake_from_env)
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Config file permissions" in result.stdout
        assert "Some checks raised warnings" in result.stdout
