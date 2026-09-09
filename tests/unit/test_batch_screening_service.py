from dataclasses import dataclass, field

import pytest

from jobpilot.llm import LLMRequestError, ModelTier
from jobpilot.models import (
    BatchJobInput,
    BatchJobStatus,
    CandidateProfile,
    JobProfile,
    MatchResult,
    MatchScoreBreakdown,
    ScreeningTier,
    Skills,
)
from jobpilot.services import (
    BatchScreeningService,
    CandidateProfileRequiredError,
    batch_fingerprint,
)
from jobpilot.storage import ApplicationRepository


@dataclass
class FakeJobAnalyzer:
    calls: list[str] = field(default_factory=list)
    MODEL_TIER = ModelTier.FLASH

    def analyze(self, jd_text: str) -> JobProfile:
        self.calls.append(jd_text)
        if "JD_FAIL" in jd_text:
            raise LLMRequestError("provider detail must stay hidden")
        return JobProfile(
            company="模型公司",
            job_title=jd_text.split()[0],
            location="模型地点",
            responsibilities=[jd_text],
            required_skills=["Python"],
        )


@dataclass
class FakeMatchingService:
    calls: list[tuple[CandidateProfile, JobProfile]] = field(default_factory=list)
    match_failures: int = 0
    MODEL_TIER = ModelTier.PRO

    def analyze(self, candidate: CandidateProfile, job: JobProfile) -> MatchResult:
        self.calls.append((candidate, job))
        text = " ".join(job.responsibilities)
        if "MATCH_FAIL" in text and self.match_failures == 0:
            self.match_failures += 1
            raise LLMRequestError("provider detail must stay hidden")
        score = 90 if "HIGH" in text else 70 if "MID" in text else 40
        missing = []
        if "GAPS2" in text:
            missing = [
                {"skill": "Docker", "importance": "required", "reason": "无证据"},
                {"skill": "LangGraph", "importance": "required", "reason": "无证据"},
            ]
        return MatchResult(
            scores=MatchScoreBreakdown(overall_score=score, skills_score=score),
            missing_skills=missing,
            strengths=["虚构候选人具备 Python 证据"],
        )


def _candidate() -> CandidateProfile:
    return CandidateProfile(skills=Skills(programming_languages=["Python"]))


def _input(index: int, text: str, **metadata) -> BatchJobInput:
    return BatchJobInput(
        index=index,
        jd_text=text,
        raw_block=text,
        **metadata,
    )


def _service(repository=None, cache=None):
    analyzer = FakeJobAnalyzer()
    matcher = FakeMatchingService()
    service = BatchScreeningService(
        analyzer, matcher, repository=repository, item_cache=cache
    )
    return service, analyzer, matcher


def test_candidate_profile_is_required() -> None:
    service, _, _ = _service()
    with pytest.raises(CandidateProfileRequiredError):
        service.process(None, None, [_input(1, "HIGH one"), _input(2, "MID two")])


def test_existing_analyzer_and_matcher_are_reused_with_expected_tiers() -> None:
    service, analyzer, matcher = _service()
    result = service.process(
        _candidate(), "a" * 64, [_input(1, "HIGH one"), _input(2, "MID two")]
    )
    assert len(analyzer.calls) == 2
    assert len(matcher.calls) == 2
    assert analyzer.MODEL_TIER is ModelTier.FLASH
    assert matcher.MODEL_TIER is ModelTier.PRO
    assert [item.screening_tier for item in result.items] == [
        ScreeningTier.PRIORITY,
        ScreeningTier.RECOMMENDED,
    ]


def test_explicit_metadata_overrides_model_extraction() -> None:
    service, _, _ = _service()
    result = service.process(
        _candidate(),
        "a" * 64,
        [
            _input(1, "HIGH one", company="显式公司", job_title="显式岗位", location="广州"),
            _input(2, "MID two"),
        ],
    )
    item = next(item for item in result.items if item.index == 1)
    assert (item.company, item.job_title, item.location) == ("显式公司", "显式岗位", "广州")
    assert item.job_profile.company == "显式公司"


def test_one_failure_does_not_stop_remaining_items() -> None:
    service, analyzer, matcher = _service()
    result = service.process(
        _candidate(),
        "a" * 64,
        [_input(1, "HIGH one"), _input(2, "JD_FAIL bad"), _input(3, "MID three")],
    )
    assert result.completed_count == 2
    assert result.failed_count == 1
    assert result.items[-1].status is BatchJobStatus.FAILED
    assert "provider detail" not in result.items[-1].error_message
    assert len(analyzer.calls) == 3
    assert len(matcher.calls) == 2


def test_session_cache_skips_both_provider_services() -> None:
    cache = {}
    service, analyzer, matcher = _service(cache=cache)
    inputs = [_input(1, "HIGH one"), _input(2, "MID two")]
    first = service.process(_candidate(), "a" * 64, inputs)
    second = service.process(_candidate(), "a" * 64, inputs)
    assert first.cached_count == 0
    assert second.cached_count == 2
    assert len(analyzer.calls) == 2
    assert len(matcher.calls) == 2


def test_modifying_one_jd_reruns_only_that_item() -> None:
    cache = {}
    service, analyzer, matcher = _service(cache=cache)
    service.process(
        _candidate(), "a" * 64, [_input(1, "HIGH one"), _input(2, "MID two")]
    )
    result = service.process(
        _candidate(), "a" * 64, [_input(1, "HIGH changed"), _input(2, "MID two")]
    )
    assert result.cached_count == 1
    assert result.newly_analyzed_count == 1
    assert len(analyzer.calls) == 3
    assert len(matcher.calls) == 3


def test_repository_snapshot_skips_provider_calls(tmp_path) -> None:
    repository = ApplicationRepository(tmp_path / "jobpilot.db")
    jd = "HIGH repository cached job"
    profile = JobProfile(job_title="缓存岗位", required_skills=["Python"])
    match = MatchResult(scores=MatchScoreBreakdown(overall_score=91))
    repository.create_application(
        company="缓存公司",
        job_title="缓存岗位",
        jd_text=jd,
        job_profile=profile,
        match_score=91,
        match_result=match,
    )
    service, analyzer, matcher = _service(repository=repository)
    result = service.process(
        _candidate(), "a" * 64, [_input(1, jd), _input(2, "MID new")]
    )
    assert result.cached_count == 1
    assert len(analyzer.calls) == 1
    assert len(matcher.calls) == 1


def test_failed_matching_retry_reuses_successful_job_profile() -> None:
    service, analyzer, matcher = _service()
    result = service.process(
        _candidate(),
        "a" * 64,
        [_input(1, "MATCH_FAIL one"), _input(2, "MID two")],
    )
    failed = result.items[-1]
    assert failed.job_profile is not None
    retried = service.retry_item(_candidate(), "a" * 64, failed)
    assert retried.status is BatchJobStatus.COMPLETED
    assert len(analyzer.calls) == 2
    assert len(matcher.calls) == 3


def test_result_counts_and_sorting_are_deterministic() -> None:
    service, _, _ = _service()
    result = service.process(
        _candidate(),
        "a" * 64,
        [
            _input(1, "MID one"),
            _input(2, "HIGH two GAPS2"),
            _input(3, "LOW three"),
        ],
    )
    assert result.total_count == 3
    assert result.completed_count == 3
    assert result.failed_count == 0
    assert [item.index for item in result.items] == [2, 1, 3]
    assert result.items[0].screening_tier is ScreeningTier.RECOMMENDED


def test_batch_fingerprint_depends_on_resume_and_ordered_jds() -> None:
    inputs = [_input(1, "HIGH one"), _input(2, "MID two")]
    original = batch_fingerprint("a" * 64, inputs)
    assert original != batch_fingerprint("b" * 64, inputs)
    assert original != batch_fingerprint("a" * 64, list(reversed(inputs)))


def test_progress_callback_reports_both_stages_for_every_item() -> None:
    service, _, _ = _service()
    events: list[tuple[int, int, BatchJobStatus]] = []
    service.process(
        _candidate(),
        "a" * 64,
        [_input(1, "HIGH one"), _input(2, "MID two")],
        progress_callback=lambda index, total, status: events.append(
            (index, total, status)
        ),
    )
    assert events == [
        (1, 2, BatchJobStatus.ANALYZING_JD),
        (1, 2, BatchJobStatus.MATCHING),
        (2, 2, BatchJobStatus.ANALYZING_JD),
        (2, 2, BatchJobStatus.MATCHING),
    ]
