"""AI provider integrations for ai-spend."""

# Import all providers to trigger registration
from ai_spend.providers.base import BaseProvider
from ai_spend.providers.registry import get_provider, register_provider

# Side-effect: register providers on import
from ai_spend.providers.anthropic import AnthropicProvider  # noqa: F401
from ai_spend.providers.manual import ManualProvider  # noqa: F401
from ai_spend.providers.openai import OpenAIProvider  # noqa: F401
from ai_spend.providers.openrouter import OpenRouterProvider  # noqa: F401

__all__ = ["BaseProvider", "get_provider", "register_provider"]
