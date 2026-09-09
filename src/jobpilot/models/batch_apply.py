"""Privacy-minimal contracts for user-confirmed future application work."""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from jobpilot.models.batch_screening import ScreeningTier
from jobpilot.models.candidate_profile import ProfileModel
from jobpilot.models.fast_screening import FastRelevance


class ApplyReadiness(str, Enum):
    READY = "ready"
    REVIEW_REQUIRED = "review_required"
    UNSUPPORTED = "unsupported"


class BatchApplyItem(ProfileModel):
    application_id: int | None = Field(default=None, gt=0)
    company: str
    job_title: str
    location: str | None = None
    source: str
    source_url: str | None = None
    screening_tier: ScreeningTier = Field(strict=False)
    match_score: float | None = Field(default=None, ge=0, le=100)
    fast_relevance: FastRelevance | None = Field(default=None, strict=False)
    main_reason: str
    main_gaps: list[str] = Field(default_factory=list)
    selected: bool
    apply_readiness: ApplyReadiness = Field(strict=False)
    action_type: Literal["initiate_contact"] = "initiate_contact"
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> "BatchApplyItem":
        if self.selected and (
            self.apply_readiness is ApplyReadiness.UNSUPPORTED
            or self.exclusion_reason is not None
        ):
            raise ValueError("unsupported or excluded items cannot be selected")
        return self


class BatchApplyPlan(ProfileModel):
    contact_plan_id: str = Field(
        default_factory=lambda: f"contact-plan-{uuid4().hex}",
        min_length=8,
        max_length=100,
    )
    screening_batch_id: str | None = Field(default=None, min_length=8, max_length=100)
    items: list[BatchApplyItem]
    selected_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_counts(self) -> "BatchApplyPlan":
        if self.total_count != len(self.items):
            raise ValueError("total_count must equal item count")
        if self.selected_count != sum(item.selected for item in self.items):
            raise ValueError("selected_count must equal selected item count")
        return self
