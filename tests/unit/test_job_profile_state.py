from jobpilot.models import JobProfile
from jobpilot.ui.state import _sync_job_profile_state, job_description_fingerprint


def test_job_fingerprint_normalizes_surrounding_line_whitespace() -> None:
    first = job_description_fingerprint(" 岗位名称 \n\n 熟悉 Python ")
    second = job_description_fingerprint("岗位名称\n熟悉 Python")

    assert first is not None
    assert first == second


def test_same_jd_fingerprint_keeps_job_profile() -> None:
    profile = JobProfile(job_title="AI 工程师")
    state = {
        "job_description_fingerprint": "jd-a",
        "job_profile_fingerprint": "jd-a",
        "job_profile": profile,
        "job_profile_error": None,
    }

    _sync_job_profile_state(state, "jd-a")

    assert state["job_profile"] is profile


def test_changed_jd_clears_old_job_profile() -> None:
    state = {
        "job_description_fingerprint": "jd-a",
        "job_profile_fingerprint": "jd-a",
        "job_profile": JobProfile(job_title="旧岗位"),
        "job_profile_error": None,
    }

    _sync_job_profile_state(state, "jd-b")

    assert state["job_description_fingerprint"] == "jd-b"
    assert state["job_profile_fingerprint"] is None
    assert state["job_profile"] is None
    assert state["job_profile_error"] is None
