"""Manual cost entry provider for ai-spend."""

from __future__ import annotations

from datetime import date

from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider
from ai_spend.providers.registry import register_provider


class ManualProvider(BaseProvider):
    """Provider for manually entered cost records."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.MANUAL

    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        """Manual provider has no API to fetch from."""
        return []

    def validate_credentials(self) -> bool:
        """Manual provider needs no credentials."""
        return True

    def create_entry(
        self,
        model: str,
        cost_usd: float,
        entry_date: date | None = None,
        note: str = "",
    ) -> UsageRecord:
        """Create a manual usage record."""
        return UsageRecord(
            provider_id=self.name,
            provider_type=ProviderType.MANUAL,
            date=entry_date or date.today(),
            model=model,
            cost_usd=cost_usd,
            metadata={"note": note} if note else {},
        )


register_provider(ProviderType.MANUAL, ManualProvider)
