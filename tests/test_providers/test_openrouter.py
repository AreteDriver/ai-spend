"""Tests for OpenRouterProvider."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
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
        route = respx.post(f"{_BASE_URL}/analytics/query").mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "data": [
                            {
                                "date__day": "2025-02-19T00:00:00.000Z",
                                "model": "qwen/qwen2.5-coder-14b-instruct",
                                "total_usage": 0.0015,
                                "tokens_prompt": 1000,
                                "tokens_completion": 500,
                            },
                            {
                                "date__day": "2025-02-20T00:00:00.000Z",
                                "model": "anthropic/claude-sonnet-4-20250514",
                                "total_usage": 0.045,
                                "tokens_prompt": 2000,
                                "tokens_completion": 1000,
                            },
                        ],
                        "metadata": {
                            "query_time_ms": 38,
                            "row_count": 2,
                            "truncated": False,
                        },
                    }
                },
            )
        )

        records = provider.fetch_usage(
            start=date(2025, 2, 18),
            end=date(2025, 2, 21),
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
        # Verify request body
        request_body = route.calls[0].request.content
        assert b"total_usage" in request_body
        assert b"tokens_prompt" in request_body
        assert b"tokens_completion" in request_body
        assert b"model" in request_body
        assert b"day" in request_body

    @respx.mock
    def test_fetch_usage_empty(self, provider: OpenRouterProvider):
        """Handle empty response gracefully."""
        route = respx.post(f"{_BASE_URL}/analytics/query").mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "data": [],
                        "metadata": {
                            "query_time_ms": 10,
                            "row_count": 0,
                            "truncated": False,
                        },
                    }
                },
            )
        )

        records = provider.fetch_usage(
            start=date(2025, 2, 18),
            end=date(2025, 2, 21),
        )

        assert records == []
        assert route.called

    @respx.mock
    def test_fetch_usage_http_error(self, provider: OpenRouterProvider):
        """HTTP errors are wrapped in ProviderError."""
        respx.post(f"{_BASE_URL}/analytics/query").mock(return_value=Response(500))

        with pytest.raises(ProviderError) as exc_info:
            provider.fetch_usage(
                start=date(2025, 2, 18),
                end=date(2025, 2, 21),
            )

        assert "500" in str(exc_info.value)

    @respx.mock
    def test_fetch_usage_connection_error(self, provider: OpenRouterProvider):
        """Connection errors are wrapped in ProviderError."""
        respx.post(f"{_BASE_URL}/analytics/query").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.fetch_usage(
                start=date(2025, 2, 18),
                end=date(2025, 2, 21),
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
            side_effect=httpx.ConnectError("Connection refused")
        )
        assert provider.validate_credentials() is False

    @respx.mock
    def test_fetch_usage_truncated(self, provider: OpenRouterProvider):
        """Truncated results raise ProviderError with guidance."""
        respx.post(f"{_BASE_URL}/analytics/query").mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "data": [],
                        "metadata": {
                            "query_time_ms": 10,
                            "row_count": 0,
                            "truncated": True,
                        },
                    }
                },
            )
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.fetch_usage(
                start=date(2025, 2, 18),
                end=date(2025, 2, 21),
            )

        assert "truncated" in str(exc_info.value).lower()

    @respx.mock
    def test_fetch_usage_string_token_counts(self, provider: OpenRouterProvider):
        """Token counts returned as strings are parsed correctly."""
        respx.post(f"{_BASE_URL}/analytics/query").mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "data": [
                            {
                                "date__day": "2025-02-19T00:00:00.000Z",
                                "model": "openai/gpt-4o",
                                "total_usage": 1.50,
                                "tokens_prompt": "3000",
                                "tokens_completion": "1500",
                            }
                        ],
                        "metadata": {
                            "query_time_ms": 15,
                            "row_count": 1,
                            "truncated": False,
                        },
                    }
                },
            )
        )

        records = provider.fetch_usage(
            start=date(2025, 2, 18),
            end=date(2025, 2, 21),
        )

        assert len(records) == 1
        assert records[0].input_tokens == 3000
        assert records[0].output_tokens == 1500
        assert records[0].cost_usd == Decimal("1.50")

    @respx.mock
    def test_fetch_usage_missing_date_defaults_to_today(
        self, provider: OpenRouterProvider
    ):
        """Missing date__day falls back to today."""
        respx.post(f"{_BASE_URL}/analytics/query").mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "data": [
                            {
                                "model": "openai/gpt-4o",
                                "total_usage": 1.0,
                                "tokens_prompt": 100,
                                "tokens_completion": 50,
                            }
                        ],
                        "metadata": {
                            "query_time_ms": 5,
                            "row_count": 1,
                            "truncated": False,
                        },
                    }
                },
            )
        )

        records = provider.fetch_usage(
            start=date(2025, 2, 18),
            end=date(2025, 2, 21),
        )

        assert len(records) == 1
        assert records[0].date == date.today()
        assert records[0].cost_usd == Decimal("1.00")

    @respx.mock
    def test_fetch_usage_no_token_fields(self, provider: OpenRouterProvider):
        """Missing token fields default to 0."""
        respx.post(f"{_BASE_URL}/analytics/query").mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "data": [
                            {
                                "date__day": "2025-02-19T00:00:00.000Z",
                                "model": "openai/gpt-4o",
                                "total_usage": 0.50,
                            }
                        ],
                        "metadata": {
                            "query_time_ms": 5,
                            "row_count": 1,
                            "truncated": False,
                        },
                    }
                },
            )
        )

        records = provider.fetch_usage(
            start=date(2025, 2, 18),
            end=date(2025, 2, 21),
        )

        assert len(records) == 1
        assert records[0].input_tokens == 0
        assert records[0].output_tokens == 0
        assert records[0].cost_usd == Decimal("0.50")
