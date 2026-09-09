"""Strict, privacy-minimal contracts for extension-assisted applications."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator

from jobpilot.models.candidate_profile import ProfileModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApplyExecutionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    CONTACTED = "contacted"
    ALREADY_CONTACTED = "already_contacted"
    APPLIED = "applied"
    MANUAL_REQUIRED = "manual_required"
    SKIPPED = "skipped"
    FAILED = "failed"
    PAUSED = "paused"


class ApplyAction(str, Enum):
    INITIATE_CONTACT = "initiate_contact"
    SAFE_HANDOFF = "safe_handoff"


TERMINAL_APPLY_STATUSES = frozenset(
    {
        ApplyExecutionStatus.APPLIED,
        ApplyExecutionStatus.CONTACTED,
        ApplyExecutionStatus.ALREADY_CONTACTED,
        ApplyExecutionStatus.SKIPPED,
        ApplyExecutionStatus.FAILED,
    }
)


class ApplyTaskPayload(ProfileModel):
    """Only fields the extension needs to open one confirmed BOSS job."""

    task_id: str = Field(min_length=8, max_length=100)
    application_id: int | None = Field(default=None, gt=0)
    company: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    source_url: str = Field(max_length=2_000)
    action: ApplyAction = Field(default=ApplyAction.INITIATE_CONTACT, strict=False)

    @model_validator(mode="after")
    def validate_boss_url(self) -> "ApplyTaskPayload":
        parsed = urlparse(self.source_url)
        hostname = (parsed.hostname or "").casefold()
        is_boss = hostname == "zhipin.com" or hostname.endswith(".zhipin.com")
        if parsed.scheme != "https" or not hostname:
            raise ValueError("apply task requires an HTTPS URL")
        if self.action is ApplyAction.INITIATE_CONTACT and not is_boss:
            raise ValueError("BOSS contact task requires a BOSS HTTPS URL")
        if self.action is ApplyAction.SAFE_HANDOFF and hostname != "example.com":
            raise ValueError("safe handoff task is restricted to example.com")
        return self


class ExtensionHeartbeat(ProfileModel):
    extension_connected: Literal[True]
    execution_id: str | None = Field(default=None, min_length=8, max_length=100)


class ApplyResultReport(ProfileModel):
    """Constrained extension result; no arbitrary command or page payload."""

    task_id: str = Field(min_length=8, max_length=100)
    status: ApplyExecutionStatus = Field(strict=False)
    message: str = Field(min_length=1, max_length=300)
    contact_button_clicked: bool = False
    contact_success_detected: bool = False
    conversation_found: bool = False

    @model_validator(mode="after")
    def validate_extension_status(self) -> "ApplyResultReport":
        if self.status not in {
            ApplyExecutionStatus.APPLIED,
            ApplyExecutionStatus.CONTACTED,
            ApplyExecutionStatus.ALREADY_CONTACTED,
            ApplyExecutionStatus.MANUAL_REQUIRED,
            ApplyExecutionStatus.SKIPPED,
            ApplyExecutionStatus.FAILED,
        }:
            raise ValueError("extension may only report a predefined result status")
        if self.status is ApplyExecutionStatus.CONTACTED and not (
            self.contact_button_clicked
            and self.contact_success_detected
            and self.conversation_found
        ):
            raise ValueError("contacted requires explicit button, success, and conversation evidence")
        if (
            self.status is ApplyExecutionStatus.ALREADY_CONTACTED
            and not self.conversation_found
        ):
            raise ValueError("already_contacted requires conversation evidence")
        return self


class BatchApplyExecutionItem(ProfileModel):
    task_id: str = Field(min_length=8, max_length=100)
    company: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    source_url: str = Field(max_length=2_000)
    location: str | None = Field(default=None, max_length=200)
    screening_tier: str | None = Field(default=None, max_length=40)
    match_score: float | None = Field(default=None, ge=0, le=100)
    action: ApplyAction = Field(default=ApplyAction.INITIATE_CONTACT, strict=False)
    status: ApplyExecutionStatus = Field(strict=False)
    message: str = Field(default="等待浏览器扩展处理。", max_length=300)
    application_id: int | None = Field(default=None, gt=0)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    contact_button_clicked: bool = False
    contact_success_detected: bool = False
    conversation_found: bool = False


class BatchApplyExecution(ProfileModel):
    execution_id: str = Field(min_length=8, max_length=100)
    contact_plan_id: str | None = Field(default=None, min_length=8, max_length=100)
    screening_batch_id: str | None = Field(default=None, min_length=8, max_length=100)
    items: list[BatchApplyExecutionItem] = Field(min_length=1, max_length=10)
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    cancelled: bool = False

    @property
    def completed_count(self) -> int:
        return sum(item.status in TERMINAL_APPLY_STATUSES for item in self.items)

    @property
    def total_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return max(0.0, (self.finished_at - self.created_at).total_seconds())

    @property
    def avg_seconds_per_application(self) -> float | None:
        elapsed = self.total_seconds
        return elapsed / len(self.items) if elapsed is not None and self.items else None
