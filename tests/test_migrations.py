"""Tests for the schema migration system."""

from __future__ import annotations

from pathlib import Path

from ai_spend.store import (
    SpendStore,
    _backup_db,
    _get_current_version,
    _get_migration_files,
)


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


class TestBackup:
    def test_backup_created_on_migration(self, tmp_db_path: Path):
        """Opening a fresh DB should create a backup when migrations run."""
        store = SpendStore(tmp_db_path)
        store.close()
        backups = list(tmp_db_path.parent.glob("*.backup.*"))
        assert len(backups) >= 1

    def test_backup_not_created_when_no_pending(self, tmp_db_path: Path):
        """Re-opening an already-migrated DB should not create extra backups."""
        s1 = SpendStore(tmp_db_path)
        s1.close()
        backups_before = list(tmp_db_path.parent.glob("*.backup.*"))

        s2 = SpendStore(tmp_db_path)
        s2.close()
        backups_after = list(tmp_db_path.parent.glob("*.backup.*"))
        assert len(backups_after) == len(backups_before)

    def test_backup_file_readable(self, tmp_db_path: Path):
        """Backup file should be a valid SQLite database."""
        store = SpendStore(tmp_db_path)
        store.close()
        backups = list(tmp_db_path.parent.glob("*.backup.*"))
        assert len(backups) >= 1
        # Verify it opens as SQLite
        import sqlite3

        conn = sqlite3.connect(str(backups[0]))
        conn.execute("SELECT 1")
        conn.close()

    def test_backup_function_directly(self, tmp_path: Path):
        """_backup_db should create a copy with a timestamped name."""
        db = tmp_path / "test.db"
        db.write_bytes(b"test data")
        backup = _backup_db(db)
        assert backup.exists()
        assert backup.read_bytes() == b"test data"
        assert "backup" in backup.name
