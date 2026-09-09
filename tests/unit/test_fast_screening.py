from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from jobpilot.llm import ModelTier
from jobpilot.models import (
    AssessmentConfidence,
    BatchJobInput,
    BatchScreeningResult,
    CandidateProfile,
    ExperienceItem,
    FastRelevance,
    FastScreeningAssessment,
    LocalScreeningDecision,
    MatchResult,
    MatchScoreBreakdown,
    PersonalInfo,
    ScreeningMode,
    ScreeningTier,
    Skills,
)
from jobpilot.services import (
    FastScreeningPipeline,
    FastScreeningService,
    LocalPreScreenService,
    candidate_fast_screening_summary,
    should_run_pro,
)
from tests.fakes import FakeLLMClient


def _candidate() -> CandidateProfile:
    return CandidateProfile(
        personal_info=PersonalInfo(
            name="测试姓名", email="private@example.com", phone="00000000000"
        ),
        skills=Skills(
            programming_languages=["Python"],
            frameworks=["FastAPI"],
            databases=["SQL"],
            tools=["Git"],
        ),
        experience=[ExperienceItem(
            position="AI 应用开发实习生",
            description="测试姓名曾使用 private@example.com 与 00000000000 作为测试数据。",
        )],
    )


def _input(index: int, marker: str) -> BatchJobInput:
    text = f"{marker} 岗位{index}职责：参与 AI 应用开发、接口建设和功能测试。任职要求：熟悉 Python，具备良好的沟通和学习能力。"
    return BatchJobInput(index=index, job_title=f"岗位{index}", jd_text=text, raw_block=text)


def _assessment(relevance: FastRelevance, confidence=AssessmentConfidence.HIGH):
    return FastScreeningAssessment(
        job_title="AI 应用工程师",
        core_required_skills=["Python"],
        matched_core_skills=["Python"],
        missing_core_skills=[],
        hard_requirement_risks=[],
        relevance=relevance,
        confidence=confidence,
        reason="核心方向相关。",
    )


@dataclass
class FakeFastService:
    calls: list[str] = field(default_factory=list)

    def assess(self, candidate, job_input):
        del candidate
        self.calls.append(job_input.jd_text)
        if "FLASH_FAIL" in job_input.jd_text:
            raise RuntimeError("private provider detail")
        if "HIGH" in job_input.jd_text:
            return _assessment(FastRelevance.HIGH)
        if "MEDIUM_UNCERTAIN" in job_input.jd_text:
            return _assessment(FastRelevance.MEDIUM, AssessmentConfidence.LOW)
        if "MEDIUM" in job_input.jd_text:
            return _assessment(FastRelevance.MEDIUM)
        return _assessment(FastRelevance.LOW)


@dataclass
class FakeMatcher:
    calls: list[str] = field(default_factory=list)

    def analyze(self, candidate, job):
        del candidate
        text = " ".join(job.responsibilities)
        self.calls.append(text)
        if "PRO_FAIL" in text:
            raise RuntimeError("private provider detail")
        score = 88 if "HIGH" in text else 68
        return MatchResult(
            scores=MatchScoreBreakdown(overall_score=score, skills_score=score),
            strengths=["具备 Python 证据"],
        )


class StepTimer:
    def __init__(self):
        self.value = -1.0

    def __call__(self):
        self.value += 1.0
        return self.value


def _pipeline(*, local_cache=None, fast_cache=None, deep_cache=None, deep_service=None):
    fast = FakeFastService()
    matcher = FakeMatcher()
    pipeline = FastScreeningPipeline(
        LocalPreScreenService(),
        fast,
        matcher,
        deep_service=deep_service,
        local_cache=local_cache,
        fast_cache=fast_cache,
        deep_cache=deep_cache,
        timer=StepTimer(),
    )
    return pipeline, fast, matcher


def test_local_rejects_internship_candidate_for_senior_hard_requirement() -> None:
    result = LocalPreScreenService().assess(
        _candidate(),
        _input(1, "高级工程师，明确要求 5 年以上工作经验。"),
    )
    assert result.decision is LocalScreeningDecision.REJECT


def test_local_rejects_clearly_unrelated_core_stack() -> None:
    result = LocalPreScreenService().assess(
        _candidate(),
        _input(1, "核心技术栈要求 Java、Spring Boot 和 Spring Cloud。"),
    )
    assert result.decision is LocalScreeningDecision.REJECT


def test_local_does_not_reject_minor_skill_gap() -> None:
    result = LocalPreScreenService().assess(
        _candidate(), _input(1, "Python 岗位，加分项为 Docker 和 LangGraph。")
    )
    assert result.decision is not LocalScreeningDecision.REJECT


def test_uncertain_local_result_passes_to_next_stage() -> None:
    empty = CandidateProfile()
    result = LocalPreScreenService().assess(
        empty, _input(1, "岗位明确要求具备业务分析能力，但具体技术方向未说明。")
    )
    assert result.decision is LocalScreeningDecision.UNCERTAIN


def test_fast_assessment_schema_has_no_final_score() -> None:
    assessment = _assessment(FastRelevance.HIGH)
    assert "score" not in assessment.model_dump()
    with pytest.raises(ValidationError):
        FastScreeningAssessment.model_validate({**assessment.model_dump(), "score": 90})


def test_fast_prompt_excludes_name_phone_and_email() -> None:
    response = _assessment(FastRelevance.HIGH).model_dump_json()
    client = FakeLLMClient([response])
    FastScreeningService(client).assess(_candidate(), _input(1, "HIGH"))
    call = client.calls[0]
    assert call["model_tier"] is ModelTier.FLASH
    assert call["json_mode"] is True
    assert call["thinking"] is False
    assert call["max_tokens"] == 1200
    assert "decision_confidence" in call["user_prompt"]
    assert "测试姓名" not in call["user_prompt"]
    assert "private@example.com" not in call["user_prompt"]
    assert "00000000000" not in call["user_prompt"]


def test_candidate_summary_has_no_personal_info() -> None:
    summary = candidate_fast_screening_summary(_candidate())
    assert "personal_info" not in summary


def test_pro_gate_rules() -> None:
    passed = LocalPreScreenService().assess(_candidate(), _input(1, "Python"))
    assert not should_run_pro(_assessment(FastRelevance.HIGH), passed)
    assert should_run_pro(
        _assessment(FastRelevance.HIGH, AssessmentConfidence.MEDIUM), passed
    )
    assert not should_run_pro(_assessment(FastRelevance.LOW), passed)
    assert not should_run_pro(_assessment(FastRelevance.MEDIUM), passed)
    assert should_run_pro(
        _assessment(FastRelevance.MEDIUM, AssessmentConfidence.LOW), passed
    )


def test_twenty_jobs_do_not_force_twenty_pro_calls_and_results_are_sorted() -> None:
    pipeline, fast, matcher = _pipeline()
    markers = ["HIGH"] * 5 + ["MEDIUM_UNCERTAIN"] * 5 + ["MEDIUM"] * 5 + ["LOW"] * 5
    result = pipeline.process(
        _candidate(), "a" * 64, [_input(i, marker) for i, marker in enumerate(markers, 1)]
    )
    assert len(fast.calls) == 20
    assert len(matcher.calls) == 5
    assert result.metrics.pro_provider_calls == 5
    assert result.items[0].screening_tier is ScreeningTier.PRIORITY
    assert result.items[-1].screening_tier is ScreeningTier.LOW_PRIORITY


def test_cache_reduces_calls_and_changed_one_jd_only_reruns_one() -> None:
    local_cache, fast_cache, deep_cache = {}, {}, {}
    pipeline, fast, matcher = _pipeline(
        local_cache=local_cache, fast_cache=fast_cache, deep_cache=deep_cache
    )
    original = [_input(1, "MEDIUM_UNCERTAIN"), _input(2, "MEDIUM")]
    pipeline.process(_candidate(), "a" * 64, original)
    repeated = pipeline.process(_candidate(), "a" * 64, original)
    assert repeated.metrics.cache_hits == 2
    assert (len(fast.calls), len(matcher.calls)) == (2, 1)
    changed = [_input(1, "MEDIUM_UNCERTAIN changed"), _input(2, "MEDIUM")]
    pipeline.process(_candidate(), "a" * 64, changed)
    assert (len(fast.calls), len(matcher.calls)) == (3, 2)


def test_failures_are_isolated_and_pro_failure_keeps_fast_result() -> None:
    pipeline, _, _ = _pipeline()
    result = pipeline.process(
        _candidate(),
        "a" * 64,
        [_input(1, "FLASH_FAIL"), _input(2, "MEDIUM_UNCERTAIN PRO_FAIL"), _input(3, "MEDIUM")],
    )
    by_index = {item.job_input.index: item for item in result.items}
    assert by_index[1].assessment is None
    assert by_index[2].deep_match is False
    assert by_index[2].deep_analysis_failed is True
    assert "快速判断" in by_index[2].screening_reason
    assert by_index[3].screening_tier is ScreeningTier.RECOMMENDED


def test_progressive_events_expose_local_then_each_flash_and_pro() -> None:
    pipeline, _, _ = _pipeline()
    events = []
    pipeline.process(
        _candidate(),
        "a" * 64,
        [_input(1, "MEDIUM_UNCERTAIN"), _input(2, "LOW")],
        progress_callback=lambda event, snapshot: events.append(
            (event.stage.value, event.visible_results, len(snapshot))
        ),
    )
    assert events[0] == ("local", 2, 2)
    assert [event[0] for event in events].count("flash") == 2
    assert [event[0] for event in events].count("pro") == 1
    assert events[-1][0] == "completed"


def test_quick_is_default_and_deep_mode_delegates_to_existing_service() -> None:
    class DeepService:
        def __init__(self):
            self.calls = 0

        def process(self, candidate, fingerprint, inputs):
            del candidate, fingerprint, inputs
            self.calls += 1
            return BatchScreeningResult(
                items=[], total_count=0, completed_count=0, failed_count=0,
                cached_count=0, newly_analyzed_count=0,
            )

    deep = DeepService()
    pipeline, fast, _ = _pipeline(deep_service=deep)
    pipeline.process(_candidate(), "a" * 64, [_input(1, "LOW"), _input(2, "LOW")])
    assert len(fast.calls) == 2
    deep_result = pipeline.process(
        _candidate(), "a" * 64, [_input(1, "LOW"), _input(2, "LOW")],
        mode=ScreeningMode.DEEP,
    )
    assert isinstance(deep_result, BatchScreeningResult)
    assert deep.calls == 1


def test_fast_only_has_no_fake_score_but_deep_uses_match_result_score() -> None:
    pipeline, _, _ = _pipeline()
    result = pipeline.process(
        _candidate(), "a" * 64, [_input(1, "MEDIUM"), _input(2, "MEDIUM_UNCERTAIN")]
    )
    by_index = {item.job_input.index: item for item in result.items}
    assert by_index[1].deep_match is False
    assert by_index[1].match_score is None
    assert by_index[2].deep_match is True
    assert by_index[2].match_score == by_index[2].match_result.scores.overall_score == 68


def test_timing_and_provider_metrics_are_produced_without_waiting() -> None:
    pipeline, _, _ = _pipeline()
    result = pipeline.process(
        _candidate(), "a" * 64, [_input(1, "MEDIUM_UNCERTAIN"), _input(2, "LOW")]
    )
    assert result.metrics.flash_provider_calls == 2
    assert result.metrics.pro_provider_calls == 1
    assert result.metrics.timing.local_seconds >= 0
    assert result.metrics.timing.flash_seconds >= 0
    assert result.metrics.timing.pro_seconds >= 0
    assert result.metrics.timing.total_elapsed_seconds >= 0
    assert result.metrics.timing.time_to_first_result_seconds >= 0
    assert result.metrics.timeline


def test_fast_pipeline_never_depends_on_optimization_service() -> None:
    import jobpilot.services.fast_screening_pipeline as module

    source_names = set(module.__dict__)
    assert "ResumeOptimizationService" not in source_names
