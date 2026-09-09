"""Sequential batch JD analysis, matching, ranking, caching, and saving."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, Sequence
from hashlib import sha256
import logging
from typing import Literal, Protocol

from jobpilot.llm import LLMConfigurationError, LLMError, LLMTimeoutError, StructuredOutputError
from jobpilot.models import (
    BatchJobInput,
    BatchJobStatus,
    BatchSaveSummary,
    BatchScreeningItem,
    BatchScreeningResult,
    CandidateProfile,
    JobApplication,
    JobProfile,
    MatchResult,
    ScreeningTier,
)
from jobpilot.services.batch_job_input_parser import MAX_BATCH_JOBS, MIN_BATCH_JOBS
from jobpilot.services.job_analyzer import (
    JobAnalyzer,
    JobDescriptionValidationError,
    LongJobDescriptionError,
    ShortJobDescriptionError,
)
from jobpilot.services.matching_service import MatchingService
from jobpilot.storage import (
    ApplicationRepository,
    ApplicationRepositoryError,
    DuplicateApplicationError,
    jd_text_fingerprint,
)


logger = logging.getLogger(__name__)
PRIORITY_SCORE_MIN = 80.0
RECOMMENDED_SCORE_MIN = 65.0
CAUTION_SCORE_MIN = 50.0
MAX_PRIORITY_REQUIRED_GAPS = 1
MAX_RECOMMENDED_REQUIRED_GAPS = 2
TIER_SORT_ORDER = {
    ScreeningTier.PRIORITY: 0,
    ScreeningTier.RECOMMENDED: 1,
    ScreeningTier.CAUTION: 2,
    ScreeningTier.LOW_PRIORITY: 3,
}

ProgressCallback = Callable[[int, int, BatchJobStatus], None]
SaveOutcome = Literal["saved", "duplicate", "failed"]


class CandidateProfileRequiredError(ValueError):
    """Raised when screening is attempted without an analyzed resume."""


class ApplicationCacheSource(Protocol):
    def list_applications(self, **kwargs) -> list[JobApplication]: ...


def batch_item_cache_key(resume_fingerprint: str, jd_fingerprint: str) -> str:
    digest = sha256()
    digest.update(resume_fingerprint.encode("ascii"))
    digest.update(b"\0")
    digest.update(jd_fingerprint.encode("ascii"))
    return digest.hexdigest()


def batch_fingerprint(
    resume_fingerprint: str, job_inputs: Sequence[BatchJobInput]
) -> str:
    digest = sha256()
    digest.update(resume_fingerprint.encode("ascii"))
    for item in job_inputs:
        digest.update(b"\0")
        digest.update(jd_text_fingerprint(item.jd_text).encode("ascii"))
    return digest.hexdigest()


def required_missing_count(match_result: MatchResult) -> int:
    return sum(
        item.importance == "required" for item in match_result.missing_skills
    )


def calculate_screening_tier(
    match_score: float | None, required_gaps: int
) -> ScreeningTier:
    """Assign a transparent tier using Python only."""
    if match_score is None:
        raise ValueError("A completed screening item requires a match score.")
    if match_score >= PRIORITY_SCORE_MIN:
        if required_gaps <= MAX_PRIORITY_REQUIRED_GAPS:
            return ScreeningTier.PRIORITY
        if required_gaps <= MAX_RECOMMENDED_REQUIRED_GAPS:
            return ScreeningTier.RECOMMENDED
        return ScreeningTier.CAUTION
    if match_score >= RECOMMENDED_SCORE_MIN:
        return (
            ScreeningTier.RECOMMENDED
            if required_gaps <= MAX_RECOMMENDED_REQUIRED_GAPS
            else ScreeningTier.CAUTION
        )
    if match_score >= CAUTION_SCORE_MIN:
        return ScreeningTier.CAUTION
    return ScreeningTier.LOW_PRIORITY


def build_screening_reason(
    tier: ScreeningTier, match_score: float, required_gaps: int
) -> str:
    gap_text = f"{required_gaps} 项必备技能缺口"
    if tier is ScreeningTier.PRIORITY:
        return f"匹配度较高，核心技能覆盖良好，当前有 {gap_text}。"
    if tier is ScreeningTier.RECOMMENDED:
        return f"整体匹配较好，但当前仍有 {gap_text}。"
    if tier is ScreeningTier.CAUTION:
        return f"具备部分相关能力，但当前有 {gap_text}，建议谨慎安排投递优先级。"
    return f"当前匹配度为 {match_score:.0f} 分，且有 {gap_text}，暂不建议优先投入时间。"


def _merge_explicit_metadata(
    profile: JobProfile, job_input: BatchJobInput
) -> JobProfile:
    """Keep explicit user metadata when it conflicts with extracted fields."""
    return profile.model_copy(
        update={
            "company": job_input.company or profile.company,
            "job_title": job_input.job_title or profile.job_title,
            "location": job_input.location or profile.location,
        },
        deep=True,
    )


def build_completed_screening_item(
    job_input: BatchJobInput,
    profile: JobProfile,
    match_result: MatchResult,
    *,
    is_cached: bool,
    cache_source: str | None,
) -> BatchScreeningItem:
    profile = _merge_explicit_metadata(profile, job_input)
    score = match_result.scores.overall_score
    gap_count = required_missing_count(match_result)
    tier = calculate_screening_tier(score, gap_count)
    return BatchScreeningItem(
        index=job_input.index,
        company=profile.company or job_input.company,
        job_title=profile.job_title or job_input.job_title,
        location=profile.location or job_input.location,
        jd_text=job_input.jd_text,
        raw_block=job_input.raw_block,
        source_url=job_input.source_url,
        jd_fingerprint=jd_text_fingerprint(job_input.jd_text),
        status=BatchJobStatus.COMPLETED,
        job_profile=profile,
        match_result=match_result,
        match_score=score,
        screening_tier=tier,
        screening_reason=build_screening_reason(tier, score, gap_count),
        required_missing_count=gap_count,
        is_cached=is_cached,
        cache_source=cache_source,
    )


def build_batch_screening_result(
    items: Sequence[BatchScreeningItem],
) -> BatchScreeningResult:
    sorted_items = sort_batch_items(items)
    completed_count = sum(
        item.status is BatchJobStatus.COMPLETED for item in items
    )
    cached_count = sum(item.is_cached for item in items)
    return BatchScreeningResult(
        items=sorted_items,
        total_count=len(items),
        completed_count=completed_count,
        failed_count=len(items) - completed_count,
        cached_count=cached_count,
        newly_analyzed_count=len(items) - cached_count,
    )


def _safe_error(error: Exception, stage: BatchJobStatus) -> str:
    if isinstance(error, ShortJobDescriptionError):
        return "岗位内容过短，请补充完整岗位职责和任职要求。"
    if isinstance(error, LongJobDescriptionError):
        return "岗位内容过长，请精简后重新分析。"
    if isinstance(error, JobDescriptionValidationError):
        return "岗位内容无效，请检查后重新分析。"
    if isinstance(error, LLMConfigurationError):
        return "AI 分析尚未配置，请完成 DeepSeek API Key 配置。"
    if isinstance(error, LLMTimeoutError):
        return "AI 服务响应超时，请稍后重新分析该岗位。"
    if isinstance(error, StructuredOutputError):
        return "AI 返回结果无法解析，请重新分析该岗位。"
    if isinstance(error, LLMError):
        return "AI 服务暂时不可用，请稍后重新分析该岗位。"
    if stage is BatchJobStatus.MATCHING:
        return "岗位匹配失败，请稍后重新分析该岗位。"
    return "岗位解析失败，请检查内容后重新分析。"


def sort_batch_items(items: Sequence[BatchScreeningItem]) -> list[BatchScreeningItem]:
    """Sort tier first, score second, failed items last, preserving input ties."""
    return sorted(
        items,
        key=lambda item: (
            4 if item.status is BatchJobStatus.FAILED else TIER_SORT_ORDER[item.screening_tier],
            -(item.match_score if item.match_score is not None else -1),
            item.index,
        ),
    )


class BatchScreeningService:
    """Orchestrate a bounded sequential batch without additional retries."""

    def __init__(
        self,
        job_analyzer: JobAnalyzer,
        matching_service: MatchingService,
        *,
        repository: ApplicationCacheSource | None = None,
        item_cache: MutableMapping[str, BatchScreeningItem] | None = None,
    ) -> None:
        self.job_analyzer = job_analyzer
        self.matching_service = matching_service
        self.repository = repository
        self.item_cache = item_cache if item_cache is not None else {}

    def _repository_items(self) -> dict[str, JobApplication]:
        if self.repository is None:
            return {}
        try:
            applications = self.repository.list_applications()
        except ApplicationRepositoryError:
            logger.warning("Batch repository cache unavailable error_type=ApplicationRepositoryError")
            return {}
        result: dict[str, JobApplication] = {}
        for application in applications:
            result.setdefault(application.jd_fingerprint, application)
        return result

    def _process_item(
        self,
        candidate: CandidateProfile,
        resume_fingerprint: str,
        job_input: BatchJobInput,
        repository_items: dict[str, JobApplication],
        total: int,
        progress_callback: ProgressCallback | None,
        *,
        force: bool = False,
        preloaded_profile: JobProfile | None = None,
    ) -> BatchScreeningItem:
        jd_fingerprint = jd_text_fingerprint(job_input.jd_text)
        cache_key = batch_item_cache_key(resume_fingerprint, jd_fingerprint)
        if not force:
            cached = self.item_cache.get(cache_key)
            if cached is not None and cached.status is BatchJobStatus.COMPLETED:
                logger.info(
                    "Batch item cache hit item_index=%d jd_fingerprint_prefix=%s source=session",
                    job_input.index,
                    jd_fingerprint[:12],
                )
                return build_completed_screening_item(
                    job_input,
                    cached.job_profile,
                    cached.match_result,
                    is_cached=True,
                    cache_source="session",
                )

            saved = repository_items.get(jd_fingerprint)
            if saved is not None and saved.match_result is not None:
                logger.info(
                    "Batch item cache hit item_index=%d jd_fingerprint_prefix=%s source=repository",
                    job_input.index,
                    jd_fingerprint[:12],
                )
                completed = build_completed_screening_item(
                    job_input,
                    saved.job_profile,
                    saved.match_result,
                    is_cached=True,
                    cache_source="repository",
                )
                self.item_cache[cache_key] = completed.model_copy(deep=True)
                return completed

        stage = BatchJobStatus.ANALYZING_JD
        profile: JobProfile | None = None
        try:
            saved = repository_items.get(jd_fingerprint) if not force else None
            if preloaded_profile is not None:
                profile = _merge_explicit_metadata(preloaded_profile, job_input)
            elif saved is not None:
                profile = _merge_explicit_metadata(saved.job_profile, job_input)
            else:
                if progress_callback:
                    progress_callback(job_input.index, total, stage)
                profile = _merge_explicit_metadata(
                    self.job_analyzer.analyze(job_input.jd_text), job_input
                )

            stage = BatchJobStatus.MATCHING
            if progress_callback:
                progress_callback(job_input.index, total, stage)
            match_result = self.matching_service.analyze(candidate, profile)
            completed = build_completed_screening_item(
                job_input,
                profile,
                match_result,
                is_cached=False,
                cache_source=None,
            )
            self.item_cache[cache_key] = completed.model_copy(deep=True)
            logger.info(
                "Batch item completed item_index=%d jd_fingerprint_prefix=%s status=completed",
                job_input.index,
                jd_fingerprint[:12],
            )
            return completed
        except Exception as exc:
            logger.warning(
                "Batch item failed item_index=%d jd_fingerprint_prefix=%s stage=%s error_type=%s",
                job_input.index,
                jd_fingerprint[:12],
                stage.value,
                type(exc).__name__,
            )
            return BatchScreeningItem(
                index=job_input.index,
                company=job_input.company,
                job_title=job_input.job_title,
                location=job_input.location,
                jd_text=job_input.jd_text,
                raw_block=job_input.raw_block,
                source_url=job_input.source_url,
                jd_fingerprint=jd_fingerprint,
                status=BatchJobStatus.FAILED,
                job_profile=profile,
                error_message=_safe_error(exc, stage),
            )

    def process(
        self,
        candidate: CandidateProfile | None,
        resume_fingerprint: str | None,
        job_inputs: Sequence[BatchJobInput],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> BatchScreeningResult:
        if candidate is None or not resume_fingerprint:
            raise CandidateProfileRequiredError(
                "请先完成简历分析，再进行批量岗位筛选。"
            )
        if not MIN_BATCH_JOBS <= len(job_inputs) <= MAX_BATCH_JOBS:
            raise ValueError("Batch screening requires 2–20 jobs.")
        repository_items = self._repository_items()
        logger.info("Batch screening started batch_size=%d", len(job_inputs))
        items = [
            self._process_item(
                candidate,
                resume_fingerprint,
                job_input,
                repository_items,
                len(job_inputs),
                progress_callback,
            )
            for job_input in job_inputs
        ]
        return build_batch_screening_result(items)

    def retry_item(
        self,
        candidate: CandidateProfile,
        resume_fingerprint: str,
        failed_item: BatchScreeningItem,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> BatchScreeningItem:
        """Explicitly retry one item once without rerunning the batch."""
        job_input = BatchJobInput(
            index=failed_item.index,
            company=failed_item.company,
            job_title=failed_item.job_title,
            location=failed_item.location,
            jd_text=failed_item.jd_text,
            source_url=failed_item.source_url,
            raw_block=failed_item.raw_block,
        )
        return self._process_item(
            candidate,
            resume_fingerprint,
            job_input,
            self._repository_items(),
            1,
            progress_callback,
            force=True,
            preloaded_profile=failed_item.job_profile,
        )


def save_batch_item(
    repository: ApplicationRepository, item: BatchScreeningItem
) -> SaveOutcome:
    """Persist one completed item as saved, preserving structured snapshots."""
    if item.status is not BatchJobStatus.COMPLETED:
        return "failed"
    try:
        duplicate = repository.find_duplicate(
            company=item.company or "未提供公司",
            job_title=item.job_title or "未命名岗位",
            jd_text=item.jd_text,
        )
        if duplicate is not None:
            return "duplicate"
        repository.create_application(
            company=item.company or "未提供公司",
            job_title=item.job_title or "未命名岗位",
            location=item.location,
            jd_text=item.jd_text,
            job_profile=item.job_profile,
            match_score=item.match_score,
            match_result=item.match_result,
            optimization_result=None,
            source="manual",
            source_url=item.source_url,
        )
        return "saved"
    except DuplicateApplicationError:
        return "duplicate"
    except (ApplicationRepositoryError, OSError, ValueError):
        return "failed"


def save_priority_items(
    repository: ApplicationRepository, items: Sequence[BatchScreeningItem]
) -> BatchSaveSummary:
    outcomes = [
        save_batch_item(repository, item)
        for item in items
        if item.screening_tier is ScreeningTier.PRIORITY
    ]
    return BatchSaveSummary(
        saved_count=outcomes.count("saved"),
        duplicate_count=outcomes.count("duplicate"),
        failed_count=outcomes.count("failed"),
    )
