"""Tests for ai-spend telemetry module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ai_spend.exceptions import StoreError
from ai_spend.telemetry import (
    TelemetryStore,
    is_enabled,
    reset_telemetry_store,
    track_command,
    track_pro_gate,
)


@pytest.fixture
def telemetry_db(tmp_path: Path) -> Path:
    return tmp_path / "telemetry.db"


@pytest.fixture
def store(telemetry_db: Path) -> TelemetryStore:
    s = TelemetryStore(telemetry_db)
    yield s
    s.close()


class TestIsEnabled:
    def test_disabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert is_enabled() is False

    def test_disabled_when_zero(self) -> None:
        with patch.dict("os.environ", {"AI_SPEND_TELEMETRY": "0"}):
            assert is_enabled() is False

    def test_enabled_when_one(self) -> None:
        with patch.dict("os.environ", {"AI_SPEND_TELEMETRY": "1"}):
            assert is_enabled() is True

    def test_disabled_when_empty(self) -> None:
        with patch.dict("os.environ", {"AI_SPEND_TELEMETRY": ""}):
            assert is_enabled() is False

    def test_disabled_when_whitespace(self) -> None:
        with patch.dict("os.environ", {"AI_SPEND_TELEMETRY": "  "}):
            assert is_enabled() is False

    def test_enabled_when_one_with_whitespace(self) -> None:
        with patch.dict("os.environ", {"AI_SPEND_TELEMETRY": " 1 "}):
            assert is_enabled() is True


class TestTelemetryStore:
    def test_record_command(self, store: TelemetryStore) -> None:
        store.record("command", "sync")
        counts = store.get_command_counts()
        assert counts == {"sync": 1}

    def test_record_multiple_commands(self, store: TelemetryStore) -> None:
        store.record("command", "sync")
        store.record("command", "sync")
        store.record("command", "summary")
        counts = store.get_command_counts()
        assert counts["sync"] == 2
        assert counts["summary"] == 1

    def test_record_pro_gate(self, store: TelemetryStore) -> None:
        store.record("pro_gate", "export")
        counts = store.get_pro_gate_counts()
        assert counts == {"export": 1}

    def test_get_total_events(self, store: TelemetryStore) -> None:
        assert store.get_total_events() == 0
        store.record("command", "sync")
        store.record("pro_gate", "export")
        assert store.get_total_events() == 2

    def test_get_first_event_time(self, store: TelemetryStore) -> None:
        assert store.get_first_event_time() is None
        store.record("command", "sync")
        assert store.get_first_event_time() is not None

    def test_get_last_event_time(self, store: TelemetryStore) -> None:
        assert store.get_last_event_time() is None
        store.record("command", "sync")
        assert store.get_last_event_time() is not None

    def test_get_daily_activity(self, store: TelemetryStore) -> None:
        store.record("command", "sync")
        store.record("command", "summary")
        activity = store.get_daily_activity()
        assert len(activity) >= 1
        assert activity[0][1] == 2  # 2 events today

    def test_reset(self, store: TelemetryStore) -> None:
        store.record("command", "sync")
        store.record("pro_gate", "export")
        assert store.get_total_events() == 2
        store.reset()
        assert store.get_total_events() == 0

    def test_record_with_metadata(self, store: TelemetryStore) -> None:
        store.record("command", "sync", metadata={"provider": "anthropic"})
        assert store.get_total_events() == 1

    def test_command_counts_ordered_by_count_desc(self, store: TelemetryStore) -> None:
        store.record("command", "summary")
        for _ in range(3):
            store.record("command", "sync")
        counts = store.get_command_counts()
        names = list(counts.keys())
        assert names[0] == "sync"
        assert names[1] == "summary"

    def test_pro_gate_counts_empty(self, store: TelemetryStore) -> None:
        assert store.get_pro_gate_counts() == {}

    def test_command_counts_empty(self, store: TelemetryStore) -> None:
        assert store.get_command_counts() == {}

    def test_daily_activity_limit(self, store: TelemetryStore) -> None:
        store.record("command", "sync")
        activity = store.get_daily_activity(last_n_days=1)
        assert len(activity) <= 1


class TestTrackHelpers:
    def test_track_command_disabled(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            reset_telemetry_store()
            track_command("sync")  # Should not raise

    def test_track_command_enabled(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {"AI_SPEND_TELEMETRY": "1"}),
            patch("ai_spend.config.get_config_dir", return_value=tmp_path),
        ):
            reset_telemetry_store()
            track_command("sync")
            # Verify it was recorded
            store = TelemetryStore(tmp_path / "telemetry.db")
            try:
                assert store.get_command_counts() == {"sync": 1}
            finally:
                store.close()
                reset_telemetry_store()

    def test_track_pro_gate_disabled(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            reset_telemetry_store()
            track_pro_gate("export")  # Should not raise

    def test_track_pro_gate_enabled(self, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", {"AI_SPEND_TELEMETRY": "1"}),
            patch("ai_spend.config.get_config_dir", return_value=tmp_path),
        ):
            reset_telemetry_store()
            track_pro_gate("export")
            store = TelemetryStore(tmp_path / "telemetry.db")
            try:
                assert store.get_pro_gate_counts() == {"export": 1}
            finally:
                store.close()
                reset_telemetry_store()

    def test_reset_telemetry_store_when_none(self) -> None:
        reset_telemetry_store()  # Should not raise


class TestStoreCreation:
    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "dir" / "telemetry.db"
        store = TelemetryStore(db_path)
        store.record("command", "test")
        assert store.get_total_events() == 1
        store.close()

    def test_close(self, telemetry_db: Path) -> None:
        store = TelemetryStore(telemetry_db)
        store.close()
        # Double close should fail (connection already closed)
        with pytest.raises(StoreError):
            store.record("command", "test")
