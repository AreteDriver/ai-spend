"""Tests for ai_spend.providers.registry."""

from __future__ import annotations

import pytest

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType
from ai_spend.providers.base import BaseProvider
from ai_spend.providers.registry import (
    clear_registry,
    get_provider,
    list_registered,
    register_provider,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure clean registry for each test."""
    clear_registry()
    yield
    clear_registry()


class SampleProvider(BaseProvider):
    @property
    def provider_type(self):
        return ProviderType.MANUAL

    def fetch_usage(self, start, end):
        return []

    def validate_credentials(self):
        return True


class TestRegistry:
    def test_register_and_get(self):
        register_provider(ProviderType.MANUAL, SampleProvider)
        p = get_provider(ProviderType.MANUAL, "test", "key")
        assert isinstance(p, SampleProvider)
        assert p.name == "test"
        assert p.api_key == "key"

    def test_get_unregistered_raises(self):
        with pytest.raises(ProviderError, match="No provider registered"):
            get_provider(ProviderType.ANTHROPIC, "test")

    def test_list_registered(self):
        register_provider(ProviderType.MANUAL, SampleProvider)
        registered = list_registered()
        assert ProviderType.MANUAL in registered

    def test_list_empty(self):
        assert list_registered() == []

    def test_clear_registry(self):
        register_provider(ProviderType.MANUAL, SampleProvider)
        clear_registry()
        assert list_registered() == []

    def test_overwrite_registration(self):
        register_provider(ProviderType.MANUAL, SampleProvider)
        register_provider(ProviderType.MANUAL, SampleProvider)
        assert len(list_registered()) == 1
