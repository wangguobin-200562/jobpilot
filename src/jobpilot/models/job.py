"""Structured facts extracted from a job description."""

from pydantic import Field

from jobpilot.models.candidate_profile import ProfileModel


class JobProfile(ProfileModel):
    """Only facts explicitly stated in a job description."""

    job_title: str | None = None
    company: str | None = None
    location: str | None = None
    employment_type: str | None = None
    salary_range: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    tools_and_technologies: list[str] = Field(default_factory=list)
    experience_requirements: str | None = None
    education_requirements: str | None = None
    language_requirements: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    other_requirements: list[str] = Field(default_factory=list)
