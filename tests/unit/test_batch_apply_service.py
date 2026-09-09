from datetime import datetime, timezone

import pytest

from jobpilot.browser import (
    ApplyMode,
    ContactMode,
    ResumeSubmissionMode,
    resolve_site_capability,
)
from jobpilot.models import (
    ApplicationStatus,
    ApplyReadiness,
    AssessmentConfidence,
    BatchApplyItem,
    BatchJobInput,
    CandidateProfile,
    FastRelevance,
    FastScreeningAssessment,
    FastScreeningItem,
    FastScreeningPipelineResult,
    JobApplication,
    LocalPreScreenResult,
    LocalScreeningDecision,
    ScreeningMetrics,
    ScreeningTier,
    ScreeningTiming,
)
from jobpilot.services import (
    BatchApplyService,
    apply_item_identity,
    calculate_apply_readiness,
)
from jobpilot.ui.state import _sync_candidate_profile_state, clear_batch_apply_state


def _screening_item(
    index: int,
    tier: ScreeningTier,
    *,
    url: str | None = None,
    risks: list[str] | None = None,
    company: str | None = None,
    title: str | None = None,
    deep: bool = False,
) -> FastScreeningItem:
    job = BatchJobInput(
        index=index,
        company=company or f"虚构公司{index}",
        job_title=title or f"虚构岗位{index}",
        source_url=url if url is not None else f"https://www.zhipin.com/job_detail/fake-{index}.html",
        jd_text=f"第 {index} 份虚构 JD，仅用于本地测试且不会发送给任何服务。",
        raw_block=f"第 {index} 份虚构 JD，仅用于本地测试且不会发送给任何服务。",
    )
    assessment = FastScreeningAssessment(
        job_title=job.job_title,
        core_required_skills=["Python"],
        matched_core_skills=["Python"],
        missing_core_skills=["Docker"] if tier is ScreeningTier.CAUTION else [],
        hard_requirement_risks=risks or [],
        relevance=(
            FastRelevance.HIGH if tier is ScreeningTier.PRIORITY
            else FastRelevance.MEDIUM if tier in {ScreeningTier.RECOMMENDED, ScreeningTier.CAUTION}
            else FastRelevance.LOW
        ),
        confidence=AssessmentConfidence.HIGH,
        reason="虚构的筛选理由。",
    )
    return FastScreeningItem(
        job_input=job,
        local_result=LocalPreScreenResult(
            decision=LocalScreeningDecision.PASS,
            reason="本地规则通过。",
            hard_requirement_risks=[],
        ),
        assessment=assessment,
        screening_tier=tier,
        screening_reason="虚构的主要原因。",
        core_gaps=assessment.missing_core_skills,
        deep_match=False,
    )


def _result(items) -> FastScreeningPipelineResult:
    return FastScreeningPipelineResult(
        items=items,
        metrics=ScreeningMetrics(
            total_jobs=len(items), local_filtered=0, flash_screened=len(items),
            pro_analyzed=0, cache_hits=0, flash_provider_calls=0, pro_provider_calls=0,
            timing=ScreeningTiming(
                local_seconds=0, flash_seconds=0, pro_seconds=0,
                total_elapsed_seconds=0, avg_seconds_per_job=0,
            ),
        ),
    )


class Repository:
    def __init__(self, applications=None):
        self.applications = applications or []

    def list_applications(self):
        return self.applications


def _application(status: ApplicationStatus, *, app_id=1, url=None) -> JobApplication:
    now = datetime.now(timezone.utc)
    return JobApplication(
        id=app_id,
        company="虚构公司1",
        job_title="虚构岗位1",
        status=status,
        jd_fingerprint="a" * 64,
        job_profile_json='{"job_title":"虚构岗位1","company":"虚构公司1"}',
        source="boss",
        source_url=url or "https://www.zhipin.com/job_detail/fake-1.html",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize(
    ("tier", "selected"),
    [
        (ScreeningTier.PRIORITY, True),
        (ScreeningTier.RECOMMENDED, True),
        (ScreeningTier.CAUTION, False),
        (ScreeningTier.LOW_PRIORITY, False),
    ],
)
def test_default_selection_rules(tier, selected) -> None:
    item = BatchApplyService(Repository()).build_selection_items(
        _result([_screening_item(1, tier)])
    )[0]
    assert item.selected is selected


def test_user_can_cancel_or_select_caution_and_plan_count_is_correct() -> None:
    service = BatchApplyService(Repository())
    items = service.build_selection_items(
        _result([
            _screening_item(1, ScreeningTier.PRIORITY),
            _screening_item(2, ScreeningTier.CAUTION),
        ])
    )
    selections = {
        apply_item_identity(items[0]): False,
        apply_item_identity(items[1]): True,
    }
    plan = service.create_plan(items, selections)
    assert [item.selected for item in plan.items] == [False, True]
    assert plan.selected_count == 1


def test_invalid_url_and_unknown_source_are_unsupported() -> None:
    assert calculate_apply_readiness(
        source="boss", source_url="not-a-url", tier=ScreeningTier.PRIORITY,
        hard_requirement_risks=[],
    ) is ApplyReadiness.UNSUPPORTED
    assert calculate_apply_readiness(
        source="unknown", source_url="https://example.com/job", tier=ScreeningTier.PRIORITY,
        hard_requirement_risks=[],
    ) is ApplyReadiness.UNSUPPORTED


def test_priority_boss_url_is_ready() -> None:
    assert calculate_apply_readiness(
        source="boss", source_url="https://www.zhipin.com/job_detail/fake.html",
        tier=ScreeningTier.PRIORITY, hard_requirement_risks=[],
    ) is ApplyReadiness.READY


def test_caution_or_hard_requirement_is_review_required() -> None:
    boss = "https://www.zhipin.com/job_detail/fake.html"
    assert calculate_apply_readiness(
        source="boss", source_url=boss, tier=ScreeningTier.CAUTION,
        hard_requirement_risks=[],
    ) is ApplyReadiness.REVIEW_REQUIRED
    assert calculate_apply_readiness(
        source="boss", source_url=boss, tier=ScreeningTier.PRIORITY,
        hard_requirement_risks=["学历硬门槛"],
    ) is ApplyReadiness.REVIEW_REQUIRED


@pytest.mark.parametrize(
    "status",
    [
        ApplicationStatus.APPLIED,
        ApplicationStatus.CONTACTED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFER,
        ApplicationStatus.CLOSED,
    ],
)
def test_already_progressed_application_is_excluded(status) -> None:
    item = BatchApplyService(Repository([_application(status)])).build_selection_items(
        _result([_screening_item(1, ScreeningTier.PRIORITY)])
    )[0]
    assert item.selected is False
    assert item.application_id == 1
    assert item.exclusion_reason is not None


def test_saved_application_is_allowed() -> None:
    item = BatchApplyService(
        Repository([_application(ApplicationStatus.SAVED)])
    ).build_selection_items(_result([_screening_item(1, ScreeningTier.PRIORITY)]))[0]
    assert item.selected is True
    assert item.application_id == 1
    assert item.exclusion_reason is None


def test_duplicate_screening_job_is_excluded() -> None:
    duplicate = _screening_item(
        2, ScreeningTier.RECOMMENDED,
        url="https://www.zhipin.com/job_detail/fake-1.html",
    )
    items = BatchApplyService(Repository()).build_selection_items(
        _result([_screening_item(1, ScreeningTier.PRIORITY), duplicate])
    )
    assert items[0].selected is True
    assert items[1].selected is False
    assert items[1].exclusion_reason == "重复岗位，已排除。"


def test_plan_has_no_jd_resume_or_pii_fields() -> None:
    item = BatchApplyService(Repository()).build_selection_items(
        _result([_screening_item(1, ScreeningTier.PRIORITY)])
    )[0]
    plan = BatchApplyService.create_plan([item], {apply_item_identity(item): True})
    payload = plan.model_dump(mode="json")
    serialized = str(payload)
    assert "jd_text" not in serialized
    assert "resume" not in serialized.casefold()
    assert "phone" not in serialized.casefold()
    assert "email" not in serialized.casefold()
    assert set(payload["items"][0]) == set(BatchApplyItem.model_fields)


def test_unsupported_item_cannot_be_forced_selected() -> None:
    item = BatchApplyService(Repository()).build_selection_items(
        _result([_screening_item(1, ScreeningTier.PRIORITY, url="")])
    )[0]
    plan = BatchApplyService.create_plan([item], {apply_item_identity(item): True})
    assert plan.selected_count == 0


def test_site_contact_and_resume_capabilities_are_explicit() -> None:
    boss = resolve_site_capability("boss")
    assert boss.contact_mode is ContactMode.EXTENSION
    assert boss.resume_submission is ResumeSubmissionMode.MANUAL
    assert boss.apply_mode is ApplyMode.UNSUPPORTED
    assert resolve_site_capability("generic_playwright").apply_mode is ApplyMode.UNSUPPORTED
    assert resolve_site_capability("unknown").apply_mode is ApplyMode.UNSUPPORTED


def test_service_has_no_ai_dependency_or_calls() -> None:
    service = BatchApplyService(Repository())
    service.build_selection_items(_result([_screening_item(1, ScreeningTier.PRIORITY)]))
    assert not hasattr(service, "llm_client")
    assert not hasattr(service, "matching_service")


def test_resume_change_clears_apply_plan_and_checkbox_state() -> None:
    state = {
        "candidate_profile_fingerprint": "old-resume",
        "batch_apply_result_fingerprint": "old-result",
        "batch_apply_selections": {"job": True},
        "batch_apply_plan": object(),
        "batch_apply_feedback": "old feedback",
        "batch_apply_checkbox_fake": True,
    }

    _sync_candidate_profile_state(state, "new-resume")

    assert state["batch_apply_plan"] is None
    assert state["batch_apply_selections"] == {}
    assert "batch_apply_checkbox_fake" not in state


def test_clear_apply_state_does_not_delete_quick_action_widget_keys() -> None:
    state = {
        "batch_apply_select_priority": True,
        "batch_apply_checkbox_fake": True,
    }

    clear_batch_apply_state(state)

    assert state["batch_apply_select_priority"] is True
    assert "batch_apply_checkbox_fake" not in state
