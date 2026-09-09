import sqlite3

from jobpilot.storage import SCHEMA_VERSION, initialize_database


def test_first_initialization_creates_database_and_table(tmp_path) -> None:
    path = tmp_path / "nested" / "jobpilot.db"

    result = initialize_database(path)

    assert result == path
    assert path.exists()
    with sqlite3.connect(path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'job_applications'"
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert table == ("job_applications",)
    assert version == SCHEMA_VERSION


def test_repeated_initialization_is_idempotent(tmp_path) -> None:
    path = tmp_path / "jobpilot.db"

    initialize_database(path)
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'job_applications'"
        ).fetchone()[0]
    assert count == 1


def test_latest_schema_contains_queue_columns(tmp_path) -> None:
    path = initialize_database(tmp_path / "jobpilot.db")
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(job_applications)")
        }
    assert {"source_url", "deferred_until"} <= columns


def test_v1_database_migrates_url_source_without_data_loss(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE job_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL, company_key TEXT NOT NULL,
                job_title TEXT NOT NULL, job_title_key TEXT NOT NULL,
                location TEXT, status TEXT NOT NULL, match_score REAL,
                jd_text TEXT NOT NULL DEFAULT '', jd_fingerprint TEXT NOT NULL,
                job_profile_json TEXT NOT NULL, match_result_json TEXT,
                optimization_result_json TEXT, notes TEXT NOT NULL DEFAULT '',
                source TEXT, applied_at TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (company_key, job_title_key, jd_fingerprint)
            );
            PRAGMA user_version = 1;
            INSERT INTO job_applications (
                company, company_key, job_title, job_title_key, status,
                jd_fingerprint, job_profile_json, source, created_at, updated_at
            ) VALUES (
                '虚构公司', '虚构公司', '虚构岗位', '虚构岗位', 'saved',
                'legacy-fingerprint', '{"job_title":"虚构岗位"}',
                'https://example.com/job/1',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
            );
            """
        )

    initialize_database(path)
    initialize_database(path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM job_applications").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION
    assert row["company"] == "虚构公司"
    assert row["source"] == "manual"
    assert row["source_url"] == "https://example.com/job/1"
    assert row["deferred_until"] is None
