"""Tests for ai_spend.providers.base."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider, _make_request


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


class TestMakeRequest:
    @respx.mock
    def test_retry_then_success(self):
        route = respx.get("https://example.com/api")
        # First two calls fail with 503, third succeeds
        route.side_effect = [
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
        client = httpx.Client()
        resp = _make_request(
            client,
            "GET",
            "https://example.com/api",
            max_attempts=3,
            base_delay=0.01,
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert route.call_count == 3

    @respx.mock
    def test_fail_fast_on_4xx(self):
        route = respx.get("https://example.com/api")
        route.return_value = httpx.Response(404)
        client = httpx.Client()
        with pytest.raises(httpx.HTTPStatusError):
            _make_request(
                client,
                "GET",
                "https://example.com/api",
                max_attempts=3,
                base_delay=0.01,
            )
        assert route.call_count == 1
