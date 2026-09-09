"""Resume text to structured candidate profile use case."""

import logging

from jobpilot.llm import EmptyCandidateProfileError, LLMClient, ModelTier
from jobpilot.llm.structured_output import generate_structured_output
from jobpilot.models import CandidateProfile
from jobpilot.prompts.resume_analysis import (
    RESUME_ANALYSIS_SYSTEM_PROMPT,
    build_resume_analysis_prompt,
)


logger = logging.getLogger(__name__)
RESUME_EXTRACTION_TEMPERATURE = 0.0
RESUME_EXTRACTION_THINKING = False


def candidate_profile_core_field_count(profile: CandidateProfile) -> int:
    """Count populated core groups required for a meaningful resume result."""
    skills = profile.skills
    has_skills = any(
        (
            skills.programming_languages,
            skills.frameworks,
            skills.tools,
            skills.databases,
            skills.other,
        )
    )
    return sum(
        (
            bool(profile.personal_info.name),
            bool(profile.education),
            has_skills,
            bool(profile.experience),
            bool(profile.projects),
        )
    )


def ensure_candidate_profile_has_core_data(
    profile: CandidateProfile,
) -> CandidateProfile:
    """Reject schema-valid profiles that contain no useful resume facts."""
    core_field_count = candidate_profile_core_field_count(profile)
    logger.info(
        "Candidate profile validated: core_fields=%d",
        core_field_count,
    )
    if core_field_count == 0:
        raise EmptyCandidateProfileError(
            "The AI response did not contain any core candidate information."
        )
    return profile


class ResumeAnalyzer:
    """Extract a CandidateProfile using the explicitly chosen Flash tier."""

    MODEL_TIER = ModelTier.FLASH

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def analyze(self, resume_text: str) -> CandidateProfile:
        if not resume_text.strip():
            raise ValueError("Resume text cannot be empty.")

        user_prompt = build_resume_analysis_prompt(resume_text)
        logger.info(
            "Resume analysis started: text_length=%d tier=%s "
            "user_message_length=%d",
            len(resume_text),
            self.MODEL_TIER.name,
            len(user_prompt),
        )
        profile = generate_structured_output(
            self.client,
            system_prompt=RESUME_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model_type=CandidateProfile,
            model_tier=self.MODEL_TIER,
            temperature=RESUME_EXTRACTION_TEMPERATURE,
            thinking=RESUME_EXTRACTION_THINKING,
        )
        top_level_keys = sorted(profile.model_fields_set)
        non_empty_top_level_count = sum(
            (
                any(
                    (
                        profile.personal_info.name,
                        profile.personal_info.email,
                        profile.personal_info.phone,
                        profile.personal_info.location,
                    )
                ),
                bool(profile.summary),
                bool(profile.education),
                any(
                    (
                        profile.skills.programming_languages,
                        profile.skills.frameworks,
                        profile.skills.tools,
                        profile.skills.databases,
                        profile.skills.other,
                    )
                ),
                bool(profile.experience),
                bool(profile.projects),
                bool(profile.certifications),
                bool(profile.languages),
            )
        )
        logger.info(
            "Resume profile summary: top_level_keys=%s "
            "non_empty_top_level_count=%d",
            top_level_keys,
            non_empty_top_level_count,
        )
        return ensure_candidate_profile_has_core_data(profile)
