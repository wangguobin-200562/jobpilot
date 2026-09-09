from jobpilot.models import (
    BatchJobStatus,
    BatchScreeningItem,
    JobProfile,
    MatchResult,
    MatchScoreBreakdown,
    ScreeningTier,
)
from jobpilot.services import save_batch_item, save_priority_items
from jobpilot.storage import ApplicationRepository, ApplicationRepositoryError


def _item(index=1, *, company="虚构公司", tier=ScreeningTier.PRIORITY):
    profile = JobProfile(
        company=company,
        job_title=f"虚构岗位{index}",
        required_skills=["Python"],
    )
    match = MatchResult(
        scores=MatchScoreBreakdown(overall_score=88),
        strengths=["具备 Python 证据"],
    )
    return BatchScreeningItem(
        index=index,
        company=company,
        job_title=f"虚构岗位{index}",
        location="广州",
        jd_text=f"第 {index} 份完整虚构岗位描述",
        raw_block=f"第 {index} 份完整虚构岗位描述",
        source_url="https://example.com/job",
        jd_fingerprint=str(index) * 64,
        status=BatchJobStatus.COMPLETED,
        job_profile=profile,
        match_result=match,
        match_score=88,
        screening_tier=tier,
        screening_reason="匹配度较高，核心技能覆盖良好。",
    )


def test_save_single_item_as_saved_with_structured_snapshots(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    item = _item()
    assert save_batch_item(repository, item) == "saved"
    saved = repository.list_applications()[0]
    assert saved.status.value == "saved"
    assert saved.job_profile == item.job_profile
    assert saved.match_result == item.match_result
    assert saved.optimization_result is None
    assert saved.source == "manual"
    assert saved.source_url == item.source_url


def test_duplicate_save_is_skipped(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    item = _item()
    assert save_batch_item(repository, item) == "saved"
    assert save_batch_item(repository, item) == "duplicate"
    assert len(repository.list_applications()) == 1


def test_bulk_save_only_saves_priority_items(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    summary = save_priority_items(
        repository,
        [_item(1), _item(2, tier=ScreeningTier.RECOMMENDED)],
    )
    assert summary.saved_count == 1
    assert summary.duplicate_count == 0
    assert len(repository.list_applications()) == 1


class PartiallyFailingRepository:
    def __init__(self, repository):
        self.repository = repository

    def find_duplicate(self, **kwargs):
        return self.repository.find_duplicate(**kwargs)

    def create_application(self, **kwargs):
        if kwargs["company"] == "失败公司":
            raise ApplicationRepositoryError("internal storage detail")
        return self.repository.create_application(**kwargs)


def test_one_bulk_save_failure_does_not_abort_remaining_items(tmp_path) -> None:
    real_repository = ApplicationRepository(tmp_path / "jobpilot.db")
    repository = PartiallyFailingRepository(real_repository)
    summary = save_priority_items(
        repository,
        [_item(1, company="失败公司"), _item(2, company="成功公司")],
    )
    assert summary.saved_count == 1
    assert summary.failed_count == 1
    assert len(real_repository.list_applications()) == 1


def test_bulk_duplicate_is_counted_without_aborting(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    item = _item()
    assert save_batch_item(repository, item) == "saved"
    summary = save_priority_items(repository, [item, _item(2)])
    assert summary.saved_count == 1
    assert summary.duplicate_count == 1
