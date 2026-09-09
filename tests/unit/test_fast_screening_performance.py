from __future__ import annotations

from collections import Counter
import threading
import time

from jobpilot.llm import LLMRateLimitError
from jobpilot.models import (
    AssessmentConfidence,
    BatchJobInput,
    CandidateProfile,
    ExperienceItem,
    FastRelevance,
    FastScreeningAssessment,
    MatchResult,
    MatchScoreBreakdown,
    PersonalInfo,
    ProjectItem,
    Skills,
)
from jobpilot.services import (
    FastScreeningPipeline,
    LocalPreScreenService,
    build_compact_candidate_profile,
    build_compact_candidate_summary,
    should_run_pro,
    trim_job_description,
)


def candidate() -> CandidateProfile:
    return CandidateProfile(
        personal_info=PersonalInfo(
            name="隐私姓名", email="secret@example.com", phone="00000000000"
        ),
        skills=Skills(
            programming_languages=["Python"],
            frameworks=["FastAPI", "LangChain"],
            databases=["PostgreSQL"],
            tools=["Git", "Docker"],
            other=["RAG", "Prompt Engineering"],
        ),
        experience=[ExperienceItem(
            position="AI 实习生",
            description="隐私姓名使用 secret@example.com 完成 Python 服务。",
            technologies=["Python", "FastAPI"],
        )],
        projects=[ProjectItem(
            name="知识库问答",
            description="使用 RAG 构建问答流程。",
            technologies=["Python", "LangChain"],
        )],
    )


def job(index: int, marker: str = "MID") -> BatchJobInput:
    text = (
        f"{marker} 岗位{index}职责：开发 Python AI 服务，参与接口设计、功能测试、"
        "技术文档和效果评估，协助完成智能工作流迭代。任职要求：熟悉 Python、"
        "FastAPI 与 Git，理解大模型应用基础，具备良好的学习、沟通和问题分析能力。"
    )
    return BatchJobInput(index=index, job_title=f"岗位{index}", jd_text=text, raw_block=text)


def assessment(
    relevance: FastRelevance = FastRelevance.MEDIUM,
    confidence: AssessmentConfidence = AssessmentConfidence.HIGH,
    *,
    risks: list[str] | None = None,
) -> FastScreeningAssessment:
    return FastScreeningAssessment(
        job_title="AI 应用实习生",
        core_required_skills=["Python", "FastAPI"],
        matched_core_skills=["Python"],
        missing_core_skills=["FastAPI"],
        hard_requirement_risks=risks or [],
        relevance=relevance,
        decision_confidence=confidence,
        reason="方向相关，存在一个可补齐的技能缺口。",
    )


class ConcurrentFast:
    def __init__(self, *, delay: float = 0.03) -> None:
        self.delay = delay
        self.calls = Counter()
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def assess(self, _candidate, job_input):
        with self.lock:
            self.calls[job_input.jd_text] += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        if "HIGH" in job_input.jd_text:
            return assessment(FastRelevance.HIGH)
        if "UNCERTAIN" in job_input.jd_text:
            return assessment(FastRelevance.MEDIUM, AssessmentConfidence.LOW)
        if "LOW" in job_input.jd_text:
            return assessment(FastRelevance.LOW)
        return assessment()


class Matcher:
    def __init__(self, delay: float = 0) -> None:
        self.calls = 0
        self.delay = delay

    def analyze(self, _candidate, _profile):
        self.calls += 1
        time.sleep(self.delay)
        return MatchResult(scores=MatchScoreBreakdown(overall_score=72, skills_score=72))


def pipeline(fast=None, matcher=None, **kwargs):
    return FastScreeningPipeline(
        LocalPreScreenService(), fast or ConcurrentFast(delay=0), matcher or Matcher(), **kwargs
    )


def test_flash_concurrency_is_bounded_at_three() -> None:
    fast = ConcurrentFast()
    started = time.perf_counter()
    pipeline(fast=fast).process(candidate(), "a" * 64, [job(i) for i in range(1, 7)])
    elapsed = time.perf_counter() - started
    assert 2 <= fast.max_active <= 3
    assert elapsed < 0.16


def test_exact_duplicate_jd_has_one_flash_call() -> None:
    fast = ConcurrentFast(delay=0)
    one = job(1)
    two = one.model_copy(update={"index": 2})
    result = pipeline(fast=fast).process(candidate(), "a" * 64, [one, two])
    assert sum(fast.calls.values()) == 1
    assert result.metrics.duplicate_jobs == 1
    assert result.metrics.cache_hits == 1


def test_duplicate_boundary_job_has_one_pro_call() -> None:
    fast = ConcurrentFast(delay=0)
    matcher = Matcher()
    one = job(1, "UNCERTAIN")
    two = one.model_copy(update={"index": 2})
    result = pipeline(fast=fast, matcher=matcher).process(
        candidate(), "a" * 64, [one, two]
    )
    assert matcher.calls == 1
    assert result.metrics.pro_provider_calls == 1
    assert all(item.deep_match for item in result.items)


def test_concurrent_results_remain_mapped_to_original_job() -> None:
    class MappingFast(ConcurrentFast):
        def assess(self, c, item):
            result = super().assess(c, item)
            return result.model_copy(update={"job_title": item.job_title})

    result = pipeline(fast=MappingFast()).process(
        candidate(), "a" * 64, [job(i) for i in range(1, 6)]
    )
    assert {
        item.job_input.index: item.assessment.job_title for item in result.items
    } == {i: f"岗位{i}" for i in range(1, 6)}


def test_same_resume_and_jd_reuses_all_quick_caches() -> None:
    caches = ({}, {}, {}, {}, {}, {})
    fast = ConcurrentFast(delay=0)
    matcher = Matcher()
    pipe = pipeline(
        fast=fast,
        matcher=matcher,
        local_cache=caches[0],
        fast_cache=caches[1],
        deep_cache=caches[2],
        trimmed_jd_cache=caches[3],
        compact_summary_cache=caches[4],
        job_profile_cache=caches[5],
    )
    jobs = [job(1, "UNCERTAIN"), job(2)]
    pipe.process(candidate(), "a" * 64, jobs)
    second = pipe.process(candidate(), "a" * 64, jobs)
    assert sum(fast.calls.values()) == 2
    assert matcher.calls == 1
    assert second.metrics.cache_hits == 2


def test_resume_change_invalidates_ai_cache_key() -> None:
    fast = ConcurrentFast(delay=0)
    pipe = pipeline(fast=fast, local_cache={}, fast_cache={})
    jobs = [job(1), job(2)]
    pipe.process(candidate(), "a" * 64, jobs)
    pipe.process(candidate(), "b" * 64, jobs)
    assert sum(fast.calls.values()) == 4


def test_jd_change_only_recomputes_changed_job() -> None:
    fast = ConcurrentFast(delay=0)
    pipe = pipeline(fast=fast, local_cache={}, fast_cache={})
    original = [job(1), job(2)]
    pipe.process(candidate(), "a" * 64, original)
    changed = [job(1, "MID changed"), job(2)]
    pipe.process(candidate(), "a" * 64, changed)
    assert sum(fast.calls.values()) == 3


def test_rate_limit_falls_back_to_one_finite_sequential_retry() -> None:
    class RateLimited(ConcurrentFast):
        def assess(self, c, item):
            self.calls[item.jd_text] += 1
            if self.calls[item.jd_text] == 1:
                raise LLMRateLimitError("busy")
            return assessment()

    fast = RateLimited(delay=0)
    result = pipeline(fast=fast).process(candidate(), "a" * 64, [job(1), job(2)])
    assert sum(fast.calls.values()) == 4
    assert result.metrics.rate_limit_retries == 2
    assert result.metrics.flash_provider_calls == 4


def test_pro_gate_skips_high_confidence_clear_high_relevance() -> None:
    local = LocalPreScreenService().assess(candidate(), job(1))
    assert not should_run_pro(assessment(FastRelevance.HIGH), local)


def test_pro_gate_runs_for_uncertainty_risk_and_explicit_request() -> None:
    local = LocalPreScreenService().assess(candidate(), job(1))
    assert should_run_pro(assessment(FastRelevance.HIGH, AssessmentConfidence.LOW), local)
    assert should_run_pro(assessment(risks=["学历要求不明确"]), local)
    assert should_run_pro(assessment(), local, explicitly_requested=True)


def test_twenty_job_gate_rate_is_at_most_thirty_percent_for_clear_set() -> None:
    fast = ConcurrentFast(delay=0)
    matcher = Matcher()
    markers = ["HIGH"] * 14 + ["UNCERTAIN"] * 6
    result = pipeline(fast=fast, matcher=matcher).process(
        candidate(), "a" * 64, [job(i, marker) for i, marker in enumerate(markers, 1)]
    )
    assert result.metrics.pro_provider_calls == 6
    assert result.metrics.pro_provider_calls / 20 <= 0.30


def test_compact_candidate_summary_is_bounded_and_has_no_pii() -> None:
    summary = build_compact_candidate_summary(candidate())
    serialized = summary.model_dump_json()
    assert len(summary.skills) <= 30
    assert "隐私姓名" not in serialized
    assert "secret@example.com" not in serialized
    assert "00000000000" not in serialized


def test_compact_candidate_summary_is_deterministic() -> None:
    assert build_compact_candidate_summary(candidate()) == build_compact_candidate_summary(candidate())


def test_compact_pro_profile_has_no_pii_and_preserves_skills() -> None:
    compact = build_compact_candidate_profile(candidate())
    serialized = compact.model_dump_json()
    assert compact.personal_info.name is None
    assert "Python" in serialized and "FastAPI" in serialized
    assert "secret@example.com" not in serialized


def test_jd_trimming_removes_css_and_page_noise_but_keeps_requirements() -> None:
    raw = "举报\n.x{display:none;font-size:0}\n岗位职责\n开发 RAG\n任职要求\n熟悉 Python\n立即沟通"
    trimmed = trim_job_description(raw)
    assert "display:none" not in trimmed
    assert "举报" not in trimmed
    assert "岗位职责" in trimmed and "任职要求" in trimmed and "Python" in trimmed


def test_long_jd_keeps_head_and_requirement_tail() -> None:
    raw = "岗位职责\n" + ("开发 AI 应用。" * 700) + "\n任职要求\n熟悉 Python 和 FastAPI"
    trimmed = trim_job_description(raw)
    assert "岗位职责" in trimmed
    assert "任职要求" in trimmed
    assert "Python" in trimmed
    assert len(trimmed) <= 3600


def test_compact_output_truncates_unbounded_skill_lists_without_repair() -> None:
    payload = assessment().model_dump()
    payload["core_required_skills"] = [str(i) for i in range(6)]
    parsed = FastScreeningAssessment.model_validate(payload)
    assert parsed.core_required_skills == ["0", "1", "2", "3", "4"]


def test_progress_callback_receives_first_flash_before_completion() -> None:
    stages: list[str] = []
    result = pipeline().process(
        candidate(),
        "a" * 64,
        [job(1), job(2)],
        progress_callback=lambda event, _items: stages.append(event.stage.value),
    )
    assert stages.index("flash") < stages.index("completed")
    assert result.metrics.timing.time_to_first_result_seconds <= result.metrics.timing.total_elapsed_seconds


def test_quick_mode_never_creates_fake_scores() -> None:
    result = pipeline().process(candidate(), "a" * 64, [job(1), job(2)])
    assert all(item.match_score is None for item in result.items)


def test_twenty_job_golden_tiers_are_stable_on_warm_run() -> None:
    fast = ConcurrentFast(delay=0)
    matcher = Matcher()
    pipe = pipeline(fast=fast, matcher=matcher, local_cache={}, fast_cache={}, deep_cache={})
    markers = ["HIGH"] * 5 + ["MID"] * 5 + ["LOW"] * 5 + ["UNCERTAIN"] * 5
    jobs = [job(i, marker) for i, marker in enumerate(markers, 1)]
    cold = pipe.process(candidate(), "a" * 64, jobs)
    warm = pipe.process(candidate(), "a" * 64, jobs)
    assert [item.screening_tier for item in cold.items] == [
        item.screening_tier for item in warm.items
    ]
    assert len(cold.items) == 20
