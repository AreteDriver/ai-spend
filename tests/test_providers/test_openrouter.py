"""Tests for OpenRouterProvider."""

from __future__ import annotations

from decimal import Decimal

import pytest
import respx
from httpx import Response

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType
from ai_spend.providers.openrouter import _BASE_URL, OpenRouterProvider


@pytest.fixture
def provider() -> OpenRouterProvider:
    """Create an OpenRouterProvider instance for testing."""
    return OpenRouterProvider(name="my-openrouter", api_key="test-key-openrouter-123")


class TestOpenRouterProvider:
    def test_provider_type(self, provider: OpenRouterProvider):
        """Provider type is OPENROUTER."""
        assert provider.provider_type == ProviderType.OPENROUTER

    @respx.mock
    def test_fetch_usage_single_page(self, provider: OpenRouterProvider):
        """Fetch usage with a single page of results."""
        route = respx.get(f"{_BASE_URL}/generations").mock(
            return_value=Response(
                200,
                json={
                    "data": [
                        {
                            "id": "gen-1",
                            "model": "qwen/qwen2.5-coder-14b-instruct",
                            "created_at": 1739923200,  # 2025-02-19T00:00:00Z
                            "native_tokens_prompt": 1000,
                            "native_tokens_completion": 500,
                            "native_cost": 0.0015,
                        },
                        {
                            "id": "gen-2",
                            "model": "anthropic/claude-sonnet-4-20250514",
                            "created_at": 1740009600,  # 2025-02-20T00:00:00Z
                            "native_tokens_prompt": 2000,
                            "native_tokens_completion": 1000,
                            "native_cost": 0.045,
                        },
                    ]
                },
            )
        )

        records = provider.fetch_usage(
            start=__import__("datetime").date(2025, 2, 18),
            end=__import__("datetime").date(2025, 2, 21),
        )

        assert len(records) == 2
        assert records[0].provider_type == ProviderType.OPENROUTER
        assert records[0].model == "qwen/qwen2.5-coder-14b-instruct"
        assert records[0].input_tokens == 1000
        assert records[0].output_tokens == 500
        assert records[0].cost_usd == Decimal("0.0015")
        assert records[1].model == "anthropic/claude-sonnet-4-20250514"
        assert records[1].cost_usd == Decimal("0.045")
        assert route.called

    @respx.mock
    def test_fetch_usage_empty(self, provider: OpenRouterProvider):
        """Handle empty response gracefully."""
        route = respx.get(f"{_BASE_URL}/generations").mock(
            return_value=Response(200, json={"data": []})
        )

        records = provider.fetch_usage(
            start=__import__("datetime").date(2025, 2, 18),
            end=__import__("datetime").date(2025, 2, 21),
        )

        assert records == []
        assert route.called

    @respx.mock
    def test_fetch_usage_http_error(self, provider: OpenRouterProvider):
        """HTTP errors are wrapped in ProviderError."""
        respx.get(f"{_BASE_URL}/generations").mock(return_value=Response(500))

        with pytest.raises(ProviderError) as exc_info:
            provider.fetch_usage(
                start=__import__("datetime").date(2025, 2, 18),
                end=__import__("datetime").date(2025, 2, 21),
            )

        assert "500" in str(exc_info.value)

    @respx.mock
    def test_fetch_usage_connection_error(self, provider: OpenRouterProvider):
        """Connection errors are wrapped in ProviderError."""
        respx.get(f"{_BASE_URL}/generations").mock(
            side_effect=__import__("httpx").ConnectError("Connection refused")
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.fetch_usage(
                start=__import__("datetime").date(2025, 2, 18),
                end=__import__("datetime").date(2025, 2, 21),
            )

        assert "failed" in str(exc_info.value).lower()

    @respx.mock
    def test_validate_credentials_success(self, provider: OpenRouterProvider):
        """Valid credentials return True."""
        route = respx.get(f"{_BASE_URL}/auth/key").mock(return_value=Response(200))
        assert provider.validate_credentials() is True
        assert route.called

    @respx.mock
    def test_validate_credentials_failure(self, provider: OpenRouterProvider):
        """Invalid credentials return False."""
        route = respx.get(f"{_BASE_URL}/auth/key").mock(return_value=Response(401))
        assert provider.validate_credentials() is False
        assert route.called

    @respx.mock
    def test_validate_credentials_connection_error(self, provider: OpenRouterProvider):
        """Connection errors during validation return False."""
        respx.get(f"{_BASE_URL}/auth/key").mock(
            side_effect=__import__("httpx").ConnectError("Connection refused")
        )
        assert provider.validate_credentials() is False

    @respx.mock
    def test_fetch_usage_fallback_to_tokens(self, provider: OpenRouterProvider):
        """When native_cost is missing, estimate from tokens."""
        route = respx.get(f"{_BASE_URL}/generations").mock(
            return_value=Response(
                200,
                json={
                    "data": [
                        {
                            "id": "gen-3",
                            "model": "meta-llama/llama-3.1-8b-instruct",
                            "created_at": 1739923200,
                            "native_tokens_prompt": 10000,
                            "native_tokens_completion": 5000,
                            # native_cost is 0.0 — should fallback to token estimate
                        },
                    ]
                },
            )
        )

        records = provider.fetch_usage(
            start=__import__("datetime").date(2025, 2, 18),
            end=__import__("datetime").date(2025, 2, 21),
        )

        assert len(records) == 1
        assert records[0].cost_usd == Decimal("15000") * Decimal("0.0000015")
        assert route.called
