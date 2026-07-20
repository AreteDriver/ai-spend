"""Local-only telemetry for ai-spend usage tracking.

Opt-in via AI_SPEND_TELEMETRY=1 environment variable.
All data stays on disk — never transmitted anywhere.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ai_spend.exceptions import StoreError

_ENV_VAR = "AI_SPEND_TELEMETRY"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    name TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
"""


def is_enabled() -> bool:
    """Check if telemetry is opt-in enabled."""
    return os.environ.get(_ENV_VAR, "").strip() == "1"


class TelemetryStore:
    """SQLite WAL store for local telemetry events."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        except sqlite3.Error as e:
            raise StoreError(f"Failed to initialize telemetry database: {e}") from e

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def record(
        self,
        event_type: str,
        name: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Record a telemetry event."""
        try:
            self._conn.execute(
                "INSERT INTO events (event_type, name, timestamp, metadata)"
                " VALUES (?, ?, ?, ?)",
                (
                    event_type,
                    name,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(metadata or {}),
                ),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StoreError(f"Failed to record telemetry event: {e}") from e

    def get_command_counts(self) -> dict[str, int]:
        """Get invocation counts by command name."""
        rows = self._conn.execute(
            "SELECT name, COUNT(*) as cnt FROM events"
            " WHERE event_type = 'command'"
            " GROUP BY name ORDER BY cnt DESC"
        ).fetchall()
        return {r["name"]: r["cnt"] for r in rows}

    def get_pro_gate_counts(self) -> dict[str, int]:
        """Get Pro gate hit counts by feature name."""
        rows = self._conn.execute(
            "SELECT name, COUNT(*) as cnt FROM events"
            " WHERE event_type = 'pro_gate'"
            " GROUP BY name ORDER BY cnt DESC"
        ).fetchall()
        return {r["name"]: r["cnt"] for r in rows}

    def get_total_events(self) -> int:
        """Get total number of telemetry events."""
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM events"
        ).fetchone()
        return int(row["cnt"])

    def get_first_event_time(self) -> str | None:
        """Get timestamp of the earliest event."""
        row = self._conn.execute(
            "SELECT MIN(timestamp) as ts FROM events"
        ).fetchone()
        return row["ts"] if row and row["ts"] else None

    def get_last_event_time(self) -> str | None:
        """Get timestamp of the most recent event."""
        row = self._conn.execute(
            "SELECT MAX(timestamp) as ts FROM events"
        ).fetchone()
        return row["ts"] if row and row["ts"] else None

    def get_daily_activity(self, last_n_days: int = 7) -> list[tuple[str, int]]:
        """Get event counts per day for the last N days."""
        rows = self._conn.execute(
            "SELECT DATE(timestamp) as day, COUNT(*) as cnt FROM events"
            " GROUP BY DATE(timestamp) ORDER BY day DESC LIMIT ?",
            (last_n_days,),
        ).fetchall()
        return [(r["day"], r["cnt"]) for r in rows]

    def reset(self) -> None:
        """Delete all telemetry data."""
        self._conn.execute("DELETE FROM events")
        self._conn.commit()
