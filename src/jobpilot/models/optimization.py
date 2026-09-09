"""Validated contracts for targeted, fact-preserving resume suggestions."""

from typing import Literal

from pydantic import Field, model_validator

from jobpilot.models.candidate_profile import ProfileModel


OptimizationDecision = Literal["keep", "optional", "recommended"]
OptimizationSection = Literal[
    "summary",
    "education",
    "experience",
    "projects",
    "skills",
    "certifications",
    "languages",
]
KeywordStatus = Literal["covered", "can_emphasize", "gap_do_not_add"]


class ResumeSuggestion(ProfileModel):
    """One independently reviewable suggestion tied to resume evidence."""

    section: OptimizationSection
    source_name: str = Field(min_length=1)
    decision: OptimizationDecision
    original: str = Field(min_length=1)
    suggested: str | None = None
    reason: str = Field(min_length=1)
    expected_benefit: str | None = None
    supported_by: list[str] = Field(min_length=1)
    related_job_requirements: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_requirements(self) -> "ResumeSuggestion":
        if self.decision == "optional" and self.suggested and not (
            self.expected_benefit and self.expected_benefit.strip()
        ):
            raise ValueError(
                "optional rewrites require an expected benefit when suggested is set"
            )
        if self.decision == "recommended":
            if not self.suggested or not self.suggested.strip():
                raise ValueError("recommended suggestions require suggested text")
            if not self.expected_benefit or not self.expected_benefit.strip():
                raise ValueError("recommended suggestions require an expected benefit")
        return self


class KeywordSuggestion(ProfileModel):
    """Safe handling guidance for one job keyword."""

    keyword: str = Field(min_length=1)
    status: KeywordStatus
    evidence: str | None = None
    guidance: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_emphasis_evidence(self) -> "KeywordSuggestion":
        if self.status == "can_emphasize" and not (
            self.evidence and self.evidence.strip()
        ):
            raise ValueError("can_emphasize keywords require resume evidence")
        return self


class ResumeOptimizationResult(ProfileModel):
    """Targeted suggestions without rewriting or mutating the source resume."""

    summary: str = Field(min_length=1)
    suggestions: list[ResumeSuggestion] = Field(default_factory=list)
    keyword_suggestions: list[KeywordSuggestion] = Field(default_factory=list)
    capability_gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
