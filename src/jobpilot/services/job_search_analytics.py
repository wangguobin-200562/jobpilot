"""Deterministic analytics over locally saved job applications."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable, Protocol

from jobpilot.models import (
    ApplicationStatus,
    FunnelMetrics,
    HighMatchProgress,
    JobApplication,
    JobSearchAnalyticsResult,
    MatchDistribution,
    RecentActivity,
    SkillFrequency,
    TopMatchingJob,
)
from jobpilot.services.matching_service import normalize_skill


HIGH_MATCH_MIN_SCORE = 80.0
MEDIUM_MATCH_MIN_SCORE = 60.0
TOP_MATCHING_JOBS_LIMIT = 5
MIN_APPLICATIONS_FOR_TRENDS = 3
MIN_MATCH_RESULTS_FOR_SKILL_INSIGHTS = 3


class ApplicationAnalyticsSource(Protocol):
    def list_applications(self, **kwargs) -> list[JobApplication]: ...


def _skill_frequencies(groups: Iterable[Iterable[str]]) -> list[SkillFrequency]:
    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for group in groups:
        group_keys: set[str] = set()
        for skill in group:
            key = normalize_skill(skill)
            if not key or key in group_keys:
                continue
            group_keys.add(key)
            counts[key] += 1
            labels.setdefault(key, skill.strip())
    return [
        SkillFrequency(skill=labels[key], count=count)
        for key, count in sorted(
            counts.items(), key=lambda item: (-item[1], labels[item[0]].casefold())
        )
    ]


def _top_job(application: JobApplication) -> TopMatchingJob:
    if application.match_score is None:
        raise ValueError("Top matching jobs require a match score.")
    return TopMatchingJob(
        application_id=application.id,
        company=application.company,
        job_title=application.job_title,
        match_score=application.match_score,
        status=application.status,
    )


class JobSearchAnalyticsService:
    """Read applications once and calculate honest, local-only insights."""

    def __init__(self, repository: ApplicationAnalyticsSource) -> None:
        self.repository = repository

    def analyze(self, *, now: datetime | None = None) -> JobSearchAnalyticsResult:
        applications = self.repository.list_applications()
        reference_time = now or datetime.now(timezone.utc)
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)

        status_counts = Counter(item.status for item in applications)
        scored = [item for item in applications if item.match_score is not None]
        average_score = (
            sum(item.match_score for item in scored if item.match_score is not None)
            / len(scored)
            if scored
            else None
        )
        sorted_scored = sorted(
            scored,
            key=lambda item: (-(item.match_score or 0), -item.id),
        )
        top_jobs = [
            _top_job(item) for item in sorted_scored[:TOP_MATCHING_JOBS_LIMIT]
        ]

        applied_population = [
            item for item in applications if item.applied_at is not None
        ]
        contacted_or_later = sum(
            item.status
            in {
                ApplicationStatus.CONTACTED,
                ApplicationStatus.INTERVIEWING,
                ApplicationStatus.OFFER,
            }
            for item in applied_population
        )
        interviewing_or_offer = sum(
            item.status
            in {ApplicationStatus.INTERVIEWING, ApplicationStatus.OFFER}
            for item in applied_population
        )
        offers = sum(
            item.status is ApplicationStatus.OFFER for item in applied_population
        )
        denominator = len(applied_population)
        funnel = FunnelMetrics(
            applied_denominator=denominator,
            contacted_or_later_count=contacted_or_later,
            interviewing_or_offer_count=interviewing_or_offer,
            offer_count=offers,
            contact_rate=contacted_or_later / denominator if denominator else None,
            interview_rate=interviewing_or_offer / denominator if denominator else None,
            offer_rate=offers / denominator if denominator else None,
        )

        with_match = [item for item in applications if item.match_result is not None]
        required_gaps = _skill_frequencies(
            (
                missing.skill
                for missing in item.match_result.missing_skills
                if missing.importance == "required"
            )
            for item in with_match
            if item.match_result is not None
        )
        preferred_gaps = _skill_frequencies(
            (
                missing.skill
                for missing in item.match_result.missing_skills
                if missing.importance == "preferred"
            )
            for item in with_match
            if item.match_result is not None
        )
        required_demand = _skill_frequencies(
            item.job_profile.required_skills for item in applications
        )
        preferred_demand = _skill_frequencies(
            item.job_profile.preferred_skills for item in applications
        )
        tools_demand = _skill_frequencies(
            item.job_profile.tools_and_technologies for item in applications
        )

        high = [
            item
            for item in scored
            if item.match_score is not None and item.match_score >= HIGH_MATCH_MIN_SCORE
        ]
        medium = [
            item
            for item in scored
            if item.match_score is not None
            and MEDIUM_MATCH_MIN_SCORE <= item.match_score < HIGH_MATCH_MIN_SCORE
        ]
        low_count = len(scored) - len(high) - len(medium)
        high_progress = HighMatchProgress(
            high_match_count=len(high),
            contacted_count=sum(
                item.status is ApplicationStatus.CONTACTED for item in high
            ),
            interviewing_count=sum(
                item.status is ApplicationStatus.INTERVIEWING for item in high
            ),
            offer_count=sum(item.status is ApplicationStatus.OFFER for item in high),
        )

        seven_days_ago = reference_time - timedelta(days=7)
        thirty_days_ago = reference_time - timedelta(days=30)
        recent = RecentActivity(
            created_last_7_days=sum(
                item.created_at >= seven_days_ago for item in applications
            ),
            created_last_30_days=sum(
                item.created_at >= thirty_days_ago for item in applications
            ),
            applied_last_30_days=sum(
                item.applied_at is not None and item.applied_at >= thirty_days_ago
                for item in applications
            ),
        )

        return JobSearchAnalyticsResult(
            total_applications=len(applications),
            saved_count=status_counts[ApplicationStatus.SAVED],
            applied_count=status_counts[ApplicationStatus.APPLIED],
            contacted_count=status_counts[ApplicationStatus.CONTACTED],
            interviewing_count=status_counts[ApplicationStatus.INTERVIEWING],
            offer_count=status_counts[ApplicationStatus.OFFER],
            closed_count=status_counts[ApplicationStatus.CLOSED],
            scored_applications_count=len(scored),
            match_result_count=len(with_match),
            average_match_score=average_score,
            highest_matching_job=top_jobs[0] if top_jobs else None,
            funnel=funnel,
            required_skill_gaps=required_gaps,
            preferred_skill_gaps=preferred_gaps,
            required_skill_demand=required_demand,
            preferred_skill_demand=preferred_demand,
            tools_demand=tools_demand,
            match_distribution=MatchDistribution(
                high_count=len(high),
                medium_count=len(medium),
                low_count=low_count,
            ),
            high_match_progress=high_progress,
            top_matching_jobs=top_jobs,
            recent_activity=recent,
            trend_data_sufficient=(
                len(applications) >= MIN_APPLICATIONS_FOR_TRENDS
            ),
            skill_gap_data_sufficient=(
                len(with_match) >= MIN_MATCH_RESULTS_FOR_SKILL_INSIGHTS
            ),
        )
