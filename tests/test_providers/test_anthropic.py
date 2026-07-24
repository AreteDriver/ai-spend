"""Tests for ai_spend.providers.anthropic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

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
                            "starting_at": "2026-02-19T00:00:00Z",
                            "ending_at": "2026-02-20T00:00:00Z",
                            "results": [
                                {
                                    "model": "claude-sonnet-4-20250514",
                                    "amount": "1.5",
                                    "currency": "USD",
                                    "cost_type": "tokens",
                                    "token_type": "output_tokens",
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
        # 1.5 cents → $0.015 USD
        assert records[0].cost_usd == Decimal("0.015")
        # Cost Report does not provide token counts
        assert records[0].input_tokens == 0
        assert records[0].output_tokens == 0

    @respx.mock
    def test_fetch_usage_pagination(self, provider: AnthropicProvider):
        route = respx.get(f"{_BASE_URL}/cost_report")
        route.side_effect = [
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "starting_at": "2026-02-18T00:00:00Z",
                            "ending_at": "2026-02-19T00:00:00Z",
                            "results": [
                                {
                                    "model": "claude-sonnet",
                                    "amount": "100",
                                    "currency": "USD",
                                    "cost_type": "tokens",
                                    "token_type": "uncached_input_tokens",
                                }
                            ],
                        }
                    ],
                    "has_more": True,
                    "next_page": "page_2_token",
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "starting_at": "2026-02-19T00:00:00Z",
                            "ending_at": "2026-02-20T00:00:00Z",
                            "results": [
                                {
                                    "model": "claude-sonnet",
                                    "amount": "200",
                                    "currency": "USD",
                                    "cost_type": "tokens",
                                    "token_type": "output_tokens",
                                }
                            ],
                        }
                    ],
                    "has_more": False,
                },
            ),
        ]
        records = provider.fetch_usage(date(2026, 2, 18), date(2026, 2, 19))
        assert len(records) == 2
        assert route.call_count == 2
        # Verify page param was sent on second request
        second_request = route.calls[1].request
        assert "page=page_2_token" in str(second_request.url)

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
                            "starting_at": "2026-02-19T00:00:00Z",
                            "ending_at": "2026-02-20T00:00:00Z",
                            "results": [
                                {
                                    "model": "claude-sonnet",
                                    "amount": "100",
                                    "currency": "USD",
                                    "cost_type": "tokens",
                                    "token_type": "uncached_input_tokens",
                                },
                                {
                                    "model": "claude-haiku",
                                    "amount": "50",
                                    "currency": "USD",
                                    "cost_type": "tokens",
                                    "token_type": "output_tokens",
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
        # 100 cents → $1.00 ; 50 cents → $0.50
        by_model = {r.model: r.cost_usd for r in records}
        assert by_model["claude-sonnet"] == Decimal("1.00")
        assert by_model["claude-haiku"] == Decimal("0.50")

    @respx.mock
    def test_fetch_aggregates_same_model_results(self, provider: AnthropicProvider):
        """Multiple result rows for the same model are aggregated."""
        respx.get(f"{_BASE_URL}/cost_report").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "starting_at": "2026-02-19T00:00:00Z",
                            "ending_at": "2026-02-20T00:00:00Z",
                            "results": [
                                {
                                    "model": "claude-sonnet",
                                    "amount": "100",
                                    "currency": "USD",
                                    "cost_type": "tokens",
                                    "token_type": "uncached_input_tokens",
                                },
                                {
                                    "model": "claude-sonnet",
                                    "amount": "50",
                                    "currency": "USD",
                                    "cost_type": "tokens",
                                    "token_type": "output_tokens",
                                },
                            ],
                        }
                    ],
                },
            )
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert len(records) == 1
        # 100 cents + 50 cents = 150 cents → $1.50
        assert records[0].cost_usd == Decimal("1.50")

    @respx.mock
    def test_fetch_usage_fractional_cents(self, provider: AnthropicProvider):
        """Amounts with fractional cents are handled with Decimal precision."""
        respx.get(f"{_BASE_URL}/cost_report").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "starting_at": "2026-02-19T00:00:00Z",
                            "ending_at": "2026-02-20T00:00:00Z",
                            "results": [
                                {
                                    "model": "claude-opus",
                                    "amount": "123.78912",
                                    "currency": "USD",
                                    "cost_type": "tokens",
                                }
                            ],
                        }
                    ],
                },
            )
        )
        records = provider.fetch_usage(date(2026, 2, 19), date(2026, 2, 19))
        assert len(records) == 1
        # 123.78912 cents → $1.2378912
        assert records[0].cost_usd == Decimal("1.2378912")
