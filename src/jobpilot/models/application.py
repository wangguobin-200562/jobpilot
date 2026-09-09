"""Persistent job-application data contracts."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from jobpilot.models.job import JobProfile
from jobpilot.models.match import MatchResult
from jobpilot.models.optimization import ResumeOptimizationResult


class ApplicationStatus(str, Enum):
    SAVED = "saved"
    APPLIED = "applied"
    CONTACTED = "contacted"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    CLOSED = "closed"


STATUS_LABELS: dict[ApplicationStatus, str] = {
    ApplicationStatus.SAVED: "待沟通",
    ApplicationStatus.APPLIED: "已投递",
    ApplicationStatus.CONTACTED: "已沟通",
    ApplicationStatus.INTERVIEWING: "面试中",
    ApplicationStatus.OFFER: "Offer",
    ApplicationStatus.CLOSED: "已结束",
}
STATUS_BY_LABEL = {label: status for status, label in STATUS_LABELS.items()}


class JobApplication(BaseModel):
    """One locally persisted application with validated JSON snapshots."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    company: str = Field(min_length=1)
    job_title: str = Field(min_length=1)
    location: str | None = None
    status: ApplicationStatus
    match_score: float | None = Field(default=None, ge=0, le=100)
    jd_text: str = ""
    jd_fingerprint: str = Field(min_length=1)
    job_profile_json: str = Field(min_length=1)
    match_result_json: str | None = None
    optimization_result_json: str | None = None
    notes: str = ""
    source: str | None = None
    source_url: str | None = None
    deferred_until: datetime | None = None
    applied_at: datetime | None = None
    contacted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def job_profile(self) -> JobProfile:
        return JobProfile.model_validate_json(self.job_profile_json)

    @property
    def match_result(self) -> MatchResult | None:
        if self.match_result_json is None:
            return None
        return MatchResult.model_validate_json(self.match_result_json)

    @property
    def optimization_result(self) -> ResumeOptimizationResult | None:
        if self.optimization_result_json is None:
            return None
        return ResumeOptimizationResult.model_validate_json(
            self.optimization_result_json
        )
