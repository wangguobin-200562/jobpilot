"""Local view models for the deterministic application queue."""

from datetime import datetime
from enum import Enum

from pydantic import Field

from jobpilot.models.batch_screening import ScreeningTier
from jobpilot.models.candidate_profile import ProfileModel


class PreparationStatus(str, Enum):
    READY = "ready"
    REVIEW_NEEDED = "review_needed"
    GAP_WARNING = "gap_warning"


class OptimizationStatus(str, Enum):
    GENERATED = "generated"
    NOT_GENERATED = "not_generated"


class QueueSort(str, Enum):
    PRIORITY = "priority"
    MATCH_SCORE = "match_score"
    NEWEST = "newest"
    OLDEST = "oldest"


class ApplicationQueueItem(ProfileModel):
    application_id: int = Field(gt=0)
    company: str
    job_title: str
    location: str | None = None
    match_score: float | None = Field(default=None, ge=0, le=100)
    screening_tier: ScreeningTier
    priority_score: float
    source: str | None = None
    source_url: str | None = None
    preparation_status: PreparationStatus
    optimization_status: OptimizationStatus
    required_missing_count: int = Field(ge=0)
    main_gap: str | None = None
    deferred_until: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApplicationQueueResult(ProfileModel):
    items: list[ApplicationQueueItem]
    deferred_items: list[ApplicationQueueItem]
    total_count: int = Field(ge=0)
    ready_count: int = Field(ge=0)
    review_needed_count: int = Field(ge=0)
    gap_warning_count: int = Field(ge=0)
