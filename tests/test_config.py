"""Tests for ai_spend.config."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ai_spend.config import (
    _load_config,
    _save_config,
    add_provider,
    get_provider,
    get_store,
    list_providers,
    remove_provider,
    reset_store,
)
from ai_spend.exceptions import ConfigError
from ai_spend.models import ProviderType


@pytest.fixture(autouse=True)
def _clean_store():
    """Reset the store singleton after each test."""
    yield
    reset_store()


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
            "my-claude", ProviderType.ANTHROPIC, "test-key-anthropic-123", tmp_config_dir
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


class TestGetStore:
    def test_get_store_creates_db(self, tmp_config_dir: Path):
        store = get_store(tmp_config_dir)
        assert (tmp_config_dir / "spend.db").exists()
        store.close()

    def test_singleton(self, tmp_config_dir: Path):
        s1 = get_store(tmp_config_dir)
        s2 = get_store(tmp_config_dir)
        assert s1 is s2
        s1.close()

    def test_reset_store(self, tmp_config_dir: Path):
        s1 = get_store(tmp_config_dir)
        reset_store()
        s2 = get_store(tmp_config_dir)
        assert s1 is not s2
        s2.close()
