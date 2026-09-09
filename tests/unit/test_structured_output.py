import pytest

from jobpilot.llm import StructuredOutputError
from jobpilot.llm.structured_output import parse_structured_output
from jobpilot.models import CandidateProfile, SemanticMatchAnalysis


@pytest.mark.parametrize(
    "response",
    [
        '{"personal_info":{"name":"Jane"}}',
        '```json\n{"personal_info":{"name":"Jane"}}\n```',
        '```\n{"personal_info":{"name":"Jane"}}\n```',
        'Here is the result: {"personal_info":{"name":"Jane"}} Done.',
    ],
)
def test_supported_json_wrappers_validate(response: str) -> None:
    profile = parse_structured_output(response, CandidateProfile)

    assert profile.personal_info.name == "Jane"


def test_empty_response_is_rejected() -> None:
    with pytest.raises(StructuredOutputError):
        parse_structured_output("", CandidateProfile)


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(StructuredOutputError):
        parse_structured_output('{"name":', CandidateProfile)


def test_pydantic_validation_error_is_rejected() -> None:
    with pytest.raises(StructuredOutputError):
        parse_structured_output(
            '{"skills":{"programming_languages":"Python"}}',
            CandidateProfile,
        )


def test_validation_diagnostics_report_fields_without_values(caplog) -> None:
    response = (
        '{"skill_analysis":[{"job_skill":"PRIVATE-VALUE",'
        '"candidate_evidence":null,"classification":"MATCHED",'
        '"reason":"PRIVATE-REASON"}],"overall_score":87}'
    )

    with pytest.raises(StructuredOutputError):
        parse_structured_output(response, SemanticMatchAnalysis)

    log_text = caplog.text
    assert "response_content_length=" in log_text
    assert "skill_analysis.0.classification" in log_text
    assert "overall_score" in log_text
    assert "PRIVATE-VALUE" not in log_text
    assert "PRIVATE-REASON" not in log_text
