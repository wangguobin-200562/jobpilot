"""Contracts for the conservative fast-screening funnel."""

from enum import Enum
from uuid import uuid4

from pydantic import AliasChoices, Field, field_validator, model_validator

from jobpilot.models.batch_screening import BatchJobInput, ScreeningTier
from jobpilot.models.candidate_profile import ProfileModel
from jobpilot.models.job import JobProfile
from jobpilot.models.match import MatchResult


class ScreeningMode(str, Enum):
    QUICK = "quick"
    DEEP = "deep"


class LocalScreeningDecision(str, Enum):
    PASS = "pass"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


class FastRelevance(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class AssessmentConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FastScreeningStage(str, Enum):
    LOCAL = "local"
    FLASH = "flash"
    PRO = "pro"
    COMPLETED = "completed"


class LocalPreScreenResult(ProfileModel):
    decision: LocalScreeningDecision
    reason: str
    hard_requirement_risks: list[str] = Field(default_factory=list)


class FastScreeningAssessment(ProfileModel):
    """Small FLASH-only judgment. It deliberately contains no numeric score."""

    job_title: str | None = None
    core_required_skills: list[str] = Field(default_factory=list, max_length=5)
    matched_core_skills: list[str] = Field(default_factory=list, max_length=5)
    missing_core_skills: list[str] = Field(default_factory=list, max_length=5)
    hard_requirement_risks: list[str] = Field(default_factory=list, max_length=5)
    relevance: FastRelevance = Field(strict=False)
    decision_confidence: AssessmentConfidence = Field(
        strict=False,
        validation_alias=AliasChoices("decision_confidence", "confidence"),
    )
    reason: str = Field(max_length=160)

    @field_validator(
        "core_required_skills",
        "matched_core_skills",
        "missing_core_skills",
        "hard_requirement_risks",
        mode="before",
    )
    @classmethod
    def keep_only_five_items(cls, value):
        """Bound provider output deterministically instead of spending a repair call."""
        return value[:5] if isinstance(value, list) else value

    @field_validator("reason", mode="before")
    @classmethod
    def keep_reason_concise(cls, value):
        return value[:160] if isinstance(value, str) else value

    @property
    def confidence(self) -> AssessmentConfidence:
        """Compatibility accessor for cached Milestone 11 objects."""
        return self.decision_confidence


class CompactCandidateSummary(ProfileModel):
    """Small deterministic, PII-free evidence packet reused across a batch."""

    skills: list[str] = Field(default_factory=list, max_length=30)
    experience_overview: list[str] = Field(default_factory=list, max_length=4)
    project_evidence: list[str] = Field(default_factory=list, max_length=4)
    education: list[str] = Field(default_factory=list, max_length=3)
    certifications: list[str] = Field(default_factory=list, max_length=5)
    languages: list[str] = Field(default_factory=list, max_length=5)


class FastScreeningItem(ProfileModel):
    job_input: BatchJobInput
    local_result: LocalPreScreenResult
    assessment: FastScreeningAssessment | None = None
    screening_tier: ScreeningTier
    screening_reason: str
    core_gaps: list[str] = Field(default_factory=list)
    deep_match: bool = False
    deep_analysis_failed: bool = False
    job_profile: JobProfile | None = None
    match_result: MatchResult | None = None
    match_score: float | None = Field(default=None, ge=0, le=100)
    is_cached: bool = False

    @model_validator(mode="after")
    def validate_score_ownership(self) -> "FastScreeningItem":
        if self.deep_match:
            if self.job_profile is None or self.match_result is None or self.match_score is None:
                raise ValueError("deep matches require a complete deterministic match result")
        elif self.match_score is not None or self.match_result is not None:
            raise ValueError("fast-only results must not expose a precise match score")
        return self


class ScreeningTiming(ProfileModel):
    local_seconds: float = Field(ge=0)
    flash_seconds: float = Field(ge=0)
    pro_seconds: float = Field(ge=0)
    total_elapsed_seconds: float = Field(ge=0)
    avg_seconds_per_job: float = Field(ge=0)
    time_to_first_result_seconds: float = Field(default=0, ge=0)


class ScreeningTimelineEvent(ProfileModel):
    stage: str
    job_index: int | None = Field(default=None, ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    cache_hit: bool = False


class ScreeningMetrics(ProfileModel):
    total_jobs: int = Field(ge=0)
    local_filtered: int = Field(ge=0)
    flash_screened: int = Field(ge=0)
    pro_analyzed: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    cache_misses: int = Field(default=0, ge=0)
    jd_parse_calls: int = Field(default=0, ge=0)
    flash_provider_calls: int = Field(ge=0)
    pro_provider_calls: int = Field(ge=0)
    duplicate_jobs: int = Field(default=0, ge=0)
    repair_calls: int = Field(default=0, ge=0)
    rate_limit_retries: int = Field(default=0, ge=0)
    timeline: list[ScreeningTimelineEvent] = Field(default_factory=list)
    timing: ScreeningTiming


class FastScreeningPipelineResult(ProfileModel):
    screening_batch_id: str = Field(
        default_factory=lambda: f"screening-{uuid4().hex}",
        min_length=8,
        max_length=100,
    )
    items: list[FastScreeningItem]
    metrics: ScreeningMetrics


class FastScreeningProgress(ProfileModel):
    stage: FastScreeningStage
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    visible_results: int = Field(ge=0)
    item_index: int | None = Field(default=None, ge=1)
