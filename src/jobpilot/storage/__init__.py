"""Local persistence adapters."""

from jobpilot.storage.application_repository import (
    ApplicationRepository,
    ApplicationRepositoryError,
    DuplicateApplicationError,
    jd_text_fingerprint,
    normalize_jd_text,
)
from jobpilot.storage.database import (
    DEFAULT_DATABASE_PATH,
    SCHEMA_VERSION,
    DatabaseError,
    database_path,
    initialize_database,
)

__all__ = [
    "ApplicationRepository",
    "ApplicationRepositoryError",
    "DEFAULT_DATABASE_PATH",
    "DatabaseError",
    "DuplicateApplicationError",
    "SCHEMA_VERSION",
    "database_path",
    "initialize_database",
    "jd_text_fingerprint",
    "normalize_jd_text",
]
