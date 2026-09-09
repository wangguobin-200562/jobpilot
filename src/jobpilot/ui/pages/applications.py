"""Local job-application management page."""

from collections.abc import Callable

import streamlit as st

from jobpilot.models import (
    ApplicationStatus,
    JobApplication,
    STATUS_BY_LABEL,
    STATUS_LABELS,
)
from jobpilot.storage import ApplicationRepository, ApplicationRepositoryError


FILTER_OPTIONS = ("全部", *STATUS_BY_LABEL)
STATUS_COLORS = {
    ApplicationStatus.SAVED: "gray",
    ApplicationStatus.APPLIED: "blue",
    ApplicationStatus.CONTACTED: "orange",
    ApplicationStatus.INTERVIEWING: "violet",
    ApplicationStatus.OFFER: "green",
    ApplicationStatus.CLOSED: "gray",
}


def _local_time(value) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _score(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}%"


def _render_feedback() -> None:
    feedback = st.session_state.pop("application_feedback", None)
    if feedback:
        level, message = feedback
        getattr(st, level)(message)


def _render_badges(values: list[str], color: str = "blue") -> None:
    if values:
        with st.container(horizontal=True, wrap=True, gap="small"):
            for value in values:
                st.badge(value, color=color)


def _render_application_detail(
    repository: ApplicationRepository, application: JobApplication
) -> None:
    st.divider()
    st.subheader("岗位详情")
    with st.container(border=True):
        columns = st.columns(5)
        for column, (label, value) in zip(
            columns,
            (
                ("公司", application.company),
                ("岗位", application.job_title),
                ("地点", application.location or "—"),
                ("状态", STATUS_LABELS[application.status]),
                ("匹配度", _score(application.match_score)),
            ),
            strict=True,
        ):
            column.caption(label)
            column.write(value)

    profile = application.job_profile
    st.markdown("#### 岗位画像")
    if profile.responsibilities:
        st.caption("岗位职责")
        for value in profile.responsibilities:
            st.markdown(f"- {value}")
    if profile.required_skills:
        st.caption("必备技能")
        _render_badges(profile.required_skills)
    if profile.preferred_skills:
        st.caption("加分技能")
        _render_badges(profile.preferred_skills, color="violet")

    match = application.match_result
    if match is not None:
        st.markdown("#### 匹配结果")
        if match.strengths:
            st.caption("优势")
            for value in match.strengths:
                st.markdown(f"- {value}")
        if match.missing_skills:
            st.caption("缺失技能")
            for value in match.missing_skills:
                st.markdown(f"- {value.skill}：{value.reason}")
        if match.gaps:
            st.caption("能力差距")
            for value in match.gaps:
                st.markdown(f"- {value}")

    optimization = application.optimization_result
    if optimization is not None:
        st.markdown("#### 岗位定向建议")
        st.write(optimization.summary)

    st.markdown("#### 状态与备注")
    status_options = list(STATUS_BY_LABEL)
    current_label = STATUS_LABELS[application.status]
    selected_label = st.selectbox(
        "投递状态",
        status_options,
        index=status_options.index(current_label),
        key=f"application_status_{application.id}",
    )
    if st.button(
        "保存状态",
        key=f"save_application_status_{application.id}",
        icon=":material/save:",
    ):
        try:
            repository.update_status(application.id, STATUS_BY_LABEL[selected_label])
            st.success("投递状态已更新。")
        except ApplicationRepositoryError:
            st.error("投递状态暂时无法更新，请稍后重试。")

    notes = st.text_area(
        "备注",
        value=application.notes,
        placeholder="记录 HR 联系、面试时间、投递渠道或其他说明……",
        key=f"application_notes_{application.id}",
    )
    if st.button(
        "保存备注",
        key=f"save_application_notes_{application.id}",
        icon=":material/note_add:",
    ):
        try:
            repository.update_notes(application.id, notes)
            st.success("备注已保存。")
        except ApplicationRepositoryError:
            st.error("备注暂时无法保存，请稍后重试。")

    with st.expander("原始 JD", expanded=False):
        st.text(application.jd_text or "未保存原始 JD。")

    st.markdown("#### 删除记录")
    if st.button(
        "删除岗位",
        key=f"delete_application_{application.id}",
        icon=":material/delete:",
    ):
        st.session_state.pending_application_delete_id = application.id

    if st.session_state.get("pending_application_delete_id") == application.id:
        st.warning("删除后无法恢复，是否确认删除这条岗位记录？")
        with st.container(horizontal=True):
            if st.button(
                "确认删除",
                type="primary",
                key=f"confirm_delete_application_{application.id}",
            ):
                try:
                    repository.delete_application(application.id)
                    st.session_state.selected_application_id = None
                    st.session_state.pending_application_delete_id = None
                    st.session_state.application_feedback = (
                        "success",
                        "岗位记录已删除。",
                    )
                    st.rerun()
                except ApplicationRepositoryError:
                    st.error("岗位记录暂时无法删除，请稍后重试。")
            if st.button("取消", key=f"cancel_delete_application_{application.id}"):
                st.session_state.pending_application_delete_id = None
                st.rerun()


def _render_all_records(
    *,
    repository_factory: Callable[[], ApplicationRepository] = ApplicationRepository,
) -> None:
    """Render persistent application filtering, detail, and editing."""
    try:
        repository = repository_factory()
        counts = repository.count_by_status()
    except ApplicationRepositoryError:
        st.error("投递数据暂时无法加载，请稍后重试。", icon=":material/error:")
        return

    metrics = [
        ("全部岗位", sum(counts.values())),
        *[(STATUS_LABELS[status], counts[status]) for status in ApplicationStatus],
    ]
    with st.container(horizontal=True, wrap=True):
        for label, value in metrics:
            st.metric(label, value, border=True)

    st.subheader("岗位列表")
    selected_label = st.segmented_control(
        "状态筛选",
        FILTER_OPTIONS,
        default="全部",
        key="applications_status_filter",
        label_visibility="collapsed",
        width="stretch",
        wrap=False,
    )
    company_column, job_column = st.columns(2)
    company_query = company_column.text_input(
        "搜索公司", placeholder="输入公司关键词", key="applications_company_query"
    )
    job_query = job_column.text_input(
        "搜索岗位", placeholder="输入岗位关键词", key="applications_job_query"
    )
    status = (
        None
        if not selected_label or selected_label == "全部"
        else STATUS_BY_LABEL[selected_label]
    )
    try:
        applications = repository.list_applications(
            status=status, company_query=company_query, job_title_query=job_query
        )
    except ApplicationRepositoryError:
        st.error("投递数据暂时无法加载，请稍后重试。", icon=":material/error:")
        return

    if not applications:
        with st.container(border=True):
            st.subheader("暂无保存的岗位")
            st.write("完成岗位分析后，可以将岗位保存到投递管理。")
    else:
        headings = st.columns([1.1, 2.5, 1, 1.2, 1.5, 0.8])
        for column, label in zip(
            headings,
            ("状态", "公司与岗位", "匹配度", "地点", "更新时间", "操作"),
            strict=True,
        ):
            column.caption(label)
        for application in applications:
            with st.container(border=True):
                columns = st.columns([1.1, 2.5, 1, 1.2, 1.5, 0.8])
                columns[0].badge(
                    STATUS_LABELS[application.status],
                    color=STATUS_COLORS[application.status],
                )
                columns[1].write(f"**{application.company} · {application.job_title}**")
                columns[2].write(_score(application.match_score))
                columns[3].write(application.location or "—")
                columns[4].write(_local_time(application.updated_at))
                if columns[5].button("查看", key=f"view_application_{application.id}"):
                    st.session_state.selected_application_id = application.id
                    st.session_state.pending_application_delete_id = None

    selected_id = st.session_state.get("selected_application_id")
    if selected_id is not None:
        try:
            selected = repository.get_application_by_id(int(selected_id))
        except ApplicationRepositoryError:
            st.error("岗位详情暂时无法加载，请稍后重试。")
        else:
            if selected is None:
                st.session_state.selected_application_id = None
            else:
                _render_application_detail(repository, selected)


def _render_contact_progress(
    *, repository_factory: Callable[[], ApplicationRepository] = ApplicationRepository
) -> None:
    """Show the primary BOSS workflow as contact progress, not an apply queue."""
    try:
        repository = repository_factory()
        applications = repository.list_applications()
    except ApplicationRepositoryError:
        st.error("求职进度暂时无法加载，请稍后重试。", icon=":material/error:")
        return

    options = ("全部", "待沟通", "已沟通", "面试中", "Offer", "已结束")
    status_for_label = {
        "待沟通": ApplicationStatus.SAVED,
        "已沟通": ApplicationStatus.CONTACTED,
        "面试中": ApplicationStatus.INTERVIEWING,
        "Offer": ApplicationStatus.OFFER,
        "已结束": ApplicationStatus.CLOSED,
    }
    with st.container(horizontal=True, wrap=True):
        for label in options:
            if label == "全部":
                count = len(applications)
            else:
                count = sum(item.status is status_for_label[label] for item in applications)
            st.metric(label, count, border=True)

    selected_label = st.segmented_control(
        "进度筛选",
        options,
        default="全部",
        key="contact_progress_filter",
        label_visibility="collapsed",
        width="stretch",
    )
    selected_status = status_for_label.get(selected_label or "全部")
    visible_items = [
        item for item in applications
        if selected_status is None or item.status is selected_status
    ]
    if not visible_items:
        with st.container(border=True):
            st.subheader("当前没有对应岗位")
            st.caption("从岗位匹配完成筛选和沟通后，状态会自动同步到这里。")
        return

    for application in visible_items:
        with st.container(border=True):
            row = st.columns([1.1, 3, 1, 1.2, 0.8])
            row[0].badge(STATUS_LABELS[application.status], color=STATUS_COLORS[application.status])
            row[1].write(f"**{application.company} · {application.job_title}**")
            row[2].write(_score(application.match_score))
            row[3].write(application.location or "—")
            if row[4].button("查看", key=f"progress_view_{application.id}"):
                st.session_state.selected_application_id = application.id

    selected_id = st.session_state.get("selected_application_id")
    if selected_id is not None:
        selected = repository.get_application_by_id(int(selected_id))
        if selected is not None:
            _render_application_detail(repository, selected)


def render_applications(
    *,
    repository_factory: Callable[[], ApplicationRepository] = ApplicationRepository,
) -> None:
    """Render contact-oriented progress while preserving all historical records."""
    st.title("求职进度")
    st.caption("集中跟踪已沟通岗位和后续求职进展。")
    _render_feedback()
    mode = st.segmented_control(
        "求职进度模式",
        ("求职进度", "投递队列", "全部记录"),
        default="求职进度",
        key="applications_mode",
        label_visibility="collapsed",
    )
    if mode == "全部记录":
        _render_all_records(repository_factory=repository_factory)
        return
    if mode == "投递队列":
        from jobpilot.ui.application_queue import render_application_queue

        render_application_queue(
            repository_factory=repository_factory,
            detail_renderer=_render_application_detail,
        )
        return

    _render_contact_progress(repository_factory=repository_factory)
