"""Application dashboard backed by the local repository."""

from collections.abc import Callable

import streamlit as st

from jobpilot.models import STATUS_BY_LABEL, STATUS_LABELS
from jobpilot.services import JobSearchAnalyticsService
from jobpilot.storage import ApplicationRepository, ApplicationRepositoryError


STATUS_OPTIONS = ("全部岗位", *STATUS_BY_LABEL)


def _local_time(value) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def render_home(
    *,
    repository_factory: Callable[[], ApplicationRepository] = ApplicationRepository,
) -> None:
    """Render the existing dashboard design with real local data."""
    st.title("求职看板")
    st.caption("查看沟通进展和下一步行动，让每一次机会都有回响。")

    try:
        repository = repository_factory()
        analytics = JobSearchAnalyticsService(repository).analyze()
    except ApplicationRepositoryError:
        st.error("投递数据暂时无法加载，请稍后重试。", icon=":material/error:")
        return

    metrics = [
        ("已沟通", analytics.contacted_count),
        ("待跟进", analytics.saved_count + analytics.applied_count),
        ("面试中", analytics.interviewing_count),
        ("Offer", analytics.offer_count),
    ]
    with st.container(horizontal=True, wrap=True):
        for label, value in metrics:
            st.metric(label, value, border=True)

    st.markdown("**求职洞察摘要**")
    average_score = (
        "—"
        if analytics.average_match_score is None
        else f"{analytics.average_match_score:.1f} 分"
    )
    interview_rate = (
        "—"
        if not analytics.trend_data_sufficient
        or analytics.funnel.interview_rate is None
        else f"{analytics.funnel.interview_rate:.1%}"
    )
    with st.container(horizontal=True, wrap=True):
        st.metric("平均匹配度", average_score, border=True)
        st.metric(
            "面试率",
            interview_rate,
            border=True,
            help="样本少于 3 个岗位时不展示；分母为已记录投递时间的岗位。",
        )

    st.subheader("岗位进展")
    selected_label = st.segmented_control(
        "按状态筛选",
        STATUS_OPTIONS,
        default="全部岗位",
        key="dashboard_status_filter",
        label_visibility="collapsed",
        width="stretch",
        wrap=False,
    )
    selected_status = (
        None
        if not selected_label or selected_label == "全部岗位"
        else STATUS_BY_LABEL[selected_label]
    )
    try:
        applications = repository.list_applications(status=selected_status)
    except ApplicationRepositoryError:
        st.error("投递数据暂时无法加载，请稍后重试。", icon=":material/error:")
        return

    if not applications:
        with st.container(border=True):
            st.subheader("还没有岗位记录")
            st.write("完成岗位分析后，可以将岗位保存到投递管理。")
        return

    rows = [
        {
            "状态": [STATUS_LABELS[item.status]],
            "公司与岗位": f"{item.company} · {item.job_title}",
            "匹配度": item.match_score,
            "地点": item.location or "—",
            "最近更新时间": _local_time(item.updated_at),
        }
        for item in applications
    ]
    st.dataframe(
        rows,
        column_config={
            "状态": st.column_config.MultiselectColumn(
                "状态",
                options=list(STATUS_BY_LABEL),
                color="auto",
                width="small",
            ),
            "公司与岗位": st.column_config.TextColumn("公司与岗位", width="large"),
            "匹配度": st.column_config.ProgressColumn(
                "匹配度",
                min_value=0,
                max_value=100,
                format="%d分",
                color="blue",
                width="medium",
            ),
            "地点": st.column_config.TextColumn("地点", width="small"),
            "最近更新时间": st.column_config.TextColumn(
                "最近更新时间", width="medium"
            ),
        },
        hide_index=True,
        width="stretch",
        height=390,
    )
