"""Three-level local, FLASH, and selective-PRO screening funnel."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import threading
from time import perf_counter

from jobpilot.llm import LLMRateLimitError
from jobpilot.models import (
    BatchJobInput,
    BatchJobStatus,
    BatchScreeningItem,
    BatchScreeningResult,
    CandidateProfile,
    JobProfile,
    ScreeningTier,
)
from jobpilot.models.fast_screening import (
    AssessmentConfidence,
    FastRelevance,
    FastScreeningAssessment,
    FastScreeningItem,
    FastScreeningPipelineResult,
    FastScreeningProgress,
    FastScreeningStage,
    LocalPreScreenResult,
    LocalScreeningDecision,
    ScreeningMetrics,
    ScreeningMode,
    ScreeningTimelineEvent,
    ScreeningTiming,
)
from jobpilot.services.batch_job_input_parser import MAX_BATCH_JOBS, MIN_BATCH_JOBS
from jobpilot.services.batch_screening_service import (
    BatchScreeningService,
    CandidateProfileRequiredError,
    batch_item_cache_key,
    build_completed_screening_item,
)
from jobpilot.services.fast_screening_service import FastScreeningService
from jobpilot.services.local_pre_screen import LocalPreScreenService
from jobpilot.services.matching_service import MatchingService
from jobpilot.services.screening_preparation import (
    build_compact_candidate_profile,
    build_compact_candidate_summary,
    trim_job_description,
)
from jobpilot.storage import jd_text_fingerprint


logger = logging.getLogger(__name__)
Timer = Callable[[], float]
ProgressCallback = Callable[[FastScreeningProgress, Sequence[FastScreeningItem]], None]


def fast_screening_cache_key(resume_fingerprint: str, jd_fingerprint: str) -> str:
    return batch_item_cache_key(resume_fingerprint, jd_fingerprint)


def should_run_pro(
    assessment: FastScreeningAssessment,
    local_result: LocalPreScreenResult,
    *,
    explicitly_requested: bool = False,
) -> bool:
    if explicitly_requested:
        return True
    if assessment.hard_requirement_risks:
        return True
    if assessment.relevance is FastRelevance.HIGH:
        return assessment.decision_confidence is not AssessmentConfidence.HIGH
    return assessment.relevance is FastRelevance.MEDIUM and (
        assessment.decision_confidence is not AssessmentConfidence.HIGH
        or local_result.decision is LocalScreeningDecision.UNCERTAIN
    )


def _fast_tier(assessment: FastScreeningAssessment) -> ScreeningTier:
    if assessment.relevance is FastRelevance.HIGH:
        return ScreeningTier.PRIORITY
    if assessment.relevance is FastRelevance.MEDIUM:
        return (
            ScreeningTier.CAUTION
            if assessment.hard_requirement_risks
            else ScreeningTier.RECOMMENDED
        )
    return ScreeningTier.LOW_PRIORITY


def _fast_job_profile(
    job_input: BatchJobInput,
    assessment: FastScreeningAssessment,
    trimmed_jd: str,
) -> JobProfile:
    """Give PRO compact structure without resending the complete raw page text."""
    return JobProfile(
        company=job_input.company,
        job_title=job_input.job_title or assessment.job_title,
        location=job_input.location,
        responsibilities=[trimmed_jd[:1800]],
        required_skills=assessment.core_required_skills,
        other_requirements=assessment.hard_requirement_risks,
        keywords=list(
            dict.fromkeys(
                [
                    *assessment.core_required_skills,
                    *assessment.matched_core_skills,
                    *assessment.missing_core_skills,
                ]
            )
        ),
    )


def _sort(items: Sequence[FastScreeningItem]) -> list[FastScreeningItem]:
    order = {
        ScreeningTier.PRIORITY: 0,
        ScreeningTier.RECOMMENDED: 1,
        ScreeningTier.CAUTION: 2,
        ScreeningTier.LOW_PRIORITY: 3,
    }
    return sorted(
        items,
        key=lambda item: (
            order[item.screening_tier],
            -(item.match_score if item.match_score is not None else -1),
            item.job_input.index,
        ),
    )


class FastScreeningPipeline:
    def __init__(
        self,
        local_service: LocalPreScreenService,
        fast_service: FastScreeningService,
        matching_service: MatchingService,
        *,
        deep_service: BatchScreeningService | None = None,
        local_cache: MutableMapping[str, LocalPreScreenResult] | None = None,
        fast_cache: MutableMapping[str, FastScreeningAssessment] | None = None,
        deep_cache: MutableMapping[str, BatchScreeningItem] | None = None,
        trimmed_jd_cache: MutableMapping[str, str] | None = None,
        compact_summary_cache: MutableMapping[str, object] | None = None,
        job_profile_cache: MutableMapping[str, JobProfile] | None = None,
        flash_max_workers: int = 3,
        pro_max_workers: int = 1,
        timer: Timer = perf_counter,
    ) -> None:
        self.local_service = local_service
        self.fast_service = fast_service
        self.matching_service = matching_service
        self.deep_service = deep_service
        self.local_cache = local_cache if local_cache is not None else {}
        self.fast_cache = fast_cache if fast_cache is not None else {}
        self.deep_cache = deep_cache if deep_cache is not None else {}
        self.trimmed_jd_cache = trimmed_jd_cache if trimmed_jd_cache is not None else {}
        self.compact_summary_cache = (
            compact_summary_cache if compact_summary_cache is not None else {}
        )
        self.job_profile_cache = job_profile_cache if job_profile_cache is not None else {}
        self.flash_max_workers = max(1, min(flash_max_workers, 3))
        self.pro_max_workers = max(1, min(pro_max_workers, 2))
        self.timer = timer

    def _fast_assess(self, candidate, job_input, summary, trimmed_jd, telemetry=None):
        if isinstance(self.fast_service, FastScreeningService):
            return self.fast_service.assess(
                candidate,
                job_input,
                candidate_summary=summary,
                trimmed_jd=trimmed_jd,
                telemetry_callback=telemetry,
            )
        return self.fast_service.assess(candidate, job_input)

    @staticmethod
    def _emit(
        callback: ProgressCallback | None,
        stage: FastScreeningStage,
        completed: int,
        total: int,
        items: Sequence[FastScreeningItem],
        item_index: int | None = None,
    ) -> None:
        if callback:
            callback(
                FastScreeningProgress(
                    stage=stage,
                    completed=completed,
                    total=total,
                    visible_results=len(items),
                    item_index=item_index,
                ),
                _sort(items),
            )

    @staticmethod
    def _local_item(
        job_input: BatchJobInput, local: LocalPreScreenResult, *, is_cached: bool
    ) -> FastScreeningItem:
        rejected = local.decision is LocalScreeningDecision.REJECT
        return FastScreeningItem(
            job_input=job_input,
            local_result=local,
            screening_tier=(
                ScreeningTier.LOW_PRIORITY if rejected else ScreeningTier.CAUTION
            ),
            screening_reason=(local.reason if rejected else "等待 FLASH 快速筛选。"),
            core_gaps=local.hard_requirement_risks,
            is_cached=is_cached,
        )

    @staticmethod
    def _fast_item(
        current: FastScreeningItem,
        assessment: FastScreeningAssessment,
        *,
        cached: bool,
        deep_failed: bool = False,
    ) -> FastScreeningItem:
        return current.model_copy(
            update={
                "assessment": assessment,
                "screening_tier": _fast_tier(assessment),
                "screening_reason": (
                    "深度分析失败，当前显示快速判断。"
                    if deep_failed
                    else assessment.reason
                ),
                "core_gaps": list(
                    dict.fromkeys(
                        [
                            *assessment.missing_core_skills,
                            *assessment.hard_requirement_risks,
                        ]
                    )
                ),
                "deep_analysis_failed": deep_failed,
                "is_cached": current.is_cached or cached,
            },
            deep=True,
        )

    @staticmethod
    def _deep_item(
        current: FastScreeningItem, completed: BatchScreeningItem, *, cached: bool
    ) -> FastScreeningItem:
        return current.model_copy(
            update={
                "screening_tier": completed.screening_tier,
                "screening_reason": completed.screening_reason,
                "core_gaps": [gap.skill for gap in completed.match_result.missing_skills],
                "deep_match": True,
                "job_profile": completed.job_profile,
                "match_result": completed.match_result,
                "match_score": completed.match_score,
                "is_cached": current.is_cached or cached,
            },
            deep=True,
        )

    def process(
        self,
        candidate: CandidateProfile | None,
        resume_fingerprint: str | None,
        job_inputs: Sequence[BatchJobInput],
        *,
        mode: ScreeningMode = ScreeningMode.QUICK,
        explicitly_deep_indices: set[int] | None = None,
        progress_callback: ProgressCallback | None = None,
        screening_batch_id: str | None = None,
    ) -> FastScreeningPipelineResult | BatchScreeningResult:
        if candidate is None or not resume_fingerprint:
            raise CandidateProfileRequiredError("请先完成简历分析，再进行批量岗位筛选。")
        if not MIN_BATCH_JOBS <= len(job_inputs) <= MAX_BATCH_JOBS:
            raise ValueError("Batch screening requires 2–20 jobs.")
        if mode is ScreeningMode.DEEP:
            if self.deep_service is None:
                raise ValueError("Deep mode requires the existing batch screening service.")
            return self.deep_service.process(candidate, resume_fingerprint, job_inputs)

        total_started = self.timer()
        wall_started = perf_counter()
        cache_hit_indices: set[int] = set()
        items: dict[int, FastScreeningItem] = {}
        timeline: list[ScreeningTimelineEvent] = []
        timeline_lock = threading.Lock()
        repair_calls = 0
        first_result_at: float | None = None

        def provider_telemetry(index: int):
            def record(tier, phase, started, ended):
                nonlocal repair_calls
                with timeline_lock:
                    if phase == "repair":
                        repair_calls += 1
                    timeline.append(
                        ScreeningTimelineEvent(
                            stage=f"{tier.value}_{phase}",
                            job_index=index,
                            start_seconds=max(0.0, started - wall_started),
                            end_seconds=max(0.0, ended - wall_started),
                            duration_seconds=max(0.0, ended - started),
                        )
                    )
            return record

        def event(stage: str, started: float, ended: float, index=None, cached=False):
            timeline.append(
                ScreeningTimelineEvent(
                    stage=stage,
                    job_index=index,
                    start_seconds=max(0.0, started - total_started),
                    end_seconds=max(0.0, ended - total_started),
                    duration_seconds=max(0.0, ended - started),
                    cache_hit=cached,
                )
            )

        # Prepare stable compact inputs once. JD cleanup is keyed only by JD content;
        # all AI result caches remain bound to both resume and JD fingerprints.
        summary = self.compact_summary_cache.get(resume_fingerprint)
        if summary is None:
            summary = build_compact_candidate_summary(candidate)
            self.compact_summary_cache[resume_fingerprint] = summary.model_copy(deep=True)
        compact_candidate = build_compact_candidate_profile(candidate)
        trimmed_by_index: dict[int, str] = {}
        key_by_index: dict[int, str] = {}
        unique_keys: set[str] = set()
        jd_parse_calls = 0
        for job_input in job_inputs:
            trim_started = self.timer()
            jd_fingerprint = jd_text_fingerprint(job_input.jd_text)
            key = fast_screening_cache_key(resume_fingerprint, jd_fingerprint)
            key_by_index[job_input.index] = key
            trim_cached = key in self.trimmed_jd_cache
            if key not in self.trimmed_jd_cache:
                self.trimmed_jd_cache[key] = trim_job_description(job_input.jd_text)
                jd_parse_calls += 1
            trimmed_by_index[job_input.index] = self.trimmed_jd_cache[key]
            unique_keys.add(key)
            trim_ended = self.timer()
            event("jd_trim", trim_started, trim_ended, job_input.index, trim_cached)
        duplicate_jobs = len(job_inputs) - len(unique_keys)

        local_started = self.timer()
        seen_local: set[str] = set()
        for job_input in job_inputs:
            item_started = self.timer()
            key = key_by_index[job_input.index]
            local = self.local_cache.get(key)
            cached = local is not None or key in seen_local
            if local is None:
                local = self.local_service.assess(candidate, job_input)
                self.local_cache[key] = local.model_copy(deep=True)
            if cached:
                cache_hit_indices.add(job_input.index)
            seen_local.add(key)
            items[job_input.index] = self._local_item(job_input, local, is_cached=cached)
            item_ended = self.timer()
            event("local", item_started, item_ended, job_input.index, cached)
        local_seconds = self.timer() - local_started
        self._emit(progress_callback, FastScreeningStage.LOCAL, len(job_inputs), len(job_inputs), list(items.values()))

        flash_started = self.timer()
        flash_count = 0
        rate_limit_retries = 0
        candidates = [
            item for item in items.values()
            if item.local_result.decision is not LocalScreeningDecision.REJECT
        ]
        flash_groups: dict[str, list[FastScreeningItem]] = {}
        completed_flash = 0
        for current in candidates:
            key = key_by_index[current.job_input.index]
            assessment = self.fast_cache.get(key)
            if assessment is not None:
                cache_hit_indices.add(current.job_input.index)
                items[current.job_input.index] = self._fast_item(current, assessment, cached=True)
                completed_flash += 1
                now = self.timer()
                event("flash", now, now, current.job_input.index, True)
                if first_result_at is None:
                    first_result_at = now
                self._emit(progress_callback, FastScreeningStage.FLASH, completed_flash, len(candidates), list(items.values()), current.job_input.index)
            else:
                flash_groups.setdefault(key, []).append(current)

        def run_flash(group: list[FastScreeningItem]):
            current = group[0]
            started = self.timer()
            result = self._fast_assess(
                candidate,
                current.job_input,
                summary,
                trimmed_by_index[current.job_input.index],
                provider_telemetry(current.job_input.index),
            )
            return result, started, self.timer()

        retry_groups: list[tuple[str, list[FastScreeningItem]]] = []
        if flash_groups:
            flash_count = len(flash_groups)
            with ThreadPoolExecutor(
                max_workers=min(self.flash_max_workers, len(flash_groups)),
                thread_name_prefix="jobpilot-flash",
            ) as executor:
                futures = {executor.submit(run_flash, group): (key, group) for key, group in flash_groups.items()}
                for future in as_completed(futures):
                    key, group = futures[future]
                    try:
                        assessment, started, ended = future.result()
                    except LLMRateLimitError:
                        retry_groups.append((key, group))
                        continue
                    except Exception as exc:
                        logger.warning("Fast screening failed item_index=%d error_type=%s", group[0].job_input.index, type(exc).__name__)
                        for current in group:
                            items[current.job_input.index] = current.model_copy(update={"screening_reason": "快速分析失败，建议人工查看该岗位。"}, deep=True)
                            completed_flash += 1
                    else:
                        self.fast_cache[key] = assessment.model_copy(deep=True)
                        for offset, current in enumerate(group):
                            cached = offset > 0
                            if cached:
                                cache_hit_indices.add(current.job_input.index)
                            items[current.job_input.index] = self._fast_item(current, assessment, cached=cached)
                            completed_flash += 1
                            event("flash", started, ended, current.job_input.index, cached)
                            self._emit(progress_callback, FastScreeningStage.FLASH, completed_flash, len(candidates), list(items.values()), current.job_input.index)
                        if first_result_at is None:
                            first_result_at = ended

        # A bounded sequential retry is safer than repeatedly increasing pressure.
        for key, group in retry_groups:
            rate_limit_retries += 1
            flash_count += 1
            try:
                assessment, started, ended = run_flash(group)
            except Exception as exc:
                logger.warning("Fast screening retry failed item_index=%d error_type=%s", group[0].job_input.index, type(exc).__name__)
                for current in group:
                    items[current.job_input.index] = current.model_copy(update={"screening_reason": "快速分析失败，建议人工查看该岗位。"}, deep=True)
                    completed_flash += 1
            else:
                self.fast_cache[key] = assessment.model_copy(deep=True)
                for offset, current in enumerate(group):
                    cached = offset > 0
                    items[current.job_input.index] = self._fast_item(current, assessment, cached=cached)
                    completed_flash += 1
                    event("flash_retry", started, ended, current.job_input.index, cached)
                    self._emit(progress_callback, FastScreeningStage.FLASH, completed_flash, len(candidates), list(items.values()), current.job_input.index)
                if first_result_at is None:
                    first_result_at = ended
        flash_seconds = self.timer() - flash_started

        pro_started = self.timer()
        pro_count = 0
        requested = explicitly_deep_indices or set()
        pro_candidates = [
            item for item in items.values()
            if item.assessment is not None
            and should_run_pro(item.assessment, item.local_result, explicitly_requested=item.job_input.index in requested)
        ]
        pro_groups: dict[str, list[FastScreeningItem]] = {}
        completed_pro = 0
        for current in pro_candidates:
            key = key_by_index[current.job_input.index]
            completed = self.deep_cache.get(key)
            cached = completed is not None and completed.status is BatchJobStatus.COMPLETED
            if cached:
                cache_hit_indices.add(current.job_input.index)
                items[current.job_input.index] = self._deep_item(current, completed, cached=True)
                completed_pro += 1
                now = self.timer()
                event("pro", now, now, current.job_input.index, True)
                self._emit(progress_callback, FastScreeningStage.PRO, completed_pro, len(pro_candidates), list(items.values()), current.job_input.index)
            else:
                pro_groups.setdefault(key, []).append(current)

        def run_pro(group: list[FastScreeningItem]):
            current = group[0]
            started = self.timer()
            key = key_by_index[current.job_input.index]
            profile = self.job_profile_cache.get(key)
            if profile is None:
                profile = _fast_job_profile(current.job_input, current.assessment, trimmed_by_index[current.job_input.index])
                self.job_profile_cache[key] = profile.model_copy(deep=True)
            if isinstance(self.matching_service, MatchingService):
                match_result = self.matching_service.analyze(
                    compact_candidate,
                    profile,
                    telemetry_callback=provider_telemetry(current.job_input.index),
                )
            else:
                match_result = self.matching_service.analyze(compact_candidate, profile)
            completed = build_completed_screening_item(current.job_input, profile, match_result, is_cached=False, cache_source=None)
            return completed, started, self.timer()

        if pro_groups:
            with ThreadPoolExecutor(
                max_workers=min(self.pro_max_workers, len(pro_groups)),
                thread_name_prefix="jobpilot-pro",
            ) as executor:
                futures = {executor.submit(run_pro, group): (key, group) for key, group in pro_groups.items()}
                for future in as_completed(futures):
                    key, group = futures[future]
                    try:
                        completed, started, ended = future.result()
                    except Exception as exc:
                        logger.warning("Selective deep matching failed item_index=%d error_type=%s", group[0].job_input.index, type(exc).__name__)
                        for current in group:
                            items[current.job_input.index] = self._fast_item(current, current.assessment, cached=False, deep_failed=True)
                            completed_pro += 1
                    else:
                        pro_count += 1
                        self.deep_cache[key] = completed.model_copy(deep=True)
                        for offset, current in enumerate(group):
                            cached = offset > 0
                            if cached:
                                cache_hit_indices.add(current.job_input.index)
                            items[current.job_input.index] = self._deep_item(current, completed, cached=cached)
                            completed_pro += 1
                            event("pro", started, ended, current.job_input.index, cached)
                            self._emit(progress_callback, FastScreeningStage.PRO, completed_pro, len(pro_candidates), list(items.values()), current.job_input.index)
        pro_seconds = self.timer() - pro_started
        total_seconds = self.timer() - total_started
        if first_result_at is None:
            first_result_at = total_started + local_seconds
        sorted_items = _sort(list(items.values()))
        self._emit(
            progress_callback,
            FastScreeningStage.COMPLETED,
            len(job_inputs),
            len(job_inputs),
            sorted_items,
        )
        metrics = ScreeningMetrics(
            total_jobs=len(job_inputs),
            local_filtered=sum(
                item.local_result.decision is LocalScreeningDecision.REJECT
                for item in items.values()
            ),
            flash_screened=len(candidates),
            pro_analyzed=len(pro_candidates),
            cache_hits=len(cache_hit_indices),
            cache_misses=len(job_inputs) - len(cache_hit_indices),
            jd_parse_calls=jd_parse_calls,
            flash_provider_calls=flash_count,
            pro_provider_calls=pro_count,
            duplicate_jobs=duplicate_jobs,
            rate_limit_retries=rate_limit_retries,
            repair_calls=repair_calls,
            timeline=timeline,
            timing=ScreeningTiming(
                local_seconds=local_seconds,
                flash_seconds=flash_seconds,
                pro_seconds=pro_seconds,
                total_elapsed_seconds=total_seconds,
                avg_seconds_per_job=total_seconds / len(job_inputs),
                time_to_first_result_seconds=max(0.0, first_result_at - total_started),
            ),
        )
        result_values = {"items": sorted_items, "metrics": metrics}
        if screening_batch_id is not None:
            result_values["screening_batch_id"] = screening_batch_id
        return FastScreeningPipelineResult(**result_values)
