"""Tests for ai_spend.providers.openai."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType
from ai_spend.providers.openai import _BASE_URL, OpenAIProvider


@pytest.fixture
def provider():
    return OpenAIProvider(name="my-openai", api_key="test-key-openai-123")


class TestOpenAIProvider:
    def test_provider_type(self, provider: OpenAIProvider):
        assert provider.provider_type == ProviderType.OPENAI

    @respx.mock
    def test_fetch_usage_single_page(self, provider: OpenAIProvider):
        respx.get(f"{_BASE_URL}/costs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "start_time": 1771459200,  # 2026-02-19 UTC
                            "results": [
                                {
                                    "model": "gpt-4o",
                                    "amount": {"value": 0.05},
                                    "input_tokens": 2000,
                                    "output_tokens": 1000,
                                }
                            ],
                        }
                    ],
                },
            )
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert len(records) == 1
        assert records[0].model == "gpt-4o"
        assert records[0].cost_usd == Decimal("0.05")

    @respx.mock
    def test_fetch_usage_pagination(self, provider: OpenAIProvider):
        route = respx.get(f"{_BASE_URL}/costs")
        route.side_effect = [
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "start_time": 1771459200,
                            "results": [{"model": "gpt-4o", "amount": {"value": 1.0}}],
                        }
                    ],
                    "next_cursor": "cursor1",
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "start_time": 1771545600,
                            "results": [{"model": "gpt-4o", "amount": {"value": 2.0}}],
                        }
                    ],
                },
            ),
        ]
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 20))
        assert len(records) == 2
        assert route.call_count == 2

    @respx.mock
    def test_fetch_usage_empty(self, provider: OpenAIProvider):
        respx.get(f"{_BASE_URL}/costs").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert records == []

    @respx.mock
    def test_fetch_usage_http_error(self, provider: OpenAIProvider):
        respx.get(f"{_BASE_URL}/costs").mock(
            return_value=httpx.Response(403, json={"error": "forbidden"})
        )
        with pytest.raises(ProviderError, match="403"):
            provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))

    @respx.mock
    def test_fetch_usage_connection_error(self, provider: OpenAIProvider):
        respx.get(f"{_BASE_URL}/costs").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(ProviderError, match="request failed"):
            provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))

    @respx.mock
    def test_validate_credentials_success(self, provider: OpenAIProvider):
        respx.get(f"{_BASE_URL}/costs").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        assert provider.validate_credentials() is True

    @respx.mock
    def test_validate_credentials_failure(self, provider: OpenAIProvider):
        respx.get(f"{_BASE_URL}/costs").mock(return_value=httpx.Response(401))
        assert provider.validate_credentials() is False

    @respx.mock
    def test_validate_credentials_connection_error(self, provider: OpenAIProvider):
        respx.get(f"{_BASE_URL}/costs").mock(side_effect=httpx.ConnectError("refused"))
        assert provider.validate_credentials() is False

    @respx.mock
    def test_fetch_with_object_id_model(self, provider: OpenAIProvider):
        """OpenAI can nest model name in result.object.id."""
        respx.get(f"{_BASE_URL}/costs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "start_time": 1771459200,
                            "results": [
                                {
                                    "object": {"id": "gpt-4-turbo"},
                                    "amount": {"value": 0.10},
                                }
                            ],
                        }
                    ],
                },
            )
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert records[0].model == "gpt-4-turbo"

    @respx.mock
    def test_fetch_missing_amount(self, provider: OpenAIProvider):
        """Missing amount field should default to 0."""
        respx.get(f"{_BASE_URL}/costs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "start_time": 1771459200,
                            "results": [{"model": "gpt-4o", "amount": {}}],
                        }
                    ],
                },
            )
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert records[0].cost_usd == Decimal("0")
