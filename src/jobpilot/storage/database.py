"""Small, idempotent SQLite initialization layer."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from jobpilot.config import PROJECT_ROOT


SCHEMA_VERSION = 3
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "jobpilot.db"


class DatabaseError(RuntimeError):
    """User-safe persistence boundary error."""


def database_path() -> Path:
    """Resolve the local path, with a test-friendly optional override."""
    configured = os.getenv("JOBPILOT_DATABASE_PATH", "").strip()
    return Path(configured) if configured else DEFAULT_DATABASE_PATH


@contextmanager
def connect(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    target = Path(path) if path is not None else database_path()
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(target)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except sqlite3.Error as exc:
        if connection is not None:
            connection.rollback()
        raise DatabaseError("Local application data is temporarily unavailable.") from exc
    finally:
        if connection is not None:
            connection.close()


def initialize_database(path: Path | str | None = None) -> Path:
    """Create or migrate the database to the latest schema without data loss."""
    target = Path(path) if path is not None else database_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatabaseError("Local application data is temporarily unavailable.") from exc

    with connect(target) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise DatabaseError("The local database schema is newer than this app.")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                company_key TEXT NOT NULL,
                job_title TEXT NOT NULL,
                job_title_key TEXT NOT NULL,
                location TEXT,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'saved', 'applied', 'contacted',
                        'interviewing', 'offer', 'closed'
                    )
                ),
                match_score REAL CHECK (
                    match_score IS NULL OR (match_score >= 0 AND match_score <= 100)
                ),
                jd_text TEXT NOT NULL DEFAULT '',
                jd_fingerprint TEXT NOT NULL,
                job_profile_json TEXT NOT NULL,
                match_result_json TEXT,
                optimization_result_json TEXT,
                notes TEXT NOT NULL DEFAULT '',
                source TEXT,
                source_url TEXT,
                deferred_until TEXT,
                applied_at TEXT,
                contacted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (company_key, job_title_key, jd_fingerprint)
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(job_applications)").fetchall()
        }
        if "source_url" not in columns:
            connection.execute("ALTER TABLE job_applications ADD COLUMN source_url TEXT")
        if "deferred_until" not in columns:
            connection.execute("ALTER TABLE job_applications ADD COLUMN deferred_until TEXT")
        if "contacted_at" not in columns:
            connection.execute("ALTER TABLE job_applications ADD COLUMN contacted_at TEXT")
        connection.execute(
            """
            UPDATE job_applications
            SET source_url = source, source = 'manual'
            WHERE source_url IS NULL
              AND (lower(source) LIKE 'http://%' OR lower(source) LIKE 'https://%')
            """
        )
        if version < SCHEMA_VERSION:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return target
