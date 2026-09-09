import pytest
from pydantic import ValidationError

from jobpilot.models import CandidateProfile


def test_complete_candidate_profile_validates() -> None:
    profile = CandidateProfile.model_validate(
        {
            "personal_info": {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "+86 12345678",
                "location": "Shanghai",
            },
            "summary": "AI application developer",
            "education": [
                {
                    "institution": "Example University",
                    "degree": "Bachelor",
                    "major": "Computer Science",
                    "start_date": "2021",
                    "end_date": "2025",
                    "details": ["Scholarship"],
                }
            ],
            "skills": {
                "programming_languages": ["Python"],
                "frameworks": ["Streamlit"],
                "tools": ["Git"],
                "databases": ["PostgreSQL"],
                "other": ["AI agents"],
            },
            "experience": [
                {
                    "company": "Acme",
                    "position": "AI Intern",
                    "start_date": "2025-01",
                    "end_date": "2025-06",
                    "description": "Built internal AI tools.",
                    "highlights": ["Delivered a working demo"],
                    "technologies": ["Python"],
                }
            ],
            "projects": [
                {
                    "name": "JobPilot",
                    "role": "Developer",
                    "description": "AI job-search copilot",
                    "highlights": ["Local resume parsing"],
                    "technologies": ["Streamlit"],
                }
            ],
            "certifications": ["Example Certificate"],
            "languages": ["Chinese", "English"],
        }
    )

    assert profile.personal_info.name == "Jane Doe"
    assert profile.skills.programming_languages == ["Python"]
    assert profile.projects[0].name == "JobPilot"


def test_candidate_profile_allows_missing_optional_information() -> None:
    profile = CandidateProfile.model_validate({})

    assert profile.personal_info.name is None
    assert profile.summary is None
    assert profile.education == []
    assert profile.skills.frameworks == []
    assert profile.experience == []


def test_candidate_profile_rejects_wrong_field_types() -> None:
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(
            {"skills": {"programming_languages": "Python"}}
        )
