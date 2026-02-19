"""Budget tracking and threshold alerts for ai-spend."""

from __future__ import annotations

from ai_spend.exceptions import BudgetError
from ai_spend.models import BudgetConfig, BudgetStatus
from ai_spend.store import SpendStore


def check_budget(store: SpendStore) -> BudgetStatus:
    """Check current spend against budget."""
    budget = store.get_budget()
    if budget is None:
        raise BudgetError("No budget configured. Use 'ai-spend budget set' first.")

    spent = store.get_total_spend_current_period(budget.period)
    remaining = budget.total_usd - spent
    utilization = spent / budget.total_usd if budget.total_usd > 0 else 0.0

    exceeded = [t for t in budget.alert_thresholds if utilization >= t]

    return BudgetStatus(
        budget=budget,
        spent_usd=round(spent, 2),
        remaining_usd=round(remaining, 2),
        utilization=round(utilization, 4),
        exceeded_thresholds=exceeded,
        is_over_budget=spent >= budget.total_usd,
    )


def set_budget(
    store: SpendStore,
    total_usd: float,
    period: str = "month",
    thresholds: list[float] | None = None,
) -> BudgetConfig:
    """Set or update the budget."""
    if total_usd <= 0:
        raise BudgetError("Budget must be greater than zero")

    from ai_spend.models import BucketWidth

    try:
        bucket = BucketWidth(period)
    except ValueError as e:
        raise BudgetError(f"Invalid period: {period}") from e

    budget = BudgetConfig(
        total_usd=total_usd,
        period=bucket,
        alert_thresholds=thresholds or [0.8, 0.9, 1.0],
    )
    store.set_budget(budget)
    return budget
