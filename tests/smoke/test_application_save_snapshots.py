from streamlit.testing.v1 import AppTest

from jobpilot.storage import ApplicationRepository


def _save_snapshot_app() -> None:
    import streamlit as st

    from jobpilot.models import (
        JobProfile,
        MatchResult,
        MatchScoreBreakdown,
        ResumeOptimizationResult,
    )
    from jobpilot.ui.pages.job_match import _render_save_application
    from jobpilot.ui.state import initialize_session_state
    from jobpilot.storage import ApplicationRepository

    initialize_session_state()
    st.session_state.match_result = MatchResult(
        scores=MatchScoreBreakdown(overall_score=88),
        strengths=["Python 经验匹配"],
    )
    st.session_state.optimization_result = ResumeOptimizationResult(
        summary="当前表达整体较成熟。"
    )
    _render_save_application(
        JobProfile(
            company="示例科技",
            job_title="AI 实习生",
            location="深圳",
            required_skills=["Python"],
        ),
        "岗位职责：开发 AI 应用",
        repository_factory=ApplicationRepository,
    )


def test_save_flow_includes_available_match_and_optimization_snapshots(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    app = AppTest.from_function(_save_snapshot_app).run()

    app.button(key="save_job_application").click().run()

    assert not app.exception
    saved = ApplicationRepository(database).list_applications()
    assert len(saved) == 1
    assert saved[0].match_score == 88
    assert saved[0].match_result is not None
    assert saved[0].optimization_result is not None
