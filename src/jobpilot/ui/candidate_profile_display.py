"""Safe, deterministic display transformations for candidate profiles."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from jobpilot.models import CandidateProfile


_CET4_PATTERN = re.compile(r"cet\s*[-_]?\s*4\b|大学英语四级", re.IGNORECASE)


def mask_phone(phone: str | None) -> str | None:
    """Return a display-safe phone number without changing the stored value."""
    if not phone:
        return phone

    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 11:
        local_number = digits[-11:]
        country_prefix = "+86 " if phone.strip().startswith("+86") else ""
        return f"{country_prefix}{local_number[:3]}****{local_number[-4:]}"
    if len(digits) <= 2:
        return "*" * max(len(digits), 1)
    return f"{digits[0]}{'*' * (len(digits) - 2)}{digits[-1]}"


def mask_email(email: str | None) -> str | None:
    """Return a display-safe email address while keeping its domain useful."""
    if not email:
        return email

    local_part, separator, domain = email.partition("@")
    if not separator:
        visible = local_part[: min(2, len(local_part))]
        return f"{visible}****"

    visible_count = min(4, max(1, len(local_part) // 2))
    return f"{local_part[:visible_count]}****@{domain}"


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    return result


def _language_kind(value: str) -> str | None:
    normalized = value.casefold().replace(" ", "")
    if (
        "英语" in normalized
        or "english" in normalized
        or _CET4_PATTERN.search(value)
    ):
        return "english"
    if "粤语" in normalized or "cantonese" in normalized:
        return "cantonese"
    return None


def _language_label(kind: str, evidence: Iterable[str]) -> str:
    evidence_text = " ".join(evidence)
    if kind == "english":
        return "英语（CET-4）" if _CET4_PATTERN.search(evidence_text) else "英语"
    if kind == "cantonese":
        return "粤语（精通）" if "精通" in evidence_text else "粤语"
    raise ValueError(f"Unsupported language kind: {kind}")


def _normalize_languages(
    languages: list[str], additional_evidence: list[str]
) -> list[str]:
    evidence_by_kind: dict[str, list[str]] = {"english": [], "cantonese": []}
    remaining: list[str] = []

    for value in [*languages, *additional_evidence]:
        kind = _language_kind(value)
        if kind is None:
            remaining.append(value)
        else:
            evidence_by_kind[kind].append(value)

    normalized = _unique(remaining)
    for kind in ("english", "cantonese"):
        evidence = evidence_by_kind[kind]
        if evidence:
            normalized.append(_language_label(kind, evidence))
    return normalized


def _is_language_evidence(value: str) -> bool:
    kind = _language_kind(value)
    if kind == "english":
        return bool(_CET4_PATTERN.search(value)) or value.strip().casefold() in {
            "英语",
            "english",
        }
    if kind == "cantonese":
        return "精通" in value or value.strip().casefold() in {"粤语", "cantonese"}
    return bool(_CET4_PATTERN.search(value))


def normalize_candidate_profile_for_display(
    profile: CandidateProfile,
) -> CandidateProfile:
    """Create a normalized deep copy for UI rendering; never mutate source data."""
    display = profile.model_copy(deep=True)

    programming_languages = _unique(display.skills.programming_languages)
    sql_values = [
        value for value in programming_languages if value.strip().casefold() == "sql"
    ]
    display.skills.programming_languages = [
        value for value in programming_languages if value.strip().casefold() != "sql"
    ]
    display.skills.frameworks = _unique(display.skills.frameworks)
    display.skills.tools = _unique(display.skills.tools)
    display.skills.databases = _unique([*display.skills.databases, *sql_values])

    language_evidence: list[str] = []
    retained_other: list[str] = []
    for value in _unique(display.skills.other):
        if _is_language_evidence(value):
            language_evidence.append(value)
        else:
            retained_other.append(value)

    for education in display.education:
        retained_details: list[str] = []
        for detail in _unique(education.details):
            if _CET4_PATTERN.search(detail):
                language_evidence.append(detail)
            else:
                retained_details.append(detail)
        education.details = retained_details

    retained_certifications: list[str] = []
    for certification in _unique(display.certifications):
        if _CET4_PATTERN.search(certification):
            language_evidence.append(certification)
        else:
            retained_certifications.append(certification)

    display.skills.other = retained_other
    display.certifications = retained_certifications
    display.languages = _normalize_languages(display.languages, language_evidence)

    # Remove exact cross-category duplicates while retaining the first, most specific
    # category in the display hierarchy.
    seen_skills: set[str] = set()
    for skill_values in (
        display.skills.programming_languages,
        display.skills.frameworks,
        display.skills.tools,
        display.skills.databases,
        display.skills.other,
    ):
        retained: list[str] = []
        for value in skill_values:
            key = value.casefold()
            if key not in seen_skills:
                retained.append(value)
                seen_skills.add(key)
        skill_values[:] = retained

    return display


def masked_candidate_profile_data(profile: CandidateProfile) -> dict[str, Any]:
    """Serialize a profile for the frontend with contact details masked."""
    data = profile.model_dump(mode="json")
    personal_info = data["personal_info"]
    personal_info["phone"] = mask_phone(personal_info.get("phone"))
    personal_info["email"] = mask_email(personal_info.get("email"))
    return data


def classify_education_details(
    details: Iterable[str],
) -> tuple[list[str], list[str], list[str]]:
    """Split education details into GPA, coursework, and lower-priority notes."""
    gpa: list[str] = []
    courses: list[str] = []
    notes: list[str] = []
    for detail in details:
        normalized = detail.casefold()
        if "gpa" in normalized or "绩点" in detail:
            gpa.append(detail)
        elif "核心课程" in detail or "主要课程" in detail:
            courses.append(detail)
        else:
            notes.append(detail)
    return gpa, courses, notes
