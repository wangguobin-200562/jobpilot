from pathlib import Path

from jobpilot.models import ScreeningTier
from jobpilot.ui.batch_apply import chinese_display_reason


ROOT = Path(__file__).resolve().parents[2]


def _extension(name: str) -> str:
    return (ROOT / "extension" / name).read_text(encoding="utf-8")


def test_continuous_capture_observes_stable_job_changes_and_deduplicates() -> None:
    content = _extension("content.js")
    background = _extension("background.js")
    assert "MutationObserver" in content
    assert "lastStableSignature" in content
    assert "lastCaptureIdentity" in content
    assert "JOBPILOT_CAPTURED_JOBS" in content
    assert "mergeJobs" in background


def test_capture_can_pause_clear_and_show_noninvasive_badge() -> None:
    sources = _extension("content.js") + _extension("popup.js")
    assert "JOBPILOT_CAPTURE_PAUSE" in sources
    assert "JOBPILOT_CAPTURE_CLEAR" in sources
    assert "jobpilot-capture-badge" in sources
    assert "已读取" in sources


def test_confirmed_tasks_auto_start_without_popup_start_button() -> None:
    popup = _extension("popup.html") + _extension("popup.js")
    background = _extension("background.js")
    assert "start-apply" not in popup
    assert "JOBPILOT_BRIDGE_TICK" in background
    assert "runOneApplyStep" in background
    assert "jobpilot_bridge_heartbeat" in background
    assert "probeBridge({ resumeTasks: true })" in background
    assert "chrome.runtime.onStartup.addListener" in background


def test_bridge_endpoint_is_fixed_and_not_derived_from_streamlit_port() -> None:
    sources = _extension("background.js") + _extension("popup.js")
    assert "http://127.0.0.1:8765" in sources
    assert "8501" not in sources
    assert "8502" not in sources


def test_extension_runtime_messages_handle_invalidated_mv3_context() -> None:
    content = _extension("content.js")
    popup = _extension("popup.js")

    assert "chrome.runtime?.id" in content
    assert "chrome.runtime.lastError" in content
    assert "clearInterval(heartbeatTimer)" in content
    assert "chrome.runtime.lastError" in popup
    assert "const tabMessage" in popup


def test_one_worker_tab_is_reused_and_child_tab_is_closed() -> None:
    background = _extension("background.js")
    assert "worker_tab_id" in background
    assert "chrome.tabs.update(state.worker_tab_id" in background
    assert "waitForChildTab" in background
    assert "chrome.tabs.remove(child.id)" in background
    assert "active: false" in background


def test_progress_polling_isolated_from_ai_pipeline() -> None:
    ui = (ROOT / "src/jobpilot/ui/batch_apply_execution.py").read_text(encoding="utf-8")
    assert '@st.fragment(run_every="2s")' in ui
    assert "DeepSeek" not in ui
    assert "MatchingService" not in ui


def test_english_model_reason_has_deterministic_chinese_fallback() -> None:
    result = chinese_display_reason(
        "Candidate has strong Python and agent workflow experience.",
        ScreeningTier.PRIORITY,
    )
    assert result == "核心能力与岗位要求高度匹配，建议优先沟通。"


def test_contact_extension_never_stores_chat_body_or_generates_greeting() -> None:
    sources = _extension("background.js") + _extension("boss_apply.js")
    lowered = sources.casefold()
    assert "chat_body" not in lowered
    assert "greeting" not in lowered
    assert "default_greeting" not in lowered
