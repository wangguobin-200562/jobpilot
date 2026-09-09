"""Deterministic selection, readiness, and duplicate protection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from urllib.parse import urlparse

from jobpilot.browser import ContactMode, resolve_site_capability
from jobpilot.models import ApplicationStatus, JobApplication, ScreeningTier
from jobpilot.models.batch_apply import ApplyReadiness, BatchApplyItem, BatchApplyPlan
from jobpilot.models.fast_screening import FastScreeningItem, FastScreeningPipelineResult
from jobpilot.storage import ApplicationRepositoryError, jd_text_fingerprint
from jobpilot.browser.job_identity import canonical_job_key, canonicalize_job_url


EXCLUDED_APPLICATION_STATUSES = frozenset(
    {
        ApplicationStatus.APPLIED,
        ApplicationStatus.CONTACTED,
        ApplicationStatus.INTERVIEWING,
        ApplicationStatus.OFFER,
        ApplicationStatus.CLOSED,
    }
)


def infer_job_source(source_url: str | None) -> str:
    if not source_url:
        return "unknown"
    try:
        hostname = (urlparse(source_url).hostname or "").casefold()
    except ValueError:
        return "unknown"
    if hostname == "zhipin.com" or hostname.endswith(".zhipin.com"):
        return "boss"
    return "unknown"


def valid_source_url(source_url: str | None) -> bool:
    if not source_url:
        return False
    try:
        parsed = urlparse(source_url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def calculate_apply_readiness(
    *,
    source: str,
    source_url: str | None,
    tier: ScreeningTier,
    hard_requirement_risks: Sequence[str],
) -> ApplyReadiness:
    capability = resolve_site_capability(source)
    if (
        not valid_source_url(source_url)
        or capability.contact_mode is ContactMode.UNSUPPORTED
    ):
        return ApplyReadiness.UNSUPPORTED
    if tier is ScreeningTier.CAUTION or hard_requirement_risks:
        return ApplyReadiness.REVIEW_REQUIRED
    if tier in {ScreeningTier.PRIORITY, ScreeningTier.RECOMMENDED}:
        return ApplyReadiness.READY
    return ApplyReadiness.REVIEW_REQUIRED


def default_selected(item: BatchApplyItem) -> bool:
    return (
        item.screening_tier in {ScreeningTier.PRIORITY, ScreeningTier.RECOMMENDED}
        and item.apply_readiness is ApplyReadiness.READY
        and item.exclusion_reason is None
    )


def screening_result_fingerprint(result: FastScreeningPipelineResult) -> str:
    digest = sha256()
    for item in sorted(result.items, key=lambda value: value.job_input.index):
        values = (
            jd_text_fingerprint(item.job_input.jd_text),
            item.job_input.company or "",
            item.job_input.job_title or "",
            item.job_input.source_url or "",
            item.screening_tier.value,
            str(item.deep_match),
            str(item.match_score),
            item.screening_reason,
            "|".join(item.core_gaps),
        )
        for value in values:
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def apply_item_identity(item: BatchApplyItem) -> str:
    return canonical_job_key(item.source_url, item.company, item.job_title)


class BatchApplyService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def _applications(self) -> list[JobApplication]:
        try:
            return self.repository.list_applications()
        except ApplicationRepositoryError:
            return []

    @staticmethod
    def _existing_match(
        item: FastScreeningItem, applications: Sequence[JobApplication]
    ) -> JobApplication | None:
        url = canonicalize_job_url(item.job_input.source_url)
        company = (item.job_input.company or "未提供公司").strip().casefold()
        title = (item.job_input.job_title or "未命名岗位").strip().casefold()
        for application in applications:
            if url and canonicalize_job_url(application.source_url) == url:
                return application
            if (
                application.company.strip().casefold() == company
                and application.job_title.strip().casefold() == title
            ):
                return application
        return None

    def build_selection_items(
        self, result: FastScreeningPipelineResult
    ) -> list[BatchApplyItem]:
        applications = self._applications()
        seen: set[str] = set()
        output: list[BatchApplyItem] = []
        for screening in result.items:
            job = screening.job_input
            source = infer_job_source(job.source_url)
            risks = list(
                dict.fromkeys(
                    [
                        *screening.local_result.hard_requirement_risks,
                        *(
                            screening.assessment.hard_requirement_risks
                            if screening.assessment
                            else []
                        ),
                    ]
                )
            )
            readiness = calculate_apply_readiness(
                source=source,
                source_url=job.source_url,
                tier=screening.screening_tier,
                hard_requirement_risks=risks,
            )
            existing = self._existing_match(screening, applications)
            exclusion_reason = None
            if existing and existing.status in EXCLUDED_APPLICATION_STATUSES:
                exclusion_reason = f"该岗位已处于“{existing.status.value}”状态，已排除。"
            draft = BatchApplyItem(
                application_id=existing.id if existing else None,
                company=job.company or "未提供公司",
                job_title=job.job_title or "未命名岗位",
                location=job.location,
                source=source,
                source_url=job.source_url,
                screening_tier=screening.screening_tier,
                match_score=screening.match_score if screening.deep_match else None,
                fast_relevance=(screening.assessment.relevance if screening.assessment else None),
                main_reason=screening.screening_reason,
                main_gaps=screening.core_gaps,
                selected=False,
                apply_readiness=readiness,
                exclusion_reason=exclusion_reason,
            )
            identity = apply_item_identity(draft)
            if identity in seen:
                draft = draft.model_copy(
                    update={"selected": False, "exclusion_reason": "重复岗位，已排除。"}
                )
            seen.add(identity)
            draft = draft.model_copy(update={"selected": default_selected(draft)})
            output.append(draft)
        return output

    @staticmethod
    def create_plan(
        items: Sequence[BatchApplyItem],
        selections: Mapping[str, bool],
        *,
        screening_batch_id: str | None = None,
    ) -> BatchApplyPlan:
        planned: list[BatchApplyItem] = []
        for item in items:
            requested = bool(selections.get(apply_item_identity(item), item.selected))
            selectable = (
                item.apply_readiness is not ApplyReadiness.UNSUPPORTED
                and item.exclusion_reason is None
            )
            planned.append(item.model_copy(update={"selected": requested and selectable}))
        digest = sha256()
        digest.update((screening_batch_id or "no-batch").encode("utf-8"))
        for item in planned:
            digest.update(b"\0")
            digest.update(apply_item_identity(item).encode("utf-8"))
            digest.update(b"\1" if item.selected else b"\0")
        return BatchApplyPlan(
            contact_plan_id=f"contact-plan-{digest.hexdigest()}",
            screening_batch_id=screening_batch_id,
            items=planned,
            selected_count=sum(item.selected for item in planned),
            total_count=len(planned),
        )
