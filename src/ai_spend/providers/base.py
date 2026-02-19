"""Base provider ABC for ai-spend."""

from __future__ import annotations

import abc
from datetime import date

from ai_spend.models import ProviderType, UsageRecord


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
