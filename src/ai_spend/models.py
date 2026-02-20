"""Pydantic models and enums for ai-spend."""

from __future__ import annotations

import hashlib
import sys
from datetime import date, datetime

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from pydantic import BaseModel, Field, computed_field


class ProviderType(StrEnum):
    """Supported AI provider types."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MANUAL = "manual"


class BucketWidth(StrEnum):
    """Time bucket widths for aggregation."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class ExportFormat(StrEnum):
    """Supported export formats."""

    JSON = "json"
    CSV = "csv"


class SyncStatus(StrEnum):
    """Status of a sync operation."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class UsageRecord(BaseModel):
    """A single usage/cost record from a provider."""

    provider_id: str
    provider_type: ProviderType
    date: date
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    metadata: dict[str, str] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def record_id(self) -> str:
        """Deterministic ID: sha256(provider_id:date:model)[:16]."""
        raw = f"{self.provider_id}:{self.date}:{self.model}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ProviderConfig(BaseModel):
    """Configuration for a registered provider."""

    name: str
    provider_type: ProviderType
    api_key: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def masked_key(self) -> str:
        """Show only last 4 chars of the API key."""
        if len(self.api_key) <= 4:
            return "****"
        return f"{'*' * (len(self.api_key) - 4)}{self.api_key[-4:]}"


class BudgetConfig(BaseModel):
    """Budget configuration for spend tracking."""

    total_usd: float
    period: BucketWidth = BucketWidth.MONTH
    alert_thresholds: list[float] = Field(default_factory=lambda: [0.8, 0.9, 1.0])


class SyncResult(BaseModel):
    """Result of a sync operation."""

    provider_id: str
    status: SyncStatus
    records_synced: int = 0
    error_message: str = ""
    synced_at: datetime | None = None


class SpendSummary(BaseModel):
    """Aggregated spend summary."""

    total_usd: float = 0.0
    by_provider: dict[str, float] = Field(default_factory=dict)
    by_model: dict[str, float] = Field(default_factory=dict)
    record_count: int = 0
    start_date: date | None = None
    end_date: date | None = None


class DailySpend(BaseModel):
    """Spend data for a single day."""

    date: date
    total_usd: float = 0.0
    by_provider: dict[str, float] = Field(default_factory=dict)
    by_model: dict[str, float] = Field(default_factory=dict)
    record_count: int = 0


class BudgetStatus(BaseModel):
    """Current budget status with threshold checks."""

    budget: BudgetConfig
    spent_usd: float = 0.0
    remaining_usd: float = 0.0
    utilization: float = 0.0
    exceeded_thresholds: list[float] = Field(default_factory=list)
    is_over_budget: bool = False
