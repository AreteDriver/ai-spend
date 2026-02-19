"""Tests for ai_spend.gates."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from ai_spend.exceptions import LicenseError
from ai_spend.gates import require_pro
from ai_spend.licensing import generate_key


class TestRequirePro:
    def test_blocks_free_tier(self):
        @require_pro("export")
        def export_data():
            return "exported"

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(LicenseError, match="export"):
                export_data()

    def test_allows_pro_tier(self):
        @require_pro("export")
        def export_data():
            return "exported"

        key = generate_key()
        with patch.dict(os.environ, {"AI_SPEND_LICENSE": key}):
            result = export_data()
            assert result == "exported"

    def test_preserves_function_name(self):
        @require_pro("test")
        def my_function():
            """My docstring."""

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_passes_args_through(self):
        @require_pro("test")
        def add(a: int, b: int) -> int:
            return a + b

        key = generate_key()
        with patch.dict(os.environ, {"AI_SPEND_LICENSE": key}):
            assert add(2, 3) == 5

    def test_passes_kwargs_through(self):
        @require_pro("test")
        def greet(name: str = "world") -> str:
            return f"hello {name}"

        key = generate_key()
        with patch.dict(os.environ, {"AI_SPEND_LICENSE": key}):
            assert greet(name="claude") == "hello claude"

    def test_error_message_includes_env_var(self):
        @require_pro("budget alerts")
        def check_alerts():
            pass

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(LicenseError, match="AI_SPEND_LICENSE"):
                check_alerts()

    def test_error_message_includes_feature_name(self):
        @require_pro("historical data")
        def get_history():
            pass

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(LicenseError, match="historical data"):
                get_history()
