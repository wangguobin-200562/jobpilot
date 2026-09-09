"""Deterministic preparation and repository synchronization for BOSS contact."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
import logging
from uuid import uuid4

from jobpilot.models import ApplicationStatus, BatchApplyPlan, JobApplication, JobProfile
from jobpilot.storage import DuplicateApplicationError
from jobpilot.models.apply_execution import (
    ApplyAction,
    ApplyExecutionStatus,
    BatchApplyExecution,
    BatchApplyExecutionItem,
    utc_now,
)
from jobpilot.services.batch_apply_service import EXCLUDED_APPLICATION_STATUSES
from jobpilot.services.batch_apply_service import infer_job_source, valid_source_url
from jobpilot.browser.job_identity import canonical_job_key, canonicalize_job_url
from jobpilot.browser.job_identity import safe_job_key


MAX_EXECUTION_JOBS = 20
logger = logging.getLogger(__name__)


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("\0".join(values).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def create_safe_handoff_execution() -> BatchApplyExecution:
    """One non-application task restricted by schema to example.com."""
    return BatchApplyExecution(
        execution_id=f"safe-execution-{uuid4().hex}",
        items=[
            BatchApplyExecutionItem(
                task_id=f"safe-task-{uuid4().hex}",
                company="JobPilot 安全测试",
                job_title="虚构任务交接验证",
                source_url="https://example.com/",
                action=ApplyAction.SAFE_HANDOFF,
                status=ApplyExecutionStatus.PENDING,
                message="等待 Extension 完成安全任务交接测试。",
            )
        ],
    )


class BatchApplyExecutionService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def _applications(self) -> list[JobApplication]:
        return self.repository.list_applications()

    @staticmethod
    def _find_existing(item, applications: Sequence[JobApplication]):
        if item.application_id:
            for application in applications:
                if application.id == item.application_id:
                    return application
        url = canonicalize_job_url(item.source_url)
        for application in applications:
            if url and canonicalize_job_url(application.source_url) == url:
                return application
            if (
                application.company.strip().casefold() == item.company.strip().casefold()
                and application.job_title.strip().casefold()
                == item.job_title.strip().casefold()
            ):
                return application
        return None

    def prepare_execution(self, plan: BatchApplyPlan) -> BatchApplyExecution:
        applications = self._applications()
        confirmed = [item for item in plan.items if item.selected][:MAX_EXECUTION_JOBS]
        if not confirmed:
            raise ValueError("当前计划没有可执行的已确认岗位。")
        execution_items: list[BatchApplyExecutionItem] = []
        seen: set[str] = set()
        for item in confirmed:
            existing = self._find_existing(item, applications)
            already_progressed = (
                existing is not None
                and existing.status in EXCLUDED_APPLICATION_STATUSES
            )
            source_url = canonicalize_job_url(item.source_url) or item.source_url or ""
            identity = canonical_job_key(source_url, item.company, item.job_title)
            duplicate = identity in seen
            seen.add(identity)
            unsupported = (
                not valid_source_url(source_url)
                or infer_job_source(source_url) != "boss"
            )
            status = (
                ApplyExecutionStatus.SKIPPED
                if already_progressed or duplicate or unsupported
                else ApplyExecutionStatus.PENDING
            )
            message = "等待浏览器扩展建立沟通。"
            if already_progressed:
                message = "该岗位已建立沟通或已进入后续流程。"
            elif duplicate:
                message = "重复岗位，执行前已跳过。"
            elif unsupported:
                message = "岗位链接无效或当前来源不支持初始沟通。"
            execution_items.append(
                BatchApplyExecutionItem(
                    task_id=_stable_id("apply", plan.contact_plan_id, identity),
                    application_id=existing.id if existing else item.application_id,
                    company=item.company,
                    job_title=item.job_title,
                    source_url=source_url,
                    location=item.location,
                    screening_tier=item.screening_tier.value,
                    match_score=item.match_score,
                    action=ApplyAction.INITIATE_CONTACT,
                    status=status,
                    message=message,
                    finished_at=(
                        utc_now() if already_progressed else None
                    ),
                )
            )
        execution = BatchApplyExecution(
            execution_id=_stable_id("execution", plan.contact_plan_id),
            contact_plan_id=plan.contact_plan_id,
            screening_batch_id=plan.screening_batch_id,
            items=execution_items,
        )
        if all(item.status is ApplyExecutionStatus.SKIPPED for item in execution.items):
            execution.finished_at = utc_now()
        return execution

    def sync_contacted_statuses(
        self, execution: BatchApplyExecution, synced_task_ids: set[str]
    ) -> set[str]:
        synced = set(synced_task_ids)
        for item in execution.items:
            if (
                item.status
                not in {
                    ApplyExecutionStatus.CONTACTED,
                    ApplyExecutionStatus.ALREADY_CONTACTED,
                }
                or item.task_id in synced
            ):
                continue
            if item.application_id is None:
                existing = self._find_existing(item, self._applications())
                if existing is None:
                    try:
                        existing = self.repository.create_application(
                            company=item.company,
                            job_title=item.job_title,
                            location=item.location,
                            jd_text="",
                            job_profile=JobProfile(
                                company=item.company,
                                job_title=item.job_title,
                                location=item.location,
                            ),
                            status=ApplicationStatus.CONTACTED,
                            match_score=item.match_score,
                            source="boss",
                            source_url=item.source_url,
                        )
                    except DuplicateApplicationError:
                        existing = self._find_existing(item, self._applications())
                if existing is not None:
                    item.application_id = existing.id
                    updated = existing
                else:
                    continue
            else:
                current = next(
                    (
                        application
                        for application in self._applications()
                        if application.id == item.application_id
                    ),
                    None,
                )
                updated = (
                    current
                    if current is not None
                    and current.status is ApplicationStatus.CONTACTED
                    else self.repository.update_status(
                        item.application_id, ApplicationStatus.CONTACTED
                    )
                )
            if updated is not None and updated.status is ApplicationStatus.CONTACTED:
                synced.add(item.task_id)
                logger.info(
                    "apply_event=repository_sync batch_id=%s plan_id=%s execution_id=%s job_key=%s task_state=%s attempt=%s reconciliation_result=%s repository_sync_result=contacted",
                    execution.screening_batch_id,
                    execution.contact_plan_id,
                    execution.execution_id,
                    safe_job_key(canonical_job_key(item.source_url, item.company, item.job_title)),
                    item.status.value,
                    item.attempt,
                    "confirmed",
                )
        return synced
