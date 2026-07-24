"""OpenRouter API provider for ai-spend."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import httpx

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider, _make_request
from ai_spend.providers.registry import register_provider

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(BaseProvider):
    """Fetch usage data from the OpenRouter Analytics API.

    Uses the beta ``POST /api/v1/analytics/query`` endpoint with daily
    granularity and ``model`` dimension.  Requires a **Management API Key**
    (regular inference keys will receive 403).
    """

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENROUTER

    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        """Fetch aggregated usage data from OpenRouter Analytics API."""
        records: list[UsageRecord] = []

        try:
            with httpx.Client(timeout=30.0) as client:
                body = {
                    "metrics": [
                        "total_usage",
                        "tokens_prompt",
                        "tokens_completion",
                    ],
                    "dimensions": ["model"],
                    "granularity": "day",
                    "time_range": {
                        "start": f"{start.isoformat()}T00:00:00Z",
                        "end": f"{end.isoformat()}T23:59:59Z",
                    },
                    "limit": 10000,
                }

                resp = _make_request(
                    client,
                    "POST",
                    f"{_BASE_URL}/analytics/query",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/AreteDriver/ai-spend",
                        "X-Title": "ai-spend",
                    },
                    json=body,
                )
                payload = resp.json()
                data = payload.get("data", {})
                rows = data.get("data", [])

                for row in rows:
                    bucket_date = self._parse_date(row.get("date__day", ""))
                    model_name = row.get("model", "unknown")

                    # total_usage is cost in USD (float)
                    raw_cost = row.get("total_usage", 0.0)
                    cost = Decimal(str(raw_cost))

                    # Token counts may be returned as strings
                    input_tokens = self._to_int(row.get("tokens_prompt", 0))
                    output_tokens = self._to_int(row.get("tokens_completion", 0))

                    records.append(
                        UsageRecord(
                            provider_id=self.name,
                            provider_type=ProviderType.OPENROUTER,
                            date=bucket_date,
                            model=model_name,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cost_usd=cost,
                        )
                    )

                # Warn if results were truncated
                metadata = data.get("metadata", {})
                if metadata.get("truncated"):
                    raise ProviderError(
                        "OpenRouter Analytics API returned truncated results. "
                        "Narrow your sync date range and retry."
                    )

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"OpenRouter API error: {e.response.status_code}"
            ) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"OpenRouter API request failed: {e}") from e

        return records

    @staticmethod
    def _parse_date(value: str) -> date:
        """Parse ISO 8601 timestamp (with trailing Z) to a date."""
        if not value:
            return date.today()
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.date()

    @staticmethod
    def _to_int(value: int | str | None) -> int:
        """Convert a possibly-string metric to int."""
        if value is None:
            return 0
        return int(value)

    def validate_credentials(self) -> bool:
        """Validate OpenRouter API key."""
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = _make_request(
                    client,
                    "GET",
                    f"{_BASE_URL}/auth/key",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "HTTP-Referer": "https://github.com/AreteDriver/ai-spend",
                    },
                    max_attempts=1,  # No retry for simple credential check
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


register_provider(ProviderType.OPENROUTER, OpenRouterProvider)
