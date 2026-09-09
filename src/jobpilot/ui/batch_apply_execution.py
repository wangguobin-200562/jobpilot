"""One-confirmation, auto-refreshing Extension contact UI."""

from __future__ import annotations

from collections import Counter
import streamlit as st

from jobpilot.browser import ApplyChannelError, ExtensionBridgeError
from jobpilot.models import ApplyExecutionStatus, BatchApplyExecution, BatchApplyPlan
from jobpilot.services import BatchApplyExecutionService
from jobpilot.storage import ApplicationRepository, ApplicationRepositoryError


STATUS_LABELS = {
    ApplyExecutionStatus.PENDING: "等待处理",
    ApplyExecutionStatus.PROCESSING: "正在沟通",
    ApplyExecutionStatus.CONTACTED: "已沟通",
    ApplyExecutionStatus.ALREADY_CONTACTED: "已存在沟通",
    ApplyExecutionStatus.MANUAL_REQUIRED: "需要人工处理",
    ApplyExecutionStatus.SKIPPED: "已跳过",
    ApplyExecutionStatus.FAILED: "失败",
    ApplyExecutionStatus.PAUSED: "已安全暂停",
    ApplyExecutionStatus.CANCELLED: "已取消",
    ApplyExecutionStatus.APPLIED: "已提交申请",
}


def _sync_snapshot(
    bridge, repository_factory, expected_batch_id: str | None = None
) -> BatchApplyExecution | None:
    snapshot = bridge.apply_channel.snapshot()
    if snapshot is None:
        return None
    if expected_batch_id is not None and snapshot.screening_batch_id != expected_batch_id:
        return None
    try:
        repository = repository_factory()
        synced = BatchApplyExecutionService(repository).sync_contacted_statuses(
            snapshot, set(st.session_state.get("batch_apply_synced_task_ids", set()))
        )
        st.session_state.batch_apply_synced_task_ids = synced
    except ApplicationRepositoryError:
        st.session_state.batch_apply_repository_sync_error = True
    st.session_state.batch_apply_execution = snapshot
    return snapshot


def publish_confirmed_plan(plan, *, repository_factory, bridge_factory) -> bool:
    """Publish exactly the user-confirmed plan; never selects extra jobs."""
    try:
        repository = repository_factory()
        bridge = bridge_factory()
        bridge.start()
        if not bridge.apply_channel.diagnostics().extension_connected:
            raise ExtensionBridgeError(
                "浏览器扩展尚未连接 JobPilot，请先恢复扩展连接。"
            )
        execution = BatchApplyExecutionService(repository).prepare_execution(plan)
        published = bridge.apply_channel.publish(execution)
        if not published:
            execution = bridge.apply_channel.snapshot() or execution
    except (ApplicationRepositoryError, ExtensionBridgeError, ApplyChannelError, ValueError) as exc:
        st.session_state.batch_apply_publish_error = str(exc)
        return False
    st.session_state.batch_apply_execution = execution
    if published:
        st.session_state.batch_apply_synced_task_ids = set()
    st.session_state.batch_apply_start_requested = False
    st.session_state.batch_apply_publish_error = None
    return True


@st.dialog("确认开始沟通", width="small")
def _confirm_dialog(plan, repository_factory, bridge_factory) -> None:
    st.write(f"即将使用你在 BOSS 已设置的默认招呼语联系 {plan.selected_count} 位招聘方。")
    st.caption("不会发送简历，也不会生成自定义消息。")
    left, right = st.columns(2)
    if left.button("取消", width="stretch"):
        st.session_state.batch_apply_start_requested = False
        st.rerun()
    if right.button("确认开始", type="primary", width="stretch"):
        if publish_confirmed_plan(plan, repository_factory=repository_factory, bridge_factory=bridge_factory):
            st.rerun()


def _render_execution_body(execution: BatchApplyExecution, bridge) -> None:
    completed = execution.completed_count
    st.write(f"**沟通进度：{completed} / {len(execution.items)}**")
    st.progress(completed / len(execution.items))
    for item in execution.items:
        with st.container(border=True):
            with st.container(horizontal=True, wrap=True, gap="small"):
                color = "green" if item.status is ApplyExecutionStatus.CONTACTED else "gray"
                st.badge(STATUS_LABELS[item.status], color=color)
                st.write(f"**{item.company} · {item.job_title}**")
            st.caption(item.message)
            if item.status in {ApplyExecutionStatus.MANUAL_REQUIRED, ApplyExecutionStatus.PAUSED}:
                st.warning("该岗位需要人工确认；扩展不会绕过验证或额外表单。")
                with st.container(horizontal=True, gap="small"):
                    st.link_button("打开处理", item.source_url, icon=":material/open_in_new:")
                    if st.button("继续任务", key=f"manual_resume_{item.task_id}"):
                        bridge.apply_channel.resume_manual(item.task_id)
                        st.rerun()
                    if st.button("跳过该岗位", key=f"manual_skip_{item.task_id}"):
                        bridge.apply_channel.resolve_manual(item.task_id, completed=False)
                        st.rerun()
    counts = Counter(item.status for item in execution.items)
    with st.container(horizontal=True, wrap=True):
        st.metric("成功沟通", counts[ApplyExecutionStatus.CONTACTED], border=True)
        st.metric("需人工", counts[ApplyExecutionStatus.MANUAL_REQUIRED], border=True)
        st.metric("已跳过", counts[ApplyExecutionStatus.SKIPPED] + counts[ApplyExecutionStatus.ALREADY_CONTACTED], border=True)
        st.metric("失败", counts[ApplyExecutionStatus.FAILED], border=True)


@st.fragment(run_every="2s")
def _auto_progress(bridge, repository_factory, expected_batch_id=None) -> None:
    execution = _sync_snapshot(bridge, repository_factory, expected_batch_id)
    if execution is None:
        return
    _render_execution_body(execution, bridge)
    if execution.finished_at is not None:
        st.rerun(scope="app")


def render_batch_apply_execution(plan: BatchApplyPlan, *, repository_factory=ApplicationRepository, bridge_factory=None) -> None:
    """Show one confirmation and then isolated automatic progress refresh."""
    if bridge_factory is None:
        from jobpilot.ui.site_discovery import get_extension_bridge
        bridge_factory = get_extension_bridge
    bridge = bridge_factory()
    try:
        bridge.start()
    except ExtensionBridgeError:
        pass
    diagnostics = bridge.apply_channel.diagnostics()
    connection_ready = bridge.running and diagnostics.extension_connected
    selected = [item for item in plan.items if item.selected]
    current_batch_id = plan.screening_batch_id
    execution = st.session_state.get("batch_apply_execution")
    if execution is not None and execution.screening_batch_id != current_batch_id:
        execution = None
    active = execution is not None and execution.finished_at is None
    if not active:
        with st.bottom:
            left, right = st.columns([3, 1])
            connection_label = "● 扩展已连接" if connection_ready else "○ 扩展未连接"
            left.write(f"**已选择 {len(selected)} 个岗位**　{connection_label}")
            if not bridge.running:
                left.caption(bridge.startup_error or "本地 Bridge 未启动。")
            elif not diagnostics.extension_connected:
                left.caption("浏览器扩展尚未连接 JobPilot，请先恢复扩展连接。")
            if right.button(f"开始沟通 {len(selected)} 个", type="primary", disabled=not selected or not connection_ready, key="request_batch_apply_execution", icon=":material/send:", width="stretch"):
                st.session_state.batch_apply_start_requested = True
    if st.session_state.get("batch_apply_start_requested") and not active:
        _confirm_dialog(plan, repository_factory, bridge_factory)
    error = st.session_state.get("batch_apply_publish_error")
    if error:
        st.error(error)
    if execution is None:
        return
    diagnostics = bridge.apply_channel.diagnostics()
    with st.expander("高级设置 · 连接诊断", expanded=False):
        st.write(f"Bridge：{'已连接' if bridge.running else '未连接'}")
        st.write(f"Extension：{'已连接' if diagnostics.extension_connected else '等待连接'}")
        st.write(f"Pending：{diagnostics.pending_count}")
        st.write(f"Processing：{diagnostics.processing_count}")
        st.write(f"Completed：{diagnostics.completed_count}")
        st.write(f"Batch ID：{diagnostics.screening_batch_id or '—'}")
        st.write(f"Plan ID：{diagnostics.contact_plan_id or '—'}")
        st.write(f"Worker Tab：{diagnostics.worker_tab_id if diagnostics.worker_tab_id is not None else '—'}")
        heartbeat_age = diagnostics.heartbeat_age_seconds
        st.write(f"Heartbeat Age：{heartbeat_age:.1f}s" if heartbeat_age is not None else "Heartbeat Age：—")
    if execution.finished_at is None:
        _auto_progress(bridge, repository_factory, current_batch_id)
        if st.button("停止本次沟通", key="cancel_batch_apply_execution", icon=":material/stop_circle:"):
            bridge.apply_channel.cancel()
            st.rerun()
    else:
        current = _sync_snapshot(bridge, repository_factory, current_batch_id) or execution
        _render_execution_body(current, bridge)
        st.success("本批沟通流程已结束，求职看板和求职进度已同步。")
