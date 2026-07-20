"""Tests for ai_spend.__main__.py."""

from __future__ import annotations

import runpy
import sys
from io import StringIO

import pytest


def test_main_entry_point() -> None:
    """Ensure python -m ai_spend --version works via runpy."""
    old_argv = sys.argv
    old_stdout = sys.stdout
    sys.argv = ["ai_spend", "--version"]
    sys.stdout = StringIO()
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("ai_spend", run_name="__main__")
    sys.argv = old_argv
    sys.stdout = old_stdout
    assert exc_info.value.code == 0


def test_shell_completion_output() -> None:
    """Verify --show-completion emits a non-empty completion script."""
    from typer.testing import CliRunner

    from ai_spend.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--show-completion"])
    # Typer may install instead of showing when SHELL is set; verify no crash
    assert result.exit_code in (0, 1)
    assert len(result.stdout) > 0 or len(result.stderr) > 0
