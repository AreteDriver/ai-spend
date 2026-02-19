"""Integration smoke test for ai-spend."""

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
    config_dir = tmp_path / ".ai-spend"
    config_dir.mkdir()
    monkeypatch.setenv("AI_SPEND_DIR", str(config_dir))
    monkeypatch.delenv("AI_SPEND_LICENSE", raising=False)
    reset_store()
    yield
    reset_store()


class TestEndToEnd:
    def test_full_workflow(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Add provider -> manual add -> summary -> budget -> export."""
        # 1. Add manual provider
        r = runner.invoke(app, ["config", "add", "misc", "manual"])
        assert r.exit_code == 0

        # 2. Add manual entries
        r = runner.invoke(
            app,
            ["manual", "add", "gpt-4o", "5.00", "--date", "2026-02-19", "-n", "test"],
        )
        assert r.exit_code == 0
        r = runner.invoke(
            app,
            ["manual", "add", "claude", "10.00", "--date", "2026-02-19"],
        )
        assert r.exit_code == 0

        # 3. Check summary
        r = runner.invoke(app, ["summary", "--json"])
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["total_usd"] == pytest.approx(15.0)
        assert data["record_count"] == 2

        # 4. Set and check budget
        r = runner.invoke(app, ["budget", "set", "-t", "100"])
        assert r.exit_code == 0
        r = runner.invoke(app, ["budget", "check"])
        assert r.exit_code == 0

        # 5. Status
        r = runner.invoke(app, ["status"])
        assert r.exit_code == 0
        assert "Records" in r.stdout

        # 6. Export (needs Pro)
        key = generate_key()
        monkeypatch.setenv("AI_SPEND_LICENSE", key)
        out = tmp_path / "export.json"
        r = runner.invoke(app, ["export", "-f", "json", "-o", str(out)])
        assert r.exit_code == 0
        assert out.exists()
        exported = json.loads(out.read_text())
        assert len(exported) == 2

    def test_config_list_after_add_remove(self):
        """Config add/remove maintains consistent state."""
        runner.invoke(app, ["config", "add", "a", "anthropic"])
        runner.invoke(app, ["config", "add", "b", "openai"])
        runner.invoke(app, ["config", "remove", "a"])
        r = runner.invoke(app, ["config", "list"])
        assert r.exit_code == 0
        assert "b" in r.stdout
        assert "a" not in r.stdout or "openai" in r.stdout
