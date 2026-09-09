import pytest
from pydantic import ValidationError

from jobpilot.models import JobProfile


def test_complete_job_profile_validates() -> None:
    profile = JobProfile.model_validate(
        {
            "job_title": "AI 应用开发实习生",
            "company": "示例科技",
            "location": "深圳",
            "employment_type": "实习",
            "salary_range": "200-300 元/天",
            "responsibilities": ["开发 AI 应用"],
            "required_skills": ["Python"],
            "preferred_skills": ["LangChain"],
            "tools_and_technologies": ["Git"],
            "experience_requirements": "有项目经验",
            "education_requirements": "本科及以上",
            "language_requirements": ["英语读写"],
            "keywords": ["LLM"],
            "benefits": ["实习证明"],
            "other_requirements": ["每周到岗四天"],
        }
    )

    assert profile.job_title == "AI 应用开发实习生"
    assert profile.required_skills == ["Python"]
    assert profile.preferred_skills == ["LangChain"]


def test_job_profile_allows_all_optional_fields_to_be_empty() -> None:
    profile = JobProfile.model_validate({})

    assert profile.job_title is None
    assert profile.company is None
    assert profile.responsibilities == []
    assert profile.required_skills == []
    assert profile.education_requirements is None


def test_job_profile_rejects_wrong_field_types() -> None:
    with pytest.raises(ValidationError):
        JobProfile.model_validate({"required_skills": "Python"})
