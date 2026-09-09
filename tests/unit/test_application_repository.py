import pytest

from jobpilot.models import (
    ApplicationStatus,
    JobProfile,
    MatchResult,
    MatchScoreBreakdown,
    ResumeOptimizationResult,
)
from jobpilot.storage import ApplicationRepository, DuplicateApplicationError


def _job() -> JobProfile:
    return JobProfile(
        job_title="AI 应用开发实习生",
        company="示例科技",
        location="深圳",
        responsibilities=["开发 AI Agent"],
        required_skills=["Python"],
        preferred_skills=["Docker"],
    )


def _match() -> MatchResult:
    return MatchResult(
        scores=MatchScoreBreakdown(overall_score=86, skills_score=80),
        strengths=["具备 Python 项目经验"],
        gaps=["暂无 Docker 证据"],
    )


def _optimization() -> ResumeOptimizationResult:
    return ResumeOptimizationResult(
        summary="当前简历整体较成熟。",
        capability_gaps=["Docker"],
    )


@pytest.fixture
def repository(tmp_path) -> ApplicationRepository:
    return ApplicationRepository(tmp_path / "jobpilot.db")


def _create(repository: ApplicationRepository, **updates):
    data = {
        "company": "示例科技",
        "job_title": "AI 应用开发实习生",
        "location": "深圳",
        "jd_text": "岗位职责：开发 AI Agent\n要求：Python",
        "job_profile": _job(),
        "match_score": 86,
        "match_result": _match(),
        "optimization_result": _optimization(),
        "source": "公司官网",
    }
    data.update(updates)
    return repository.create_application(**data)


def test_create_and_get_application(repository) -> None:
    created = _create(repository)

    loaded = repository.get_application_by_id(created.id)

    assert loaded is not None
    assert loaded.company == "示例科技"
    assert loaded.job_title == "AI 应用开发实习生"
    assert loaded.match_score == 86


def test_list_and_filter_applications(repository) -> None:
    _create(repository)
    _create(
        repository,
        company="远景数据",
        job_title="数据分析实习生",
        jd_text="职责：数据分析",
        job_profile=JobProfile(job_title="数据分析实习生", company="远景数据"),
        status="applied",
    )

    assert len(repository.list_applications()) == 2
    applied = repository.list_applications(status=ApplicationStatus.APPLIED)
    assert len(applied) == 1
    assert applied[0].company == "远景数据"
    assert len(repository.list_applications(company_query="示例")) == 1
    assert len(repository.list_applications(job_title_query="数据分析")) == 1


def test_update_status_and_notes(repository) -> None:
    created = _create(repository)

    updated = repository.update_status(created.id, "contacted")
    with_notes = repository.update_notes(created.id, "HR 已联系，周五沟通。")

    assert updated is not None
    assert updated.status is ApplicationStatus.CONTACTED
    assert updated.contacted_at is not None
    assert updated.applied_at is None
    assert with_notes is not None
    assert with_notes.notes == "HR 已联系，周五沟通。"
    assert with_notes.updated_at >= created.updated_at


def test_delete_application(repository) -> None:
    created = _create(repository)

    assert repository.delete_application(created.id) is True
    assert repository.get_application_by_id(created.id) is None
    assert repository.delete_application(created.id) is False


def test_duplicate_detection_normalizes_identity_and_jd(repository) -> None:
    created = _create(repository)

    found = repository.find_duplicate(
        company="  示例科技 ",
        job_title="AI  应用开发实习生",
        jd_text="岗位职责：开发 AI Agent\n\n要求：Python  ",
    )

    assert found is not None
    assert found.id == created.id
    with pytest.raises(DuplicateApplicationError):
        _create(
            repository,
            company=" 示例科技 ",
            job_title="AI  应用开发实习生",
            jd_text="岗位职责：开发 AI Agent\n要求：Python",
        )


def test_applied_at_is_set_once_and_not_removed_on_status_rollback(repository) -> None:
    created = _create(repository, match_score=None)
    assert created.applied_at is None

    applied = repository.update_status(created.id, "applied")
    assert applied is not None
    assert applied.applied_at is not None
    first_applied_at = applied.applied_at

    saved = repository.update_status(created.id, "saved")
    assert saved is not None
    assert saved.applied_at == first_applied_at

    applied_again = repository.update_status(created.id, "applied")
    assert applied_again is not None
    assert applied_again.applied_at == first_applied_at


def test_structured_json_round_trip(repository) -> None:
    created = _create(repository)
    loaded = repository.get_application_by_id(created.id)

    assert loaded is not None
    assert loaded.job_profile == _job()
    assert loaded.match_result == _match()
    assert loaded.optimization_result == _optimization()


def test_count_by_status_includes_zero_counts(repository) -> None:
    _create(repository)

    counts = repository.count_by_status()

    assert counts[ApplicationStatus.SAVED] == 1
    assert counts[ApplicationStatus.OFFER] == 0
