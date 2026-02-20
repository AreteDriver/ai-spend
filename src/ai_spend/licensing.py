"""License key validation for ai-spend (ASPD keys)."""

from __future__ import annotations

import hashlib
import os
import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from ai_spend.exceptions import LicenseError

_PREFIX = "ASPD"
_SALT = "ai-spend-v1"
_ENV_VAR = "AI_SPEND_LICENSE"
MAX_FREE_PROVIDERS = 3


class Tier(StrEnum):
    """License tiers."""

    FREE = "free"
    PRO = "pro"


class LicenseInfo:
    """Parsed license information."""

    def __init__(self, tier: Tier, key: str = "") -> None:
        self.tier = tier
        self.key = key

    @property
    def is_pro(self) -> bool:
        return self.tier == Tier.PRO


def _compute_checksum(body: str) -> str:
    """Derive checksum from key body: SHA256(salt:body)[:4].upper()."""
    raw = f"{_SALT}:{body}"
    return hashlib.sha256(raw.encode()).hexdigest()[:4].upper()


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

    return LicenseInfo(tier=Tier.PRO, key=key)


def get_license() -> LicenseInfo:
    """Get current license from environment."""
    key = os.environ.get(_ENV_VAR, "")
    if not key:
        return LicenseInfo(tier=Tier.FREE)
    try:
        return validate_key(key)
    except LicenseError:
        return LicenseInfo(tier=Tier.FREE)


def generate_key(body: str | None = None) -> str:
    """Generate a valid ASPD key (for testing/admin)."""
    if body is None:
        body = "TEST-KEY0"
    checksum = _compute_checksum(body)
    return f"{_PREFIX}-{body}-{checksum}"
