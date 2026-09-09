"""Deterministic compact inputs for the quick screening path."""

from __future__ import annotations

import re

from jobpilot.models import (
    CandidateProfile,
    EducationItem,
    ExperienceItem,
    ProjectItem,
    Skills,
)
from jobpilot.models.fast_screening import CompactCandidateSummary


MAX_TRIMMED_JD_CHARACTERS = 3600
_CSS_BLOCK = re.compile(r"[^\s{}]{1,80}\{[^{}]{0,1200}\}", re.DOTALL)
_CSS_DECLARATION = re.compile(
    r"(?:display|font-size|font-style|font-weight|width|height|visibility|"
    r"line-height|overflow)\s*:[^;\s]{0,100};?",
    re.IGNORECASE,
)
_NOISE_LINE = re.compile(
    r"^(?:举报|微信扫码分享|不合适|收藏|立即沟通|继续沟通|公司基本信息|"
    r"下载app|查看全部职位|工作地址|工商信息)\s*$",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


def _clean_text(value: str | None, *, limit: int = 220) -> str:
    return " ".join((value or "").split())[:limit]


def _unique(values: list[str], *, limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            output.append(cleaned)
            seen.add(key)
        if len(output) >= limit:
            break
    return output


def _redact(values: list[str], private_values: tuple[str, ...]) -> list[str]:
    output: list[str] = []
    for value in values:
        cleaned = value
        for private in private_values:
            cleaned = cleaned.replace(private, "[已移除]")
        output.append(_PHONE.sub("[已移除]", _EMAIL.sub("[已移除]", cleaned)))
    return output


def build_compact_candidate_summary(
    candidate: CandidateProfile,
) -> CompactCandidateSummary:
    """Build once per resume; omit identity/contact data by construction."""
    skills = _unique(
        [
            *candidate.skills.programming_languages,
            *candidate.skills.frameworks,
            *candidate.skills.tools,
            *candidate.skills.databases,
            *candidate.skills.other,
            *[tech for item in candidate.experience for tech in item.technologies],
            *[tech for item in candidate.projects for tech in item.technologies],
        ],
        limit=30,
    )
    experience = _unique(
        [
            "；".join(
                part
                for part in (
                    _clean_text(item.position, limit=60),
                    _clean_text(item.description, limit=180),
                    _clean_text("、".join(item.highlights[:2]), limit=180),
                    _clean_text("技术：" + "、".join(item.technologies[:8]), limit=120)
                    if item.technologies
                    else "",
                )
                if part
            )
            for item in candidate.experience[:4]
        ],
        limit=4,
    )
    projects = _unique(
        [
            "；".join(
                part
                for part in (
                    _clean_text(item.name, limit=60),
                    _clean_text(item.description, limit=160),
                    _clean_text("技术：" + "、".join(item.technologies[:8]), limit=120)
                    if item.technologies
                    else "",
                )
                if part
            )
            for item in candidate.projects[:4]
        ],
        limit=4,
    )
    education = _unique(
        [
            " / ".join(
                part
                for part in (
                    _clean_text(item.degree, limit=40),
                    _clean_text(item.major, limit=60),
                )
                if part
            )
            for item in candidate.education[:3]
        ],
        limit=3,
    )
    private_values = tuple(
        value
        for value in (
            candidate.personal_info.name,
            candidate.personal_info.email,
            candidate.personal_info.phone,
        )
        if value
    )
    return CompactCandidateSummary(
        skills=_redact(skills, private_values),
        experience_overview=_redact(experience, private_values),
        project_evidence=_redact(projects, private_values),
        education=_redact(education, private_values),
        certifications=_redact(_unique(candidate.certifications, limit=5), private_values),
        languages=_redact(_unique(candidate.languages, limit=5), private_values),
    )


def build_compact_candidate_profile(candidate: CandidateProfile) -> CandidateProfile:
    """Retain bounded matching evidence while omitting identity and contact data."""
    private_values = tuple(
        value
        for value in (
            candidate.personal_info.name,
            candidate.personal_info.email,
            candidate.personal_info.phone,
        )
        if value
    )

    def safe(value: str | None, limit: int) -> str | None:
        cleaned = _clean_text(value, limit=limit)
        return (_redact([cleaned], private_values)[0] if cleaned else None)

    return CandidateProfile(
        summary=safe(candidate.summary, 280),
        skills=Skills(
            programming_languages=_redact(_unique(candidate.skills.programming_languages, limit=10), private_values),
            frameworks=_redact(_unique(candidate.skills.frameworks, limit=10), private_values),
            tools=_redact(_unique(candidate.skills.tools, limit=10), private_values),
            databases=_redact(_unique(candidate.skills.databases, limit=10), private_values),
            other=_redact(_unique(candidate.skills.other, limit=12), private_values),
        ),
        experience=[
            ExperienceItem(
                position=safe(item.position, 60),
                description=safe(item.description, 220),
                highlights=_redact(_unique(item.highlights, limit=2), private_values),
                technologies=_redact(_unique(item.technologies, limit=10), private_values),
            )
            for item in candidate.experience[:4]
        ],
        projects=[
            ProjectItem(
                name=safe(item.name, 60),
                role=safe(item.role, 60),
                description=safe(item.description, 200),
                highlights=_redact(_unique(item.highlights, limit=2), private_values),
                technologies=_redact(_unique(item.technologies, limit=10), private_values),
            )
            for item in candidate.projects[:4]
        ],
        education=[
            EducationItem(
                degree=_clean_text(item.degree, limit=40) or None,
                major=_clean_text(item.major, limit=60) or None,
            )
            for item in candidate.education[:3]
        ],
        certifications=_redact(_unique(candidate.certifications, limit=5), private_values),
        languages=_redact(_unique(candidate.languages, limit=5), private_values),
    )


def trim_job_description(jd_text: str) -> str:
    """Remove known page chrome/CSS while keeping requirement-bearing text."""
    cleaned = _CSS_BLOCK.sub(" ", jd_text)
    cleaned = _CSS_DECLARATION.sub(" ", cleaned)
    lines: list[str] = []
    previous = ""
    for raw_line in cleaned.splitlines():
        line = " ".join(raw_line.split())
        if not line or _NOISE_LINE.fullmatch(line) or line == previous:
            continue
        lines.append(line)
        previous = line
    normalized = "\n".join(lines)
    if len(normalized) <= MAX_TRIMMED_JD_CHARACTERS:
        return normalized

    # Keep both the opening context and the tail where qualification sections often live.
    head_size = int(MAX_TRIMMED_JD_CHARACTERS * 0.62)
    tail_size = MAX_TRIMMED_JD_CHARACTERS - head_size - 20
    return normalized[:head_size].rstrip() + "\n[内容截断]\n" + normalized[-tail_size:].lstrip()
