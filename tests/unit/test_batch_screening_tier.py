import pytest
from pydantic import ValidationError

from jobpilot.models import BatchJobStatus, BatchScreeningItem, ScreeningTier
from jobpilot.services import calculate_screening_tier


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (80, ScreeningTier.PRIORITY),
        (79, ScreeningTier.RECOMMENDED),
        (65, ScreeningTier.RECOMMENDED),
        (64, ScreeningTier.CAUTION),
        (50, ScreeningTier.CAUTION),
        (49, ScreeningTier.LOW_PRIORITY),
    ],
)
def test_score_thresholds(score, expected) -> None:
    assert calculate_screening_tier(score, 0) is expected


def test_required_gaps_downgrade_priority() -> None:
    assert calculate_screening_tier(90, 1) is ScreeningTier.PRIORITY
    assert calculate_screening_tier(90, 2) is ScreeningTier.RECOMMENDED
    assert calculate_screening_tier(90, 3) is ScreeningTier.CAUTION


def test_tier_is_closed_enum_not_arbitrary_llm_text() -> None:
    with pytest.raises(ValueError):
        ScreeningTier("likely_offer")


def test_none_score_cannot_form_completed_item() -> None:
    with pytest.raises(ValidationError):
        BatchScreeningItem(
            index=1,
            jd_text="完整岗位描述",
            raw_block="完整岗位描述",
            jd_fingerprint="a" * 64,
            status=BatchJobStatus.COMPLETED,
        )


def test_none_score_is_rejected_by_tier_calculation() -> None:
    with pytest.raises(ValueError, match="match score"):
        calculate_screening_tier(None, 0)

