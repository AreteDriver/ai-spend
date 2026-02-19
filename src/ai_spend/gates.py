"""Feature gating decorators for ai-spend."""

from __future__ import annotations

import functools
from typing import Any

from ai_spend.exceptions import LicenseError
from ai_spend.licensing import Tier, get_license


def require_pro(feature: str):
    """Decorator that gates a function behind Pro tier."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            info = get_license()
            if info.tier != Tier.PRO:
                raise LicenseError(
                    f"'{feature}' requires a Pro license. "
                    f"Set {_ENV_VAR} environment variable."
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


_ENV_VAR = "AI_SPEND_LICENSE"
