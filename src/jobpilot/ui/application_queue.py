"""Streamlit view for the local-only application queue."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from jobpilot.models import (
    JobApplication, PreparationStatus, QueueSort, ScreeningTier,
)
from jobpilot.services import ApplicationQueueService, SOURCE_LABELS
from jobpilot.storage import ApplicationRepository, ApplicationRepositoryError


TIER_LABELS = {
    ScreeningTier.PRIORITY: "优先投", ScreeningTier.RECOMMENDED: "可以投",
    ScreeningTier.CAUTION: "谨慎投", ScreeningTier.LOW_PRIORITY: "暂不优先",
}
TIER_COLORS = {
    ScreeningTier.PRIORITY: "blue", ScreeningTier.RECOMMENDED: "green",
    ScreeningTier.CAUTION: "orange", ScreeningTier.LOW_PRIORITY: "gray",
}
PREPARATION_LABELS = {
    PreparationStatus.READY: "可以投递",
    PreparationStatus.REVIEW_NEEDED: "建议先检查",
    PreparationStatus.GAP_WARNING: "存在明显缺口",
}
PREPARATION_COLORS = {
    PreparationStatus.READY: "green",
    PreparationStatus.REVIEW_NEEDED: "orange",
    PreparationStatus.GAP_WARNING: "red",
}
SORT_OPTIONS = {
    "投递优先级": QueueSort.PRIORITY,
    "匹配度最高": QueueSort.MATCH_SCORE,
    "最近保存": QueueSort.NEWEST,
    "最早保存": QueueSort.OLDEST,
}
FILTER_OPTIONS = ("全部待投递", "优先投", "可以投", "建议先检查")


def _local_time(value) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _set_feedback(message: str) -> None:
    st.session_state.application_feedback = ("success", message)


def render_application_queue(
    *,
    repository_factory: Callable[[], ApplicationRepository],
    detail_renderer: Callable[[ApplicationRepository, JobApplication], None],
) -> None:
    """Render saved applications as a deterministic daily action queue."""
    try:
        repository = repository_factory()
        service = ApplicationQueueService(repository)
    except ApplicationRepositoryError:
        st.error("投递队列暂时无法加载，请稍后重试。", icon=":material/error:")
        return

    search_col, sort_col = st.columns([2, 1])
    query = search_col.text_input(
        "搜索公司或岗位", placeholder="输入公司或岗位关键词", key="queue_search"
    )
    sort_label = sort_col.selectbox(
        "排序", tuple(SORT_OPTIONS), key="queue_sort"
    )
    selected_filter = st.segmented_control(
        "队列筛选", FILTER_OPTIONS, default="全部待投递", key="queue_filter",
        label_visibility="collapsed", width="stretch", wrap=False,
    )
    tier = (
        ScreeningTier.PRIORITY if selected_filter == "优先投"
        else ScreeningTier.RECOMMENDED if selected_filter == "可以投" else None
    )
    preparation = (
        PreparationStatus.REVIEW_NEEDED if selected_filter == "建议先检查" else None
    )
    try:
        result = service.load_queue(
            query=query, tier=tier, preparation=preparation,
            sort=SORT_OPTIONS[sort_label],
        )
    except ApplicationRepositoryError:
        st.error("投递队列暂时无法加载，请稍后重试。", icon=":material/error:")
        return

    with st.container(horizontal=True, wrap=True):
        st.metric("待投递", result.total_count, border=True)
        st.metric("可以投递", result.ready_count, border=True)
        st.metric("建议先检查", result.review_needed_count, border=True)
        st.metric("存在明显缺口", result.gap_warning_count, border=True)

    st.subheader("待投递队列")
    if not result.items:
        with st.container(border=True):
            if result.total_count == 0:
                st.subheader("当前没有待投递岗位")
                st.write("可以先在岗位匹配中进行批量筛选，并将合适岗位保存到投递管理。")
            else:
                st.subheader("没有符合当前条件的岗位")
                st.write("可以调整搜索关键词、筛选条件或排序方式。")
    else:
        for item in result.items:
            with st.container(border=True):
                with st.container(horizontal=True, wrap=True, gap="small"):
                    st.badge(TIER_LABELS[item.screening_tier], color=TIER_COLORS[item.screening_tier])
                    st.badge(PREPARATION_LABELS[item.preparation_status], color=PREPARATION_COLORS[item.preparation_status])
                    st.caption(SOURCE_LABELS.get(item.source or "other", "其他"))
                st.write(f"**{item.company} · {item.job_title}**")
                st.caption(
                    f"地点：{item.location or '—'}　·　匹配度："
                    f"{'—' if item.match_score is None else f'{item.match_score:.0f}%'}　·　"
                    f"保存时间：{_local_time(item.created_at)}"
                )
                st.write(f"主要缺口：{item.main_gap or '暂无明显必备技能缺口'}")
                if item.optimization_status.value == "generated":
                    st.caption("已生成岗位定向建议")
                elif item.preparation_status is PreparationStatus.READY:
                    st.caption("当前可直接投递，如有需要可查看岗位定向建议。")
                else:
                    st.caption("未生成岗位定向建议，可在完整分析中按需生成。")
                with st.container(horizontal=True, wrap=True):
                    if st.button("查看详情", key=f"queue_view_{item.application_id}", icon=":material/visibility:"):
                        st.session_state.selected_application_id = item.application_id
                    if item.source_url:
                        st.link_button("打开岗位", item.source_url, icon=":material/open_in_new:")
                    if st.button("标记已投递", key=f"queue_apply_{item.application_id}", type="primary", icon=":material/check_circle:"):
                        try:
                            service.mark_applied(item.application_id)
                        except ApplicationRepositoryError:
                            st.error("投递状态暂时无法更新，请稍后重试。")
                        else:
                            _set_feedback("已标记为已投递。")
                            st.rerun()
                    if st.button("明天再处理", key=f"queue_defer_1_{item.application_id}", icon=":material/snooze:"):
                        try:
                            service.defer(item.application_id, 1)
                        except ApplicationRepositoryError:
                            st.error("岗位暂时无法延期，请稍后重试。")
                        else:
                            _set_feedback("岗位已暂缓到明天。")
                            st.rerun()
                    if st.button("3 天后处理", key=f"queue_defer_3_{item.application_id}"):
                        try:
                            service.defer(item.application_id, 3)
                        except ApplicationRepositoryError:
                            st.error("岗位暂时无法延期，请稍后重试。")
                        else:
                            _set_feedback("岗位已暂缓 3 天。")
                            st.rerun()

    if result.deferred_items:
        with st.expander(f"稍后处理（{len(result.deferred_items)}）", expanded=False):
            for item in result.deferred_items:
                with st.container(border=True):
                    st.write(f"**{item.company} · {item.job_title}**")
                    st.caption(f"恢复时间：{_local_time(item.deferred_until)}")
                    if st.button("提前恢复", key=f"queue_restore_{item.application_id}", icon=":material/restore:"):
                        try:
                            service.cancel_defer(item.application_id)
                        except ApplicationRepositoryError:
                            st.error("岗位暂时无法恢复，请稍后重试。")
                        else:
                            _set_feedback("岗位已恢复到待投递队列。")
                            st.rerun()

    selected_id = st.session_state.get("selected_application_id")
    if selected_id is not None:
        try:
            selected = repository.get_application_by_id(int(selected_id))
        except ApplicationRepositoryError:
            st.error("岗位详情暂时无法加载，请稍后重试。")
        else:
            if selected is not None:
                detail_renderer(repository, selected)
