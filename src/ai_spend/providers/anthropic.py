"""Anthropic Admin API provider for ai-spend."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider, _make_request
from ai_spend.providers.registry import register_provider

_BASE_URL = "https://api.anthropic.com/v1/organizations"


class AnthropicProvider(BaseProvider):
    """Fetch usage data from the Anthropic Admin API."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.ANTHROPIC

    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        """Fetch cost report from Anthropic Admin API with cursor pagination."""
        records: list[UsageRecord] = []
        cursor: str | None = None

        try:
            with httpx.Client(timeout=30.0) as client:
                while True:
                    params: dict[str, str] = {
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                    }
                    if cursor:
                        params["cursor"] = cursor

                    resp = _make_request(
                        client,
                        "GET",
                        f"{_BASE_URL}/cost_report",
                        headers={
                            "x-api-key": self.api_key,
                            "anthropic-version": "2023-06-01",
                        },
                        params=params,
                    )
                    data = resp.json()

                    for bucket in data.get("data", []):
                        bucket_date = bucket.get("date", start.isoformat())
                        for model_entry in bucket.get("models", []):
                            model_name = model_entry.get("model", "unknown")
                            # Anthropic returns costs in USD as decimal strings
                            cost_str = model_entry.get("cost", "0")
                            cost = Decimal(cost_str)
                            input_tokens = model_entry.get("input_tokens", 0)
                            output_tokens = model_entry.get("output_tokens", 0)
                            records.append(
                                UsageRecord(
                                    provider_id=self.name,
                                    provider_type=ProviderType.ANTHROPIC,
                                    date=date.fromisoformat(bucket_date),
                                    model=model_name,
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                    cost_usd=cost,
                                )
                            )

                    cursor = data.get("next_cursor")
                    if not cursor:
                        break

        except httpx.HTTPStatusError as e:
            raise ProviderError(f"Anthropic API error: {e.response.status_code}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"Anthropic API request failed: {e}") from e

        return records

    def validate_credentials(self) -> bool:
        """Validate Anthropic admin API key."""
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = _make_request(
                    client,
                    "GET",
                    f"{_BASE_URL}/cost_report",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    params={"start_date": "2026-01-01", "end_date": "2026-01-01"},
                    max_attempts=1,  # No retry for simple credential check
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


register_provider(ProviderType.ANTHROPIC, AnthropicProvider)
