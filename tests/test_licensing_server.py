"""Tests for server-side license validation in ai_spend.licensing."""

from __future__ import annotations

import json
import time

from ai_spend.licensing import (
    Tier,
    _compute_checksum,
    _get_machine_id,
    _read_cache,
    _validate_server,
    _write_cache,
    generate_key,
    get_license,
)

# Save reference before conftest autouse fixture patches it
_real_validate_server = _validate_server


def _make_valid_key() -> str:
    """Build a valid ASPD license key with correct checksum."""
    return generate_key("TEST-ABCD")


class TestMachineId:
    def test_returns_hex_string(self) -> None:
        mid = _get_machine_id()
        assert len(mid) == 16
        assert all(c in "0123456789abcdef" for c in mid)

    def test_deterministic(self) -> None:
        assert _get_machine_id() == _get_machine_id()


class TestCache:
    def test_write_and_read(self, tmp_path, monkeypatch) -> None:
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)

        _write_cache({"key": "test", "tier": "pro", "valid": True})
        result = _read_cache()
        assert result is not None
        assert result["key"] == "test"
        assert result["tier"] == "pro"

    def test_expired_cache_returns_none(self, tmp_path, monkeypatch) -> None:
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)

        data = {"key": "test", "cached_at": time.time() - 100000}
        cache_file.write_text(json.dumps(data))

        result = _read_cache()
        assert result is None

    def test_missing_cache_returns_none(self, tmp_path, monkeypatch) -> None:
        cache_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)

        result = _read_cache()
        assert result is None

    def test_corrupt_cache_returns_none(self, tmp_path, monkeypatch) -> None:
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)
        cache_file.write_text("not json")

        result = _read_cache()
        assert result is None

    def test_cache_file_permissions(self, tmp_path, monkeypatch) -> None:
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)

        _write_cache({"key": "test"})
        assert cache_file.stat().st_mode & 0o777 == 0o600


class TestServerValidation:
    """Tests call _validate_server directly, bypassing the autouse mock."""

    def test_returns_none_without_httpx(self, monkeypatch) -> None:
        def _block(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError("No module named 'httpx'")
            return __builtins__.__import__(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _block)
        result = _real_validate_server("ASPD-TEST-ABCD-1234")
        assert result is None

    def test_returns_none_on_connection_error(self, monkeypatch) -> None:
        import httpx

        def _mock_post(*args, **kwargs):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("httpx.post", _mock_post)
        result = _real_validate_server("ASPD-TEST-ABCD-1234")
        assert result is None

    def test_returns_response_on_success(self, monkeypatch) -> None:
        class MockResponse:
            status_code = 200

            def json(self):
                return {"valid": True, "tier": "pro", "product": "ai-spend"}

        monkeypatch.setattr("httpx.post", lambda *a, **kw: MockResponse())
        result = _real_validate_server("ASPD-TEST-ABCD-1234")
        assert result is not None
        assert result["valid"] is True

    def test_returns_none_on_non_200(self, monkeypatch) -> None:
        class MockResponse:
            status_code = 500

        monkeypatch.setattr("httpx.post", lambda *a, **kw: MockResponse())
        result = _real_validate_server("ASPD-TEST-ABCD-1234")
        assert result is None

    def test_sends_correct_product(self, monkeypatch) -> None:
        captured = {}

        class MockResponse:
            status_code = 200

            def json(self):
                return {"valid": True, "tier": "pro"}

        def _capture_post(url, json=None, **kw):
            captured.update(json or {})
            return MockResponse()

        monkeypatch.setattr("httpx.post", _capture_post)
        _real_validate_server("ASPD-TEST-ABCD-1234")
        assert captured["product"] == "ai-spend"

    def test_custom_server_url(self, monkeypatch) -> None:
        captured_url = []

        class MockResponse:
            status_code = 200

            def json(self):
                return {"valid": True, "tier": "pro"}

        def _capture_post(url, **kw):
            captured_url.append(url)
            return MockResponse()

        monkeypatch.setattr("httpx.post", _capture_post)
        monkeypatch.setenv("AI_SPEND_LICENSE_SERVER", "https://custom.example.com")
        _real_validate_server("ASPD-TEST-ABCD-1234")
        assert "custom.example.com" in captured_url[0]


class TestGetLicenseWithServer:
    """Test get_license with server validation paths."""

    def test_uses_fresh_cache(self, tmp_path, monkeypatch) -> None:
        key = _make_valid_key()
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)
        monkeypatch.setenv("AI_SPEND_LICENSE", key)

        _write_cache({"key": key, "tier": "pro", "valid": True, "metadata": {}})

        monkeypatch.setattr("ai_spend.licensing._validate_server", lambda k: None)

        info = get_license()
        assert info.tier == Tier.PRO
        assert info.valid is True

    def test_server_success_caches_result(self, tmp_path, monkeypatch) -> None:
        key = _make_valid_key()
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)
        monkeypatch.setenv("AI_SPEND_LICENSE", key)

        monkeypatch.setattr(
            "ai_spend.licensing._validate_server",
            lambda k: {"valid": True, "tier": "pro", "metadata": {}},
        )

        info = get_license()
        assert info.tier == Tier.PRO
        assert info.valid is True

        assert cache_file.is_file()
        cached = json.loads(cache_file.read_text())
        assert cached["key"] == key

    def test_server_rejects_returns_free(self, tmp_path, monkeypatch) -> None:
        key = _make_valid_key()
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)
        monkeypatch.setenv("AI_SPEND_LICENSE", key)

        monkeypatch.setattr(
            "ai_spend.licensing._validate_server",
            lambda k: {"valid": False, "tier": "free", "metadata": {}},
        )

        info = get_license()
        assert info.tier == Tier.FREE
        assert info.valid is False

    def test_server_down_uses_expired_cache(self, tmp_path, monkeypatch) -> None:
        key = _make_valid_key()
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)
        monkeypatch.setenv("AI_SPEND_LICENSE", key)

        expired = {"key": key, "tier": "pro", "valid": True, "cached_at": time.time() - 200000}
        cache_file.write_text(json.dumps(expired))

        monkeypatch.setattr("ai_spend.licensing._validate_server", lambda k: None)

        info = get_license()
        assert info.tier == Tier.PRO
        assert info.degraded is True

    def test_server_down_no_cache_falls_back_local(self, tmp_path, monkeypatch) -> None:
        key = _make_valid_key()
        cache_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)
        monkeypatch.setenv("AI_SPEND_LICENSE", key)

        monkeypatch.setattr("ai_spend.licensing._validate_server", lambda k: None)

        info = get_license()
        assert info.tier == Tier.PRO
        assert info.degraded is True

    def test_degraded_flag_false_on_server_success(self, tmp_path, monkeypatch) -> None:
        key = _make_valid_key()
        cache_file = tmp_path / "license_cache.json"
        monkeypatch.setattr("ai_spend.licensing._CACHE_DIR", tmp_path)
        monkeypatch.setattr("ai_spend.licensing._CACHE_FILE", cache_file)
        monkeypatch.setenv("AI_SPEND_LICENSE", key)

        monkeypatch.setattr(
            "ai_spend.licensing._validate_server",
            lambda k: {"valid": True, "tier": "pro", "metadata": {}},
        )

        info = get_license()
        assert info.degraded is False
