"""Shared test fixtures for ai-spend."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ai_spend.models import (
    BucketWidth,
    BudgetConfig,
    ProviderConfig,
    ProviderType,
    SyncResult,
    SyncStatus,
    UsageRecord,
)


@pytest.fixture(autouse=True)
def _no_server_validation(monkeypatch, tmp_path):
    """Prevent license server calls and cache reads in all tests."""
    monkeypatch.setattr("ai_spend.licensing._validate_server", lambda k: None)
    monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", tmp_path / "no_cache.json")
    monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Temporary database file path."""
    return tmp_path / "spend.db"


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """Temporary config directory."""
    d = tmp_path / ".ai-spend"
    d.mkdir()
    return d


@pytest.fixture
def sample_usage_record() -> UsageRecord:
    """A sample usage record."""
    return UsageRecord(
        provider_id="my-anthropic",
        provider_type=ProviderType.ANTHROPIC,
        date=date(2026, 2, 19),
        model="claude-sonnet-4-20250514",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=Decimal("0.015"),
    )


@pytest.fixture
def sample_provider_config() -> ProviderConfig:
    """A sample provider config."""
    return ProviderConfig(
        name="my-anthropic",
        provider_type=ProviderType.ANTHROPIC,
        api_key="test-admin-key-1234567890",
    )


@pytest.fixture
def sample_budget() -> BudgetConfig:
    """A sample budget config."""
    return BudgetConfig(
        total_usd=Decimal("100"),
        period=BucketWidth.MONTH,
    )


@pytest.fixture
def sample_sync_result() -> SyncResult:
    """A sample sync result."""
    return SyncResult(
        provider_id="my-anthropic",
        status=SyncStatus.SUCCESS,
        records_synced=42,
        synced_at=datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc),
    )
