"""Tests for ai_spend.providers.manual."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ai_spend.models import ProviderType
from ai_spend.providers.manual import ManualProvider


class TestManualProvider:
    def test_provider_type(self):
        p = ManualProvider(name="misc")
        assert p.provider_type == ProviderType.MANUAL

    def test_fetch_usage_returns_empty(self):
        p = ManualProvider(name="misc")
        records = p.fetch_usage(date(2026, 1, 1), date(2026, 12, 31))
        assert records == []

    def test_validate_credentials(self):
        p = ManualProvider(name="misc")
        assert p.validate_credentials() is True

    def test_create_entry(self):
        p = ManualProvider(name="misc")
        r = p.create_entry("gpt-4o", Decimal("5"), date(2026, 2, 19), "test charge")
        assert r.provider_id == "misc"
        assert r.provider_type == ProviderType.MANUAL
        assert r.model == "gpt-4o"
        assert r.cost_usd == Decimal("5")
        assert r.date == date(2026, 2, 19)
        assert r.metadata == {"note": "test charge"}

    def test_create_entry_default_date(self):
        p = ManualProvider(name="misc")
        r = p.create_entry("misc", Decimal("1"))
        assert r.date == date.today()

    def test_create_entry_no_note(self):
        p = ManualProvider(name="misc")
        r = p.create_entry("misc", 1.0, date(2026, 2, 19))
        assert r.metadata == {}

    def test_create_entry_empty_note(self):
        p = ManualProvider(name="misc")
        r = p.create_entry("misc", 1.0, date(2026, 2, 19), "")
        assert r.metadata == {}
