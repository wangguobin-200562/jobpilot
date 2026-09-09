from __future__ import annotations

from streamlit.testing.v1 import AppTest

from jobpilot.models import (
    ApplyExecutionStatus,
    ApplyReadiness,
    ApplyResultReport,
    BatchApplyExecution,
    BatchApplyExecutionItem,
    BatchApplyItem,
    BatchApplyPlan,
    ScreeningTier,
    ExtensionHeartbeat,
)


def _plan(count=2):
    items = [
        BatchApplyItem(
            application_id=index,
            company=f"虚构公司{index}",
            job_title=f"虚构岗位{index}",
            source="boss",
            source_url=f"https://www.zhipin.com/job_detail/ui-apply-{index}.html",
            screening_tier=ScreeningTier.PRIORITY,
            main_reason="虚构推荐理由。",
            selected=True,
            apply_readiness=ApplyReadiness.READY,
        )
        for index in range(1, count + 1)
    ]
    return BatchApplyPlan(items=items, selected_count=count, total_count=count)


def _app() -> None:
    import streamlit as st

    from jobpilot.browser import ApplyTaskChannel
    from jobpilot.models import ExtensionHeartbeat
    from jobpilot.ui.batch_apply_execution import render_batch_apply_execution
    from jobpilot.ui.state import initialize_session_state

    class FakeBridge:
        def __init__(self):
            self.apply_channel = ApplyTaskChannel()
            self.running = False
            self.token = "masked-test-token"

        def start(self):
            self.running = True
            return self

    class Repository:
        def list_applications(self):
            return []

        def update_status(self, application_id, status):
            del application_id, status
            return None

    initialize_session_state()
    if "test_apply_bridge" not in st.session_state:
        st.session_state.test_apply_bridge = FakeBridge()
        if st.session_state.get("test_bridge_should_connect", True):
            st.session_state.test_apply_bridge.start()
            st.session_state.test_apply_bridge.apply_channel.heartbeat(
                ExtensionHeartbeat(extension_connected=True, execution_id=None)
            )
    render_batch_apply_execution(
        st.session_state.test_apply_plan,
        repository_factory=Repository,
        bridge_factory=lambda: st.session_state.test_apply_bridge,
    )


def _ready_app(count=2):
    app = AppTest.from_function(_app)
    app.session_state["test_apply_plan"] = _plan(count)
    return app.run()


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _start(app):
    _button(app, "开始沟通 2 个").click().run()
    assert any("默认招呼语联系 2 位招聘方" in item.value for item in app.markdown)
    _button(app, "确认开始").click().run()
    return app


def test_one_dialog_confirmation_is_required_before_tasks_are_published() -> None:
    app = _ready_app()
    assert app.session_state["batch_apply_execution"] is None

    _button(app, "开始沟通 2 个").click().run()

    assert app.session_state["batch_apply_execution"] is None
    _button(app, "确认开始").click().run()
    assert len(app.session_state["batch_apply_execution"].items) == 2
    diagnostics = app.session_state["test_apply_bridge"].apply_channel.diagnostics()
    assert diagnostics.pending_count == 2
    assert diagnostics.processing_count == 0


def test_rerun_preserves_bridge_token_channel_and_pending_tasks() -> None:
    app = _start(_ready_app())
    bridge = app.session_state["test_apply_bridge"]
    token = bridge.token
    channel = bridge.apply_channel

    app.run()

    assert app.session_state["test_apply_bridge"].token == token
    assert app.session_state["test_apply_bridge"].apply_channel is channel
    assert channel.diagnostics().pending_count == 2


def test_progress_refresh_shows_contacted_and_failure_without_hiding_items() -> None:
    app = _start(_ready_app())
    channel = app.session_state["test_apply_bridge"].apply_channel
    _, first = channel.next_task()
    channel.report(
        ApplyResultReport(
            task_id=first.task_id,
            status=ApplyExecutionStatus.CONTACTED,
            message="已建立沟通会话。",
            contact_button_clicked=True,
            contact_success_detected=True,
            conversation_found=True,
        )
    )
    _, second = channel.next_task()
    channel.report(
        ApplyResultReport(
            task_id=second.task_id,
            status=ApplyExecutionStatus.FAILED,
            message="虚构技术错误。",
        )
    )

    app.run()

    assert not app.exception
    metric_values = {metric.label: metric.value for metric in app.metric}
    assert metric_values["成功沟通"] == "1"
    assert metric_values["失败"] == "1"
    assert any("虚构技术错误" in item.value for item in app.caption)


def test_manual_required_can_be_skipped_and_next_task_remains_available() -> None:
    app = _start(_ready_app())
    channel = app.session_state["test_apply_bridge"].apply_channel
    _, first = channel.next_task()
    channel.report(
        ApplyResultReport(
            task_id=first.task_id,
            status=ApplyExecutionStatus.MANUAL_REQUIRED,
            message="出现验证码。",
        )
    )
    app.run()

    _button(app, "跳过该岗位").click().run()

    assert not app.exception
    assert channel.next_task()[0] == "task"


def test_cancel_stops_remaining_pending_work() -> None:
    app = _start(_ready_app())

    _button(app, "停止本次沟通").click().run()

    execution = app.session_state["batch_apply_execution"]
    assert execution.cancelled is True
    assert all(item.status is ApplyExecutionStatus.CANCELLED for item in execution.items)


def test_heartbeat_diagnostics_are_collapsed_and_token_is_not_rendered() -> None:
    app = _ready_app()
    bridge = app.session_state["test_apply_bridge"]
    bridge.start()
    bridge.apply_channel.heartbeat(
        ExtensionHeartbeat(extension_connected=True, execution_id=None)
    )
    app = _start(app)

    assert any(expander.label == "高级设置 · 连接诊断" for expander in app.expander)
    assert not any(item.value == bridge.token for item in app.code)


def test_old_execution_is_not_rendered_or_blocking_for_new_screening_batch() -> None:
    app = AppTest.from_function(_app)
    plan = _plan(1).model_copy(update={"screening_batch_id": "screening-new"})
    old = BatchApplyExecution(
        execution_id="execution-old",
        screening_batch_id="screening-old",
        items=[
            BatchApplyExecutionItem(
                task_id="task-old-1",
                company="上一轮失败公司",
                job_title="上一轮失败岗位",
                source_url="https://www.zhipin.com/job_detail/old.html",
                status=ApplyExecutionStatus.FAILED,
                message="上一轮失败结果。",
            )
        ],
    )
    app.session_state["test_apply_plan"] = plan
    app.session_state["batch_apply_execution"] = old
    app.run()

    assert not app.exception
    assert _button(app, "开始沟通 1 个")
    assert not any("上一轮失败" in item.value for item in app.caption)


def test_contact_start_is_blocked_without_bridge_heartbeat_and_keeps_selection() -> None:
    app = AppTest.from_function(_app)
    app.session_state["test_apply_plan"] = _plan(2)
    app.session_state["test_bridge_should_connect"] = False
    app.run()

    button = _button(app, "开始沟通 2 个")
    assert button.disabled is True
    assert app.session_state["batch_apply_execution"] is None
    assert app.session_state["test_apply_plan"].selected_count == 2


def test_reconnect_enables_contact_without_creating_duplicate_tasks() -> None:
    app = AppTest.from_function(_app)
    app.session_state["test_apply_plan"] = _plan(2)
    app.session_state["test_bridge_should_connect"] = False
    app.run()
    bridge = app.session_state["test_apply_bridge"]
    bridge.start()
    bridge.apply_channel.heartbeat(
        ExtensionHeartbeat(extension_connected=True, execution_id=None)
    )

    app.run()
    assert _button(app, "开始沟通 2 个").disabled is False
    _start(app)
    assert bridge.apply_channel.diagnostics().pending_count == 2
    app.run()
    assert bridge.apply_channel.diagnostics().pending_count == 2
