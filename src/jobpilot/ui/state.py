"""Small helpers for Streamlit session state."""

from hashlib import sha256

import streamlit as st

from jobpilot.models import (
    BatchScreeningItem,
    CandidateProfile,
    JobProfile,
    MatchResult,
    ParsedResume,
    ResumeOptimizationResult,
)


def initialize_session_state() -> None:
    """Initialize user-specific state shared across pages."""
    st.session_state.setdefault("resume_file_fingerprint", None)
    st.session_state.setdefault("parsed_resume", None)
    st.session_state.setdefault("resume_parse_error", None)
    st.session_state.setdefault("candidate_profile_fingerprint", None)
    st.session_state.setdefault("candidate_profile", None)
    st.session_state.setdefault("candidate_profile_error", None)
    st.session_state.setdefault("job_description_fingerprint", None)
    st.session_state.setdefault("job_profile_fingerprint", None)
    st.session_state.setdefault("job_profile", None)
    st.session_state.setdefault("job_profile_error", None)
    st.session_state.setdefault("match_fingerprint", None)
    st.session_state.setdefault("match_result", None)
    st.session_state.setdefault("match_error", None)
    st.session_state.setdefault("optimization_fingerprint", None)
    st.session_state.setdefault("optimization_result", None)
    st.session_state.setdefault("optimization_error", None)
    st.session_state.setdefault("selected_application_id", None)
    st.session_state.setdefault("pending_application_delete_id", None)
    st.session_state.setdefault("application_feedback", None)
    st.session_state.setdefault("batch_input_fingerprint", None)
    st.session_state.setdefault("batch_screening_result", None)
    st.session_state.setdefault("batch_input_error", None)
    st.session_state.setdefault("batch_item_cache", {})
    st.session_state.setdefault("fast_local_cache", {})
    st.session_state.setdefault("fast_assessment_cache", {})
    st.session_state.setdefault("fast_trimmed_jd_cache", {})
    st.session_state.setdefault("fast_candidate_summary_cache", {})
    st.session_state.setdefault("fast_job_profile_cache", {})
    st.session_state.setdefault("batch_screening_mode_used", None)
    st.session_state.setdefault("current_screening_batch_id", None)
    st.session_state.setdefault("batch_apply_result_fingerprint", None)
    st.session_state.setdefault("batch_apply_selections", {})
    st.session_state.setdefault("batch_apply_plan", None)
    st.session_state.setdefault("batch_apply_feedback", None)
    st.session_state.setdefault("batch_apply_start_requested", False)
    st.session_state.setdefault("batch_apply_execution", None)
    st.session_state.setdefault("contact_execution_history", [])
    st.session_state.setdefault("batch_apply_synced_task_ids", set())
    st.session_state.setdefault("selected_batch_item_index", None)
    st.session_state.setdefault("boss_discovery_result", None)
    st.session_state.setdefault("boss_discovery_error", None)
    st.session_state.setdefault("screened_discovery_keys", set())
    st.session_state.setdefault("boss_inbox_revision_seen", -1)
    st.session_state.setdefault("extension_bridge_started", False)


def _clear_optimization_state(state: dict) -> None:
    state["optimization_fingerprint"] = None
    state["optimization_result"] = None
    state["optimization_error"] = None


def _clear_match_state(state: dict) -> None:
    state["match_fingerprint"] = None
    state["match_result"] = None
    state["match_error"] = None
    _clear_optimization_state(state)


def _sync_candidate_profile_state(state: dict, fingerprint: str) -> None:
    """Clear AI results when a different resume becomes current."""
    if state.get("candidate_profile_fingerprint") == fingerprint:
        return
    state["candidate_profile_fingerprint"] = fingerprint
    state["candidate_profile"] = None
    state["candidate_profile_error"] = None
    state["batch_screening_result"] = None
    state["batch_input_error"] = None
    state["selected_batch_item_index"] = None
    clear_batch_apply_state(state)
    state["current_screening_batch_id"] = None
    _clear_match_state(state)


def resume_fingerprint(filename: str, file_bytes: bytes) -> str:
    """Identify an upload so unchanged files are not parsed again."""
    digest = sha256()
    digest.update(filename.encode("utf-8"))
    digest.update(b"\0")
    digest.update(file_bytes)
    return digest.hexdigest()


def cached_resume_result(
    fingerprint: str,
) -> tuple[ParsedResume | None, str | None] | None:
    """Return the cached result only when it belongs to this upload."""
    if st.session_state.resume_file_fingerprint != fingerprint:
        return None
    return st.session_state.parsed_resume, st.session_state.resume_parse_error


def store_resume_result(
    fingerprint: str,
    parsed_resume: ParsedResume | None,
    error: str | None,
) -> None:
    """Store one parse outcome for the current browser session."""
    _sync_candidate_profile_state(st.session_state, fingerprint)
    st.session_state.resume_file_fingerprint = fingerprint
    st.session_state.parsed_resume = parsed_resume
    st.session_state.resume_parse_error = error


def cached_candidate_profile(
    fingerprint: str,
) -> tuple[CandidateProfile | None, str | None]:
    """Return AI output only when it belongs to the current resume."""
    if st.session_state.candidate_profile_fingerprint != fingerprint:
        return None, None
    return st.session_state.candidate_profile, st.session_state.candidate_profile_error


def store_candidate_profile(
    fingerprint: str,
    profile: CandidateProfile | None,
    error: str | None,
) -> None:
    """Bind a candidate profile outcome to one resume fingerprint."""
    if st.session_state.resume_file_fingerprint != fingerprint:
        return
    st.session_state.candidate_profile_fingerprint = fingerprint
    st.session_state.candidate_profile = profile
    st.session_state.candidate_profile_error = error


def job_description_fingerprint(job_description: str) -> str | None:
    """Identify normalized JD text without storing its contents in the digest."""
    normalized = "\n".join(
        line.strip()
        for line in job_description.strip().splitlines()
        if line.strip()
    )
    if not normalized:
        return None
    return sha256(normalized.encode("utf-8")).hexdigest()


def _sync_job_profile_state(state: dict, fingerprint: str | None) -> None:
    """Clear a job result when the active normalized JD identity changes."""
    if state.get("job_description_fingerprint") == fingerprint:
        return
    state["job_description_fingerprint"] = fingerprint
    state["job_profile_fingerprint"] = None
    state["job_profile"] = None
    state["job_profile_error"] = None
    _clear_match_state(state)


def sync_job_description_state(fingerprint: str | None) -> None:
    """Clear an old job result immediately when the current JD changes."""
    _sync_job_profile_state(st.session_state, fingerprint)


def cached_job_profile(
    fingerprint: str | None,
) -> tuple[JobProfile | None, str | None]:
    """Return a job result only when it belongs to the current JD."""
    if fingerprint is None or st.session_state.job_profile_fingerprint != fingerprint:
        return None, None
    return st.session_state.job_profile, st.session_state.job_profile_error


def store_job_profile(
    fingerprint: str,
    profile: JobProfile | None,
    error: str | None,
) -> None:
    """Bind one JobProfile outcome to the active JD fingerprint."""
    if st.session_state.job_description_fingerprint != fingerprint:
        return
    st.session_state.job_profile_fingerprint = fingerprint
    st.session_state.job_profile = profile
    st.session_state.job_profile_error = error


def match_result_fingerprint(
    resume_fingerprint_value: str, job_fingerprint_value: str
) -> str:
    """Bind a match result to both analyzed source profiles."""
    digest = sha256()
    digest.update(resume_fingerprint_value.encode("ascii"))
    digest.update(b"\0")
    digest.update(job_fingerprint_value.encode("ascii"))
    return digest.hexdigest()


def _sync_match_result_state(state: dict, fingerprint: str | None) -> None:
    """Clear a result when either source profile identity changes."""
    if state.get("match_fingerprint") == fingerprint:
        return
    state["match_fingerprint"] = fingerprint
    state["match_result"] = None
    state["match_error"] = None
    _clear_optimization_state(state)


def sync_match_result_state(fingerprint: str | None) -> None:
    _sync_match_result_state(st.session_state, fingerprint)


def cached_match_result(
    fingerprint: str | None,
) -> tuple[MatchResult | None, str | None]:
    if fingerprint is None or st.session_state.match_fingerprint != fingerprint:
        return None, None
    return st.session_state.match_result, st.session_state.match_error


def store_match_result(
    fingerprint: str,
    result: MatchResult | None,
    error: str | None,
) -> None:
    if st.session_state.match_fingerprint != fingerprint:
        return
    st.session_state.match_result = result
    st.session_state.match_error = error
    _clear_optimization_state(st.session_state)


def optimization_result_fingerprint(
    resume_fingerprint_value: str,
    job_fingerprint_value: str,
    match_fingerprint_value: str,
) -> str:
    """Bind optimization output to the resume, JD, and match identities."""
    digest = sha256()
    for value in (
        resume_fingerprint_value,
        job_fingerprint_value,
        match_fingerprint_value,
    ):
        digest.update(value.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _sync_optimization_result_state(state: dict, fingerprint: str | None) -> None:
    if state.get("optimization_fingerprint") == fingerprint:
        return
    state["optimization_fingerprint"] = fingerprint
    state["optimization_result"] = None
    state["optimization_error"] = None


def sync_optimization_result_state(fingerprint: str | None) -> None:
    _sync_optimization_result_state(st.session_state, fingerprint)


def cached_optimization_result(
    fingerprint: str | None,
) -> tuple[ResumeOptimizationResult | None, str | None]:
    if (
        fingerprint is None
        or st.session_state.optimization_fingerprint != fingerprint
    ):
        return None, None
    return st.session_state.optimization_result, st.session_state.optimization_error


def store_optimization_result(
    fingerprint: str,
    result: ResumeOptimizationResult | None,
    error: str | None,
) -> None:
    if st.session_state.optimization_fingerprint != fingerprint:
        return
    st.session_state.optimization_result = result
    st.session_state.optimization_error = error


def sync_batch_input_state(raw_input: str) -> str | None:
    """Clear displayed batch output when input changes while retaining item cache."""
    normalized = raw_input.strip()
    fingerprint = sha256(normalized.encode("utf-8")).hexdigest() if normalized else None
    if st.session_state.batch_input_fingerprint != fingerprint:
        st.session_state.batch_input_fingerprint = fingerprint
        st.session_state.batch_screening_result = None
        st.session_state.batch_input_error = None
        st.session_state.selected_batch_item_index = None
        st.session_state.batch_screening_mode_used = None
        clear_batch_apply_state(st.session_state)
        st.session_state.current_screening_batch_id = None
    return fingerprint


def store_batch_screening_result(result, error: str | None) -> None:
    if result is not None and hasattr(result, "screening_batch_id"):
        batch_id = result.screening_batch_id
        if st.session_state.get("current_screening_batch_id") != batch_id:
            clear_batch_apply_state(st.session_state, clear_execution=True)
            st.session_state.current_screening_batch_id = batch_id
    st.session_state.batch_screening_result = result
    st.session_state.batch_input_error = error


def _archive_contact_execution(state) -> None:
    execution = state.get("batch_apply_execution")
    if execution is None:
        return
    history = list(state.get("contact_execution_history", []))
    if not any(item.execution_id == execution.execution_id for item in history):
        history.append(execution.model_copy(deep=True))
    state["contact_execution_history"] = history[-20:]


def clear_batch_apply_state(state, *, clear_execution: bool = True) -> None:
    """Drop a plan and all selection widgets when its screening source changes."""
    for key in list(state):
        if str(key).startswith("batch_apply_checkbox_"):
            del state[key]
    state["batch_apply_result_fingerprint"] = None
    state["batch_apply_selections"] = {}
    state["batch_apply_plan"] = None
    state["batch_apply_feedback"] = None
    state["batch_apply_start_requested"] = False
    state["batch_apply_publish_error"] = None
    if clear_execution:
        _archive_contact_execution(state)
        state["batch_apply_execution"] = None
        state["batch_apply_synced_task_ids"] = set()


def sync_batch_apply_state(
    fingerprint: str, defaults: dict[str, bool], screening_batch_id: str | None = None
) -> None:
    """Initialize once per screening result and preserve later user edits."""
    if (
        st.session_state.get("batch_apply_result_fingerprint") == fingerprint
        and st.session_state.get("current_screening_batch_id") == screening_batch_id
    ):
        return
    clear_batch_apply_state(st.session_state, clear_execution=True)
    st.session_state.current_screening_batch_id = screening_batch_id
    st.session_state.batch_apply_result_fingerprint = fingerprint
    st.session_state.batch_apply_selections = dict(defaults)


def store_batch_apply_plan(plan) -> None:
    st.session_state.batch_apply_plan = plan
    st.session_state.batch_apply_feedback = (
        f"已准备 {plan.selected_count} 个岗位进入沟通流程。"
    )
    st.session_state.batch_apply_start_requested = False


def handoff_batch_item_to_single(
    item: BatchScreeningItem, resume_fingerprint_value: str
) -> None:
    """Load a completed batch item into the existing single-job state."""
    if item.job_profile is None or item.match_result is None:
        return
    st.session_state.job_match_mode = "单岗位分析"
    st.session_state.job_description_input = item.jd_text
    st.session_state.job_description_fingerprint = item.jd_fingerprint
    st.session_state.job_profile_fingerprint = item.jd_fingerprint
    st.session_state.job_profile = item.job_profile.model_copy(deep=True)
    st.session_state.job_profile_error = None
    fingerprint = match_result_fingerprint(
        resume_fingerprint_value, item.jd_fingerprint
    )
    st.session_state.match_fingerprint = fingerprint
    st.session_state.match_result = item.match_result.model_copy(deep=True)
    st.session_state.match_error = None
    _clear_optimization_state(st.session_state)
