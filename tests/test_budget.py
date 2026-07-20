"""Tests for ai_spend.budget."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ai_spend.budget import check_budget, set_budget
from ai_spend.exceptions import BudgetError
from ai_spend.models import BucketWidth, ProviderType, UsageRecord
from ai_spend.store import SpendStore


@pytest.fixture
def store(tmp_db_path: Path) -> SpendStore:
    s = SpendStore(tmp_db_path)
    yield s
    s.close()


class TestSetBudget:
    def test_set_budget(self, store: SpendStore):
        b = set_budget(store, 100.0)
        assert b.total_usd == Decimal("100")
        assert b.period == BucketWidth.MONTH

    def test_set_budget_custom_period(self, store: SpendStore):
        b = set_budget(store, 50.0, period="week")
        assert b.period == BucketWidth.WEEK

    def test_set_budget_custom_thresholds(self, store: SpendStore):
        b = set_budget(store, 100.0, thresholds=[0.5, 0.75])
        assert b.alert_thresholds == [0.5, 0.75]

    def test_set_budget_zero_raises(self, store: SpendStore):
        with pytest.raises(BudgetError, match="greater than zero"):
            set_budget(store, 0.0)

    def test_set_budget_negative_raises(self, store: SpendStore):
        with pytest.raises(BudgetError, match="greater than zero"):
            set_budget(store, -10.0)

    def test_set_budget_invalid_period(self, store: SpendStore):
        with pytest.raises(BudgetError, match="Invalid period"):
            set_budget(store, 100.0, period="year")

    def test_update_budget(self, store: SpendStore):
        set_budget(store, 50.0)
        b = set_budget(store, 200.0)
        assert b.total_usd == 200.0


class TestCheckBudget:
    def test_no_budget_raises(self, store: SpendStore):
        with pytest.raises(BudgetError, match="No budget configured"):
            check_budget(store)

    def test_under_budget(self, store: SpendStore):
        set_budget(store, 100.0)
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date.today(),
                    model="claude",
                    cost_usd=Decimal("30"),
                ),
            ]
        )
        status = check_budget(store)
        assert not status.is_over_budget
        assert status.spent_usd == Decimal("30")
        assert status.remaining_usd == Decimal("70")
        assert status.exceeded_thresholds == []

    def test_over_budget(self, store: SpendStore):
        set_budget(store, 100.0)
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date.today(),
                    model="claude",
                    cost_usd=Decimal("110"),
                ),
            ]
        )
        status = check_budget(store)
        assert status.is_over_budget
        assert status.remaining_usd == Decimal("-10")
        assert 1.0 in status.exceeded_thresholds

    def test_threshold_80_percent(self, store: SpendStore):
        set_budget(store, 100.0)
        store.add_provider("a", ProviderType.ANTHROPIC)
        store.add_usage_records(
            [
                UsageRecord(
                    provider_id="a",
                    provider_type=ProviderType.ANTHROPIC,
                    date=date.today(),
                    model="claude",
                    cost_usd=Decimal("85"),
                ),
            ]
        )
        status = check_budget(store)
        assert 0.8 in status.exceeded_thresholds
        assert 0.9 not in status.exceeded_thresholds

    def test_zero_spend(self, store: SpendStore):
        set_budget(store, 100.0)
        status = check_budget(store)
        assert status.spent_usd == Decimal("0")
        assert status.utilization == 0.0
        assert not status.is_over_budget
