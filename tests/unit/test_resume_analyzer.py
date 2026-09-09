from pathlib import Path

import pytest

from jobpilot.llm import EmptyCandidateProfileError, ModelTier, StructuredOutputError
from jobpilot.prompts.resume_analysis import RESUME_ANALYSIS_SYSTEM_PROMPT
from jobpilot.services import ResumeAnalyzer
from tests.fakes import FakeLLMClient


VALID_PROFILE = '{"personal_info":{"name":"Jane"},"skills":{"programming_languages":["Python"]}}'


def test_resume_analyzer_returns_candidate_profile() -> None:
    client = FakeLLMClient([VALID_PROFILE])

    profile = ResumeAnalyzer(client).analyze("Jane\nPython")

    assert profile.personal_info.name == "Jane"
    assert profile.skills.programming_languages == ["Python"]
    assert client.calls[0]["model_tier"] is ModelTier.FLASH
    assert client.calls[0]["json_mode"] is True
    assert client.calls[0]["temperature"] == 0.0
    assert client.calls[0]["thinking"] is False


def test_resume_text_is_included_in_user_message() -> None:
    client = FakeLLMClient([VALID_PROFILE])
    resume_text = "王国彬\n珠海科技学院\nTripMind AI 旅行规划 Agent"

    ResumeAnalyzer(client).analyze(resume_text)

    user_prompt = client.calls[0]["user_prompt"]
    assert resume_text in user_prompt
    assert f"<resume>\n{resume_text}\n</resume>" in user_prompt


def test_prompt_prioritizes_explicit_extraction_and_rejects_empty_profile() -> None:
    assert "Do not omit information that is explicitly present" in (
        RESUME_ANALYSIS_SYSTEM_PROMPT
    )
    assert "Do not return an entirely empty profile" in (
        RESUME_ANALYSIS_SYSTEM_PROMPT
    )
    assert "Example JSON output" in RESUME_ANALYSIS_SYSTEM_PROMPT
    assert "张三" in RESUME_ANALYSIS_SYSTEM_PROMPT


def test_main_prompt_does_not_embed_full_pydantic_json_schema() -> None:
    client = FakeLLMClient([VALID_PROFILE])

    ResumeAnalyzer(client).analyze("Jane\nPython")

    user_prompt = client.calls[0]["user_prompt"]
    assert '"$defs"' not in user_prompt
    assert '"properties"' not in user_prompt


def test_resume_analyzer_defaults_to_flash_tier() -> None:
    client = FakeLLMClient([VALID_PROFILE])

    ResumeAnalyzer(client).analyze("Jane\nPython")

    assert all(call["model_tier"] is ModelTier.FLASH for call in client.calls)


def test_invalid_then_valid_response_succeeds_after_one_repair() -> None:
    client = FakeLLMClient(["invalid", VALID_PROFILE])

    profile = ResumeAnalyzer(client).analyze("Jane\nPython")

    assert profile.personal_info.name == "Jane"
    assert len(client.calls) == 2
    assert client.calls[1]["model_tier"] is ModelTier.FLASH
    assert client.calls[1]["temperature"] == 0.0
    assert client.calls[1]["thinking"] is False
    assert "Jane\nPython" in client.calls[1]["user_prompt"]


def test_chinese_resume_sample_can_produce_non_empty_candidate_profile() -> None:
    response = (
        '{"personal_info":{"name":"张三"},"education":['
        '{"institution":"北京某大学","major":"计算机科学与技术"}],'
        '"skills":{"programming_languages":["Python","SQL"],'
        '"frameworks":["FastAPI"]},"projects":[{"name":"智能问答系统",'
        '"technologies":["Python","FastAPI"]}]}'
    )
    client = FakeLLMClient([response])

    profile = ResumeAnalyzer(client).analyze(
        "张三\n北京某大学\n计算机科学与技术\n技能：Python、SQL\n"
        "项目：智能问答系统，使用 Python 和 FastAPI"
    )

    assert profile.personal_info.name == "张三"
    assert profile.education[0].institution == "北京某大学"
    assert profile.skills.programming_languages == ["Python", "SQL"]
    assert profile.projects[0].name == "智能问答系统"


def test_two_invalid_responses_raise_structured_output_error() -> None:
    client = FakeLLMClient(["invalid", "still invalid"])

    with pytest.raises(StructuredOutputError):
        ResumeAnalyzer(client).analyze("Jane\nPython")

    assert len(client.calls) == 2


def test_empty_llm_responses_raise_structured_output_error() -> None:
    client = FakeLLMClient(["", ""])

    with pytest.raises(StructuredOutputError):
        ResumeAnalyzer(client).analyze("Jane\nPython")

    assert len(client.calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        "{}",
        (
            '{"personal_info":{"name":null,"email":null,"phone":null,'
            '"location":null},"summary":null,"education":[],"skills":{'
            '"programming_languages":[],"frameworks":[],"tools":[],'
            '"databases":[],"other":[]},"experience":[],"projects":[],'
            '"certifications":[],"languages":[]}'
        ),
    ],
)
def test_empty_candidate_profiles_are_rejected(response: str) -> None:
    client = FakeLLMClient([response])

    with pytest.raises(EmptyCandidateProfileError):
        ResumeAnalyzer(client).analyze("Jane\nPython")

    assert len(client.calls) == 1


def test_repaired_empty_candidate_profile_is_rejected() -> None:
    client = FakeLLMClient(["not JSON", "{}"])

    with pytest.raises(EmptyCandidateProfileError):
        ResumeAnalyzer(client).analyze("Jane\nPython")

    assert len(client.calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        '{"personal_info":{"name":"Jane"}}',
        '{"education":[{"institution":"Example University"}]}',
        '{"skills":{"programming_languages":["Python"]}}',
        '{"experience":[{"company":"Acme"}]}',
        '{"projects":[{"name":"JobPilot"}]}',
    ],
)
def test_any_supported_core_candidate_data_is_accepted(response: str) -> None:
    profile = ResumeAnalyzer(FakeLLMClient([response])).analyze("Resume text")

    assert profile is not None


def test_resume_service_does_not_hardcode_provider_model_names() -> None:
    service_source = Path(
        "src/jobpilot/services/resume_analyzer.py"
    ).read_text(encoding="utf-8")

    assert "deepseek-v4-flash" not in service_source
    assert "deepseek-v4-pro" not in service_source
