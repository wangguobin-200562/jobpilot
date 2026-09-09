"""Structured representation of facts extracted from a resume."""

from pydantic import BaseModel, ConfigDict, Field


class ProfileModel(BaseModel):
    """Strict base model for untrusted LLM output."""

    model_config = ConfigDict(extra="forbid", strict=True)


class PersonalInfo(ProfileModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None


class EducationItem(ProfileModel):
    institution: str | None = None
    degree: str | None = None
    major: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    details: list[str] = Field(default_factory=list)


class ExperienceItem(ProfileModel):
    company: str | None = None
    position: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class ProjectItem(ProfileModel):
    name: str | None = None
    role: str | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Skills(ProfileModel):
    programming_languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)


class CandidateProfile(ProfileModel):
    """AI-extracted candidate facts; missing information remains empty."""

    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    summary: str | None = None
    education: list[EducationItem] = Field(default_factory=list)
    skills: Skills = Field(default_factory=Skills)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
