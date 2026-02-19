"""Tests for ai_spend.providers.base."""

from __future__ import annotations

from datetime import date

import pytest

from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider


class ConcreteProvider(BaseProvider):
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.MANUAL

    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        return []

    def validate_credentials(self) -> bool:
        return True


class TestBaseProvider:
    def test_init(self):
        p = ConcreteProvider(name="test", api_key="key123")
        assert p.name == "test"
        assert p.api_key == "key123"

    def test_default_empty_key(self):
        p = ConcreteProvider(name="test")
        assert p.api_key == ""

    def test_abstract_methods(self):
        p = ConcreteProvider(name="test")
        assert p.provider_type == ProviderType.MANUAL
        assert p.fetch_usage(date(2026, 1, 1), date(2026, 1, 31)) == []
        assert p.validate_credentials() is True

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseProvider(name="test")  # type: ignore[abstract]
