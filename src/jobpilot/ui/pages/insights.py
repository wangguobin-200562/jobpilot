"""Local-only job-search analytics page."""

from collections.abc import Callable, Sequence

import streamlit as st

from jobpilot.models import JobSearchAnalyticsResult, SkillFrequency, STATUS_LABELS
from jobpilot.services import JobSearchAnalyticsService
from jobpilot.storage import ApplicationRepository, ApplicationRepositoryError


def _score(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} 分"


def _rate(value: float | None, *, sufficient: bool) -> str:
    if value is None or not sufficient:
        return "—"
    return f"{value:.1%}"


def _render_frequency_chart(
    title: str,
    values: Sequence[SkillFrequency],
    *,
    empty_text: str = "暂无可展示的数据。",
) -> None:
    st.markdown(f"**{title}**")
    if not values:
        st.caption(empty_text)
        return
    rows = [
        {"技能": item.skill, "岗位数": item.count}
        for item in reversed(values[:8])
    ]
    st.bar_chart(
        rows,
        x="岗位数",
        y="技能",
        horizontal=True,
        color="#2563eb",
        height=max(220, len(rows) * 34),
        width="stretch",
    )


def _render_core_metrics(analytics: JobSearchAnalyticsResult) -> None:
    highest = analytics.highest_matching_job
    with st.container(horizontal=True, wrap=True):
        st.metric("全部岗位", analytics.total_applications, border=True)
        st.metric(
            "平均匹配度",
            _score(analytics.average_match_score),
            border=True,
        )
        st.metric("已投递", analytics.applied_count, border=True)
        st.metric("面试中", analytics.interviewing_count, border=True)
        st.metric("Offer", analytics.offer_count, border=True)
        st.metric(
            "最高匹配岗位",
            _score(highest.match_score if highest else None),
            border=True,
            help=(
                f"{highest.company} · {highest.job_title}"
                if highest
                else "暂无已评分岗位"
            ),
        )
    st.caption(f"已有 {analytics.scored_applications_count} 个岗位包含匹配分数。")


def _render_funnel(analytics: JobSearchAnalyticsResult) -> None:
    funnel = analytics.funnel
    st.subheader("求职漏斗")
    st.caption(
        "以已记录投递时间的岗位为样本，展示当前所处阶段；由于尚未保存状态历史，"
        "已结束岗位不会被推断为曾经到达某一阶段。"
    )
    with st.container(horizontal=True, wrap=True):
        st.metric("已投递样本", funnel.applied_denominator, border=True)
        st.metric(
            "沟通率",
            _rate(funnel.contact_rate, sufficient=analytics.trend_data_sufficient),
            border=True,
        )
        st.metric(
            "面试率",
            _rate(funnel.interview_rate, sufficient=analytics.trend_data_sufficient),
            border=True,
        )
        st.metric(
            "Offer 率",
            _rate(funnel.offer_rate, sufficient=analytics.trend_data_sufficient),
            border=True,
        )


def _render_match_insights(analytics: JobSearchAnalyticsResult) -> None:
    st.subheader("匹配度分布")
    st.caption("高匹配为 80–100 分，中匹配为 60–79 分，低匹配为 0–59 分；未评分岗位不计入。")
    distribution = analytics.match_distribution
    with st.container(horizontal=True, wrap=True):
        st.metric("高匹配", distribution.high_count, border=True)
        st.metric("中匹配", distribution.medium_count, border=True)
        st.metric("低匹配", distribution.low_count, border=True)

    st.markdown("**高匹配岗位当前进展**")
    progress = analytics.high_match_progress
    st.caption("以下仅描述高匹配岗位目前的状态，不代表匹配度与求职结果存在因果关系。")
    with st.container(horizontal=True, wrap=True):
        st.metric("高匹配岗位", progress.high_match_count, border=True)
        st.metric("当前已沟通", progress.contacted_count, border=True)
        st.metric("当前面试中", progress.interviewing_count, border=True)
        st.metric("当前 Offer", progress.offer_count, border=True)


def _render_skill_insights(analytics: JobSearchAnalyticsResult) -> None:
    st.subheader("能力缺口")
    if not analytics.skill_gap_data_sufficient:
        st.info("数据不足：至少保存 3 个包含匹配结果的岗位后，才展示能力缺口排行。")
    else:
        left, right = st.columns(2, gap="large")
        with left:
            _render_frequency_chart("必备技能缺口", analytics.required_skill_gaps)
        with right:
            _render_frequency_chart("加分技能缺口", analytics.preferred_skill_gaps)

    st.subheader("目标岗位技能趋势")
    if not analytics.trend_data_sufficient:
        st.info("数据不足：至少保存 3 个岗位后，才展示目标岗位技能趋势。")
        return
    required, preferred, tools = st.columns(3, gap="large")
    with required:
        _render_frequency_chart("必备技能需求", analytics.required_skill_demand)
    with preferred:
        _render_frequency_chart("加分技能需求", analytics.preferred_skill_demand)
    with tools:
        _render_frequency_chart("工具与技术需求", analytics.tools_demand)


def _render_top_jobs(analytics: JobSearchAnalyticsResult) -> None:
    st.subheader("最匹配岗位")
    if not analytics.top_matching_jobs:
        st.caption("暂无已评分岗位。")
        return
    rows = [
        {
            "公司": item.company,
            "岗位": item.job_title,
            "匹配度": item.match_score,
            "当前状态": [STATUS_LABELS[item.status]],
        }
        for item in analytics.top_matching_jobs
    ]
    st.dataframe(
        rows,
        column_config={
            "公司": st.column_config.TextColumn("公司", width="medium"),
            "岗位": st.column_config.TextColumn("岗位", width="large"),
            "匹配度": st.column_config.ProgressColumn(
                "匹配度", min_value=0, max_value=100, format="%d分", color="blue"
            ),
            "当前状态": st.column_config.MultiselectColumn(
                "当前状态", options=list(STATUS_LABELS.values()), color="auto"
            ),
        },
        hide_index=True,
        width="stretch",
    )


def _render_recent_activity(analytics: JobSearchAnalyticsResult) -> None:
    recent = analytics.recent_activity
    st.subheader("最近求职活动")
    with st.container(horizontal=True, wrap=True):
        st.metric("近 7 天新增岗位", recent.created_last_7_days, border=True)
        st.metric("近 30 天新增岗位", recent.created_last_30_days, border=True)
        st.metric("近 30 天已投递", recent.applied_last_30_days, border=True)


def render_insights(
    *,
    repository_factory: Callable[[], ApplicationRepository] = ApplicationRepository,
) -> None:
    """Render deterministic insights over locally saved applications."""
    st.title("求职洞察")
    st.caption("基于本地投递记录，了解求职进展、能力缺口与目标岗位需求。")

    try:
        analytics = JobSearchAnalyticsService(repository_factory()).analyze()
    except ApplicationRepositoryError:
        st.error("求职洞察暂时无法加载，请稍后重试。", icon=":material/error:")
        return

    st.caption("本页仅分析本地 SQLite 数据，不会调用 AI 模型或外部 API。")
    if analytics.total_applications == 0:
        with st.container(border=True):
            st.subheader("暂无可分析的岗位")
            st.write("先在岗位匹配中保存分析结果，或在投递管理中添加岗位记录。")
        return

    if not analytics.trend_data_sufficient:
        st.info("当前数据较少，继续保存和更新岗位后，会逐步生成更有参考价值的求职洞察。")

    st.subheader("核心数据")
    _render_core_metrics(analytics)
    _render_funnel(analytics)
    _render_skill_insights(analytics)
    _render_match_insights(analytics)
    _render_top_jobs(analytics)
    _render_recent_activity(analytics)
