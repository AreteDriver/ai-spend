"""Tests for the schema migration system."""

from __future__ import annotations

from pathlib import Path

from ai_spend.store import SpendStore, _get_current_version, _get_migration_files


class TestMigrationDiscovery:
    def test_migrations_found(self):
        files = _get_migration_files()
        assert len(files) >= 2
        versions = [v for v, _ in files]
        assert versions == sorted(versions)
        assert 1 in versions
        assert 2 in versions


class TestMigrationRunner:
    def test_new_database_gets_all_migrations(self, tmp_db_path: Path):
        store = SpendStore(tmp_db_path)
        version = _get_current_version(store._conn)
        assert version >= 2
        store.close()

    def test_migration_idempotent(self, tmp_db_path: Path):
        """Opening the same DB twice should not re-run migrations."""
        s1 = SpendStore(tmp_db_path)
        version1 = _get_current_version(s1._conn)
        s1.close()

        s2 = SpendStore(tmp_db_path)
        version2 = _get_current_version(s2._conn)
        s2.close()

        assert version1 == version2

    def test_schema_version_table_exists(self, tmp_db_path: Path):
        store = SpendStore(tmp_db_path)
        rows = store._conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type='table' AND name='schema_version'"
        ).fetchall()
        assert len(rows) == 1
        store.close()
