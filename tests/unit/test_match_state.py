from jobpilot.models import MatchResult, MatchScoreBreakdown
from jobpilot.ui.state import (
    _sync_candidate_profile_state,
    _sync_job_profile_state,
    _sync_match_result_state,
    match_result_fingerprint,
)


def _result() -> MatchResult:
    return MatchResult(scores=MatchScoreBreakdown(overall_score=80))


def test_match_fingerprint_binds_resume_and_jd() -> None:
    fingerprint = match_result_fingerprint("a" * 64, "b" * 64)

    assert fingerprint == match_result_fingerprint("a" * 64, "b" * 64)
    assert fingerprint != match_result_fingerprint("c" * 64, "b" * 64)
    assert fingerprint != match_result_fingerprint("a" * 64, "d" * 64)


def test_same_pair_keeps_match_result() -> None:
    result = _result()
    state = {
        "match_fingerprint": "pair-a",
        "match_result": result,
        "match_error": None,
    }

    _sync_match_result_state(state, "pair-a")

    assert state["match_result"] is result


def test_resume_change_clears_match_result() -> None:
    state = {
        "candidate_profile_fingerprint": "resume-a",
        "candidate_profile": object(),
        "candidate_profile_error": None,
        "match_fingerprint": "pair-a",
        "match_result": _result(),
        "match_error": None,
    }

    _sync_candidate_profile_state(state, "resume-b")

    assert state["match_fingerprint"] is None
    assert state["match_result"] is None


def test_jd_change_clears_match_result() -> None:
    state = {
        "job_description_fingerprint": "jd-a",
        "job_profile_fingerprint": "jd-a",
        "job_profile": object(),
        "job_profile_error": None,
        "match_fingerprint": "pair-a",
        "match_result": _result(),
        "match_error": None,
    }

    _sync_job_profile_state(state, "jd-b")

    assert state["match_fingerprint"] is None
    assert state["match_result"] is None
