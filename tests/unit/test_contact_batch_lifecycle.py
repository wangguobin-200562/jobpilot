from streamlit.testing.v1 import AppTest

from jobpilot.browser import JobDiscoveryItem


def _discovery_state_app() -> None:
    import streamlit as st

    from jobpilot.ui.site_discovery import _store_received_jobs
    from jobpilot.ui.state import initialize_session_state

    initialize_session_state()
    _store_received_jobs(st.session_state["incoming_jobs"])


def test_cumulative_extension_payload_only_exposes_unscreened_jobs() -> None:
    old = JobDiscoveryItem(
        company="旧公司",
        job_title="旧岗位",
        source_url="https://www.zhipin.com/job_detail/old.html",
        jd_text="旧批次的虚构岗位描述。",
    )
    new = JobDiscoveryItem(
        company="新公司",
        job_title="新岗位",
        source_url="https://www.zhipin.com/job_detail/new.html",
        jd_text="新批次的虚构岗位描述。",
    )
    app = AppTest.from_function(_discovery_state_app)
    app.session_state["incoming_jobs"] = [old, new]
    app.session_state["screened_discovery_keys"] = {
        "url:https://www.zhipin.com/job_detail/old.html"
    }
    app.run()

    result = app.session_state["boss_discovery_result"]
    assert not app.exception
    assert result.discovered_count == 1
    assert result.items[0].job_title == "新岗位"
