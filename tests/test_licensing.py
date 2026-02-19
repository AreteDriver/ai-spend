"""Tests for ai_spend.licensing."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from ai_spend.exceptions import LicenseError
from ai_spend.licensing import (
    MAX_FREE_PROVIDERS,
    LicenseInfo,
    Tier,
    _compute_checksum,
    generate_key,
    get_license,
    validate_key,
)


class TestTier:
    def test_values(self):
        assert Tier.FREE == "free"
        assert Tier.PRO == "pro"

    def test_all_members(self):
        assert len(Tier) == 2


class TestLicenseInfo:
    def test_free(self):
        info = LicenseInfo(tier=Tier.FREE)
        assert not info.is_pro
        assert info.key == ""

    def test_pro(self):
        info = LicenseInfo(tier=Tier.PRO, key="ASPD-XXXX-XXXX-XXXX")
        assert info.is_pro
        assert info.key == "ASPD-XXXX-XXXX-XXXX"


class TestChecksum:
    def test_deterministic(self):
        c1 = _compute_checksum("TEST-KEY0")
        c2 = _compute_checksum("TEST-KEY0")
        assert c1 == c2

    def test_different_input(self):
        c1 = _compute_checksum("TEST-KEY0")
        c2 = _compute_checksum("DIFF-KEY1")
        assert c1 != c2

    def test_length_four(self):
        c = _compute_checksum("anything")
        assert len(c) == 4

    def test_uppercase(self):
        c = _compute_checksum("test")
        assert c == c.upper()


class TestValidateKey:
    def test_valid_key(self):
        key = generate_key()
        info = validate_key(key)
        assert info.is_pro
        assert info.key == key

    def test_empty_key_raises(self):
        with pytest.raises(LicenseError, match="Empty"):
            validate_key("")

    def test_wrong_segments_raises(self):
        with pytest.raises(LicenseError, match="format"):
            validate_key("ASPD-XXXX")

    def test_wrong_prefix_raises(self):
        with pytest.raises(LicenseError, match="prefix"):
            validate_key("XYZQ-AAAA-BBBB-CCCC")

    def test_bad_checksum_raises(self):
        with pytest.raises(LicenseError, match="checksum"):
            validate_key("ASPD-AAAA-BBBB-0000")

    def test_whitespace_stripped(self):
        key = generate_key()
        info = validate_key(f"  {key}  ")
        assert info.is_pro

    def test_case_insensitive_checksum(self):
        key = generate_key("ABCD-EF01")
        lower = key[:-4] + key[-4:].lower()
        info = validate_key(lower)
        assert info.is_pro


class TestGenerateKey:
    def test_default(self):
        key = generate_key()
        assert key.startswith("ASPD-")
        parts = key.split("-")
        assert len(parts) == 4

    def test_custom_body(self):
        key = generate_key("MY00-CODE")
        assert "MY00-CODE" in key
        validate_key(key)  # Should not raise

    def test_roundtrip(self):
        for body in ["AAAA-BBBB", "1234-5678", "ZZZZ-9999"]:
            key = generate_key(body)
            info = validate_key(key)
            assert info.is_pro


class TestGetLicense:
    def test_no_env_returns_free(self):
        with patch.dict(os.environ, {}, clear=True):
            info = get_license()
            assert info.tier == Tier.FREE

    def test_valid_env_returns_pro(self):
        key = generate_key()
        with patch.dict(os.environ, {"AI_SPEND_LICENSE": key}):
            info = get_license()
            assert info.is_pro

    def test_invalid_env_returns_free(self):
        with patch.dict(os.environ, {"AI_SPEND_LICENSE": "bad-key"}):
            info = get_license()
            assert info.tier == Tier.FREE

    def test_empty_env_returns_free(self):
        with patch.dict(os.environ, {"AI_SPEND_LICENSE": ""}):
            info = get_license()
            assert info.tier == Tier.FREE


class TestConstants:
    def test_max_free_providers(self):
        assert MAX_FREE_PROVIDERS == 3
