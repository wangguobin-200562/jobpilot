"""Application navigation."""

from pathlib import Path

import streamlit as st

PLANNED_NAVIGATION = (
    "求职看板",
    "我的简历",
    "岗位匹配",
    "求职进度",
)

_ASSET_DIR = Path(__file__).resolve().parents[3] / "assets"


def create_navigation() -> st.Page:
    """Create the persistent product navigation."""
    from jobpilot.ui.pages.home import render_home
    from jobpilot.ui.pages.job_match import render_job_match
    from jobpilot.ui.pages.applications import render_applications
    from jobpilot.ui.pages.resume_analysis import render_resume_analysis

    st.logo(
        _ASSET_DIR / "jobpilot-logo.svg",
        size="large",
        icon_image=":material/send:",
    )
    st.sidebar.caption("让每一次投递，更接近理想的你")

    return st.navigation(
        [
            st.Page(
                render_home,
                title="求职看板",
                icon=":material/dashboard:",
                default=True,
            ),
            st.Page(
                render_resume_analysis,
                title="我的简历",
                icon=":material/document_search:",
            ),
            st.Page(
                render_job_match,
                title="岗位匹配",
                icon=":material/target:",
            ),
            st.Page(
                render_applications,
                title="求职进度",
                icon=":material/work_history:",
            ),
        ],
        position="sidebar",
        expanded=True,
    )
