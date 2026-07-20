"""Base provider ABC for ai-spend."""

from __future__ import annotations

import abc
import time
from datetime import date
from typing import Any

import httpx

from ai_spend.log import get_logger
from ai_spend.models import ProviderType, UsageRecord

logger = get_logger(__name__)


class BaseProvider(abc.ABC):
    """Abstract base for AI provider integrations."""

    def __init__(self, name: str, api_key: str = "") -> None:
        self.name = name
        self.api_key = api_key

    @property
    @abc.abstractmethod
    def provider_type(self) -> ProviderType:
        """The provider type enum value."""

    @abc.abstractmethod
    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        """Fetch usage records from the provider API."""

    @abc.abstractmethod
    def validate_credentials(self) -> bool:
        """Validate that the API credentials are working."""


def _make_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    **kwargs: Any,
) -> httpx.Response:
    """Make an HTTP request with exponential backoff retry.

    Retries on transient failures:
    - 429 Too Many Requests (respects Retry-After header)
    - 500, 502, 503, 504 server errors
    - Connection errors and timeouts
    """
    delay = base_delay
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            if method.upper() == "GET":
                resp = client.get(url, **kwargs)
            else:
                resp = client.request(method.upper(), url, **kwargs)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
            last_exc = e
            if attempt == max_attempts - 1:
                break

            # Only retry on transient failures
            if isinstance(e, httpx.HTTPStatusError):
                status = e.response.status_code
                if status == 429:
                    # Respect Retry-After header
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            pass
                elif status >= 500:
                    pass  # Retry on server errors
                else:
                    break  # Fail fast on 4xx client errors

            logger.warning(
                "request_retry",
                extra={
                    "extra_fields": {
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "delay": delay,
                        "status": getattr(
                            getattr(e, "response", None), "status_code", None
                        ),
                        "url": url,
                    }
                },
            )
            time.sleep(delay)
            delay = min(delay * 2, max_delay)

    logger.error(
        "request_failed",
        extra={
            "extra_fields": {
                "url": url,
                "attempts": max_attempts,
                "error": str(last_exc),
            }
        },
    )
    raise last_exc  # type: ignore[misc]
