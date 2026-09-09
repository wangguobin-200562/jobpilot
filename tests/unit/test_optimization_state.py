from jobpilot.models import ResumeOptimizationResult
from jobpilot.ui.state import (
    _clear_match_state,
    _sync_match_result_state,
    _sync_optimization_result_state,
    optimization_result_fingerprint,
)


def _optimization() -> ResumeOptimizationResult:
    return ResumeOptimizationResult(summary="无需大范围修改。")


def test_optimization_fingerprint_binds_resume_jd_and_match() -> None:
    value = optimization_result_fingerprint("a" * 64, "b" * 64, "c" * 64)

    assert value == optimization_result_fingerprint("a" * 64, "b" * 64, "c" * 64)
    assert value != optimization_result_fingerprint("d" * 64, "b" * 64, "c" * 64)
    assert value != optimization_result_fingerprint("a" * 64, "e" * 64, "c" * 64)
    assert value != optimization_result_fingerprint("a" * 64, "b" * 64, "f" * 64)


def test_same_inputs_keep_optimization_result() -> None:
    result = _optimization()
    state = {
        "optimization_fingerprint": "bound",
        "optimization_result": result,
        "optimization_error": None,
    }

    _sync_optimization_result_state(state, "bound")

    assert state["optimization_result"] is result


def test_match_change_and_clear_remove_optimization_result() -> None:
    for operation in (
        lambda state: _sync_match_result_state(state, "new-match"),
        _clear_match_state,
    ):
        state = {
            "match_fingerprint": "old-match",
            "match_result": object(),
            "match_error": None,
            "optimization_fingerprint": "bound",
            "optimization_result": _optimization(),
            "optimization_error": None,
        }

        operation(state)

        assert state["optimization_fingerprint"] is None
        assert state["optimization_result"] is None
