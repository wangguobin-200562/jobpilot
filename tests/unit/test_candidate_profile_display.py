from jobpilot.models import CandidateProfile
from jobpilot.ui.candidate_profile_display import (
    classify_education_details,
    mask_email,
    mask_phone,
    masked_candidate_profile_data,
    normalize_candidate_profile_for_display,
)


def _profile_for_display() -> CandidateProfile:
    return CandidateProfile(
        personal_info={
            "name": "测试用户",
            "email": "candidate@example.com",
            "phone": "00000000000",
        },
        education=[
            {
                "institution": "示例大学",
                "degree": "本科",
                "major": "计算机科学",
                "start_date": "2021",
                "end_date": "2025",
                "details": [
                    "GPA 3.8/4.0",
                    "CET-4 通过",
                    "核心课程：数据结构、数据库",
                    "校级奖学金",
                ],
            }
        ],
        skills={
            "programming_languages": ["Python", "SQL", "python"],
            "frameworks": ["FastAPI"],
            "tools": ["Git"],
            "databases": ["PostgreSQL"],
            "other": ["英语CET-4", "精通粤语", "Docker", "Git"],
        },
        certifications=["CET-4", "云计算认证"],
        languages=["英语", "粤语"],
    )


def test_phone_and_email_are_masked_for_display() -> None:
    assert mask_phone("00000000000") == "000****0000"
    assert mask_phone("+86 135-1234-6619") == "+86 135****6619"
    assert mask_email("candidate@example.com") == "cand****@example.com"


def test_masking_and_normalization_do_not_mutate_source_profile() -> None:
    profile = _profile_for_display()
    original = profile.model_dump(mode="json")

    display = normalize_candidate_profile_for_display(profile)
    safe_data = masked_candidate_profile_data(display)

    assert profile.model_dump(mode="json") == original
    assert profile.personal_info.phone == "00000000000"
    assert profile.personal_info.email == "candidate@example.com"
    assert safe_data["personal_info"]["phone"] == "000****0000"
    assert safe_data["personal_info"]["email"] == "cand****@example.com"


def test_skills_are_deduplicated_and_sql_moves_to_query_category() -> None:
    display = normalize_candidate_profile_for_display(_profile_for_display())

    assert display.skills.programming_languages == ["Python"]
    assert display.skills.databases == ["PostgreSQL", "SQL"]
    assert display.skills.frameworks == ["FastAPI"]
    assert display.skills.tools == ["Git"]
    assert display.skills.other == ["Docker"]

    displayed_facts = {
        *display.skills.programming_languages,
        *display.skills.frameworks,
        *display.skills.tools,
        *display.skills.databases,
        *display.skills.other,
    }
    assert {"Python", "SQL", "FastAPI", "Git", "PostgreSQL", "Docker"} <= (
        displayed_facts
    )


def test_language_evidence_is_merged_without_duplicate_badges() -> None:
    display = normalize_candidate_profile_for_display(_profile_for_display())

    assert display.languages == ["英语（CET-4）", "粤语（精通）"]
    assert not any("英语" in value for value in display.skills.other)
    assert not any("粤语" in value for value in display.skills.other)
    assert "CET-4" not in display.certifications
    assert not any("CET-4" in detail for detail in display.education[0].details)


def test_education_details_are_classified_without_losing_content() -> None:
    display = normalize_candidate_profile_for_display(_profile_for_display())

    gpa, courses, notes = classify_education_details(display.education[0].details)

    assert gpa == ["GPA 3.8/4.0"]
    assert courses == ["核心课程：数据结构、数据库"]
    assert notes == ["校级奖学金"]
