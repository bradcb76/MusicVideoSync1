from __future__ import annotations

import contextlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

LATEST_SCHEMA_VERSION = 3


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def backup(self, destination_dir: Path) -> Path | None:
        if not self.path.exists():
            return None
        destination_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = destination_dir / f"{self.path.stem}-pre-migration-{stamp}{self.path.suffix}"
        shutil.copy2(self.path, target)
        return target

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
            migrations = {1: self._migration_1, 2: self._migration_2, 3: self._migration_3}
            for version, migration in migrations.items():
                if version not in applied:
                    migration(db)
                    db.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, datetime.now(timezone.utc).isoformat()),
                    )

    @staticmethod
    def _migration_1(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE,
                filename TEXT, artist TEXT, album TEXT, title TEXT,
                track_number TEXT, duration_seconds REAL, extension TEXT,
                video_status TEXT DEFAULT 'not_searched'
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                track_id INTEGER, artist TEXT, video_id TEXT, destination TEXT,
                dry_run INTEGER NOT NULL DEFAULT 1, attempts INTEGER NOT NULL DEFAULT 0,
                progress INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                diagnostics TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, started_at TEXT, completed_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_active_track
                ON jobs(track_id) WHERE state IN ('queued','searching','downloading','processing');
            CREATE INDEX IF NOT EXISTS ix_jobs_state ON jobs(state);
            """
        )

    @staticmethod
    def _migration_2(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS download_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER,
                track_id INTEGER NOT NULL, video_id TEXT NOT NULL,
                destination TEXT NOT NULL, business_date TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0, completed_at TEXT NOT NULL,
                UNIQUE(track_id), UNIQUE(video_id), UNIQUE(destination)
            );
            CREATE TABLE IF NOT EXISTS scheduler_control (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                state TEXT NOT NULL DEFAULT 'paused', owner TEXT,
                heartbeat_at TEXT, stop_after_current INTEGER NOT NULL DEFAULT 0,
                dry_run INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO scheduler_control(singleton, updated_at)
                VALUES(1, CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL,
                event TEXT NOT NULL, message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _migration_3(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS integration_status (
                provider TEXT PRIMARY KEY, server_name TEXT NOT NULL DEFAULT '',
                server_version TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'disabled',
                last_test_at TEXT, last_refresh_at TEXT, last_result TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS refresh_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
                path TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,
                message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

    def get_setting(self, key: str, default: str) -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (key, value, datetime.now(timezone.utc).isoformat()),
            )
