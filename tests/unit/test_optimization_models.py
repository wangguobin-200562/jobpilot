import pytest
from pydantic import ValidationError

from jobpilot.models import KeywordSuggestion, ResumeSuggestion


def _suggestion(**updates) -> dict:
    data = {
        "section": "projects",
        "source_name": "TripMind",
        "decision": "keep",
        "original": "使用 Python 开发 AI Agent",
        "suggested": None,
        "reason": "当前表达已清楚对应岗位要求。",
        "expected_benefit": None,
        "supported_by": ["使用 Python 开发 AI Agent"],
        "related_job_requirements": ["开发 AI Agent"],
    }
    data.update(updates)
    return data


def test_keep_does_not_require_suggested_text() -> None:
    item = ResumeSuggestion.model_validate(_suggestion())

    assert item.decision == "keep"
    assert item.suggested is None


def test_optional_may_include_suggested_text() -> None:
    item = ResumeSuggestion.model_validate(
        _suggestion(
            decision="optional",
            suggested="突出已有 Python 项目证据",
            expected_benefit="帮助招聘方更快看到与 Python 要求对应的证据。",
        )
    )

    assert item.suggested == "突出已有 Python 项目证据"


def test_recommended_requires_suggestion_and_specific_benefit_field() -> None:
    with pytest.raises(ValidationError):
        ResumeSuggestion.model_validate(
            _suggestion(decision="recommended", suggested=None)
        )
    with pytest.raises(ValidationError):
        ResumeSuggestion.model_validate(
            _suggestion(
                decision="recommended",
                suggested="突出已有证据",
                expected_benefit=None,
            )
        )


def test_can_emphasize_keyword_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        KeywordSuggestion(
            keyword="Python",
            status="can_emphasize",
            evidence=None,
            guidance="突出已有证据。",
        )
