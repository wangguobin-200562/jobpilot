import pytest
from pydantic import ValidationError

from jobpilot.models import (
    ExperienceRelevance,
    ImprovementPriority,
    MatchResult,
    SemanticMatchAnalysis,
    SkillSemanticAnalysis,
)


def _payload(overall_score: float = 82) -> dict:
    return {
        "scores": {
            "overall_score": overall_score,
            "skills_score": 85,
            "experience_score": 70,
            "projects_score": 90,
            "education_other_score": None,
        },
        "matched_skills": [
            {
                "skill": "Python",
                "resume_evidence": "Python",
                "job_requirement": "Python",
                "match_type": "exact",
            }
        ],
        "missing_skills": [
            {"skill": "Docker", "importance": "preferred", "reason": "未找到证据"}
        ],
        "partial_matches": [],
        "strengths": ["具有 Python 项目经验"],
        "gaps": ["当前简历中未找到 Docker 证据"],
        "evidence": [],
        "improvement_priorities": [
            {"priority": "medium", "action": "学习 Docker", "reason": "岗位加分项"}
        ],
        "summary": "整体匹配良好。",
    }


def test_complete_match_result_validates() -> None:
    result = MatchResult.model_validate(_payload())

    assert result.scores.overall_score == 82
    assert result.matched_skills[0].match_type == "exact"
    assert result.improvement_priorities[0].priority == "medium"


def test_score_above_100_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MatchResult.model_validate(_payload(100.1))


def test_score_below_zero_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MatchResult.model_validate(_payload(-0.1))


def test_semantic_model_rejects_any_llm_generated_score() -> None:
    with pytest.raises(ValidationError):
        SemanticMatchAnalysis.model_validate(
            {"skill_analysis": [], "overall_score": 87}
        )


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            SkillSemanticAnalysis,
            {
                "job_skill": "Python",
                "candidate_evidence": "Python",
                "classification": "MATCHED",
                "reason": "same",
            },
        ),
        (
            ExperienceRelevance,
            {
                "experience_reference": "internship",
                "job_requirement": "development",
                "candidate_evidence": "development",
                "relevance": "relevant",
                "assessment": "related",
            },
        ),
        (
            ImprovementPriority,
            {"priority": "urgent", "action": "practice", "reason": "gap"},
        ),
    ],
)
def test_semantic_enum_values_are_strict(model, payload: dict) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_nested_semantic_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SkillSemanticAnalysis.model_validate(
            {
                "job_skill": "Python",
                "candidate_evidence": "Python",
                "classification": "matched",
                "reason": "same",
                "score": 100,
            }
        )


def test_none_relevance_can_have_null_candidate_evidence() -> None:
    item = ExperienceRelevance.model_validate(
        {
            "experience_reference": "unrelated internship",
            "job_requirement": "AI development",
            "candidate_evidence": None,
            "relevance": "none",
            "assessment": "No related evidence is present.",
        }
    )

    assert item.candidate_evidence is None
