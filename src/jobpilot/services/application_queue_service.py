"""Deterministic, local-only application queue orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from jobpilot.models import (
    ApplicationQueueItem, ApplicationQueueResult, ApplicationStatus,
    JobApplication, OptimizationStatus, PreparationStatus, QueueSort,
    ScreeningTier,
)
from jobpilot.services.batch_screening_service import calculate_screening_tier, required_missing_count
from jobpilot.storage import ApplicationRepository


TIER_ADJUSTMENTS = {
    ScreeningTier.PRIORITY: 20.0,
    ScreeningTier.RECOMMENDED: 10.0,
    ScreeningTier.CAUTION: 0.0,
    ScreeningTier.LOW_PRIORITY: -20.0,
}
SOURCE_LABELS = {
    "boss": "BOSS直聘", "linkedin": "LinkedIn", "company_site": "公司官网",
    "manual": "手动添加", "demo": "Demo", "other": "其他",
}


def safe_external_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    return value.strip() if parsed.scheme in {"http", "https"} and parsed.netloc else None


def normalize_source(source: str | None, source_url: str | None) -> str:
    value = (source or "").strip().casefold()
    aliases = {
        "boss": "boss", "boss直聘": "boss", "linkedin": "linkedin",
        "company_site": "company_site", "公司官网": "company_site",
        "manual": "manual", "手动添加": "manual", "batch": "manual",
        "demo": "demo", "other": "other",
    }
    if value in aliases:
        return aliases[value]
    url = safe_external_url(source_url)
    if url:
        host = urlparse(url).netloc.casefold()
        if "zhipin.com" in host:
            return "boss"
        if "linkedin.com" in host:
            return "linkedin"
        return "company_site"
    return "other" if value else "manual"


def queue_tier(application: JobApplication) -> tuple[ScreeningTier, int]:
    match = application.match_result
    gaps = required_missing_count(match) if match is not None else 0
    if application.match_score is None:
        return ScreeningTier.LOW_PRIORITY, gaps
    return calculate_screening_tier(application.match_score, gaps), gaps


def calculate_priority_score(match_score: float | None, tier: ScreeningTier) -> float:
    return (match_score or 0.0) + TIER_ADJUSTMENTS[tier]


def calculate_preparation_status(tier: ScreeningTier, required_gaps: int) -> PreparationStatus:
    if tier is ScreeningTier.PRIORITY and required_gaps <= 1:
        return PreparationStatus.READY
    if tier is ScreeningTier.RECOMMENDED:
        return PreparationStatus.REVIEW_NEEDED
    return PreparationStatus.GAP_WARNING


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def build_queue_item(application: JobApplication) -> ApplicationQueueItem:
    tier, gap_count = queue_tier(application)
    match = application.match_result
    missing = match.missing_skills if match is not None else []
    required = [item.skill for item in missing if item.importance == "required"]
    all_gaps = required or [item.skill for item in missing]
    source_url = safe_external_url(application.source_url)
    return ApplicationQueueItem(
        application_id=application.id, company=application.company,
        job_title=application.job_title, location=application.location,
        match_score=application.match_score, screening_tier=tier,
        priority_score=calculate_priority_score(application.match_score, tier),
        source=normalize_source(application.source, source_url), source_url=source_url,
        preparation_status=calculate_preparation_status(tier, gap_count),
        optimization_status=(OptimizationStatus.GENERATED if application.optimization_result_json else OptimizationStatus.NOT_GENERATED),
        required_missing_count=gap_count, main_gap=all_gaps[0] if all_gaps else None,
        deferred_until=application.deferred_until,
        created_at=application.created_at, updated_at=application.updated_at,
    )


def sort_queue_items(items: list[ApplicationQueueItem], sort: QueueSort) -> list[ApplicationQueueItem]:
    if sort is QueueSort.MATCH_SCORE:
        return sorted(items, key=lambda item: (-(item.match_score if item.match_score is not None else -1), _as_utc(item.created_at), item.application_id))
    if sort is QueueSort.NEWEST:
        return sorted(items, key=lambda item: (_as_utc(item.created_at), item.application_id), reverse=True)
    if sort is QueueSort.OLDEST:
        return sorted(items, key=lambda item: (_as_utc(item.created_at), item.application_id))
    return sorted(items, key=lambda item: (-item.priority_score, _as_utc(item.created_at), item.application_id))


class ApplicationQueueService:
    """Load and mutate the saved-application queue without any AI dependency."""

    def __init__(self, repository: ApplicationRepository, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self.repository = repository
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def load_queue(self, *, query: str = "", tier: ScreeningTier | None = None,
                   preparation: PreparationStatus | None = None,
                   sort: QueueSort = QueueSort.PRIORITY) -> ApplicationQueueResult:
        items = [build_queue_item(item) for item in self.repository.list_applications(status=ApplicationStatus.SAVED)]
        now = _as_utc(self.now_provider())
        all_deferred = [item for item in items if item.deferred_until is not None and _as_utc(item.deferred_until) > now]
        all_active = [item for item in items if item not in all_deferred]
        needle = query.strip().casefold()
        if needle:
            items = [item for item in items if needle in item.company.casefold() or needle in item.job_title.casefold()]
        if tier is not None:
            items = [item for item in items if item.screening_tier is tier]
        if preparation is not None:
            items = [item for item in items if item.preparation_status is preparation]
        deferred = [item for item in items if item.deferred_until is not None and _as_utc(item.deferred_until) > now]
        active = [item for item in items if item not in deferred]
        return ApplicationQueueResult(
            items=sort_queue_items(active, sort), deferred_items=sort_queue_items(deferred, QueueSort.OLDEST),
            total_count=len(all_active),
            ready_count=sum(item.preparation_status is PreparationStatus.READY for item in all_active),
            review_needed_count=sum(item.preparation_status is PreparationStatus.REVIEW_NEEDED for item in all_active),
            gap_warning_count=sum(item.preparation_status is PreparationStatus.GAP_WARNING for item in all_active),
        )

    def defer(self, application_id: int, days: int) -> JobApplication | None:
        if days not in {1, 3}:
            raise ValueError("Queue deferral supports 1 or 3 days.")
        return self.repository.update_deferred_until(application_id, _as_utc(self.now_provider()) + timedelta(days=days))

    def cancel_defer(self, application_id: int) -> JobApplication | None:
        return self.repository.update_deferred_until(application_id, None)

    def mark_applied(self, application_id: int) -> JobApplication | None:
        return self.repository.update_status(application_id, ApplicationStatus.APPLIED)

    def restore_saved(self, application_id: int) -> JobApplication | None:
        return self.repository.update_status(application_id, ApplicationStatus.SAVED)
