import json

from jobpilot.llm import ModelTier
from jobpilot.models import (
    CandidateProfile,
    JobProfile,
    MatchResult,
    MatchScoreBreakdown,
)
from jobpilot.prompts.resume_optimization import RESUME_OPTIMIZATION_SYSTEM_PROMPT
from jobpilot.services import ResumeOptimizationService
from tests.fakes import FakeLLMClient


def _candidate() -> CandidateProfile:
    return CandidateProfile(
        personal_info={
            "name": "Private Name",
            "email": "private@example.com",
            "phone": "00000000000",
        },
        summary="专注 AI 应用开发。",
        education=[{"institution": "示例大学", "degree": "本科"}],
        skills={
            "programming_languages": ["Python"],
            "frameworks": ["Streamlit"],
            "other": ["DeepSeek API"],
        },
        projects=[
            {
                "name": "TripMind",
                "description": "负责开发 TripMind AI Agent",
                "highlights": ["使用 Python 开发 AI 应用"],
                "technologies": ["Python", "DeepSeek API"],
            }
        ],
    )


def _job() -> JobProfile:
    return JobProfile(
        job_title="AI 应用开发实习生",
        responsibilities=["开发 AI Agent"],
        required_skills=["Python", "Docker"],
        preferred_skills=["DeepSeek API"],
        keywords=["Python", "AI Agent", "Docker"],
    )


def _match() -> MatchResult:
    return MatchResult(
        scores=MatchScoreBreakdown(
            overall_score=82,
            skills_score=75,
            projects_score=100,
        ),
        matched_skills=[
            {
                "skill": "Python",
                "resume_evidence": "Python",
                "job_requirement": "Python",
                "match_type": "exact",
            },
            {
                "skill": "DeepSeek API",
                "resume_evidence": "DeepSeek API",
                "job_requirement": "DeepSeek API",
                "match_type": "exact",
            },
        ],
        missing_skills=[
            {
                "skill": "Docker",
                "importance": "required",
                "reason": "当前简历中未找到 Docker 证据。",
            }
        ],
        gaps=["当前简历中未找到 Docker 证据。"],
        summary="项目方向匹配，Docker 尚无证据。",
    )


def _item(**updates) -> dict:
    data = {
        "section": "projects",
        "source_name": "TripMind",
        "decision": "keep",
        "original": "使用 Python 开发 AI 应用",
        "suggested": None,
        "reason": "表述已经清晰并对应 Python 要求。",
        "expected_benefit": None,
        "supported_by": ["使用 Python 开发 AI 应用"],
        "related_job_requirements": ["Python"],
    }
    data.update(updates)
    return data


def _response(*, suggestions=None, keywords=None) -> str:
    return json.dumps(
        {
            "summary": "当前简历整体较成熟。",
            "suggestions": suggestions or [],
            "keyword_suggestions": keywords or [],
            "capability_gaps": ["Docker"],
            "warnings": ["不要虚构。"],
        },
        ensure_ascii=False,
    )


def test_excellent_resume_can_return_only_keep_and_zero_recommended() -> None:
    result = ResumeOptimizationService(
        FakeLLMClient([_response(suggestions=[_item()])])
    ).analyze(_candidate(), _job(), _match())

    assert result.suggestions
    assert all(item.decision == "keep" for item in result.suggestions)
    assert not any(item.decision == "recommended" for item in result.suggestions)
    assert "无需大范围修改" in result.summary


def test_optional_and_recommended_are_preserved_when_benefit_is_specific() -> None:
    optional = _item(
        decision="optional",
        suggested="负责开发 TripMind AI Agent，并注明使用 Python",
        reason="可让已有技术证据更靠近项目职责。",
        expected_benefit="帮助招聘方更快定位 Python 项目证据。",
    )
    recommended = _item(
        decision="recommended",
        original="负责开发 TripMind AI Agent",
        suggested="负责开发 TripMind AI Agent，使用 Python 完成核心功能",
        reason="岗位明确要求 Python 与 AI Agent 开发。",
        expected_benefit="让招聘方直接看到与 AI Agent 开发职责对应的 Python 证据。",
        supported_by=["负责开发 TripMind AI Agent", "Python"],
        related_job_requirements=["开发 AI Agent", "Python"],
    )
    result = ResumeOptimizationService(
        FakeLLMClient([_response(suggestions=[optional, recommended])])
    ).analyze(_candidate(), _job(), _match())

    decisions = {item.decision for item in result.suggestions}
    assert "optional" in decisions
    assert "recommended" in decisions


def test_missing_skill_is_never_promoted_into_suggested_resume_text() -> None:
    unsafe = _item(
        decision="recommended",
        suggested="使用 Python 和 Docker 开发 AI 应用",
        reason="Docker 是岗位要求。",
        expected_benefit="直接对应岗位的 Docker 技能要求。",
        related_job_requirements=["Docker"],
    )
    result = ResumeOptimizationService(
        FakeLLMClient(
            [
                _response(
                    suggestions=[unsafe],
                    keywords=[
                        {
                            "keyword": "Docker",
                            "status": "covered",
                            "evidence": "使用 Python 开发 AI 应用",
                            "guidance": "加入关键词。",
                        }
                    ],
                )
            ]
        )
    ).analyze(_candidate(), _job(), _match())

    assert not any("Docker" in (item.suggested or "") for item in result.suggestions)
    docker = next(item for item in result.keyword_suggestions if item.keyword == "Docker")
    assert docker.status == "gap_do_not_add"
    assert "不要直接写入简历" in docker.guidance


def test_any_gap_do_not_add_keyword_is_blocked_from_suggested_text() -> None:
    unsafe = _item(
        decision="recommended",
        suggested="使用 Python 和 Kubernetes 开发 AI 应用",
        reason="关键词对岗位有帮助。",
        expected_benefit="对应岗位的基础设施要求。",
        related_job_requirements=["Python"],
    )
    result = ResumeOptimizationService(
        FakeLLMClient(
            [
                _response(
                    suggestions=[unsafe],
                    keywords=[
                        {
                            "keyword": "Kubernetes",
                            "status": "gap_do_not_add",
                            "evidence": None,
                            "guidance": "没有证据，不能加入。",
                        }
                    ],
                )
            ]
        )
    ).analyze(_candidate(), _job(), _match())

    assert not any(
        "Kubernetes" in (item.suggested or "") for item in result.suggestions
    )


def test_keyword_strategy_prevents_stuffing_and_requires_grounded_emphasis() -> None:
    keywords = [
        {
            "keyword": "Python",
            "status": "covered",
            "evidence": "Python",
            "guidance": "重复加入 Python。",
        },
        {
            "keyword": "AI Agent",
            "status": "can_emphasize",
            "evidence": "负责开发 TripMind AI Agent",
            "guidance": "可在项目首句突出已有证据。",
        },
    ]
    result = ResumeOptimizationService(
        FakeLLMClient([_response(keywords=keywords)])
    ).analyze(_candidate(), _job(), _match())

    python = next(item for item in result.keyword_suggestions if item.keyword == "Python")
    agent = next(item for item in result.keyword_suggestions if item.keyword == "AI Agent")
    assert python.guidance == "已覆盖，无需重复堆叠。"
    assert agent.status == "can_emphasize"
    assert agent.evidence == "负责开发 TripMind AI Agent"


def test_nonexistent_source_is_rejected_and_near_synonym_is_downgraded() -> None:
    nonexistent = _item(source_name="不存在的公司")
    cosmetic = _item(
        decision="recommended",
        suggested="使用Python开发AI应用。",
        reason="措辞微调。",
        expected_benefit="更专业",
    )
    result = ResumeOptimizationService(
        FakeLLMClient([_response(suggestions=[nonexistent, cosmetic])])
    ).analyze(_candidate(), _job(), _match())

    assert not any(item.source_name == "不存在的公司" for item in result.suggestions)
    cosmetic_result = next(
        item for item in result.suggestions if item.original == "使用 Python 开发 AI 应用"
    )
    assert cosmetic_result.decision == "keep"
    assert cosmetic_result.suggested is None


def test_original_candidate_is_unchanged_and_private_fields_are_not_sent() -> None:
    candidate = _candidate()
    original = candidate.model_dump(mode="json")
    client = FakeLLMClient([_response(suggestions=[_item()])])

    ResumeOptimizationService(client).analyze(candidate, _job(), _match())

    assert candidate.model_dump(mode="json") == original
    call = client.calls[0]
    assert call["model_tier"] is ModelTier.PRO
    assert call["json_mode"] is True
    assert call["temperature"] == 0.0
    assert call["thinking"] is False
    assert "Private Name" not in call["user_prompt"]
    assert "private@example.com" not in call["user_prompt"]
    assert "00000000000" not in call["user_prompt"]
    assert "complete rewritten resume" in RESUME_OPTIMIZATION_SYSTEM_PROMPT
    assert "KEEP is a valid and desirable result" in RESUME_OPTIMIZATION_SYSTEM_PROMPT


def test_invalid_pro_output_gets_only_one_format_repair() -> None:
    client = FakeLLMClient(["invalid", _response(suggestions=[_item()])])

    result = ResumeOptimizationService(client).analyze(_candidate(), _job(), _match())

    assert result.suggestions
    assert [call["model_tier"] for call in client.calls] == [
        ModelTier.PRO,
        ModelTier.FLASH,
    ]
    assert "Original task input:" not in client.calls[1]["user_prompt"]
    assert "Repair format and schema only" in client.calls[1]["user_prompt"]
