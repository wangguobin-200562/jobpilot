"""Job-description text to structured job profile use case."""

import logging

from jobpilot.llm import EmptyJobProfileError, LLMClient, ModelTier
from jobpilot.llm.structured_output import generate_structured_output
from jobpilot.models import JobProfile
from jobpilot.prompts.job_analysis import (
    JOB_ANALYSIS_SYSTEM_PROMPT,
    build_job_analysis_prompt,
)


logger = logging.getLogger(__name__)
MIN_JOB_DESCRIPTION_CHARACTERS = 50
MAX_JOB_DESCRIPTION_CHARACTERS = 20_000
JOB_EXTRACTION_TEMPERATURE = 0.0
JOB_EXTRACTION_THINKING = False


class JobDescriptionValidationError(ValueError):
    """Base error for invalid local JD input."""


class EmptyJobDescriptionError(JobDescriptionValidationError):
    """Raised when no JD content was provided."""


class ShortJobDescriptionError(JobDescriptionValidationError):
    """Raised when the JD is too short for reliable extraction."""


class LongJobDescriptionError(JobDescriptionValidationError):
    """Raised when the JD exceeds the supported request size."""


def normalize_job_description(job_description: str) -> str:
    """Normalize surrounding and line whitespace for validation and identity."""
    return "\n".join(
        line.strip() for line in job_description.strip().splitlines() if line.strip()
    )


def validate_job_description(job_description: str) -> str:
    """Validate JD input locally before any model request is possible."""
    normalized = normalize_job_description(job_description)
    if not normalized:
        raise EmptyJobDescriptionError("Job description cannot be empty.")
    if len(normalized) < MIN_JOB_DESCRIPTION_CHARACTERS:
        raise ShortJobDescriptionError("Job description is too short.")
    if len(normalized) > MAX_JOB_DESCRIPTION_CHARACTERS:
        raise LongJobDescriptionError("Job description is too long.")
    return normalized


def job_profile_core_field_count(profile: JobProfile) -> int:
    """Count populated fields that make a job extraction meaningful."""
    return sum(
        (
            bool(profile.job_title),
            bool(profile.responsibilities),
            bool(profile.required_skills),
            bool(profile.preferred_skills),
            bool(profile.experience_requirements),
            bool(profile.education_requirements),
        )
    )


def ensure_job_profile_has_core_data(profile: JobProfile) -> JobProfile:
    """Reject schema-valid job profiles with no meaningful extracted facts."""
    core_field_count = job_profile_core_field_count(profile)
    logger.info("Job profile validated: core_fields=%d", core_field_count)
    if core_field_count == 0:
        raise EmptyJobProfileError(
            "The AI response did not contain any core job information."
        )
    return profile


class JobAnalyzer:
    """Extract a JobProfile using the explicitly selected Flash tier."""

    MODEL_TIER = ModelTier.FLASH

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def analyze(self, job_description: str) -> JobProfile:
        normalized = validate_job_description(job_description)
        user_prompt = build_job_analysis_prompt(normalized)
        logger.info(
            "Job analysis started: jd_text_length=%d tier=%s "
            "user_message_length=%d",
            len(normalized),
            self.MODEL_TIER.name,
            len(user_prompt),
        )
        profile = generate_structured_output(
            self.client,
            system_prompt=JOB_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model_type=JobProfile,
            model_tier=self.MODEL_TIER,
            temperature=JOB_EXTRACTION_TEMPERATURE,
            thinking=JOB_EXTRACTION_THINKING,
        )
        non_empty_top_level_count = sum(
            bool(value) for value in profile.model_dump(mode="python").values()
        )
        logger.info(
            "Job profile summary: top_level_keys=%s "
            "non_empty_top_level_count=%d core_fields=%d",
            sorted(profile.model_fields_set),
            non_empty_top_level_count,
            job_profile_core_field_count(profile),
        )
        return ensure_job_profile_has_core_data(profile)
