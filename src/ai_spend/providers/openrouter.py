"""OpenRouter API provider for ai-spend."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider
from ai_spend.providers.registry import register_provider

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(BaseProvider):
    """Fetch usage data from the OpenRouter API."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENROUTER

    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        """Fetch costs from OpenRouter generations API with cursor pagination."""
        records: list[UsageRecord] = []
        cursor: str | None = None
        start_ts = int(
            datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp()
        )
        end_ts = int(
            datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc).timestamp()
        )

        try:
            with httpx.Client(timeout=30.0) as client:
                while True:
                    params: dict[str, str | int] = {
                        "start_time": start_ts,
                        "end_time": end_ts,
                        "limit": 100,
                    }
                    if cursor:
                        params["cursor"] = cursor

                    resp = client.get(
                        f"{_BASE_URL}/generations",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "HTTP-Referer": "https://github.com/AreteDriver/ai-spend",
                            "X-Title": "ai-spend",
                        },
                        params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    for gen in data.get("data", []):
                        created_at = gen.get("created_at", 0)
                        if isinstance(created_at, (int, float)):
                            gen_date = datetime.fromtimestamp(
                                created_at, tz=timezone.utc
                            ).date()
                        else:
                            gen_date = start

                        model_name = gen.get("model", "unknown")
                        # OpenRouter returns native_cost in USD
                        cost = float(gen.get("native_cost", 0.0))
                        # Fallback to tokens if cost not available
                        if cost == 0.0:
                            total_tokens = gen.get("native_tokens_prompt", 0) + gen.get(
                                "native_tokens_completion", 0
                            )
                            # Rough estimate: ~$0.0015 per 1K tokens average
                            cost = total_tokens * 0.0000015

                        input_tokens = gen.get("native_tokens_prompt", 0)
                        output_tokens = gen.get("native_tokens_completion", 0)

                        records.append(
                            UsageRecord(
                                provider_id=self.name,
                                provider_type=ProviderType.OPENROUTER,
                                date=gen_date,
                                model=model_name,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                cost_usd=cost,
                            )
                        )

                    # OpenRouter uses offset-based or cursor-based pagination
                    # Check for next cursor in response
                    cursor = data.get("next_cursor")
                    if not cursor or not data.get("data"):
                        break

        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"OpenRouter API error: {e.response.status_code}"
            ) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"OpenRouter API request failed: {e}") from e

        return records

    def validate_credentials(self) -> bool:
        """Validate OpenRouter API key."""
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{_BASE_URL}/auth/key",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "HTTP-Referer": "https://github.com/AreteDriver/ai-spend",
                    },
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


register_provider(ProviderType.OPENROUTER, OpenRouterProvider)
