"""YAML config and store singleton for ai-spend."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import yaml

from ai_spend.exceptions import ConfigError
from ai_spend.models import ProviderConfig, ProviderType

_DEFAULT_DIR = Path.home() / ".ai-spend"
_CONFIG_FILE = "config.yaml"


def get_config_dir() -> Path:
    """Get the config directory path (respects AI_SPEND_DIR env var)."""
    return Path(os.environ.get("AI_SPEND_DIR", str(_DEFAULT_DIR)))


def _ensure_config_dir(config_dir: Path) -> None:
    """Create config dir with secure permissions (owner-only, 0o700)."""
    if not config_dir.exists():
        config_dir.mkdir(parents=True, exist_ok=False)
    config_dir.chmod(0o700)


def _config_path(config_dir: Path | None = None) -> Path:
    d = config_dir or get_config_dir()
    return d / _CONFIG_FILE


def _load_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Load YAML config from disk."""
    path = _config_path(config_dir)
    if not path.exists():
        return {"providers": []}
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {"providers": []}
    except (yaml.YAMLError, OSError) as e:
        raise ConfigError(f"Failed to read config: {e}") from e


def _save_config(data: dict[str, Any], config_dir: Path | None = None) -> None:
    """Save YAML config to disk with 0o600 permissions."""
    d = config_dir or get_config_dir()
    _ensure_config_dir(d)
    path = d / _CONFIG_FILE
    try:
        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError as e:
        raise ConfigError(f"Failed to write config: {e}") from e


def add_provider(
    name: str,
    provider_type: ProviderType,
    api_key: str = "",
    config_dir: Path | None = None,
) -> ProviderConfig:
    """Add a provider to the YAML config."""
    data = _load_config(config_dir)
    providers = data.get("providers", [])
    for p in providers:
        if p.get("name") == name:
            raise ConfigError(f"Provider '{name}' already exists")
    entry = {"name": name, "provider_type": provider_type.value, "api_key": api_key}
    providers.append(entry)
    data["providers"] = providers
    _save_config(data, config_dir)
    return ProviderConfig(name=name, provider_type=provider_type, api_key=api_key)


def remove_provider(name: str, config_dir: Path | None = None) -> None:
    """Remove a provider from the YAML config."""
    data = _load_config(config_dir)
    providers = data.get("providers", [])
    new = [p for p in providers if p.get("name") != name]
    if len(new) == len(providers):
        raise ConfigError(f"Provider '{name}' not found")
    data["providers"] = new
    _save_config(data, config_dir)


def list_providers(config_dir: Path | None = None) -> list[ProviderConfig]:
    """List all configured providers."""
    data = _load_config(config_dir)
    providers = data.get("providers", [])
    return [
        ProviderConfig(
            name=p["name"],
            provider_type=ProviderType(p["provider_type"]),
            api_key=p.get("api_key", ""),
        )
        for p in providers
    ]


def get_provider(name: str, config_dir: Path | None = None) -> ProviderConfig | None:
    """Get a single provider config by name."""
    for p in list_providers(config_dir):
        if p.name == name:
            return p
    return None
