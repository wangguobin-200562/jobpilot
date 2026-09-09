import json

import pytest

from jobpilot.llm import ModelTier, StructuredOutputError
from jobpilot.models import CandidateProfile, JobProfile
from jobpilot.prompts.matching_analysis import MATCHING_ANALYSIS_SYSTEM_PROMPT
from jobpilot.services import MatchingService, normalize_skill
from tests.fakes import FakeLLMClient


def _candidate() -> CandidateProfile:
    return CandidateProfile(
        personal_info={
            "name": "Private Name",
            "email": "private@example.com",
            "phone": "00000000000",
        },
        education=[
            {"institution": "示例大学", "degree": "本科", "details": ["CET-4"]}
        ],
        skills={
            "programming_languages": ["Python"],
            "frameworks": ["Streamlit"],
            "other": ["DeepSeek API", "Prompt Engineering", "Agent Workflow"],
        },
        experience=[
            {
                "company": "示例银行",
                "position": "数据支持实习生",
                "description": "整理业务数据",
                "technologies": ["Excel"],
            }
        ],
        projects=[
            {
                "name": "TripMind",
                "description": "AI 旅行 Agent",
                "highlights": ["设计自研 Agent Workflow", "调用 DeepSeek API"],
                "technologies": ["Python", "DeepSeek API", "Streamlit"],
            }
        ],
        languages=["英语 CET-4"],
    )


def _job() -> JobProfile:
    return JobProfile(
        job_title="AI 应用开发实习生",
        responsibilities=["开发 AI Agent", "对接大模型 API"],
        required_skills=["Python", "LLM API", "LangGraph", "FastAPI"],
        preferred_skills=["Docker"],
        education_requirements="本科及以上",
        language_requirements=["英语 CET-4"],
    )


def _semantic_response() -> str:
    return json.dumps(
        {
            "skill_analysis": [
                {
                    "job_skill": "LLM API",
                    "candidate_evidence": "TripMind 调用 DeepSeek API",
                    "classification": "matched",
                    "reason": "具体大模型 API 调用可证明该能力。",
                },
                {
                    "job_skill": "LangGraph",
                    "candidate_evidence": "TripMind 的自研 Agent Workflow",
                    "classification": "matched",
                    "reason": "相关但未证明使用 LangGraph。",
                },
                {
                    "job_skill": "FastAPI",
                    "candidate_evidence": "Streamlit",
                    "classification": "matched",
                    "reason": "均用于 Python Web 应用。",
                },
                {
                    "job_skill": "Docker",
                    "candidate_evidence": None,
                    "classification": "missing",
                    "reason": "当前简历中未找到 Docker 证据。",
                },
            ],
            "experience_relevance": [
                {
                    "experience_reference": "示例银行数据支持实习",
                    "job_requirement": "开发 AI Agent",
                    "candidate_evidence": "整理业务数据",
                    "relevance": "medium",
                    "assessment": "具有数据工作基础，但与 AI 开发并非直接对应。",
                }
            ],
            "project_relevance": [
                {
                    "project_reference": "TripMind",
                    "job_requirement": "开发 AI Agent、对接大模型 API",
                    "candidate_evidence": "AI 旅行 Agent；调用 DeepSeek API",
                    "relevance": "high",
                    "assessment": "项目与核心岗位职责高度相关。",
                }
            ],
            "education_other_analysis": [
                {
                    "job_requirement": "本科及以上",
                    "candidate_evidence": "示例大学，本科",
                    "classification": "matched",
                    "reason": "学历要求匹配。",
                },
                {
                    "job_requirement": "英语 CET-4",
                    "candidate_evidence": "英语 CET-4",
                    "classification": "matched",
                    "reason": "语言要求匹配。",
                },
            ],
            "strengths": ["TripMind 提供了 AI Agent 项目证据"],
            "gaps": ["当前简历中未找到 Docker 使用证据"],
            "improvement_priorities": [],
            "summary": "项目经历与岗位核心职责相关。",
        },
        ensure_ascii=False,
    )


def test_matching_uses_pro_and_python_computes_expected_result() -> None:
    client = FakeLLMClient([_semantic_response()])

    result = MatchingService(client).analyze(_candidate(), _job())

    assert client.calls[0]["model_tier"] is ModelTier.PRO
    assert client.calls[0]["json_mode"] is True
    assert client.calls[0]["temperature"] == 0.0
    assert client.calls[0]["thinking"] is False
    assert result.scores.skills_score == 50.0
    assert result.scores.experience_score == 70.0
    assert result.scores.projects_score == 100.0
    assert result.scores.education_other_score == 100.0
    assert result.scores.overall_score == 72.5


def test_python_exact_match_is_kept_as_exact() -> None:
    result = MatchingService(FakeLLMClient([_semantic_response()])).analyze(
        _candidate(), _job()
    )

    python_match = next(item for item in result.matched_skills if item.skill == "Python")
    assert normalize_skill("Python") == normalize_skill("python")
    assert python_match.match_type == "exact"


def test_llm_api_and_deepseek_api_can_be_semantic_match() -> None:
    result = MatchingService(FakeLLMClient([_semantic_response()])).analyze(
        _candidate(), _job()
    )

    match = next(item for item in result.matched_skills if item.skill == "LLM API")
    assert match.match_type == "semantic"
    assert "DeepSeek API" in match.resume_evidence


def test_langgraph_and_custom_agent_workflow_is_capped_at_partial() -> None:
    result = MatchingService(FakeLLMClient([_semantic_response()])).analyze(
        _candidate(), _job()
    )

    partial = next(
        item for item in result.partial_matches if item.job_requirement == "LangGraph"
    )
    assert "Agent Workflow" in partial.resume_evidence


def test_fastapi_and_streamlit_cannot_be_promoted_to_match() -> None:
    result = MatchingService(FakeLLMClient([_semantic_response()])).analyze(
        _candidate(), _job()
    )

    missing = next(item for item in result.missing_skills if item.skill == "FastAPI")
    assert missing.importance == "required"
    assert not any(item.skill == "FastAPI" for item in result.matched_skills)


def test_no_candidate_evidence_becomes_missing_with_importance() -> None:
    result = MatchingService(FakeLLMClient([_semantic_response()])).analyze(
        _candidate(), _job()
    )

    docker = next(item for item in result.missing_skills if item.skill == "Docker")
    assert docker.importance == "preferred"
    assert "当前简历" in docker.reason


def test_prompt_contains_profiles_but_excludes_personal_contact_data() -> None:
    client = FakeLLMClient([_semantic_response()])

    MatchingService(client).analyze(_candidate(), _job())

    prompt = client.calls[0]["user_prompt"]
    assert "TripMind" in prompt
    assert "AI 应用开发实习生" in prompt
    assert "private@example.com" not in prompt
    assert "00000000000" not in prompt
    assert "Private Name" not in prompt
    assert "Do not produce an overall match score" in MATCHING_ANALYSIS_SYSTEM_PROMPT
    assert "Python will calculate all" in MATCHING_ANALYSIS_SYSTEM_PROMPT


def test_invalid_semantic_json_uses_one_controlled_flash_repair() -> None:
    client = FakeLLMClient(["invalid", _semantic_response()])

    result = MatchingService(client).analyze(_candidate(), _job())

    assert result.scores.overall_score == 72.5
    assert len(client.calls) == 2
    assert client.calls[0]["model_tier"] is ModelTier.PRO
    assert client.calls[1]["model_tier"] is ModelTier.FLASH


def test_score_field_is_removed_by_format_only_flash_repair() -> None:
    invalid_payload = json.loads(_semantic_response())
    invalid_payload["overall_score"] = 87
    client = FakeLLMClient(
        [json.dumps(invalid_payload, ensure_ascii=False), _semantic_response()]
    )

    result = MatchingService(client).analyze(_candidate(), _job())

    assert result.scores.overall_score == 72.5
    assert len(client.calls) == 2
    repair_prompt = client.calls[1]["user_prompt"]
    assert "Original task input:" not in repair_prompt
    assert "Do not add or change semantic classifications" in repair_prompt
    assert "Remove every numeric score" in repair_prompt


def test_matching_repair_is_attempted_at_most_once() -> None:
    client = FakeLLMClient(["invalid", "still invalid", _semantic_response()])

    with pytest.raises(StructuredOutputError):
        MatchingService(client).analyze(_candidate(), _job())

    assert len(client.calls) == 2


def test_empty_pro_response_is_not_reanalyzed_by_flash() -> None:
    client = FakeLLMClient([""])

    with pytest.raises(StructuredOutputError):
        MatchingService(client).analyze(_candidate(), _job())

    assert len(client.calls) == 1


def test_null_project_evidence_is_valid_and_rendered_as_missing_evidence() -> None:
    payload = json.loads(_semantic_response())
    payload["project_relevance"].append(
        {
            "project_reference": "其他项目",
            "job_requirement": "容器化部署",
            "candidate_evidence": None,
            "relevance": "none",
            "assessment": "当前简历项目中未找到相关证据。",
        }
    )

    result = MatchingService(
        FakeLLMClient([json.dumps(payload, ensure_ascii=False)])
    ).analyze(_candidate(), _job())

    evidence = next(
        item
        for item in result.evidence
        if item.job_requirement == "容器化部署"
    )
    assert evidence.resume_evidence == "未找到相关证据"
