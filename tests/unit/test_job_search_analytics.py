from datetime import datetime, timedelta, timezone

import pytest

from jobpilot.models import (
    JobApplication,
    JobProfile,
    MatchResult,
    MatchScoreBreakdown,
)
from jobpilot.services import (
    HIGH_MATCH_MIN_SCORE,
    MEDIUM_MATCH_MIN_SCORE,
    MIN_APPLICATIONS_FOR_TRENDS,
    MIN_MATCH_RESULTS_FOR_SKILL_INSIGHTS,
    TOP_MATCHING_JOBS_LIMIT,
    JobSearchAnalyticsService,
)


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self, applications=None):
        self.applications = applications or []
        self.calls = 0

    def list_applications(self, **kwargs):
        self.calls += 1
        return list(self.applications)


def _match(required=(), preferred=()) -> MatchResult:
    return MatchResult(
        scores=MatchScoreBreakdown(overall_score=70),
        missing_skills=[
            *[
                {"skill": skill, "importance": "required", "reason": "缺少证据"}
                for skill in required
            ],
            *[
                {"skill": skill, "importance": "preferred", "reason": "缺少证据"}
                for skill in preferred
            ],
        ],
    )


def _application(
    identifier: int,
    *,
    status="saved",
    score=None,
    match=None,
    required=(),
    preferred=(),
    tools=(),
    created_at=NOW,
    applied_at=None,
) -> JobApplication:
    profile = JobProfile(
        company=f"公司{identifier}",
        job_title=f"岗位{identifier}",
        required_skills=list(required),
        preferred_skills=list(preferred),
        tools_and_technologies=list(tools),
    )
    return JobApplication(
        id=identifier,
        company=f"公司{identifier}",
        job_title=f"岗位{identifier}",
        status=status,
        match_score=score,
        jd_fingerprint=str(identifier) * 64,
        job_profile_json=profile.model_dump_json(),
        match_result_json=match.model_dump_json() if match else None,
        created_at=created_at,
        updated_at=created_at,
        applied_at=applied_at,
    )


def _analyze(applications):
    source = FakeRepository(applications)
    result = JobSearchAnalyticsService(source).analyze(now=NOW)
    assert source.calls == 1
    return result


def test_empty_repository_returns_zero_metrics_and_none_rates() -> None:
    result = _analyze([])

    assert result.total_applications == 0
    assert result.average_match_score is None
    assert result.highest_matching_job is None
    assert result.funnel.contact_rate is None
    assert result.top_matching_jobs == []


def test_total_and_status_counts() -> None:
    statuses = ["saved", "applied", "contacted", "interviewing", "offer", "closed"]
    result = _analyze(
        [_application(index, status=status) for index, status in enumerate(statuses, 1)]
    )

    assert result.total_applications == 6
    assert result.saved_count == 1
    assert result.applied_count == 1
    assert result.contacted_count == 1
    assert result.interviewing_count == 1
    assert result.offer_count == 1
    assert result.closed_count == 1


def test_average_match_score_ignores_none() -> None:
    result = _analyze(
        [_application(1, score=80), _application(2, score=None), _application(3, score=60)]
    )

    assert result.scored_applications_count == 2
    assert result.average_match_score == 70


def test_average_is_none_when_no_application_has_score() -> None:
    result = _analyze([_application(1), _application(2)])

    assert result.average_match_score is None
    assert result.scored_applications_count == 0


def test_funnel_uses_only_applied_at_population_and_current_known_states() -> None:
    applied_at = NOW - timedelta(days=10)
    statuses = ["applied", "contacted", "interviewing", "offer", "closed"]
    applications = [
        _application(index, status=status, applied_at=applied_at)
        for index, status in enumerate(statuses, 1)
    ]
    applications.append(_application(6, status="contacted", applied_at=None))

    funnel = _analyze(applications).funnel

    assert funnel.applied_denominator == 5
    assert funnel.contacted_or_later_count == 3
    assert funnel.interviewing_or_offer_count == 2
    assert funnel.offer_count == 1
    assert funnel.contact_rate == pytest.approx(0.6)
    assert funnel.interview_rate == pytest.approx(0.4)
    assert funnel.offer_rate == pytest.approx(0.2)


def test_funnel_rates_are_none_when_applied_denominator_is_zero() -> None:
    funnel = _analyze([_application(1, status="saved")]).funnel

    assert funnel.applied_denominator == 0
    assert funnel.contact_rate is None
    assert funnel.interview_rate is None
    assert funnel.offer_rate is None


def test_required_and_preferred_gap_aggregation_normalizes_skills() -> None:
    result = _analyze(
        [
            _application(1, match=_match(required=["Python"], preferred=["Docker"])),
            _application(2, match=_match(required=["python"], preferred=["docker"])),
            _application(3, match=_match(required=["FastAPI"])),
        ]
    )

    assert [(item.skill, item.count) for item in result.required_skill_gaps] == [
        ("Python", 2),
        ("FastAPI", 1),
    ]
    assert [(item.skill, item.count) for item in result.preferred_skill_gaps] == [
        ("Docker", 2)
    ]


def test_applications_without_match_result_are_ignored_for_skill_gaps() -> None:
    result = _analyze(
        [_application(1), _application(2, match=_match(required=["Docker"]))]
    )

    assert result.match_result_count == 1
    assert result.required_skill_gaps[0].count == 1


def test_skill_gap_sufficiency_threshold() -> None:
    insufficient = _analyze(
        [
            _application(index, match=_match(required=["Docker"]))
            for index in range(1, MIN_MATCH_RESULTS_FOR_SKILL_INSIGHTS)
        ]
    )
    sufficient = _analyze(
        [
            _application(index, match=_match(required=["Docker"]))
            for index in range(1, MIN_MATCH_RESULTS_FOR_SKILL_INSIGHTS + 1)
        ]
    )

    assert insufficient.skill_gap_data_sufficient is False
    assert sufficient.skill_gap_data_sufficient is True


def test_required_preferred_and_tools_demand_are_separate_and_normalized() -> None:
    result = _analyze(
        [
            _application(1, required=["Python"], preferred=["Docker"], tools=["Git"]),
            _application(2, required=["python"], preferred=["docker"], tools=["git"]),
            _application(3, required=["SQL"], tools=["Linux"]),
        ]
    )

    assert [(item.skill, item.count) for item in result.required_skill_demand] == [
        ("Python", 2),
        ("SQL", 1),
    ]
    assert result.preferred_skill_demand[0].count == 2
    assert result.tools_demand[0].skill == "Git"
    assert result.tools_demand[0].count == 2


def test_skill_frequency_counts_each_skill_once_per_job() -> None:
    result = _analyze(
        [
            _application(1, required=["Python", "python", "Python"]),
            _application(2, required=["PYTHON"]),
            _application(
                3,
                match=_match(required=["Docker", "docker"]),
            ),
        ]
    )

    assert result.required_skill_demand[0].count == 2
    assert result.required_skill_gaps[0].count == 1


def test_match_distribution_threshold_boundaries_and_none_exclusion() -> None:
    assert HIGH_MATCH_MIN_SCORE == 80
    assert MEDIUM_MATCH_MIN_SCORE == 60
    result = _analyze(
        [
            _application(1, score=100),
            _application(2, score=80),
            _application(3, score=79.9),
            _application(4, score=60),
            _application(5, score=59.9),
            _application(6, score=0),
            _application(7, score=None),
        ]
    )

    assert result.match_distribution.high_count == 2
    assert result.match_distribution.medium_count == 2
    assert result.match_distribution.low_count == 2
    assert result.scored_applications_count == 6


def test_top_matching_jobs_are_descending_limited_and_exclude_none() -> None:
    applications = [
        _application(index, score=score)
        for index, score in enumerate([50, 99, 70, 88, None, 92, 60], 1)
    ]

    result = _analyze(applications)

    assert len(result.top_matching_jobs) == TOP_MATCHING_JOBS_LIMIT
    assert [item.match_score for item in result.top_matching_jobs] == [99, 92, 88, 70, 60]
    assert result.highest_matching_job == result.top_matching_jobs[0]


def test_high_match_progress_reports_current_facts_only() -> None:
    result = _analyze(
        [
            _application(1, score=85, status="contacted"),
            _application(2, score=90, status="interviewing"),
            _application(3, score=95, status="offer"),
            _application(4, score=70, status="offer"),
        ]
    )

    assert result.high_match_progress.high_match_count == 3
    assert result.high_match_progress.contacted_count == 1
    assert result.high_match_progress.interviewing_count == 1
    assert result.high_match_progress.offer_count == 1


def test_recent_activity_uses_seven_and_thirty_day_windows() -> None:
    result = _analyze(
        [
            _application(1, created_at=NOW - timedelta(days=6), applied_at=NOW - timedelta(days=2)),
            _application(2, created_at=NOW - timedelta(days=7), applied_at=NOW - timedelta(days=30)),
            _application(3, created_at=NOW - timedelta(days=8), applied_at=NOW - timedelta(days=31)),
            _application(4, created_at=NOW - timedelta(days=30)),
            _application(5, created_at=NOW - timedelta(days=31)),
        ]
    )

    assert result.recent_activity.created_last_7_days == 2
    assert result.recent_activity.created_last_30_days == 4
    assert result.recent_activity.applied_last_30_days == 2


def test_overall_trend_sufficiency_threshold() -> None:
    insufficient = _analyze(
        [_application(index) for index in range(1, MIN_APPLICATIONS_FOR_TRENDS)]
    )
    sufficient = _analyze(
        [_application(index) for index in range(1, MIN_APPLICATIONS_FOR_TRENDS + 1)]
    )

    assert insufficient.trend_data_sufficient is False
    assert sufficient.trend_data_sufficient is True
