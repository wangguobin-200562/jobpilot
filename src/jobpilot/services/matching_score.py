"""Deterministic and explainable scoring rules for resume-to-job matching."""

from collections.abc import Iterable

from jobpilot.models import MatchScoreBreakdown


DIMENSION_WEIGHTS = {
    "skills_score": 0.40,
    "experience_score": 0.25,
    "projects_score": 0.20,
    "education_other_score": 0.15,
}
SKILL_GROUP_WEIGHTS = {"required": 0.80, "preferred": 0.20}
CLASSIFICATION_POINTS = {"matched": 1.0, "partial": 0.5, "missing": 0.0}
RELEVANCE_POINTS = {"high": 100.0, "medium": 70.0, "low": 40.0, "none": 0.0}


def _bounded(score: float) -> float:
    return round(max(0.0, min(100.0, score)), 1)


def _classification_score(classifications: Iterable[str]) -> float | None:
    values = [CLASSIFICATION_POINTS[value] for value in classifications]
    if not values:
        return None
    return _bounded(sum(values) / len(values) * 100)


def calculate_skill_score(
    required_classifications: Iterable[str],
    preferred_classifications: Iterable[str],
) -> float | None:
    """Score required skills more heavily, normalizing absent skill groups."""
    group_scores = {
        "required": _classification_score(required_classifications),
        "preferred": _classification_score(preferred_classifications),
    }
    active = {name: score for name, score in group_scores.items() if score is not None}
    if not active:
        return None
    active_weight = sum(SKILL_GROUP_WEIGHTS[name] for name in active)
    return _bounded(
        sum(
            score * SKILL_GROUP_WEIGHTS[name]
            for name, score in active.items()
        )
        / active_weight
    )


def calculate_relevance_score(
    relevances: Iterable[str], *, applicable: bool
) -> float | None:
    """Map discrete relevance to a fixed score; strongest evidence represents fit."""
    if not applicable:
        return None
    values = [RELEVANCE_POINTS[value] for value in relevances]
    return _bounded(max(values)) if values else 0.0


def calculate_education_other_score(
    classifications: Iterable[str], *, applicable: bool
) -> float | None:
    """Score explicit education/language/other requirements only when present."""
    if not applicable:
        return None
    return _classification_score(classifications) or 0.0


def calculate_overall_score(
    *,
    skills_score: float | None,
    experience_score: float | None,
    projects_score: float | None,
    education_other_score: float | None,
) -> float:
    """Apply base weights and renormalize after removing N/A dimensions."""
    scores = {
        "skills_score": skills_score,
        "experience_score": experience_score,
        "projects_score": projects_score,
        "education_other_score": education_other_score,
    }
    active = {name: score for name, score in scores.items() if score is not None}
    if not active:
        return 0.0
    active_weight = sum(DIMENSION_WEIGHTS[name] for name in active)
    return _bounded(
        sum(score * DIMENSION_WEIGHTS[name] for name, score in active.items())
        / active_weight
    )


def calculate_score_breakdown(
    *,
    required_classifications: Iterable[str],
    preferred_classifications: Iterable[str],
    experience_relevances: Iterable[str],
    project_relevances: Iterable[str],
    education_other_classifications: Iterable[str],
    experience_applicable: bool,
    projects_applicable: bool,
    education_other_applicable: bool,
) -> MatchScoreBreakdown:
    """Calculate every score from fixed mappings and explicit applicability."""
    skills_score = calculate_skill_score(
        required_classifications, preferred_classifications
    )
    experience_score = calculate_relevance_score(
        experience_relevances, applicable=experience_applicable
    )
    projects_score = calculate_relevance_score(
        project_relevances, applicable=projects_applicable
    )
    education_other_score = calculate_education_other_score(
        education_other_classifications,
        applicable=education_other_applicable,
    )
    overall_score = calculate_overall_score(
        skills_score=skills_score,
        experience_score=experience_score,
        projects_score=projects_score,
        education_other_score=education_other_score,
    )
    return MatchScoreBreakdown(
        overall_score=overall_score,
        skills_score=skills_score,
        experience_score=experience_score,
        projects_score=projects_score,
        education_other_score=education_other_score,
    )
