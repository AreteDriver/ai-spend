"""Anthropic Admin API provider for ai-spend."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

import httpx

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider, _make_request
from ai_spend.providers.registry import register_provider

_BASE_URL = "https://api.anthropic.com/v1/organizations"


def _to_rfc3339(d: date) -> str:
    """Convert a date to midnight UTC RFC 3339 timestamp."""
    return f"{d.isoformat()}T00:00:00Z"


def _parse_bucket_date(starting_at: str) -> date:
    """Parse RFC 3339 timestamp (with trailing Z) to a date."""
    # datetime.fromisoformat does not accept trailing Z in Python < 3.11
    return datetime.fromisoformat(starting_at.replace("Z", "+00:00")).date()


class AnthropicProvider(BaseProvider):
    """Fetch usage data from the Anthropic Admin API.

    Uses the ``/cost_report`` endpoint.  Token counts are **not** available
    from this endpoint; they are returned as ``0``.  Cost amounts are
    returned in the lowest currency unit (cents) as decimal strings and are
    converted to USD (``amount / 100``).
    """

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.ANTHROPIC

    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        """Fetch cost report from Anthropic Admin API with page pagination."""
        records: list[UsageRecord] = []
        page_token: str | None = None

        try:
            with httpx.Client(timeout=30.0) as client:
                while True:
                    params: dict[str, str] = {
                        "starting_at": _to_rfc3339(start),
                        "ending_at": _to_rfc3339(end),
                    }
                    if page_token:
                        params["page"] = page_token

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

                    # Aggregate results by (date, model) because the API can
                    # return multiple result rows per model (different
                    # token_type values, etc.).
                    aggregated: dict[tuple[date, str], Decimal] = defaultdict(
                        lambda: Decimal("0")
                    )

                    for bucket in data.get("data", []):
                        bucket_date = _parse_bucket_date(
                            bucket.get("starting_at", _to_rfc3339(start))
                        )
                        for result in bucket.get("results", []):
                            model_name = result.get("model") or "unknown"
                            # Amount is in cents (lowest currency unit) as a
                            # decimal string, e.g. "123.45" → $1.2345 USD.
                            amount_cents = Decimal(result.get("amount", "0"))
                            aggregated[(bucket_date, model_name)] += (
                                amount_cents / 100
                            )

                    for (bucket_date, model_name), cost in aggregated.items():
                        records.append(
                            UsageRecord(
                                provider_id=self.name,
                                provider_type=ProviderType.ANTHROPIC,
                                date=bucket_date,
                                model=model_name,
                                input_tokens=0,
                                output_tokens=0,
                                cost_usd=cost,
                            )
                        )

                    if not data.get("has_more"):
                        break
                    page_token = data.get("next_page")
                    if not page_token:
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
                    params={
                        "starting_at": "2026-01-01T00:00:00Z",
                        "ending_at": "2026-01-01T00:00:00Z",
                    },
                    max_attempts=1,  # No retry for simple credential check
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


register_provider(ProviderType.ANTHROPIC, AnthropicProvider)
