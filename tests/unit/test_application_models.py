from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from jobpilot.models import ApplicationStatus, JobApplication, JobProfile


def _payload(**updates) -> dict:
    now = datetime.now(timezone.utc)
    data = {
        "id": 1,
        "company": "示例科技",
        "job_title": "AI 实习生",
        "status": "saved",
        "match_score": None,
        "jd_fingerprint": "a" * 64,
        "job_profile_json": JobProfile(job_title="AI 实习生").model_dump_json(),
        "created_at": now,
        "updated_at": now,
    }
    data.update(updates)
    return data


def test_invalid_application_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JobApplication.model_validate(_payload(status="unknown"))


@pytest.mark.parametrize("score", [-0.1, 100.1])
def test_match_score_must_be_between_zero_and_one_hundred(score) -> None:
    with pytest.raises(ValidationError):
        JobApplication.model_validate(_payload(match_score=score))


def test_optional_application_fields_accept_none() -> None:
    application = JobApplication.model_validate(
        _payload(
            location=None,
            match_result_json=None,
            optimization_result_json=None,
            source=None,
            applied_at=None,
        )
    )

    assert application.status is ApplicationStatus.SAVED
    assert application.match_score is None
    assert application.match_result is None
    assert application.optimization_result is None
