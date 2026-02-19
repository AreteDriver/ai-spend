"""OpenAI Admin API provider for ai-spend."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider
from ai_spend.providers.registry import register_provider

_BASE_URL = "https://api.openai.com/v1/organization"


class OpenAIProvider(BaseProvider):
    """Fetch usage data from the OpenAI Admin API."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENAI

    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        """Fetch costs from OpenAI Admin API with cursor pagination."""
        records: list[UsageRecord] = []
        cursor: str | None = None
        start_ts = int(
            datetime.combine(
                start, datetime.min.time(), tzinfo=timezone.utc
            ).timestamp()
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
                    }
                    if cursor:
                        params["cursor"] = cursor

                    resp = client.get(
                        f"{_BASE_URL}/costs",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        params=params,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    for bucket in data.get("data", []):
                        # OpenAI returns Unix timestamps
                        ts = bucket.get("start_time", start_ts)
                        bucket_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()

                        for result in bucket.get("results", []):
                            obj = result.get("object")
                            if isinstance(obj, dict):
                                model_name = obj.get("id", "unknown")
                            else:
                                model_name = result.get("model", "unknown")
                            cost = float(result.get("amount", {}).get("value", 0.0))
                            input_tokens = result.get("input_tokens", 0)
                            output_tokens = result.get("output_tokens", 0)
                            records.append(
                                UsageRecord(
                                    provider_id=self.name,
                                    provider_type=ProviderType.OPENAI,
                                    date=bucket_date,
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
            raise ProviderError(f"OpenAI API error: {e.response.status_code}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"OpenAI API request failed: {e}") from e

        return records

    def validate_credentials(self) -> bool:
        """Validate OpenAI admin API key."""
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{_BASE_URL}/costs",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    params={"start_time": 0, "end_time": 0},
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


register_provider(ProviderType.OPENAI, OpenAIProvider)
