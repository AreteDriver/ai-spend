"""Provider registry for ai-spend."""

from __future__ import annotations

from ai_spend.exceptions import ProviderError
from ai_spend.models import ProviderType
from ai_spend.providers.base import BaseProvider

_registry: dict[ProviderType, type[BaseProvider]] = {}


def register_provider(provider_type: ProviderType, cls: type[BaseProvider]) -> None:
    """Register a provider class for a given type."""
    _registry[provider_type] = cls


def get_provider(
    provider_type: ProviderType,
    name: str,
    api_key: str = "",
) -> BaseProvider:
    """Create a provider instance from the registry."""
    cls = _registry.get(provider_type)
    if cls is None:
        raise ProviderError(f"No provider registered for type '{provider_type}'")
    return cls(name=name, api_key=api_key)


def list_registered() -> list[ProviderType]:
    """List all registered provider types."""
    return list(_registry.keys())


def clear_registry() -> None:
    """Clear all registrations (for testing)."""
    _registry.clear()
