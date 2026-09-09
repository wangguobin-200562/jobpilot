from streamlit.testing.v1 import AppTest


def _complete_matching_app() -> None:
    import streamlit as st

    from jobpilot.config import load_config
    from jobpilot.models import (
        CandidateProfile,
        JobProfile,
        MatchResult,
        MatchScoreBreakdown,
    )
    from jobpilot.ui.pages.job_match import _render_matching_analysis
    from jobpilot.ui.state import initialize_session_state

    class FakeMatchingService:
        def analyze(self, candidate, job) -> MatchResult:
            st.session_state["fake_matching_calls"] = (
                st.session_state.get("fake_matching_calls", 0) + 1
            )
            return MatchResult(
                scores=MatchScoreBreakdown(
                    overall_score=82,
                    skills_score=85,
                    experience_score=70,
                    projects_score=92,
                    education_other_score=100,
                ),
                matched_skills=[
                    {
                        "skill": "Python",
                        "resume_evidence": "Python 项目开发",
                        "job_requirement": "Python",
                        "match_type": "exact",
                    }
                ],
                partial_matches=[
                    {
                        "job_requirement": "LangGraph",
                        "resume_evidence": "自研 Agent Workflow",
                        "gap": "相关但尚未体现 LangGraph 使用证据。",
                    }
                ],
                missing_skills=[
                    {
                        "skill": "Docker",
                        "importance": "required",
                        "reason": "当前简历中未找到 Docker 相关证据。",
                    }
                ],
                strengths=["拥有 AI Agent 项目经验"],
                gaps=["当前简历中未找到 Docker 相关证据"],
                evidence=[
                    {
                        "category": "项目经历",
                        "job_requirement": "AI Agent 开发",
                        "resume_evidence": "TripMind AI Agent",
                        "assessment": "高度相关",
                    }
                ],
                improvement_priorities=[
                    {
                        "priority": "high",
                        "action": "补充 Docker 基础实践",
                        "reason": "岗位必备技能",
                    }
                ],
                summary="核心项目与岗位方向匹配。",
            )

    initialize_session_state()
    st.session_state.candidate_profile = CandidateProfile(
        skills={"programming_languages": ["Python"]},
        projects=[{"name": "TripMind"}],
    )
    st.session_state.candidate_profile_fingerprint = "a" * 64
    st.session_state.job_profile = JobProfile(
        job_title="AI 应用开发实习生",
        required_skills=["Python", "Docker"],
        responsibilities=["开发 AI Agent"],
    )
    st.session_state.job_profile_fingerprint = "b" * 64
    _render_matching_analysis(
        st.session_state.job_profile,
        load_config(),
        matching_service_factory=FakeMatchingService,
    )


def test_matching_button_appears_only_with_both_profiles(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    app = AppTest.from_function(_complete_matching_app).run()

    assert not app.exception
    assert app.button(key="analyze_resume_job_match").label == "开始匹配分析"
    assert "fake_matching_calls" not in app.session_state


def test_matching_runs_only_on_click_and_result_survives_rerun(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = AppTest.from_function(_complete_matching_app).run()

    app.button(key="analyze_resume_job_match").click().run()

    assert not app.exception
    assert app.session_state["fake_matching_calls"] == 1
    assert any(item.value == "匹配结果" for item in app.subheader)

    app.run()

    assert not app.exception
    assert app.session_state["fake_matching_calls"] == 1
    assert any(item.value == "匹配结果" for item in app.subheader)


def test_matching_result_displays_scores_and_skill_gap(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = AppTest.from_function(_complete_matching_app).run()
    app.button(key="analyze_resume_job_match").click().run()

    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics == {
        "岗位匹配度": "82%",
        "技能匹配": "85%",
        "经历匹配": "70%",
        "项目匹配": "92%",
        "教育及其他": "100%",
    }
    headings = [item.value for item in app.markdown]
    for heading in (
        "#### 你的优势",
        "#### 已匹配技能",
        "#### 部分匹配",
        "#### 缺失技能",
        "#### 匹配证据",
        "#### 能力差距",
        "#### 提升优先级",
    ):
        assert heading in headings
    visible = " ".join(
        item.value for collection in (app.markdown, app.caption) for item in collection
    )
    assert "Python" in visible
    assert "LangGraph" in visible
    assert "Docker" in visible
    assert "TripMind AI Agent" in visible


def test_missing_candidate_profile_shows_guidance(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def app_script() -> None:
        import streamlit as st

        from jobpilot.config import load_config
        from jobpilot.models import JobProfile
        from jobpilot.ui.pages.job_match import _render_matching_analysis
        from jobpilot.ui.state import initialize_session_state

        initialize_session_state()
        job = JobProfile(job_title="AI 实习生")
        st.session_state.job_profile_fingerprint = "b" * 64
        _render_matching_analysis(job, load_config())

    app = AppTest.from_function(app_script).run()

    assert not app.exception
    assert any("请先前往“简历分析”" in item.value for item in app.info)
    assert len(app.button) == 0


def test_missing_job_profile_shows_guidance(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def app_script() -> None:
        import streamlit as st

        from jobpilot.config import load_config
        from jobpilot.models import CandidateProfile
        from jobpilot.ui.pages.job_match import _render_matching_analysis
        from jobpilot.ui.state import initialize_session_state

        initialize_session_state()
        st.session_state.candidate_profile = CandidateProfile(
            skills={"programming_languages": ["Python"]}
        )
        st.session_state.candidate_profile_fingerprint = "a" * 64
        _render_matching_analysis(None, load_config())

    app = AppTest.from_function(app_script).run()

    assert not app.exception
    assert any("请先完成当前岗位 JD 分析" in item.value for item in app.info)
    assert len(app.button) == 0
