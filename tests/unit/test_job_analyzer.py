from pathlib import Path

import pytest

from jobpilot.llm import EmptyJobProfileError, ModelTier, StructuredOutputError
from jobpilot.prompts.job_analysis import (
    JOB_ANALYSIS_SYSTEM_PROMPT,
    build_job_analysis_prompt,
)
from jobpilot.services import (
    MAX_JOB_DESCRIPTION_CHARACTERS,
    MIN_JOB_DESCRIPTION_CHARACTERS,
    EmptyJobDescriptionError,
    JobAnalyzer,
    LongJobDescriptionError,
    ShortJobDescriptionError,
    validate_job_description,
)
from jobpilot.services.resume_analyzer import ResumeAnalyzer
from tests.fakes import FakeLLMClient


VALID_JD = (
    "AI 应用开发实习生\n"
    "岗位职责：使用 Python 开发 AI 应用并调用大模型 API。\n"
    "任职要求：熟悉 Python 和 Prompt Engineering；"
    "有 LangChain 项目经验优先；本科及以上。"
)
VALID_PROFILE = (
    '{"job_title":"AI 应用开发实习生",'
    '"responsibilities":["使用 Python 开发 AI 应用","调用大模型 API"],'
    '"required_skills":["Python","Prompt Engineering"],'
    '"preferred_skills":["LangChain"],'
    '"education_requirements":"本科及以上"}'
)


def test_job_analyzer_returns_profile_with_flash_extraction_parameters() -> None:
    client = FakeLLMClient([VALID_PROFILE])

    profile = JobAnalyzer(client).analyze(VALID_JD)

    assert profile.job_title == "AI 应用开发实习生"
    assert profile.required_skills == ["Python", "Prompt Engineering"]
    assert client.calls[0]["model_tier"] is ModelTier.FLASH
    assert client.calls[0]["json_mode"] is True
    assert client.calls[0]["temperature"] == 0.0
    assert client.calls[0]["thinking"] is False


def test_chinese_jd_produces_non_empty_job_profile_without_resume_analyzer(
    monkeypatch,
) -> None:
    def unexpected_resume_call(*args, **kwargs):
        raise AssertionError("ResumeAnalyzer must not be called by JD intelligence")

    monkeypatch.setattr(ResumeAnalyzer, "analyze", unexpected_resume_call)
    profile = JobAnalyzer(FakeLLMClient([VALID_PROFILE])).analyze(VALID_JD)

    assert profile.responsibilities
    assert profile.required_skills
    assert profile.preferred_skills == ["LangChain"]


def test_job_prompt_contains_jd_and_factual_extraction_rules() -> None:
    prompt = build_job_analysis_prompt(VALID_JD)

    assert f"<job_description>\n{VALID_JD}\n</job_description>" in prompt
    assert "Do not invent or infer requirements" in JOB_ANALYSIS_SYSTEM_PROMPT
    assert "required_skills" in JOB_ANALYSIS_SYSTEM_PROMPT
    assert "preferred_skills" in JOB_ANALYSIS_SYSTEM_PROMPT
    assert "Do not return an entirely empty JobProfile" in (
        JOB_ANALYSIS_SYSTEM_PROMPT
    )
    assert "LangChain" in JOB_ANALYSIS_SYSTEM_PROMPT


def test_job_analyzer_accepts_code_fenced_json() -> None:
    response = f"```json\n{VALID_PROFILE}\n```"

    profile = JobAnalyzer(FakeLLMClient([response])).analyze(VALID_JD)

    assert profile.job_title == "AI 应用开发实习生"


@pytest.mark.parametrize("responses", [["invalid", "still invalid"], ["", ""]])
def test_invalid_or_empty_responses_fail_after_one_repair(responses: list[str]) -> None:
    client = FakeLLMClient(responses)

    with pytest.raises(StructuredOutputError):
        JobAnalyzer(client).analyze(VALID_JD)

    assert len(client.calls) == 2
    assert all(call["model_tier"] is ModelTier.FLASH for call in client.calls)


@pytest.mark.parametrize(
    "response",
    [
        "{}",
        (
            '{"job_title":null,"company":null,"location":null,'
            '"employment_type":null,"salary_range":null,'
            '"responsibilities":[],"required_skills":[],"preferred_skills":[],'
            '"tools_and_technologies":[],"experience_requirements":null,'
            '"education_requirements":null,"language_requirements":[],'
            '"keywords":[],"benefits":[],"other_requirements":[]}'
        ),
    ],
)
def test_empty_job_profiles_are_rejected(response: str) -> None:
    client = FakeLLMClient([response])

    with pytest.raises(EmptyJobProfileError):
        JobAnalyzer(client).analyze(VALID_JD)

    assert len(client.calls) == 1


def test_valid_repair_succeeds_and_preserves_original_jd() -> None:
    client = FakeLLMClient(["not JSON", VALID_PROFILE])

    profile = JobAnalyzer(client).analyze(VALID_JD)

    assert profile.job_title == "AI 应用开发实习生"
    assert len(client.calls) == 2
    assert client.calls[1]["model_tier"] is ModelTier.FLASH
    assert client.calls[1]["temperature"] == 0.0
    assert client.calls[1]["thinking"] is False
    assert VALID_JD in client.calls[1]["user_prompt"]


def test_wrong_field_type_can_be_repaired_once() -> None:
    client = FakeLLMClient(['{"required_skills":"Python"}', VALID_PROFILE])

    profile = JobAnalyzer(client).analyze(VALID_JD)

    assert profile.required_skills == ["Python", "Prompt Engineering"]
    assert len(client.calls) == 2


def test_repaired_empty_job_profile_is_rejected() -> None:
    client = FakeLLMClient(["not JSON", "{}"])

    with pytest.raises(EmptyJobProfileError):
        JobAnalyzer(client).analyze(VALID_JD)

    assert len(client.calls) == 2


def test_job_description_validation_prevents_bad_inputs() -> None:
    with pytest.raises(EmptyJobDescriptionError):
        validate_job_description("  \n ")
    with pytest.raises(ShortJobDescriptionError):
        validate_job_description("Python开发")
    with pytest.raises(LongJobDescriptionError):
        validate_job_description("A" * (MAX_JOB_DESCRIPTION_CHARACTERS + 1))

    assert len(validate_job_description("A" * MIN_JOB_DESCRIPTION_CHARACTERS)) == (
        MIN_JOB_DESCRIPTION_CHARACTERS
    )


def test_job_service_does_not_hardcode_provider_model_names() -> None:
    service_source = Path("src/jobpilot/services/job_analyzer.py").read_text(
        encoding="utf-8"
    )

    assert "deepseek-v4-flash" not in service_source
    assert "deepseek-v4-pro" not in service_source
