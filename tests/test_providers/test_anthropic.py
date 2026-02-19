"""Tests for ai_spend.providers.anthropic."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType
from ai_spend.providers.anthropic import _BASE_URL, AnthropicProvider


@pytest.fixture
def provider():
    return AnthropicProvider(name="my-anthropic", api_key="test-key-anthropic-123")


class TestAnthropicProvider:
    def test_provider_type(self, provider: AnthropicProvider):
        assert provider.provider_type == ProviderType.ANTHROPIC

    @respx.mock
    def test_fetch_usage_single_page(self, provider: AnthropicProvider):
        respx.get(f"{_BASE_URL}/cost_report").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "date": "2026-02-19",
                            "models": [
                                {
                                    "model": "claude-sonnet-4-20250514",
                                    "cost": "0.015",
                                    "input_tokens": 1000,
                                    "output_tokens": 500,
                                }
                            ],
                        }
                    ],
                },
            )
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert len(records) == 1
        assert records[0].model == "claude-sonnet-4-20250514"
        assert records[0].cost_usd == 0.015
        assert records[0].input_tokens == 1000

    @respx.mock
    def test_fetch_usage_pagination(self, provider: AnthropicProvider):
        route = respx.get(f"{_BASE_URL}/cost_report")
        route.side_effect = [
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "date": "2026-02-18",
                            "models": [
                                {
                                    "model": "claude",
                                    "cost": "1.0",
                                    "input_tokens": 100,
                                    "output_tokens": 50,
                                }
                            ],
                        }
                    ],
                    "next_cursor": "abc123",
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "date": "2026-02-19",
                            "models": [
                                {
                                    "model": "claude",
                                    "cost": "2.0",
                                    "input_tokens": 200,
                                    "output_tokens": 100,
                                }
                            ],
                        }
                    ],
                },
            ),
        ]
        records = provider.fetch_usage(date(2026, 2, 18), date(2026, 2, 19))
        assert len(records) == 2
        assert route.call_count == 2

    @respx.mock
    def test_fetch_usage_empty(self, provider: AnthropicProvider):
        respx.get(f"{_BASE_URL}/cost_report").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert records == []

    @respx.mock
    def test_fetch_usage_http_error(self, provider: AnthropicProvider):
        respx.get(f"{_BASE_URL}/cost_report").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"})
        )
        with pytest.raises(ProviderError, match="401"):
            provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))

    @respx.mock
    def test_fetch_usage_connection_error(self, provider: AnthropicProvider):
        respx.get(f"{_BASE_URL}/cost_report").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        with pytest.raises(ProviderError, match="request failed"):
            provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))

    @respx.mock
    def test_validate_credentials_success(self, provider: AnthropicProvider):
        respx.get(f"{_BASE_URL}/cost_report").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        assert provider.validate_credentials() is True

    @respx.mock
    def test_validate_credentials_failure(self, provider: AnthropicProvider):
        respx.get(f"{_BASE_URL}/cost_report").mock(return_value=httpx.Response(401))
        assert provider.validate_credentials() is False

    @respx.mock
    def test_validate_credentials_connection_error(self, provider: AnthropicProvider):
        respx.get(f"{_BASE_URL}/cost_report").mock(
            side_effect=httpx.ConnectError("refused")
        )
        assert provider.validate_credentials() is False

    @respx.mock
    def test_fetch_multiple_models_per_bucket(self, provider: AnthropicProvider):
        respx.get(f"{_BASE_URL}/cost_report").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "date": "2026-02-19",
                            "models": [
                                {
                                    "model": "claude-sonnet",
                                    "cost": "1.0",
                                    "input_tokens": 100,
                                    "output_tokens": 50,
                                },
                                {
                                    "model": "claude-haiku",
                                    "cost": "0.5",
                                    "input_tokens": 500,
                                    "output_tokens": 200,
                                },
                            ],
                        }
                    ],
                },
            )
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert len(records) == 2
        models = {r.model for r in records}
        assert models == {"claude-sonnet", "claude-haiku"}
