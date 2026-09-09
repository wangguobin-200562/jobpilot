"""Thread-safe, fail-safe task channel shared by Streamlit and its localhost bridge."""

from __future__ import annotations

import threading
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
    utc_now,
)


HEARTBEAT_TIMEOUT_SECONDS = 45


@dataclass(frozen=True, slots=True)
class ApplyChannelDiagnostics:
    execution_id: str | None
    pending_count: int
    processing_count: int
    completed_count: int
    extension_connected: bool
    last_heartbeat_at: datetime | None
    last_task_request_at: datetime | None


class ApplyChannelError(RuntimeError):
    pass


class ApplyTaskChannel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._execution: BatchApplyExecution | None = None
        self._history: list[BatchApplyExecution] = []
        self._last_heartbeat_at: datetime | None = None
        self._last_task_request_at: datetime | None = None

    def publish(self, execution: BatchApplyExecution) -> None:
        with self._lock:
            if self._execution and not self._is_complete(self._execution):
                same_batch = (
                    self._execution.screening_batch_id is not None
                    and self._execution.screening_batch_id == execution.screening_batch_id
                )
                if same_batch:
                    raise ApplyChannelError("当前筛选批次已有沟通任务正在进行。")
            if self._execution:
                self._history.append(self._execution.model_copy(deep=True))
                self._history = self._history[-20:]
            self._execution = execution.model_copy(deep=True)

    def history(self) -> list[BatchApplyExecution]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._history]

    def snapshot(self) -> BatchApplyExecution | None:
        with self._lock:
            return self._execution.model_copy(deep=True) if self._execution else None

    def heartbeat(self, heartbeat: ExtensionHeartbeat) -> ApplyChannelDiagnostics:
        with self._lock:
            execution_id = self._execution.execution_id if self._execution else None
            if heartbeat.execution_id and heartbeat.execution_id != execution_id:
                raise ApplyChannelError("心跳 execution_id 与当前批次不匹配。")
            self._last_heartbeat_at = utc_now()
            return self._diagnostics_unlocked()

    def diagnostics(self) -> ApplyChannelDiagnostics:
        with self._lock:
            return self._diagnostics_unlocked()

    def _diagnostics_unlocked(self) -> ApplyChannelDiagnostics:
        execution = self._execution
        items = execution.items if execution else []
        connected = bool(
            self._last_heartbeat_at
            and utc_now() - self._last_heartbeat_at
            <= timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
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
        )

    @staticmethod
    def _is_complete(execution: BatchApplyExecution) -> bool:
        return all(item.status in TERMINAL_APPLY_STATUSES for item in execution.items)

    def next_task(self) -> tuple[str, ApplyTaskPayload | None]:
        """Atomically reserve one task. Reserved work is never silently retried."""
        with self._lock:
            self._last_task_request_at = utc_now()
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
                        "message": "浏览器扩展正在建立沟通。",
                        "started_at": utc_now(),
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
                    }
                )
                execution.items[index] = updated
                self._finish_if_terminal(execution)
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
            }
        )
        execution.items[index] = updated
        execution.finished_at = None
        self._finish_if_terminal(execution)
        return updated.model_copy(deep=True)

    def resolve_manual(self, task_id: str, *, completed: bool) -> None:
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
                            "status": (
                                ApplyExecutionStatus.CONTACTED
                                if completed
                                else ApplyExecutionStatus.SKIPPED
                            ),
                            "message": (
                                "用户确认已人工完成沟通。"
                                if completed
                                else "用户选择跳过该岗位。"
                            ),
                            "finished_at": utc_now(),
                        }
                    )
                    self._finish_if_terminal(execution)
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
                            "status": ApplyExecutionStatus.SKIPPED,
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
