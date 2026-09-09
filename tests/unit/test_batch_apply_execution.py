from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from jobpilot.browser import ApplyTaskChannel
from jobpilot.models import (
    ApplicationStatus,
    ApplyExecutionStatus,
    ApplyReadiness,
    ApplyResultReport,
    BatchApplyExecution,
    BatchApplyExecutionItem,
    BatchApplyItem,
    BatchApplyPlan,
    JobProfile,
    ScreeningTier,
    ExtensionHeartbeat,
)
from jobpilot.models.apply_execution import utc_now
from jobpilot.services import BatchApplyExecutionService
from jobpilot.storage import ApplicationRepository


def _plan(count=2, *, selected=True, application_id=None) -> BatchApplyPlan:
    items = [
        BatchApplyItem(
            application_id=application_id if index == 1 else None,
            company=f"虚构公司{index}",
            job_title=f"虚构岗位{index}",
            source="boss",
            source_url=f"https://www.zhipin.com/job_detail/apply-fake-{index}.html",
            screening_tier=ScreeningTier.PRIORITY,
            main_reason="虚构推荐理由。",
            main_gaps=[],
            selected=selected,
            apply_readiness=ApplyReadiness.READY,
        )
        for index in range(1, count + 1)
    ]
    return BatchApplyPlan(
        items=items,
        selected_count=sum(item.selected for item in items),
        total_count=len(items),
    )


class Repository:
    def __init__(self, applications=None):
        self.applications = applications or []
        self.updates = []

    def list_applications(self):
        return self.applications

    def update_status(self, application_id, status):
        self.updates.append((application_id, status))
        return next((item for item in self.applications if item.id == application_id), None)


def _execution(count=2):
    return BatchApplyExecution(
        execution_id="execution-test",
        items=[
            BatchApplyExecutionItem(
                task_id=f"task-test-{index}",
                company=f"虚构公司{index}",
                job_title=f"虚构岗位{index}",
                source_url=f"https://www.zhipin.com/job_detail/apply-fake-{index}.html",
                status=ApplyExecutionStatus.PENDING,
            )
            for index in range(1, count + 1)
        ],
    )


def test_only_selected_jobs_are_prepared_and_maximum_is_ten() -> None:
    plan = _plan(12)
    plan.items[1] = plan.items[1].model_copy(update={"selected": False})
    plan.selected_count = 11

    execution = BatchApplyExecutionService(Repository()).prepare_execution(plan)

    assert len(execution.items) == 10
    assert all(item.job_title != "虚构岗位2" for item in execution.items)


def test_execution_keeps_screening_batch_and_contact_plan_identity() -> None:
    plan = _plan(1).model_copy(update={"screening_batch_id": "screening-linked"})

    execution = BatchApplyExecutionService(Repository()).prepare_execution(plan)

    assert execution.screening_batch_id == "screening-linked"
    assert execution.contact_plan_id == plan.contact_plan_id


def test_already_applied_is_skipped_during_second_check(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    existing = repository.create_application(
        company="虚构公司1",
        job_title="虚构岗位1",
        jd_text="完全虚构 JD",
        job_profile=JobProfile(company="虚构公司1", job_title="虚构岗位1"),
        status=ApplicationStatus.APPLIED,
        source="boss",
        source_url="https://www.zhipin.com/job_detail/apply-fake-1.html",
    )

    execution = BatchApplyExecutionService(repository).prepare_execution(
        _plan(1, application_id=existing.id)
    )

    assert execution.items[0].status is ApplyExecutionStatus.SKIPPED
    assert "已建立沟通" in execution.items[0].message


def test_invalid_url_is_skipped_before_extension_execution() -> None:
    plan = _plan(1)
    plan.items[0] = plan.items[0].model_copy(
        update={"source_url": "https://example.com/not-supported"}
    )

    execution = BatchApplyExecutionService(Repository()).prepare_execution(plan)

    assert execution.items[0].status is ApplyExecutionStatus.SKIPPED
    assert "不支持" in execution.items[0].message


@pytest.mark.parametrize(
    "uncertain_status",
    [ApplyExecutionStatus.FAILED, ApplyExecutionStatus.MANUAL_REQUIRED],
)
def test_uncertain_contact_result_can_reconcile_to_contacted(uncertain_status) -> None:
    channel = ApplyTaskChannel()
    execution = _execution(1)
    channel.publish(execution)
    _, task = channel.next_task()
    channel.report(
        ApplyResultReport(
            task_id=task.task_id,
            status=uncertain_status,
            message="初次未能确认。",
        )
    )

    reconciled = channel.reconcile_contact_result(
        ApplyResultReport(
            task_id=task.task_id,
            status=ApplyExecutionStatus.CONTACTED,
            message="延迟核对确认会话已建立。",
            contact_button_clicked=True,
            contact_success_detected=True,
            conversation_found=True,
        )
    )

    assert reconciled.status is ApplyExecutionStatus.CONTACTED
    assert channel.snapshot().finished_at is not None


def test_new_screening_batch_replaces_old_execution_but_keeps_history() -> None:
    channel = ApplyTaskChannel()
    first = _execution(1).model_copy(update={"screening_batch_id": "screening-first"})
    second = _execution(1).model_copy(
        update={"execution_id": "execution-second", "screening_batch_id": "screening-second"}
    )
    channel.publish(first)
    channel.publish(second)

    assert channel.snapshot().execution_id == "execution-second"
    assert [item.execution_id for item in channel.history()] == ["execution-test"]


def test_same_active_screening_batch_cannot_publish_twice() -> None:
    channel = ApplyTaskChannel()
    first = _execution(1).model_copy(update={"screening_batch_id": "screening-same"})
    second = _execution(1).model_copy(
        update={"execution_id": "execution-second", "screening_batch_id": "screening-same"}
    )
    channel.publish(first)
    with pytest.raises(Exception, match="当前筛选批次"):
        channel.publish(second)


def test_contacted_result_updates_repository_without_applied_at(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    existing = repository.create_application(
        company="虚构公司1",
        job_title="虚构岗位1",
        jd_text="完全虚构 JD",
        job_profile=JobProfile(company="虚构公司1", job_title="虚构岗位1"),
        source="boss",
        source_url="https://www.zhipin.com/job_detail/apply-fake-1.html",
    )
    execution = BatchApplyExecutionService(repository).prepare_execution(
        _plan(1, application_id=existing.id)
    )
    execution.items[0] = execution.items[0].model_copy(
        update={"status": ApplyExecutionStatus.CONTACTED}
    )

    synced = BatchApplyExecutionService(repository).sync_contacted_statuses(
        execution, set()
    )
    updated = repository.get_application_by_id(existing.id)

    assert execution.items[0].task_id in synced
    assert updated.status is ApplicationStatus.CONTACTED
    assert updated.applied_at is None


def test_contacted_result_auto_creates_repository_record_when_not_saved(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    execution = BatchApplyExecutionService(repository).prepare_execution(_plan(1))
    execution.items[0] = execution.items[0].model_copy(
        update={
            "status": ApplyExecutionStatus.CONTACTED,
            "contact_button_clicked": True,
            "contact_success_detected": True,
            "conversation_found": True,
        }
    )

    synced = BatchApplyExecutionService(repository).sync_contacted_statuses(execution, set())
    applications = repository.list_applications()

    assert execution.items[0].task_id in synced
    assert len(applications) == 1
    assert applications[0].status is ApplicationStatus.CONTACTED
    assert applications[0].applied_at is None
    assert applications[0].source == "boss"


def test_already_contacted_result_syncs_to_contacted_without_applied_at(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    existing = repository.create_application(
        company="虚构公司1",
        job_title="虚构岗位1",
        jd_text="完全虚构 JD",
        job_profile=JobProfile(company="虚构公司1", job_title="虚构岗位1"),
        source="boss",
        source_url="https://www.zhipin.com/job_detail/apply-fake-1.html",
    )
    execution = BatchApplyExecutionService(repository).prepare_execution(
        _plan(1, application_id=existing.id)
    )
    execution.items[0] = execution.items[0].model_copy(
        update={"status": ApplyExecutionStatus.ALREADY_CONTACTED}
    )

    BatchApplyExecutionService(repository).sync_contacted_statuses(execution, set())
    updated = repository.get_application_by_id(existing.id)

    assert updated.status is ApplicationStatus.CONTACTED
    assert updated.applied_at is None


def test_contacted_report_requires_all_explicit_contact_evidence() -> None:
    with pytest.raises(ValidationError, match="contacted requires explicit"):
        ApplyResultReport(
            task_id="task-evidence-test",
            status=ApplyExecutionStatus.CONTACTED,
            message="缺少明确证据。",
            contact_button_clicked=True,
            contact_success_detected=True,
            conversation_found=False,
        )


def test_already_contacted_report_requires_conversation_evidence() -> None:
    with pytest.raises(ValidationError, match="already_contacted requires"):
        ApplyResultReport(
            task_id="task-existing-test",
            status=ApplyExecutionStatus.ALREADY_CONTACTED,
            message="无法确认既有会话。",
        )


def test_plan_items_explicitly_describe_initial_contact_action() -> None:
    assert _plan(1).items[0].action_type == "initiate_contact"


def test_manual_required_does_not_update_repository() -> None:
    repository = Repository()
    execution = _execution(1)
    execution.items[0] = execution.items[0].model_copy(
        update={"status": ApplyExecutionStatus.MANUAL_REQUIRED, "application_id": 1}
    )

    BatchApplyExecutionService(repository).sync_contacted_statuses(execution, set())

    assert repository.updates == []


def test_one_failure_does_not_abort_next_contact_task() -> None:
    channel = ApplyTaskChannel()
    channel.publish(_execution(2))
    state, first = channel.next_task()
    assert state == "task"
    channel.report(
        ApplyResultReport(
            task_id=first.task_id,
            status=ApplyExecutionStatus.FAILED,
            message="虚构技术错误。",
        )
    )

    state, second = channel.next_task()
    assert state == "task"
    assert second.task_id != first.task_id
    channel.report(
        ApplyResultReport(
            task_id=second.task_id,
            status=ApplyExecutionStatus.CONTACTED,
            message="已建立沟通会话。",
            contact_button_clicked=True,
            contact_success_detected=True,
            conversation_found=True,
        )
    )
    assert channel.next_task() == ("no_pending_task", None)


def test_manual_required_blocks_next_job_until_user_resolves_it() -> None:
    channel = ApplyTaskChannel()
    channel.publish(_execution(2))
    _, first = channel.next_task()
    channel.report(
        ApplyResultReport(
            task_id=first.task_id,
            status=ApplyExecutionStatus.MANUAL_REQUIRED,
            message="出现验证码。",
        )
    )

    assert channel.next_task() == ("manual_required", None)
    channel.resolve_manual(first.task_id, completed=False)
    assert channel.next_task()[0] == "task"


def test_disconnect_pauses_reserved_task_without_retrying_it() -> None:
    channel = ApplyTaskChannel()
    channel.publish(_execution(1))
    _, task = channel.next_task()

    channel.pause_active()

    assert channel.snapshot().items[0].status is ApplyExecutionStatus.PAUSED
    assert channel.next_task() == ("busy", None)
    channel.resolve_manual(task.task_id, completed=False)
    assert channel.next_task() == ("no_pending_task", None)


def test_cancel_stops_all_remaining_tasks() -> None:
    channel = ApplyTaskChannel()
    channel.publish(_execution(3))
    channel.next_task()

    channel.cancel()
    snapshot = channel.snapshot()

    assert snapshot.cancelled is True
    assert snapshot.items[0].status is ApplyExecutionStatus.PAUSED
    assert all(
        item.status is ApplyExecutionStatus.SKIPPED for item in snapshot.items[1:]
    )
    assert channel.next_task() == ("cancelled", None)


def test_apply_task_payload_has_no_jd_resume_or_pii() -> None:
    channel = ApplyTaskChannel()
    channel.publish(_execution(1))
    _, task = channel.next_task()
    payload = task.model_dump(mode="json")
    serialized = str(payload).casefold()

    assert set(payload) == {
        "task_id", "application_id", "company", "job_title", "source_url", "action"
    }
    assert all(term not in serialized for term in ("jd", "resume", "phone", "email"))
    assert payload["action"] == "initiate_contact"


def test_execution_layer_has_no_ai_dependency() -> None:
    service = BatchApplyExecutionService(Repository())
    assert not hasattr(service, "llm_client")
    assert not hasattr(service, "matching_service")


def test_publish_two_exposes_exact_pending_and_processing_counts() -> None:
    channel = ApplyTaskChannel()
    channel.publish(_execution(2))
    diagnostics = channel.diagnostics()
    assert diagnostics.pending_count == 2
    assert diagnostics.processing_count == 0

    channel.next_task()
    diagnostics = channel.diagnostics()
    assert diagnostics.pending_count == 1
    assert diagnostics.processing_count == 1


def test_heartbeat_reports_connected_then_disconnects_after_timeout() -> None:
    channel = ApplyTaskChannel()
    execution = _execution(1)
    channel.publish(execution)
    connected = channel.heartbeat(
        ExtensionHeartbeat(
            extension_connected=True,
            execution_id=execution.execution_id,
        )
    )
    assert connected.extension_connected is True

    channel._last_heartbeat_at = utc_now() - timedelta(seconds=60)
    assert channel.diagnostics().extension_connected is False
