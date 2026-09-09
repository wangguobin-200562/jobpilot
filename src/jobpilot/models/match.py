"""Validated contracts for explainable resume-to-job matching."""

from typing import Literal

from pydantic import Field

from jobpilot.models.candidate_profile import ProfileModel


Score = float
MatchType = Literal["exact", "semantic", "partial"]
Importance = Literal["required", "preferred"]
Relevance = Literal["high", "medium", "low", "none"]
SemanticClassification = Literal["matched", "partial", "missing"]
Priority = Literal["high", "medium", "low"]


class MatchScoreBreakdown(ProfileModel):
    overall_score: Score = Field(ge=0, le=100)
    skills_score: Score | None = Field(default=None, ge=0, le=100)
    experience_score: Score | None = Field(default=None, ge=0, le=100)
    projects_score: Score | None = Field(default=None, ge=0, le=100)
    education_other_score: Score | None = Field(default=None, ge=0, le=100)


class MatchedSkill(ProfileModel):
    skill: str
    resume_evidence: str
    job_requirement: str
    match_type: MatchType


class MissingSkill(ProfileModel):
    skill: str
    importance: Importance
    reason: str


class PartialMatch(ProfileModel):
    job_requirement: str
    resume_evidence: str
    gap: str


class MatchEvidence(ProfileModel):
    category: str
    job_requirement: str
    resume_evidence: str
    assessment: str


class ImprovementPriority(ProfileModel):
    priority: Priority
    action: str
    reason: str


class SkillSemanticAnalysis(ProfileModel):
    job_skill: str
    candidate_evidence: str | None = None
    classification: SemanticClassification
    reason: str


class ExperienceRelevance(ProfileModel):
    experience_reference: str
    job_requirement: str
    candidate_evidence: str | None = None
    relevance: Relevance
    assessment: str


class ProjectRelevance(ProfileModel):
    project_reference: str
    job_requirement: str
    candidate_evidence: str | None = None
    relevance: Relevance
    assessment: str


class RequirementSemanticAnalysis(ProfileModel):
    job_requirement: str
    candidate_evidence: str | None = None
    classification: SemanticClassification
    reason: str


class SemanticMatchAnalysis(ProfileModel):
    """Discrete semantic signals returned by PRO; intentionally contains no scores."""

    skill_analysis: list[SkillSemanticAnalysis] = Field(default_factory=list)
    experience_relevance: list[ExperienceRelevance] = Field(default_factory=list)
    project_relevance: list[ProjectRelevance] = Field(default_factory=list)
    education_other_analysis: list[RequirementSemanticAnalysis] = Field(
        default_factory=list
    )
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    improvement_priorities: list[ImprovementPriority] = Field(default_factory=list)
    summary: str | None = None


class MatchResult(ProfileModel):
    scores: MatchScoreBreakdown
    matched_skills: list[MatchedSkill] = Field(default_factory=list)
    missing_skills: list[MissingSkill] = Field(default_factory=list)
    partial_matches: list[PartialMatch] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    evidence: list[MatchEvidence] = Field(default_factory=list)
    improvement_priorities: list[ImprovementPriority] = Field(default_factory=list)
    summary: str | None = None
