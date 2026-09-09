from __future__ import annotations

from datetime import timedelta

import pytest

from jobpilot.browser import ApplyChannelError, ApplyTaskChannel
from jobpilot.browser.job_identity import canonical_job_key, canonicalize_job_url
from jobpilot.models import (
    ApplicationStatus,
    ApplyExecutionStatus,
    ApplyReadiness,
    ApplyResultReport,
    BatchApplyItem,
    BatchApplyPlan,
    ScreeningTier,
)
from jobpilot.models.apply_execution import utc_now
from jobpilot.services import BatchApplyExecutionService, BatchApplyService
from jobpilot.storage import ApplicationRepository


def _plan(count: int = 20, *, batch_id: str = "screening-reliability") -> BatchApplyPlan:
    items = [
        BatchApplyItem(
            company=f"虚构公司{index}",
            job_title=f"虚构岗位{index}",
            source="boss",
            source_url=f"https://www.zhipin.com/job_detail/reliability-{index}.html?ka=search",
            screening_tier=ScreeningTier.PRIORITY,
            main_reason="虚构稳定性测试。",
            main_gaps=[],
            selected=True,
            apply_readiness=ApplyReadiness.READY,
        )
        for index in range(1, count + 1)
    ]
    selections = {
        canonical_job_key(item.source_url, item.company, item.job_title): True
        for item in items
    }
    return BatchApplyService.create_plan(
        items, selections, screening_batch_id=batch_id
    )


def _contacted(task_id: str) -> ApplyResultReport:
    return ApplyResultReport(
        task_id=task_id,
        status=ApplyExecutionStatus.CONTACTED,
        message="已确认建立虚构会话。",
        contact_button_clicked=True,
        contact_success_detected=True,
        conversation_found=True,
    )


def _already(task_id: str) -> ApplyResultReport:
    return ApplyResultReport(
        task_id=task_id,
        status=ApplyExecutionStatus.ALREADY_CONTACTED,
        message="已确认存在虚构会话。",
        conversation_found=True,
    )


def _expire_processing(channel: ApplyTaskChannel) -> None:
    current = channel._execution
    assert current is not None
    for index, item in enumerate(current.items):
        if item.status is ApplyExecutionStatus.PROCESSING:
            current.items[index] = item.model_copy(
                update={"lease_expires_at": utc_now() - timedelta(seconds=1)}
            )
            return
    raise AssertionError("expected one processing item")


def test_canonical_job_key_removes_tracking_and_host_variants() -> None:
    first = "https://www.zhipin.com/job_detail/abc.html?ka=search#detail"
    second = "https://m.zhipin.com/job_detail/abc.html"
    assert canonicalize_job_url(first) == "https://www.zhipin.com/job_detail/abc.html"
    assert canonical_job_key(first, "A", "B") == canonical_job_key(second, "A", "B")


def test_same_batch_and_selection_produce_stable_plan_and_task_ids() -> None:
    first = _plan(3)
    second = _plan(3)
    assert first.contact_plan_id == second.contact_plan_id

    service = BatchApplyExecutionService(type("Repo", (), {"list_applications": lambda self: []})())
    first_execution = service.prepare_execution(first)
    second_execution = service.prepare_execution(second)
    assert first_execution.execution_id == second_execution.execution_id
    assert [item.task_id for item in first_execution.items] == [item.task_id for item in second_execution.items]


def test_repeated_publish_of_same_plan_is_idempotent() -> None:
    service = BatchApplyExecutionService(type("Repo", (), {"list_applications": lambda self: []})())
    execution = service.prepare_execution(_plan(2))
    channel = ApplyTaskChannel()
    assert channel.publish(execution) is True
    assert channel.publish(execution.model_copy(deep=True)) is False
    assert channel.diagnostics().pending_count == 2


def test_expired_processing_lease_is_reissued_for_reconciliation_first() -> None:
    service = BatchApplyExecutionService(type("Repo", (), {"list_applications": lambda self: []})())
    channel = ApplyTaskChannel()
    channel.publish(service.prepare_execution(_plan(1)))
    _, first = channel.next_task()
    assert first is not None and first.attempt == 1
    _expire_processing(channel)

    state, recovered = channel.next_task()
    assert state == "task"
    assert recovered is not None
    assert recovered.task_id == first.task_id
    assert recovered.attempt == 2
    assert recovered.reconciliation_required is True


def test_manual_completion_cannot_bypass_conversation_evidence() -> None:
    service = BatchApplyExecutionService(type("Repo", (), {"list_applications": lambda self: []})())
    channel = ApplyTaskChannel()
    channel.publish(service.prepare_execution(_plan(1)))
    _, task = channel.next_task()
    channel.report(
        ApplyResultReport(
            task_id=task.task_id,
            status=ApplyExecutionStatus.MANUAL_REQUIRED,
            message="出现虚构安全验证。",
        )
    )
    with pytest.raises(ApplyChannelError, match="不能直接标记成功"):
        channel.resolve_manual(task.task_id, completed=True)

    channel.resume_manual(task.task_id)
    _, recovered = channel.next_task()
    assert recovered.reconciliation_required is True


def test_twenty_job_reliability_simulation_has_no_loss_or_duplicate_sync(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "reliability.db")
    service = BatchApplyExecutionService(repository)
    execution = service.prepare_execution(_plan())
    channel = ApplyTaskChannel()
    channel.publish(execution)

    task_ids: list[str] = []
    greeting_attempts: set[str] = set()
    for index in range(1, 21):
        state, task = channel.next_task()
        assert state == "task"
        assert task is not None
        task_ids.append(task.task_id)

        if index <= 10:
            greeting_attempts.add(task.task_id)
            channel.report(_contacted(task.task_id))
        elif index <= 12:
            channel.report(_already(task.task_id))
        elif index <= 14:  # slow pages remain claimed, then succeed
            greeting_attempts.add(task.task_id)
            channel.report(_contacted(task.task_id))
        elif index <= 17:  # injection, worker-tab, and Bridge interruption recovery
            _expire_processing(channel)
            recovered_state, recovered = channel.next_task()
            assert recovered_state == "task"
            assert recovered.task_id == task.task_id
            assert recovered.reconciliation_required is True
            greeting_attempts.add(task.task_id)
            channel.report(_contacted(task.task_id))
        elif index == 18:
            channel.report(
                ApplyResultReport(
                    task_id=task.task_id,
                    status=ApplyExecutionStatus.MANUAL_REQUIRED,
                    message="虚构验证码，需要人工处理。",
                )
            )
            channel.resolve_manual(task.task_id, completed=False)
        elif index == 19:
            channel.report(
                ApplyResultReport(
                    task_id=task.task_id,
                    status=ApplyExecutionStatus.FAILED,
                    message="虚构页面失败。",
                )
            )
        else:
            channel.report(
                ApplyResultReport(
                    task_id=task.task_id,
                    status=ApplyExecutionStatus.FAILED,
                    message="首次结果不明确。",
                )
            )
            greeting_attempts.add(task.task_id)
            channel.reconcile_contact_result(_contacted(task.task_id))

    snapshot = channel.snapshot()
    assert snapshot is not None
    assert len(task_ids) == len(set(task_ids)) == 20
    assert channel.next_task() == ("no_pending_task", None)
    assert channel.diagnostics().completed_count == 20
    assert len(greeting_attempts) == 16

    first_sync = service.sync_contacted_statuses(snapshot, set())
    second_sync = service.sync_contacted_statuses(snapshot, set())
    applications = repository.list_applications()
    assert len(first_sync) == 18
    assert len(second_sync) == 18
    assert len(applications) == 18
    assert all(item.status is ApplicationStatus.CONTACTED for item in applications)
    assert all(item.applied_at is None for item in applications)


def test_extension_reliability_contracts_are_present() -> None:
    background = ("extension/background.js")
    content = ("extension/content.js")
    background_source = open(background, encoding="utf-8").read()
    content_source = open(content, encoding="utf-8").read()
    for marker in (
        "RESULT_REPORT_RETRIES",
        "pending_report",
        "lease_expires_at",
        "reconciliation_required",
        "chrome.tabs.onRemoved",
        "worker_tab_id",
    ):
        assert marker in background_source
    for marker in (
        "capture_event_id",
        "canonical_job_key",
        "capture_pending",
        "capture_failed",
    ):
        assert marker in content_source
