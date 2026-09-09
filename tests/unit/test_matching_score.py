import pytest

from jobpilot.services.matching_score import (
    calculate_education_other_score,
    calculate_overall_score,
    calculate_relevance_score,
    calculate_skill_score,
)


def test_all_exact_required_skills_produce_high_score() -> None:
    assert calculate_skill_score(["matched", "matched"], []) == 100.0


def test_missing_required_skill_hurts_more_than_missing_preferred_skill() -> None:
    missing_required = calculate_skill_score(
        ["matched", "missing"], ["matched", "matched"]
    )
    missing_preferred = calculate_skill_score(
        ["matched", "matched"], ["matched", "missing"]
    )

    assert missing_required == 60.0
    assert missing_preferred == 90.0
    assert missing_required < missing_preferred


def test_partial_skill_is_between_matched_and_missing() -> None:
    matched = calculate_skill_score(["matched"], [])
    partial = calculate_skill_score(["partial"], [])
    missing = calculate_skill_score(["missing"], [])

    assert matched == 100.0
    assert partial == 50.0
    assert missing == 0.0


def test_identical_inputs_produce_identical_skill_score() -> None:
    first = calculate_skill_score(["matched", "partial"], ["missing"])
    second = calculate_skill_score(["matched", "partial"], ["missing"])

    assert first == second


@pytest.mark.parametrize(
    "score",
    [
        calculate_skill_score(["missing"], []),
        calculate_skill_score(["matched"], []),
        calculate_relevance_score(["low"], applicable=True),
        calculate_education_other_score(["partial"], applicable=True),
    ],
)
def test_dimension_scores_remain_within_bounds(score: float | None) -> None:
    assert score is not None
    assert 0 <= score <= 100


def test_overall_score_uses_documented_weights() -> None:
    score = calculate_overall_score(
        skills_score=80,
        experience_score=70,
        projects_score=90,
        education_other_score=100,
    )

    assert score == 82.5


def test_not_applicable_dimensions_are_removed_and_weights_renormalized() -> None:
    score = calculate_overall_score(
        skills_score=80,
        experience_score=60,
        projects_score=100,
        education_other_score=None,
    )

    assert score == pytest.approx(78.8)


def test_absent_education_requirement_does_not_reduce_score() -> None:
    assert calculate_education_other_score([], applicable=False) is None
    assert calculate_overall_score(
        skills_score=100,
        experience_score=None,
        projects_score=None,
        education_other_score=None,
    ) == 100.0


@pytest.mark.parametrize(
    ("relevance", "expected"),
    [("high", 100.0), ("medium", 70.0), ("low", 40.0), ("none", 0.0)],
)
def test_experience_relevance_uses_fixed_mapping(
    relevance: str, expected: float
) -> None:
    assert calculate_relevance_score([relevance], applicable=True) == expected


@pytest.mark.parametrize(
    ("relevance", "expected"),
    [("high", 100.0), ("medium", 70.0), ("none", 0.0)],
)
def test_project_relevance_uses_fixed_mapping(
    relevance: str, expected: float
) -> None:
    assert calculate_relevance_score([relevance], applicable=True) == expected
