"""Thread-safe, fail-safe task channel shared by Streamlit and its localhost bridge."""

from __future__ import annotations

import threading
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from jobpilot.models.apply_execution import (
    ApplyAction,
    ApplyExecutionStatus,
    ApplyResultReport,
    ApplyTaskPayload,
    BatchApplyExecution,
    BatchApplyExecutionItem,
    ExtensionHeartbeat,
    TERMINAL_APPLY_STATUSES,
    is_legal_apply_transition,
    utc_now,
)
from jobpilot.browser.job_identity import canonical_job_key, safe_job_key


HEARTBEAT_TIMEOUT_SECONDS = 45
TASK_LEASE_SECONDS = 75
MAX_TASK_ATTEMPTS = 3

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApplyChannelDiagnostics:
    execution_id: str | None
    pending_count: int
    processing_count: int
    completed_count: int
    extension_connected: bool
    last_heartbeat_at: datetime | None
    last_task_request_at: datetime | None
    contact_plan_id: str | None = None
    screening_batch_id: str | None = None
    worker_tab_id: int | None = None
    heartbeat_age_seconds: float | None = None


class ApplyChannelError(RuntimeError):
    pass


class ApplyTaskChannel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._execution: BatchApplyExecution | None = None
        self._history: list[BatchApplyExecution] = []
        self._last_heartbeat_at: datetime | None = None
        self._last_task_request_at: datetime | None = None
        self._worker_tab_id: int | None = None

    def publish(self, execution: BatchApplyExecution) -> bool:
        with self._lock:
            known = [self._execution, *self._history]
            if any(
                item is not None
                and (
                    item.execution_id == execution.execution_id
                    or (
                        item.contact_plan_id is not None
                        and item.contact_plan_id == execution.contact_plan_id
                    )
                )
                for item in known
            ):
                return False
            if self._execution and not self._is_complete(self._execution):
                if (
                    self._execution.screening_batch_id is not None
                    and self._execution.screening_batch_id == execution.screening_batch_id
                ):
                    raise ApplyChannelError("当前筛选批次已有沟通任务正在进行。")
                raise ApplyChannelError("已有沟通任务正在进行，请先完成或停止当前批次。")
            if self._execution:
                self._history.append(self._execution.model_copy(deep=True))
                self._history = self._history[-20:]
            self._execution = execution.model_copy(deep=True)
            logger.info(
                "apply_event=published batch_id=%s plan_id=%s execution_id=%s task_state=pending count=%s",
                execution.screening_batch_id,
                execution.contact_plan_id,
                execution.execution_id,
                len(execution.items),
            )
            return True

    def history(self) -> list[BatchApplyExecution]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._history]

    def snapshot(self) -> BatchApplyExecution | None:
        with self._lock:
            return self._execution.model_copy(deep=True) if self._execution else None

    def heartbeat(self, heartbeat: ExtensionHeartbeat) -> ApplyChannelDiagnostics:
        with self._lock:
            self._recover_expired_lease_unlocked()
            execution_id = self._execution.execution_id if self._execution else None
            if heartbeat.execution_id and heartbeat.execution_id != execution_id:
                logger.info(
                    "apply_event=stale_heartbeat execution_id=%s current_execution_id=%s",
                    heartbeat.execution_id,
                    execution_id,
                )
            self._last_heartbeat_at = utc_now()
            self._worker_tab_id = heartbeat.worker_tab_id
            if (
                heartbeat.task_id
                and self._execution
                and heartbeat.execution_id == execution_id
            ):
                for index, item in enumerate(self._execution.items):
                    if (
                        item.task_id == heartbeat.task_id
                        and item.status is ApplyExecutionStatus.PROCESSING
                    ):
                        self._execution.items[index] = item.model_copy(
                            update={
                                "lease_expires_at": utc_now()
                                + timedelta(seconds=TASK_LEASE_SECONDS)
                            }
                        )
                        break
            return self._diagnostics_unlocked()

    def diagnostics(self) -> ApplyChannelDiagnostics:
        with self._lock:
            self._recover_expired_lease_unlocked()
            return self._diagnostics_unlocked()

    def _diagnostics_unlocked(self) -> ApplyChannelDiagnostics:
        execution = self._execution
        items = execution.items if execution else []
        heartbeat_age = (
            (utc_now() - self._last_heartbeat_at).total_seconds()
            if self._last_heartbeat_at
            else None
        )
        connected = bool(
            self._last_heartbeat_at
            and heartbeat_age is not None
            and heartbeat_age <= HEARTBEAT_TIMEOUT_SECONDS
        )
        return ApplyChannelDiagnostics(
            execution_id=execution.execution_id if execution else None,
            pending_count=sum(
                item.status is ApplyExecutionStatus.PENDING for item in items
            ),
            processing_count=sum(
                item.status is ApplyExecutionStatus.PROCESSING for item in items
            ),
            completed_count=sum(item.status in TERMINAL_APPLY_STATUSES for item in items),
            extension_connected=connected,
            last_heartbeat_at=self._last_heartbeat_at,
            last_task_request_at=self._last_task_request_at,
            contact_plan_id=execution.contact_plan_id if execution else None,
            screening_batch_id=execution.screening_batch_id if execution else None,
            worker_tab_id=self._worker_tab_id,
            heartbeat_age_seconds=heartbeat_age,
        )

    def _recover_expired_lease_unlocked(self) -> None:
        execution = self._execution
        if execution is None or execution.cancelled:
            return
        now = utc_now()
        for index, item in enumerate(execution.items):
            if (
                item.status is ApplyExecutionStatus.PROCESSING
                and item.lease_expires_at is not None
                and item.lease_expires_at <= now
            ):
                next_status = (
                    ApplyExecutionStatus.PENDING
                    if item.attempt < MAX_TASK_ATTEMPTS
                    else ApplyExecutionStatus.MANUAL_REQUIRED
                )
                execution.items[index] = item.model_copy(
                    update={
                        "status": next_status,
                        "message": (
                            "执行租约已过期；重新领取前将先核对现有会话。"
                            if next_status is ApplyExecutionStatus.PENDING
                            else "多次执行中断，需要人工确认岗位当前状态。"
                        ),
                        "lease_expires_at": None,
                        "reconciliation_required": True,
                    }
                )
                logger.warning(
                    "apply_event=lease_expired batch_id=%s plan_id=%s execution_id=%s job_key=%s task_state=%s attempt=%s worker_tab_id=%s reconciliation_result=pending",
                    execution.screening_batch_id,
                    execution.contact_plan_id,
                    execution.execution_id,
                    safe_job_key(canonical_job_key(item.source_url, item.company, item.job_title)),
                    next_status.value,
                    item.attempt,
                    self._worker_tab_id,
                )

    @staticmethod
    def _is_complete(execution: BatchApplyExecution) -> bool:
        return all(item.status in TERMINAL_APPLY_STATUSES for item in execution.items)

    def next_task(self) -> tuple[str, ApplyTaskPayload | None]:
        """Atomically reserve one task. Reserved work is never silently retried."""
        with self._lock:
            self._last_task_request_at = utc_now()
            self._recover_expired_lease_unlocked()
            execution = self._execution
            if execution is None:
                return "no_pending_task", None
            if execution.cancelled:
                return "cancelled", None
            if any(
                item.status in {
                    ApplyExecutionStatus.PROCESSING,
                    ApplyExecutionStatus.PAUSED,
                    ApplyExecutionStatus.MANUAL_REQUIRED,
                }
                for item in execution.items
            ):
                state = (
                    "manual_required"
                    if any(item.status is ApplyExecutionStatus.MANUAL_REQUIRED for item in execution.items)
                    else "busy"
                )
                return state, None
            for index, item in enumerate(execution.items):
                if item.status is not ApplyExecutionStatus.PENDING:
                    continue
                updated = item.model_copy(
                    update={
                        "status": ApplyExecutionStatus.PROCESSING,
                        "message": (
                            "浏览器扩展正在核对中断任务。"
                            if item.reconciliation_required
                            else "浏览器扩展正在建立沟通。"
                        ),
                        "started_at": utc_now(),
                        "attempt": item.attempt + 1,
                        "lease_expires_at": utc_now()
                        + timedelta(seconds=TASK_LEASE_SECONDS),
                    }
                )
                execution.items[index] = updated
                return "task", ApplyTaskPayload(
                    task_id=updated.task_id,
                    application_id=updated.application_id,
                    company=updated.company,
                    job_title=updated.job_title,
                    source_url=updated.source_url,
                    action=updated.action,
                    attempt=updated.attempt,
                    lease_expires_at=updated.lease_expires_at,
                    reconciliation_required=updated.reconciliation_required,
                )
            self._finish_if_terminal(execution)
            return "no_pending_task", None

    def report(self, report: ApplyResultReport) -> BatchApplyExecutionItem:
        with self._lock:
            execution = self._execution
            if execution is None:
                raise ApplyChannelError("沟通批次不存在。")
            for index, item in enumerate(execution.items):
                if item.task_id != report.task_id:
                    continue
                if (
                    item.status is ApplyExecutionStatus.FAILED
                    and report.status
                    in {
                        ApplyExecutionStatus.CONTACTED,
                        ApplyExecutionStatus.ALREADY_CONTACTED,
                    }
                ):
                    return self._reconcile_unlocked(execution, index, item, report)
                if item.status in TERMINAL_APPLY_STATUSES:
                    return item.model_copy(deep=True)
                if item.status not in {
                    ApplyExecutionStatus.PROCESSING,
                    ApplyExecutionStatus.PAUSED,
                    ApplyExecutionStatus.MANUAL_REQUIRED,
                }:
                    raise ApplyChannelError("任务尚未进入可回报状态。")
                if not is_legal_apply_transition(item.status, report.status):
                    raise ApplyChannelError("任务状态转换不合法。")
                if (
                    item.action is ApplyAction.INITIATE_CONTACT
                    and report.status is ApplyExecutionStatus.APPLIED
                ):
                    raise ApplyChannelError("BOSS 初始沟通不能回报为已投递简历。")
                finished_at = (
                    utc_now() if report.status in TERMINAL_APPLY_STATUSES else None
                )
                updated = item.model_copy(
                    update={
                        "status": report.status,
                        "message": report.message,
                        "finished_at": finished_at,
                        "contact_button_clicked": report.contact_button_clicked,
                        "contact_success_detected": report.contact_success_detected,
                        "conversation_found": report.conversation_found,
                        "lease_expires_at": None,
                        "reconciliation_required": False,
                    }
                )
                execution.items[index] = updated
                self._finish_if_terminal(execution)
                logger.info(
                    "apply_event=result batch_id=%s plan_id=%s execution_id=%s job_key=%s task_state=%s attempt=%s worker_tab_id=%s reconciliation_result=%s repository_sync_result=pending",
                    execution.screening_batch_id,
                    execution.contact_plan_id,
                    execution.execution_id,
                    safe_job_key(canonical_job_key(item.source_url, item.company, item.job_title)),
                    updated.status.value,
                    updated.attempt,
                    self._worker_tab_id,
                    "confirmed" if updated.status in {ApplyExecutionStatus.CONTACTED, ApplyExecutionStatus.ALREADY_CONTACTED} else "not_applicable",
                )
                return updated.model_copy(deep=True)
            raise ApplyChannelError("未知沟通任务。")

    def reconcile_contact_result(
        self, report: ApplyResultReport
    ) -> BatchApplyExecutionItem:
        """Correct an uncertain/failed result when explicit BOSS evidence arrives."""
        if report.status not in {
            ApplyExecutionStatus.CONTACTED,
            ApplyExecutionStatus.ALREADY_CONTACTED,
        }:
            raise ApplyChannelError("沟通核对只接受明确的会话成功结果。")
        with self._lock:
            execution = self._execution
            if execution is None:
                raise ApplyChannelError("沟通批次不存在。")
            for index, item in enumerate(execution.items):
                if item.task_id != report.task_id:
                    continue
                if item.status in {
                    ApplyExecutionStatus.PROCESSING,
                    ApplyExecutionStatus.PAUSED,
                    ApplyExecutionStatus.MANUAL_REQUIRED,
                    ApplyExecutionStatus.FAILED,
                }:
                    return self._reconcile_unlocked(execution, index, item, report)
                return item.model_copy(deep=True)
            raise ApplyChannelError("未知沟通任务。")

    def _reconcile_unlocked(
        self,
        execution: BatchApplyExecution,
        index: int,
        item: BatchApplyExecutionItem,
        report: ApplyResultReport,
    ) -> BatchApplyExecutionItem:
        updated = item.model_copy(
            update={
                "status": report.status,
                "message": report.message,
                "finished_at": utc_now(),
                "contact_button_clicked": report.contact_button_clicked,
                "contact_success_detected": report.contact_success_detected,
                "conversation_found": report.conversation_found,
                "lease_expires_at": None,
                "reconciliation_required": False,
            }
        )
        execution.items[index] = updated
        execution.finished_at = None
        self._finish_if_terminal(execution)
        logger.info(
            "apply_event=reconciled batch_id=%s plan_id=%s execution_id=%s job_key=%s task_state=%s attempt=%s worker_tab_id=%s reconciliation_result=confirmed repository_sync_result=pending",
            execution.screening_batch_id,
            execution.contact_plan_id,
            execution.execution_id,
            safe_job_key(canonical_job_key(item.source_url, item.company, item.job_title)),
            updated.status.value,
            updated.attempt,
            self._worker_tab_id,
        )
        return updated.model_copy(deep=True)

    def resolve_manual(self, task_id: str, *, completed: bool) -> None:
        if completed:
            raise ApplyChannelError("人工操作不能直接标记成功，请通过会话证据核对。")
        with self._lock:
            execution = self._execution
            if execution is None:
                raise ApplyChannelError("沟通批次不存在。")
            for index, item in enumerate(execution.items):
                if item.task_id == task_id:
                    if item.status not in {
                        ApplyExecutionStatus.MANUAL_REQUIRED,
                        ApplyExecutionStatus.PAUSED,
                    }:
                        raise ApplyChannelError("该任务不在人工处理或安全暂停状态。")
                    execution.items[index] = item.model_copy(
                        update={
                            "status": ApplyExecutionStatus.SKIPPED,
                            "message": "用户选择跳过该岗位。",
                            "finished_at": utc_now(),
                            "lease_expires_at": None,
                        }
                    )
                    self._finish_if_terminal(execution)
                    return
            raise ApplyChannelError("未知沟通任务。")

    def resume_manual(self, task_id: str) -> None:
        """Resume only through a reconciliation-first retry."""
        with self._lock:
            execution = self._execution
            if execution is None:
                raise ApplyChannelError("沟通批次不存在。")
            for index, item in enumerate(execution.items):
                if item.task_id != task_id:
                    continue
                if item.status not in {
                    ApplyExecutionStatus.MANUAL_REQUIRED,
                    ApplyExecutionStatus.PAUSED,
                }:
                    raise ApplyChannelError("该任务不在可继续状态。")
                execution.items[index] = item.model_copy(
                    update={
                        "status": ApplyExecutionStatus.PENDING,
                        "message": "等待扩展先核对现有会话，再继续任务。",
                        "lease_expires_at": None,
                        "reconciliation_required": True,
                    }
                )
                execution.finished_at = None
                return
            raise ApplyChannelError("未知沟通任务。")

    def pause_active(self, message: str = "扩展连接中断，沟通任务已安全暂停。") -> None:
        with self._lock:
            if not self._execution:
                return
            for index, item in enumerate(self._execution.items):
                if item.status is ApplyExecutionStatus.PROCESSING:
                    self._execution.items[index] = item.model_copy(
                        update={"status": ApplyExecutionStatus.PAUSED, "message": message}
                    )

    def cancel(self) -> None:
        with self._lock:
            if not self._execution:
                return
            self._execution.cancelled = True
            now = utc_now()
            for index, item in enumerate(self._execution.items):
                if item.status is ApplyExecutionStatus.PENDING:
                    self._execution.items[index] = item.model_copy(
                        update={
                            "status": ApplyExecutionStatus.CANCELLED,
                            "message": "用户停止本次沟通，未执行。",
                            "finished_at": now,
                        }
                    )
                elif item.status is ApplyExecutionStatus.PROCESSING:
                    self._execution.items[index] = item.model_copy(
                        update={
                            "status": ApplyExecutionStatus.PAUSED,
                            "message": "用户已停止批次；当前任务等待安全确认。",
                        }
                    )
            self._finish_if_terminal(self._execution)

    @staticmethod
    def _finish_if_terminal(execution: BatchApplyExecution) -> None:
        if all(item.status in TERMINAL_APPLY_STATUSES for item in execution.items):
            execution.finished_at = execution.finished_at or utc_now()
