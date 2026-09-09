import pytest

from jobpilot.llm import (
    EmptyJobProfileError,
    LLMConfigurationError,
    LLMError,
    LLMRequestError,
    LLMTimeoutError,
    StructuredOutputError,
)
from jobpilot.services import (
    EmptyJobDescriptionError,
    LongJobDescriptionError,
    ShortJobDescriptionError,
)
from jobpilot.ui.pages.job_match import (
    _localized_job_input_error,
    _localized_job_llm_error,
    _localized_matching_error,
)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (EmptyJobDescriptionError("detail"), "请先粘贴岗位描述。"),
        (
            ShortJobDescriptionError("detail"),
            "岗位描述内容过短，请粘贴更完整的 JD 后再分析。",
        ),
        (
            LongJobDescriptionError("detail"),
            "岗位描述内容过长，请精简至 20,000 个字符以内后再分析。",
        ),
    ],
)
def test_job_input_errors_are_localized_without_internal_details(
    error, expected: str
) -> None:
    message = _localized_job_input_error(error)

    assert message == expected
    assert "detail" not in message


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            EmptyJobProfileError("provider detail"),
            "AI 未能从当前岗位描述中提取有效信息，请检查 JD 后重新分析。",
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
            "AI 返回结果无法转换为有效的岗位画像，请重新分析。",
        ),
        (LLMError("provider detail"), "AI 分析暂时无法完成，请稍后重试。"),
    ],
)
def test_job_llm_errors_are_localized_without_provider_details(
    error: LLMError, expected: str
) -> None:
    message = _localized_job_llm_error(error)

    assert message == expected
    assert "provider detail" not in message


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            LLMConfigurationError("provider detail"),
            "AI 分析尚未配置，请完成 DeepSeek API Key 配置后重试。",
        ),
        (
            LLMTimeoutError("provider detail"),
            "岗位匹配分析请求超时，请稍后重试。",
        ),
        (
            LLMRequestError("provider detail"),
            "AI 服务暂时无法完成岗位匹配分析，请稍后重试。",
        ),
        (
            StructuredOutputError("provider detail"),
            "AI 返回的匹配分析结果无法解析，请重新分析。",
        ),
    ],
)
def test_matching_errors_are_localized_without_provider_details(
    error: LLMError, expected: str
) -> None:
    message = _localized_matching_error(error)

    assert message == expected
    assert "provider detail" not in message
