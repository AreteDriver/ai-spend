"""Application context for dependency injection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_spend.store import SpendStore
from ai_spend.telemetry import TelemetryStore, is_enabled


@dataclass
class AppContext:
    """Holds runtime dependencies for ai-spend commands."""

    config_dir: Path
    store: SpendStore
    verbose: bool = False
    _telemetry: TelemetryStore | None = field(default=None, repr=False)

    @classmethod
    def from_env(
        cls, config_dir: Path | None = None, verbose: bool = False
    ) -> AppContext:
        """Create AppContext from environment or explicit path."""
        from ai_spend.config import _ensure_config_dir, get_config_dir

        resolved = config_dir or get_config_dir()
        _ensure_config_dir(resolved)
        store = SpendStore(resolved / "spend.db")
        return cls(config_dir=resolved, store=store, verbose=verbose)

    @property
    def telemetry(self) -> TelemetryStore | None:
        """Get telemetry store if enabled."""
        if not is_enabled():
            return None
        if self._telemetry is None:
            self._telemetry = TelemetryStore(self.config_dir / "telemetry.db")
        return self._telemetry

    def track(self, event_type: str, name: str) -> None:
        """Record a telemetry event if enabled."""
        ts = self.telemetry
        if ts is not None:
            ts.record(event_type, name)
