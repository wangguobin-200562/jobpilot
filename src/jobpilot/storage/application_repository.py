"""Parameterized SQLite repository for job-application tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any

from pydantic import ValidationError

from jobpilot.models import (
    ApplicationStatus,
    JobApplication,
    JobProfile,
    MatchResult,
    ResumeOptimizationResult,
)
from jobpilot.browser.job_identity import canonicalize_job_url
from jobpilot.storage.database import DatabaseError, connect, initialize_database


logger = logging.getLogger(__name__)


class ApplicationRepositoryError(RuntimeError):
    """User-safe repository operation failure."""


class DuplicateApplicationError(ApplicationRepositoryError):
    """Raised when the same company, role, and JD are already saved."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def normalize_jd_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.strip().splitlines() if line.strip())


def jd_text_fingerprint(value: str) -> str:
    return sha256(normalize_jd_text(value).encode("utf-8")).hexdigest()


def _status(value: ApplicationStatus | str) -> ApplicationStatus:
    try:
        return value if isinstance(value, ApplicationStatus) else ApplicationStatus(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported application status: {value!r}") from exc


class ApplicationRepository:
    """Persist structured analysis snapshots without exposing SQL to the UI."""

    def __init__(self, path: Path | str | None = None) -> None:
        try:
            self.path = initialize_database(path)
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application storage could not be initialized."
            ) from exc

    @staticmethod
    def _to_application(row: sqlite3.Row | None) -> JobApplication | None:
        if row is None:
            return None
        payload = {
            key: row[key]
            for key in (
                "id",
                "company",
                "job_title",
                "location",
                "status",
                "match_score",
                "jd_text",
                "jd_fingerprint",
                "job_profile_json",
                "match_result_json",
                "optimization_result_json",
                "notes",
                "source",
                "source_url",
                "deferred_until",
                "applied_at",
                "contacted_at",
                "created_at",
                "updated_at",
            )
        }
        try:
            application = JobApplication.model_validate(payload)
            application.job_profile
            application.match_result
            application.optimization_result
            return application
        except (ValidationError, ValueError) as exc:
            raise ApplicationRepositoryError(
                "Stored application data could not be read."
            ) from exc

    def create_application(
        self,
        *,
        company: str,
        job_title: str,
        jd_text: str,
        job_profile: JobProfile,
        location: str | None = None,
        status: ApplicationStatus | str = ApplicationStatus.SAVED,
        match_score: float | None = None,
        match_result: MatchResult | None = None,
        optimization_result: ResumeOptimizationResult | None = None,
        notes: str = "",
        source: str | None = None,
        source_url: str | None = None,
        deferred_until: datetime | None = None,
    ) -> JobApplication:
        validated_status = _status(status)
        company = company.strip()
        job_title = job_title.strip()
        if not company or not job_title:
            raise ValueError("Company and job title are required.")
        if match_score is not None and not 0 <= match_score <= 100:
            raise ValueError("Match score must be between 0 and 100.")
        fingerprint = jd_text_fingerprint(jd_text)
        now = _utc_now()
        applied_at = now if validated_status is ApplicationStatus.APPLIED else None
        contacted_at = (
            now
            if validated_status
            in {
                ApplicationStatus.CONTACTED,
                ApplicationStatus.INTERVIEWING,
                ApplicationStatus.OFFER,
            }
            else None
        )
        values = (
            company,
            _identity_key(company),
            job_title,
            _identity_key(job_title),
            location.strip() if location and location.strip() else None,
            validated_status.value,
            match_score,
            jd_text,
            fingerprint,
            job_profile.model_dump_json(),
            match_result.model_dump_json() if match_result else None,
            optimization_result.model_dump_json() if optimization_result else None,
            notes,
            source.strip() if source and source.strip() else None,
            canonicalize_job_url(source_url),
            deferred_until.isoformat() if deferred_until else None,
            applied_at,
            contacted_at,
            now,
            now,
        )
        try:
            with connect(self.path) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO job_applications (
                        company, company_key, job_title, job_title_key,
                        location, status, match_score, jd_text, jd_fingerprint,
                        job_profile_json, match_result_json,
                        optimization_result_json, notes, source, source_url,
                        deferred_until, applied_at, contacted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                application_id = int(cursor.lastrowid)
        except DatabaseError as exc:
            if isinstance(exc.__cause__, sqlite3.IntegrityError):
                raise DuplicateApplicationError(
                    "The application already exists."
                ) from exc
            raise ApplicationRepositoryError(
                "Application data could not be saved."
            ) from exc
        logger.info("Application operation: operation_type=create application_id=%d", application_id)
        application = self.get_application_by_id(application_id)
        if application is None:
            raise ApplicationRepositoryError("Saved application could not be read.")
        return application

    def get_application_by_id(self, application_id: int) -> JobApplication | None:
        try:
            with connect(self.path) as connection:
                row = connection.execute(
                    "SELECT * FROM job_applications WHERE id = ?", (application_id,)
                ).fetchone()
            return self._to_application(row)
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application data could not be loaded."
            ) from exc

    def list_applications(
        self,
        *,
        status: ApplicationStatus | str | None = None,
        company_query: str | None = None,
        job_title_query: str | None = None,
    ) -> list[JobApplication]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            parameters.append(_status(status).value)
        if company_query and company_query.strip():
            clauses.append("company_key LIKE ?")
            parameters.append(f"%{_identity_key(company_query)}%")
        if job_title_query and job_title_query.strip():
            clauses.append("job_title_key LIKE ?")
            parameters.append(f"%{_identity_key(job_title_query)}%")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with connect(self.path) as connection:
                rows = connection.execute(
                    f"SELECT * FROM job_applications{where} ORDER BY updated_at DESC, id DESC",
                    parameters,
                ).fetchall()
            return [item for row in rows if (item := self._to_application(row))]
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application data could not be loaded."
            ) from exc

    def find_duplicate(
        self, *, company: str, job_title: str, jd_text: str
    ) -> JobApplication | None:
        try:
            with connect(self.path) as connection:
                row = connection.execute(
                    """
                    SELECT * FROM job_applications
                    WHERE company_key = ? AND job_title_key = ? AND jd_fingerprint = ?
                    """,
                    (
                        _identity_key(company),
                        _identity_key(job_title),
                        jd_text_fingerprint(jd_text),
                    ),
                ).fetchone()
            return self._to_application(row)
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application data could not be checked."
            ) from exc

    def update_status(
        self, application_id: int, status: ApplicationStatus | str
    ) -> JobApplication | None:
        validated_status = _status(status)
        now = _utc_now()
        try:
            with connect(self.path) as connection:
                connection.execute(
                    """
                    UPDATE job_applications
                    SET status = ?,
                        applied_at = CASE
                            WHEN ? = 'applied' AND applied_at IS NULL THEN ?
                            ELSE applied_at
                        END,
                        contacted_at = CASE
                            WHEN ? IN ('contacted', 'interviewing', 'offer')
                                 AND contacted_at IS NULL THEN ?
                            ELSE contacted_at
                        END,
                        deferred_until = CASE
                            WHEN ? = 'applied' THEN NULL
                            ELSE deferred_until
                        END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        validated_status.value,
                        validated_status.value,
                        now,
                        validated_status.value,
                        now,
                        validated_status.value,
                        now,
                        application_id,
                    ),
                )
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application status could not be updated."
            ) from exc
        logger.info(
            "Application operation: operation_type=update_status application_id=%d status=%s",
            application_id,
            validated_status.value,
        )
        return self.get_application_by_id(application_id)

    def update_deferred_until(
        self, application_id: int, deferred_until: datetime | None
    ) -> JobApplication | None:
        """Defer a saved application until an aware UTC-compatible datetime."""
        if deferred_until is not None and deferred_until.tzinfo is None:
            raise ValueError("deferred_until must be timezone-aware")
        value = deferred_until.astimezone(timezone.utc).isoformat() if deferred_until else None
        try:
            with connect(self.path) as connection:
                connection.execute(
                    "UPDATE job_applications SET deferred_until = ?, updated_at = ? WHERE id = ?",
                    (value, _utc_now(), application_id),
                )
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application deferral could not be updated."
            ) from exc
        logger.info(
            "Application operation: operation_type=update_deferred application_id=%d deferred=%s",
            application_id,
            deferred_until is not None,
        )
        return self.get_application_by_id(application_id)

    def update_notes(self, application_id: int, notes: str) -> JobApplication | None:
        try:
            with connect(self.path) as connection:
                connection.execute(
                    "UPDATE job_applications SET notes = ?, updated_at = ? WHERE id = ?",
                    (notes, _utc_now(), application_id),
                )
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application notes could not be updated."
            ) from exc
        logger.info("Application operation: operation_type=update_notes application_id=%d", application_id)
        return self.get_application_by_id(application_id)

    def delete_application(self, application_id: int) -> bool:
        try:
            with connect(self.path) as connection:
                cursor = connection.execute(
                    "DELETE FROM job_applications WHERE id = ?", (application_id,)
                )
                deleted = cursor.rowcount > 0
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application data could not be deleted."
            ) from exc
        if deleted:
            logger.info("Application operation: operation_type=delete application_id=%d", application_id)
        return deleted

    def delete_demo_applications(self) -> int:
        """Delete demo-seeded records without touching user-created data."""
        try:
            with connect(self.path) as connection:
                cursor = connection.execute(
                    "DELETE FROM job_applications WHERE source = 'demo'"
                )
                deleted_count = cursor.rowcount
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application data could not be deleted."
            ) from exc
        logger.info(
            "Application operation: operation_type=delete_demo deleted_count=%d",
            deleted_count,
        )
        return deleted_count

    def count_by_status(self) -> dict[ApplicationStatus, int]:
        counts = {status: 0 for status in ApplicationStatus}
        try:
            with connect(self.path) as connection:
                rows = connection.execute(
                    "SELECT status, COUNT(*) AS count FROM job_applications GROUP BY status"
                ).fetchall()
        except DatabaseError as exc:
            raise ApplicationRepositoryError(
                "Application statistics could not be loaded."
            ) from exc
        for row in rows:
            counts[ApplicationStatus(row["status"])] = int(row["count"])
        return counts
