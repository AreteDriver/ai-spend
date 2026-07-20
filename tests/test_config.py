"""Tests for ai_spend.config."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ai_spend.config import (
    _load_config,
    _save_config,
    add_provider,
    encrypt_config,
    get_provider,
    list_providers,
    remove_provider,
)
from ai_spend.exceptions import ConfigError
from ai_spend.models import ProviderType


class TestLoadSaveConfig:
    def test_load_missing_file(self, tmp_config_dir: Path):
        data = _load_config(tmp_config_dir)
        assert data == {"providers": []}

    def test_save_and_load(self, tmp_config_dir: Path):
        _save_config(
            {"providers": [{"name": "x", "provider_type": "manual"}]},
            tmp_config_dir,
        )
        data = _load_config(tmp_config_dir)
        assert len(data["providers"]) == 1

    def test_file_permissions(self, tmp_config_dir: Path):
        _save_config({"providers": []}, tmp_config_dir)
        path = tmp_config_dir / "config.yaml"
        mode = path.stat().st_mode
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)

    def test_load_invalid_yaml(self, tmp_config_dir: Path):
        path = tmp_config_dir / "config.yaml"
        path.write_text("{{{{invalid yaml")
        with pytest.raises(ConfigError, match="Failed to read config"):
            _load_config(tmp_config_dir)

    def test_load_non_dict_yaml(self, tmp_config_dir: Path):
        path = tmp_config_dir / "config.yaml"
        path.write_text("- item1\n- item2\n")
        data = _load_config(tmp_config_dir)
        assert data == {"providers": []}


class TestProviderCRUD:
    def test_add_provider(self, tmp_config_dir: Path):
        pc = add_provider(
            "my-claude",
            ProviderType.ANTHROPIC,
            "test-key-anthropic-123",
            tmp_config_dir,
        )
        assert pc.name == "my-claude"
        assert pc.provider_type == ProviderType.ANTHROPIC

    def test_add_duplicate_raises(self, tmp_config_dir: Path):
        add_provider("x", ProviderType.MANUAL, "", tmp_config_dir)
        with pytest.raises(ConfigError, match="already exists"):
            add_provider("x", ProviderType.MANUAL, "", tmp_config_dir)

    def test_remove_provider(self, tmp_config_dir: Path):
        add_provider("x", ProviderType.MANUAL, "", tmp_config_dir)
        remove_provider("x", tmp_config_dir)
        assert list_providers(tmp_config_dir) == []

    def test_remove_missing_raises(self, tmp_config_dir: Path):
        with pytest.raises(ConfigError, match="not found"):
            remove_provider("nope", tmp_config_dir)

    def test_list_providers(self, tmp_config_dir: Path):
        add_provider("a", ProviderType.ANTHROPIC, "key-a", tmp_config_dir)
        add_provider("o", ProviderType.OPENAI, "key-o", tmp_config_dir)
        providers = list_providers(tmp_config_dir)
        assert len(providers) == 2
        assert providers[0].name == "a"
        assert providers[1].name == "o"

    def test_get_provider_found(self, tmp_config_dir: Path):
        add_provider("a", ProviderType.ANTHROPIC, "key", tmp_config_dir)
        p = get_provider("a", tmp_config_dir)
        assert p is not None
        assert p.name == "a"

    def test_get_provider_missing(self, tmp_config_dir: Path):
        assert get_provider("nope", tmp_config_dir) is None

    def test_provider_with_empty_key(self, tmp_config_dir: Path):
        pc = add_provider("manual", ProviderType.MANUAL, "", tmp_config_dir)
        assert pc.api_key == ""

    def test_multiple_add_remove(self, tmp_config_dir: Path):
        add_provider("a", ProviderType.ANTHROPIC, "k1", tmp_config_dir)
        add_provider("b", ProviderType.OPENAI, "k2", tmp_config_dir)
        add_provider("c", ProviderType.MANUAL, "", tmp_config_dir)
        remove_provider("b", tmp_config_dir)
        providers = list_providers(tmp_config_dir)
        assert len(providers) == 2
        names = [p.name for p in providers]
        assert "a" in names
        assert "c" in names


class TestEncryptionAtRest:
    def _read_raw_yaml(self, config_dir: Path) -> dict:
        import yaml

        with open(config_dir / "config.yaml") as f:
            return yaml.safe_load(f)

    def test_add_provider_encrypts_key(self, tmp_config_dir: Path):
        key = "secret-api-key-123"
        add_provider("x", ProviderType.OPENAI, key, tmp_config_dir)
        # list_providers returns decrypted plaintext
        providers = list_providers(tmp_config_dir)
        assert providers[0].api_key == key
        # On-disk YAML should be encrypted
        raw = self._read_raw_yaml(tmp_config_dir)
        assert raw["providers"][0]["api_key"] != key

    def test_load_decrypts_existing_keys(self, tmp_config_dir: Path):
        key = "my-key"
        add_provider("x", ProviderType.OPENAI, key, tmp_config_dir)
        # Simulate fresh load
        providers = list_providers(tmp_config_dir)
        assert providers[0].api_key == key

    def test_edit_provider_re_encrypts(self, tmp_config_dir: Path):
        from ai_spend.config import edit_provider

        add_provider("x", ProviderType.OPENAI, "old", tmp_config_dir)
        edit_provider("x", api_key="new", config_dir=tmp_config_dir)
        providers = list_providers(tmp_config_dir)
        assert providers[0].api_key == "new"
        raw = self._read_raw_yaml(tmp_config_dir)
        assert raw["providers"][0]["api_key"] != "new"

    def test_encrypt_config_migrates_plaintext(self, tmp_config_dir: Path):
        # Write plaintext config manually (legacy)
        import yaml

        path = tmp_config_dir / "config.yaml"
        with open(path, "w") as f:
            yaml.safe_dump(
                {
                    "providers": [
                        {"name": "x", "provider_type": "openai", "api_key": "plain"}
                    ]
                },
                f,
            )
        # Remove the key file to simulate pre-encryption state
        key_path = tmp_config_dir / ".key"
        if key_path.exists():
            key_path.unlink()
        encrypt_config(tmp_config_dir)
        # Now load should decrypt transparently
        providers = list_providers(tmp_config_dir)
        assert providers[0].api_key == "plain"

    def test_empty_key_not_encrypted(self, tmp_config_dir: Path):
        add_provider("x", ProviderType.MANUAL, "", tmp_config_dir)
        raw = self._read_raw_yaml(tmp_config_dir)
        assert raw["providers"][0]["api_key"] == ""

    def test_key_file_created_with_save(self, tmp_config_dir: Path):
        add_provider("x", ProviderType.OPENAI, "k", tmp_config_dir)
        key_path = tmp_config_dir / ".key"
        assert key_path.exists()
        mode = key_path.stat().st_mode
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)


class TestNameValidation:
    def test_empty_name_raises(self, tmp_config_dir: Path):
        with pytest.raises(ConfigError, match="empty"):
            add_provider("", ProviderType.OPENAI, "k", tmp_config_dir)

    def test_whitespace_name_raises(self, tmp_config_dir: Path):
        with pytest.raises(ConfigError, match="empty"):
            add_provider("   ", ProviderType.OPENAI, "k", tmp_config_dir)

    def test_invalid_chars_raises(self, tmp_config_dir: Path):
        with pytest.raises(ConfigError, match="letters"):
            add_provider("bad name!", ProviderType.OPENAI, "k", tmp_config_dir)

    def test_valid_names_accepted(self, tmp_config_dir: Path):
        add_provider("my-provider_123", ProviderType.OPENAI, "k", tmp_config_dir)
        providers = list_providers(tmp_config_dir)
        assert providers[0].name == "my-provider_123"


class TestConfigBackup:
    def test_edit_creates_backup(self, tmp_config_dir: Path):
        add_provider("x", ProviderType.OPENAI, "old", tmp_config_dir)
        from ai_spend.config import edit_provider

        edit_provider("x", api_key="new", config_dir=tmp_config_dir)
        backups = list(tmp_config_dir.glob("config.yaml.backup.*"))
        assert len(backups) == 1

    def test_edit_backup_is_readable(self, tmp_config_dir: Path):
        add_provider("x", ProviderType.OPENAI, "old", tmp_config_dir)
        from ai_spend.config import edit_provider

        edit_provider("x", api_key="new", config_dir=tmp_config_dir)
        backups = list(tmp_config_dir.glob("config.yaml.backup.*"))
        data = backups[0].read_text()
        assert "x" in data

    def test_edit_backup_is_exact_copy(self, tmp_config_dir: Path):
        add_provider("x", ProviderType.OPENAI, "old", tmp_config_dir)
        config_path = tmp_config_dir / "config.yaml"
        original = config_path.read_bytes()
        from ai_spend.config import edit_provider

        edit_provider("x", api_key="new", config_dir=tmp_config_dir)
        backups = list(tmp_config_dir.glob("config.yaml.backup.*"))
        backup = backups[0].read_bytes()
        assert backup == original
        # The backup is the encrypted pre-edit file; the new file is different
        new_file = config_path.read_bytes()
        assert backup != new_file

