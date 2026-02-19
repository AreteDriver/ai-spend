"""Tests for ai_spend.cli."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_spend.cli import app
from ai_spend.config import reset_store
from ai_spend.licensing import generate_key

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate each test with its own config/store directory."""
    config_dir = tmp_path / ".ai-spend"
    config_dir.mkdir()
    monkeypatch.setenv("AI_SPEND_DIR", str(config_dir))
    monkeypatch.delenv("AI_SPEND_LICENSE", raising=False)
    reset_store()
    yield
    reset_store()


class TestVersion:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_version_short(self):
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "ai-spend" in result.stdout


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
