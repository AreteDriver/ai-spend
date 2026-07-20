"""License key validation for ai-spend (ASPD keys).

Validates license keys locally (format + SHA256 checksum), then optionally
against the shared license server at cmdf-license.fly.dev for full validation.
Falls back gracefully to local-only validation if the server is unreachable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from ai_spend.exceptions import LicenseError

logger = logging.getLogger(__name__)

_PREFIX = "ASPD"
_SALT = "ai-spend-v1"
_ENV_VAR = "AI_SPEND_LICENSE"
_ENV_LICENSE_SERVER = "AI_SPEND_LICENSE_SERVER"
_DEFAULT_LICENSE_SERVER = "https://cmdf-license.fly.dev"
_PRODUCT = "ai-spend"
MAX_FREE_PROVIDERS = 3

_CACHE_DIR = Path("~/.ai-spend").expanduser()
_CACHE_FILE = _CACHE_DIR / "license_cache.json"
_CACHE_TTL_SECONDS = 86400  # 24 hours


class Tier(StrEnum):
    """License tiers."""

    FREE = "free"
    PRO = "pro"


class LicenseInfo:
    """Parsed license information."""

    def __init__(
        self,
        tier: Tier,
        key: str = "",
        valid: bool = False,
        degraded: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.tier = tier
        self.key = key
        self.valid = valid
        self.degraded = degraded
        self.metadata = metadata or {}

    @property
    def is_pro(self) -> bool:
        return self.tier == Tier.PRO


def _compute_checksum(body: str) -> str:
    """Derive checksum from key body: SHA256(salt:body)[:4].upper()."""
    raw = f"{_SALT}:{body}"
    return hashlib.sha256(raw.encode()).hexdigest()[:4].upper()


def _get_machine_id() -> str:
    """Generate a stable machine identifier (hostname + username hash)."""
    import platform

    user = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
    raw = f"{platform.node()}:{user}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _read_cache() -> dict[str, Any] | None:
    """Read cached license validation result if fresh."""
    try:
        if not _CACHE_FILE.is_file():
            return None
        data = json.loads(_CACHE_FILE.read_text())
        cached_at = data.get("cached_at", 0)
        if time.time() - cached_at > _CACHE_TTL_SECONDS:
            return None
        return cast(dict[str, Any], data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _write_cache(data: dict[str, Any]) -> None:
    """Write license validation result to cache."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data["cached_at"] = time.time()
        _CACHE_FILE.write_text(json.dumps(data))
        _CACHE_FILE.chmod(0o600)
    except OSError:
        pass


def _validate_server(key: str) -> dict[str, Any] | None:
    """Validate key against the license server. Returns None on failure."""
    try:
        import httpx
    except ImportError:
        return None

    server = os.environ.get(_ENV_LICENSE_SERVER, _DEFAULT_LICENSE_SERVER)

    try:
        resp = httpx.post(
            f"{server}/v1/validate",
            json={
                "license_key": key,
                "product": _PRODUCT,
                "machine_id": _get_machine_id(),
            },
            timeout=5.0,
        )
        if resp.status_code == 200:
            return cast(dict[str, Any], resp.json())
    except Exception:
        logger.debug("License server unreachable, falling back to local validation")

    return None


def validate_key(key: str) -> LicenseInfo:
    """Validate an ASPD license key.

    Format: ASPD-XXXX-XXXX-XXXX
    Last segment is checksum of first two body segments.
    """
    if not key:
        raise LicenseError("Empty license key")

    parts = key.strip().split("-")
    if len(parts) != 4:
        raise LicenseError(
            f"Invalid key format: expected ASPD-XXXX-XXXX-XXXX,"
            f" got {len(parts)} segments"
        )

    if parts[0] != _PREFIX:
        raise LicenseError(
            f"Invalid key prefix: expected '{_PREFIX}', got '{parts[0]}'"
        )

    body = f"{parts[1]}-{parts[2]}"
    expected_checksum = _compute_checksum(body)
    if parts[3].upper() != expected_checksum:
        raise LicenseError("Invalid license key checksum")

    return LicenseInfo(tier=Tier.PRO, key=key, valid=True)


def get_license() -> LicenseInfo:
    """Get current license from environment.

    Validation pipeline:
    1. Find key (env var)
    2. Local format + checksum check
    3. Check fresh cache (24h TTL)
    4. Call license server (5s timeout)
    5. Server down -> use expired cache with degraded flag
    6. No cache -> local-only validation (Pro if checksum passes)
    """
    key = os.environ.get(_ENV_VAR, "")
    if not key:
        return LicenseInfo(tier=Tier.FREE)

    try:
        validate_key(key)
    except LicenseError:
        return LicenseInfo(tier=Tier.FREE)

    # Check fresh cache
    cached = _read_cache()
    if cached and cached.get("key") == key:
        return LicenseInfo(
            tier=Tier(cached.get("tier", "pro")),
            key=key,
            valid=cached.get("valid", True),
            metadata=cached.get("metadata", {}),
        )

    # Try server validation
    server_result = _validate_server(key)
    if server_result is not None:
        tier = Tier(server_result.get("tier", "pro"))
        valid = server_result.get("valid", False)
        metadata = server_result.get("metadata", {})
        _write_cache(
            {
                "key": key,
                "tier": tier.value,
                "valid": valid,
                "metadata": metadata,
            }
        )
        result_tier = tier if valid else Tier.FREE
        return LicenseInfo(tier=result_tier, key=key, valid=valid, metadata=metadata)

    # Server unreachable — try expired cache
    try:
        if _CACHE_FILE.is_file():
            data = json.loads(_CACHE_FILE.read_text())
            if data.get("key") == key:
                return LicenseInfo(
                    tier=Tier(data.get("tier", "pro")),
                    key=key,
                    valid=data.get("valid", True),
                    degraded=True,
                    metadata=data.get("metadata", {}),
                )
    except (OSError, json.JSONDecodeError, TypeError):
        pass

    # Local-only fallback — checksum passed, grant Pro
    return LicenseInfo(tier=Tier.PRO, key=key, valid=True, degraded=True)


def generate_key(body: str | None = None) -> str:
    """Generate a valid ASPD key (for testing/admin)."""
    if body is None:
        body = "TEST-KEY0"
    checksum = _compute_checksum(body)
    return f"{_PREFIX}-{body}-{checksum}"
