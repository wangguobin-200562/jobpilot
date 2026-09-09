from jobpilot.models import CandidateProfile
from jobpilot.ui.state import _sync_candidate_profile_state


def test_same_resume_fingerprint_keeps_candidate_profile() -> None:
    profile = CandidateProfile(summary="Existing profile")
    state = {
        "candidate_profile_fingerprint": "resume-a",
        "candidate_profile": profile,
        "candidate_profile_error": None,
    }

    _sync_candidate_profile_state(state, "resume-a")

    assert state["candidate_profile"] is profile


def test_new_resume_fingerprint_clears_old_candidate_profile() -> None:
    state = {
        "candidate_profile_fingerprint": "resume-a",
        "candidate_profile": CandidateProfile(summary="Resume A"),
        "candidate_profile_error": None,
    }

    _sync_candidate_profile_state(state, "resume-b")

    assert state["candidate_profile_fingerprint"] == "resume-b"
    assert state["candidate_profile"] is None
    assert state["candidate_profile_error"] is None
