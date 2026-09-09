from datetime import datetime, timedelta, timezone

import pytest

from jobpilot.models import (
    ApplicationStatus, JobProfile, MatchResult, MatchScoreBreakdown,
    OptimizationStatus, PreparationStatus, QueueSort, ResumeOptimizationResult,
    ScreeningTier,
)
from jobpilot.services import (
    ApplicationQueueService, calculate_preparation_status,
    calculate_priority_score, normalize_source, safe_external_url,
)
from jobpilot.storage import ApplicationRepository


NOW = datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc)


def _create(repository, index, score=85, *, status="saved", gaps=0, source_url=None):
    missing = [
        {"skill": f"缺口{i}", "importance": "required", "reason": "无证据"}
        for i in range(gaps)
    ]
    match = MatchResult(
        scores=MatchScoreBreakdown(overall_score=score), missing_skills=missing
    )
    return repository.create_application(
        company=f"虚构公司{index}", job_title=f"虚构岗位{index}",
        jd_text=f"虚构岗位描述 {index}", job_profile=JobProfile(job_title=f"虚构岗位{index}"),
        status=status, match_score=score, match_result=match,
        source="manual", source_url=source_url,
    )


@pytest.fixture
def repository(tmp_path):
    return ApplicationRepository(tmp_path / "queue.db")


def test_only_saved_applications_are_eligible(repository) -> None:
    _create(repository, 1, status="saved")
    _create(repository, 2, status="applied")
    result = ApplicationQueueService(repository).load_queue()
    assert [item.job_title for item in result.items] == ["虚构岗位1"]


def test_priority_score_uses_transparent_tier_adjustment() -> None:
    assert calculate_priority_score(80, ScreeningTier.PRIORITY) == 100
    assert calculate_priority_score(70, ScreeningTier.RECOMMENDED) == 80
    assert calculate_priority_score(None, ScreeningTier.LOW_PRIORITY) == -20


@pytest.mark.parametrize(
    ("tier", "gaps", "expected"),
    [
        (ScreeningTier.PRIORITY, 1, PreparationStatus.READY),
        (ScreeningTier.RECOMMENDED, 0, PreparationStatus.REVIEW_NEEDED),
        (ScreeningTier.CAUTION, 0, PreparationStatus.GAP_WARNING),
        (ScreeningTier.LOW_PRIORITY, 0, PreparationStatus.GAP_WARNING),
    ],
)
def test_preparation_status_is_deterministic(tier, gaps, expected) -> None:
    assert calculate_preparation_status(tier, gaps) is expected


def test_tier_gap_and_default_priority_sorting(repository) -> None:
    _create(repository, 1, score=90, gaps=2)
    _create(repository, 2, score=85, gaps=0)
    _create(repository, 3, score=70, gaps=0)
    result = ApplicationQueueService(repository).load_queue()
    assert [item.application_id for item in result.items] == [2, 1, 3]
    assert result.items[0].preparation_status is PreparationStatus.READY
    assert result.items[1].screening_tier is ScreeningTier.RECOMMENDED
    assert result.items[1].main_gap == "缺口0"


def test_none_match_score_is_safe(repository) -> None:
    application = repository.create_application(
        company="空分数公司", job_title="空分数岗位", jd_text="空分数虚构 JD",
        job_profile=JobProfile(job_title="空分数岗位"), match_score=None,
    )
    item = ApplicationQueueService(repository).load_queue().items[0]
    assert item.application_id == application.id
    assert item.screening_tier is ScreeningTier.LOW_PRIORITY
    assert item.priority_score == -20


def test_search_tier_and_sort_filters(repository) -> None:
    _create(repository, 1, score=85)
    _create(repository, 2, score=70)
    service = ApplicationQueueService(repository)
    assert len(service.load_queue(query="公司1").items) == 1
    assert len(service.load_queue(tier=ScreeningTier.RECOMMENDED).items) == 1
    assert service.load_queue(sort=QueueSort.MATCH_SCORE).items[0].match_score == 85


def test_defer_hide_expire_cancel_and_datetime_persistence(repository) -> None:
    application = _create(repository, 1)
    service = ApplicationQueueService(repository, now_provider=lambda: NOW)
    deferred = service.defer(application.id, 1)
    assert deferred.deferred_until == NOW + timedelta(days=1)
    assert service.load_queue().total_count == 0
    assert len(service.load_queue().deferred_items) == 1
    expired = ApplicationQueueService(
        repository, now_provider=lambda: NOW + timedelta(days=2)
    ).load_queue()
    assert expired.total_count == 1
    service.cancel_defer(application.id)
    assert service.load_queue().total_count == 1


def test_apply_removes_item_but_record_remains_and_restore_reenters(repository) -> None:
    application = _create(repository, 1)
    service = ApplicationQueueService(repository, now_provider=lambda: NOW)
    service.defer(application.id, 1)
    applied = service.mark_applied(application.id)
    assert applied.status is ApplicationStatus.APPLIED
    assert applied.applied_at is not None
    assert service.load_queue().total_count == 0
    assert repository.get_application_by_id(application.id) is not None
    assert applied.deferred_until is None
    service.restore_saved(application.id)
    assert service.load_queue().total_count == 1


def test_optimization_status_reflects_persisted_snapshot(repository) -> None:
    _create(repository, 1)
    repository.create_application(
        company="已有建议公司", job_title="已有建议岗位", jd_text="已有建议虚构 JD",
        job_profile=JobProfile(job_title="已有建议岗位"), match_score=70,
        match_result=MatchResult(scores=MatchScoreBreakdown(overall_score=70)),
        optimization_result=ResumeOptimizationResult(summary="无需强制修改。"),
    )
    statuses = {
        item.company: item.optimization_status
        for item in ApplicationQueueService(repository).load_queue().items
    }
    assert statuses["虚构公司1"] is OptimizationStatus.NOT_GENERATED
    assert statuses["已有建议公司"] is OptimizationStatus.GENERATED


def test_source_url_is_optional_safe_and_never_requested(repository, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("No HTTP request is allowed")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    _create(repository, 1, source_url="https://example.com/job/1")
    item = ApplicationQueueService(repository).load_queue().items[0]
    assert item.source_url == "https://example.com/job/1"
    assert normalize_source("manual", item.source_url) == "manual"
    assert safe_external_url("javascript:alert(1)") is None
