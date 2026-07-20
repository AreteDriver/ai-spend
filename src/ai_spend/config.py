"""YAML config and store singleton for ai-spend."""

from __future__ import annotations

import copy
import os
import re
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ai_spend.crypto import decrypt, encrypt, get_or_create_key
from ai_spend.exceptions import ConfigError
from ai_spend.models import ProviderConfig, ProviderType

_DEFAULT_DIR = Path.home() / ".ai-spend"
_CONFIG_FILE = "config.yaml"
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_name(name: str) -> None:
    """Reject invalid provider names."""
    if not name or not name.strip():
        raise ConfigError("Provider name cannot be empty")
    if not _NAME_RE.match(name):
        raise ConfigError(
            "Provider name must contain only letters, numbers, underscores, and hyphens"
        )


def _backup_config(config_dir: Path) -> Path | None:
    """Create a timestamped backup of config.yaml before destructive edits."""
    path = config_dir / _CONFIG_FILE
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = config_dir / f"config.yaml.backup.{ts}"
    shutil.copy2(path, backup)
    backup.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return backup


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


def _decrypt_config(data: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    """Transparently decrypt API keys in loaded config."""
    key_path = config_dir / ".key"
    if not key_path.exists():
        return data
    key = key_path.read_bytes().strip()
    for p in data.get("providers", []):
        api_key = p.get("api_key")
        if api_key:
            p["api_key"] = decrypt(api_key, key)
    return data


def _load_config(config_dir: Path | None = None) -> dict[str, Any]:
    """Load YAML config from disk."""
    d = config_dir or get_config_dir()
    path = d / _CONFIG_FILE
    if not path.exists():
        return {"providers": []}
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        data = data if isinstance(data, dict) else {"providers": []}
        return _decrypt_config(data, d)
    except (yaml.YAMLError, OSError) as e:
        raise ConfigError(f"Failed to read config: {e}") from e


def _encrypt_config(data: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    """Return a deep copy with API keys encrypted at rest."""
    key = get_or_create_key(config_dir)
    out = copy.deepcopy(data)
    for p in out.get("providers", []):
        api_key = p.get("api_key")
        if api_key:
            p["api_key"] = encrypt(api_key, key)
    return out


def _save_config(data: dict[str, Any], config_dir: Path | None = None) -> None:
    """Save YAML config to disk with 0o600 permissions."""
    d = config_dir or get_config_dir()
    _ensure_config_dir(d)
    path = d / _CONFIG_FILE
    data_to_save = _encrypt_config(data, d)
    try:
        with open(path, "w") as f:
            yaml.safe_dump(data_to_save, f, default_flow_style=False)
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
    _validate_name(name)
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


def edit_provider(
    name: str,
    *,
    api_key: str | None = None,
    provider_type: ProviderType | None = None,
    config_dir: Path | None = None,
) -> ProviderConfig:
    """Edit an existing provider's fields."""
    d = config_dir or get_config_dir()
    _validate_name(name)
    _backup_config(d)
    data = _load_config(d)
    providers = data.get("providers", [])
    for p in providers:
        if p.get("name") == name:
            if api_key is not None:
                p["api_key"] = api_key
            if provider_type is not None:
                p["provider_type"] = provider_type.value
            _save_config(data, d)
            return ProviderConfig(
                name=name,
                provider_type=ProviderType(p["provider_type"]),
                api_key=p.get("api_key", ""),
            )
    raise ConfigError(f"Provider '{name}' not found")


def encrypt_config(config_dir: Path | None = None) -> None:
    """Force encryption of all existing plaintext API keys in config."""
    d = config_dir or get_config_dir()
    data = _load_config(d)
    # Re-saving transparently encrypts any plaintext keys.
    _save_config(data, d)


def get_provider(name: str, config_dir: Path | None = None) -> ProviderConfig | None:
    """Get a single provider config by name."""
    for p in list_providers(config_dir):
        if p.name == name:
            return p
    return None
