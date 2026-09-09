"""Small validated result models for deterministic job-search analytics."""

from pydantic import BaseModel, ConfigDict, Field

from jobpilot.models.application import ApplicationStatus


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillFrequency(AnalyticsModel):
    skill: str = Field(min_length=1)
    count: int = Field(gt=0)


class TopMatchingJob(AnalyticsModel):
    application_id: int = Field(gt=0)
    company: str
    job_title: str
    match_score: float = Field(ge=0, le=100)
    status: ApplicationStatus


class FunnelMetrics(AnalyticsModel):
    applied_denominator: int = Field(ge=0)
    contacted_or_later_count: int = Field(ge=0)
    interviewing_or_offer_count: int = Field(ge=0)
    offer_count: int = Field(ge=0)
    contact_rate: float | None = Field(default=None, ge=0, le=1)
    interview_rate: float | None = Field(default=None, ge=0, le=1)
    offer_rate: float | None = Field(default=None, ge=0, le=1)


class MatchDistribution(AnalyticsModel):
    high_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)
    low_count: int = Field(ge=0)


class HighMatchProgress(AnalyticsModel):
    high_match_count: int = Field(ge=0)
    contacted_count: int = Field(ge=0)
    interviewing_count: int = Field(ge=0)
    offer_count: int = Field(ge=0)


class RecentActivity(AnalyticsModel):
    created_last_7_days: int = Field(ge=0)
    created_last_30_days: int = Field(ge=0)
    applied_last_30_days: int = Field(ge=0)


class JobSearchAnalyticsResult(AnalyticsModel):
    total_applications: int = Field(ge=0)
    saved_count: int = Field(ge=0)
    applied_count: int = Field(ge=0)
    contacted_count: int = Field(ge=0)
    interviewing_count: int = Field(ge=0)
    offer_count: int = Field(ge=0)
    closed_count: int = Field(ge=0)
    scored_applications_count: int = Field(ge=0)
    match_result_count: int = Field(ge=0)
    average_match_score: float | None = Field(default=None, ge=0, le=100)
    highest_matching_job: TopMatchingJob | None = None
    funnel: FunnelMetrics
    required_skill_gaps: list[SkillFrequency] = Field(default_factory=list)
    preferred_skill_gaps: list[SkillFrequency] = Field(default_factory=list)
    required_skill_demand: list[SkillFrequency] = Field(default_factory=list)
    preferred_skill_demand: list[SkillFrequency] = Field(default_factory=list)
    tools_demand: list[SkillFrequency] = Field(default_factory=list)
    match_distribution: MatchDistribution
    high_match_progress: HighMatchProgress
    top_matching_jobs: list[TopMatchingJob] = Field(default_factory=list)
    recent_activity: RecentActivity
    trend_data_sufficient: bool
    skill_gap_data_sufficient: bool
