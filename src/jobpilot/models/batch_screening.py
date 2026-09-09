"""Validated contracts for deterministic batch job screening."""

from datetime import datetime, timezone
from enum import Enum

from pydantic import Field, model_validator

from jobpilot.models.candidate_profile import ProfileModel
from jobpilot.models.job import JobProfile
from jobpilot.models.match import MatchResult


class BatchJobStatus(str, Enum):
    PENDING = "pending"
    ANALYZING_JD = "analyzing_jd"
    MATCHING = "matching"
    COMPLETED = "completed"
    FAILED = "failed"


class ScreeningTier(str, Enum):
    PRIORITY = "priority"
    RECOMMENDED = "recommended"
    CAUTION = "caution"
    LOW_PRIORITY = "low_priority"


class BatchJobInput(ProfileModel):
    index: int = Field(ge=1)
    company: str | None = None
    job_title: str | None = None
    location: str | None = None
    jd_text: str = Field(min_length=1)
    source_url: str | None = None
    raw_block: str = Field(min_length=1)


class BatchScreeningItem(ProfileModel):
    index: int = Field(ge=1)
    company: str | None = None
    job_title: str | None = None
    location: str | None = None
    jd_text: str = Field(min_length=1)
    raw_block: str = Field(min_length=1)
    source_url: str | None = None
    jd_fingerprint: str = Field(min_length=64, max_length=64)
    status: BatchJobStatus
    job_profile: JobProfile | None = None
    match_result: MatchResult | None = None
    match_score: float | None = Field(default=None, ge=0, le=100)
    screening_tier: ScreeningTier | None = None
    screening_reason: str | None = None
    error_message: str | None = None
    required_missing_count: int = Field(default=0, ge=0)
    is_cached: bool = False
    cache_source: str | None = None

    @model_validator(mode="after")
    def validate_terminal_state(self) -> "BatchScreeningItem":
        if self.status is BatchJobStatus.COMPLETED:
            if (
                self.job_profile is None
                or self.match_result is None
                or self.match_score is None
                or self.screening_tier is None
                or not self.screening_reason
            ):
                raise ValueError("completed batch items require complete screening data")
        if self.status is BatchJobStatus.FAILED and not self.error_message:
            raise ValueError("failed batch items require an error message")
        return self


class BatchScreeningResult(ProfileModel):
    items: list[BatchScreeningItem]
    total_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    cached_count: int = Field(ge=0)
    newly_analyzed_count: int = Field(ge=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def validate_counts(self) -> "BatchScreeningResult":
        if self.total_count != len(self.items):
            raise ValueError("total_count must equal the number of items")
        if self.completed_count + self.failed_count != self.total_count:
            raise ValueError("completed and failed counts must cover all items")
        return self


class BatchSaveSummary(ProfileModel):
    saved_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
