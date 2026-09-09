import pytest

from jobpilot.llm import (
    EmptyCandidateProfileError,
    LLMConfigurationError,
    LLMError,
    LLMRequestError,
    LLMTimeoutError,
    StructuredOutputError,
)
from jobpilot.ui.pages.resume_analysis import _localized_llm_error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            EmptyCandidateProfileError("provider detail"),
            "AI 未能从当前简历中提取有效信息，请重新分析。",
        ),
        (
            LLMConfigurationError("provider detail"),
            "AI 分析尚未配置，请完成 DeepSeek API Key 配置后重试。",
        ),
        (LLMTimeoutError("provider detail"), "AI 请求超时，请稍后重试。"),
        (
            LLMRequestError("provider detail"),
            "AI 服务暂时无法完成请求，请稍后重试。",
        ),
        (
            StructuredOutputError("provider detail"),
            "AI 返回结果无法转换为有效的候选人画像，请重新分析。",
        ),
        (LLMError("provider detail"), "AI 分析暂时无法完成，请稍后重试。"),
    ],
)
def test_llm_errors_are_localized_without_exposing_provider_detail(
    error: LLMError,
    expected: str,
) -> None:
    message = _localized_llm_error(error)

    assert message == expected
    assert "provider detail" not in message
