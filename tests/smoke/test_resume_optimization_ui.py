from streamlit.testing.v1 import AppTest


def _optimization_app() -> None:
    import streamlit as st

    from jobpilot.config import load_config
    from jobpilot.models import (
        CandidateProfile,
        JobProfile,
        MatchResult,
        MatchScoreBreakdown,
        ResumeOptimizationResult,
    )
    from jobpilot.ui.pages.job_match import _render_matching_analysis
    from jobpilot.ui.state import initialize_session_state, match_result_fingerprint

    class FakeOptimizationService:
        def analyze(self, candidate, job, match) -> ResumeOptimizationResult:
            st.session_state["fake_optimization_calls"] = (
                st.session_state.get("fake_optimization_calls", 0) + 1
            )
            return ResumeOptimizationResult(
                summary="当前简历整体表达已经较成熟，无需大范围修改。",
                suggestions=[
                    {
                        "section": "projects",
                        "source_name": "TripMind",
                        "decision": "keep",
                        "original": "使用 Python 开发 AI Agent",
                        "suggested": None,
                        "reason": "已对应岗位要求。",
                        "expected_benefit": None,
                        "supported_by": ["使用 Python 开发 AI Agent"],
                        "related_job_requirements": ["Python"],
                    },
                    {
                        "section": "projects",
                        "source_name": "TripMind",
                        "decision": "optional",
                        "original": "使用 Python 开发 AI Agent",
                        "suggested": "在项目首句突出已有 Python 证据",
                        "reason": "便于快速定位相关经验。",
                        "expected_benefit": "提高岗位证据的可见性。",
                        "supported_by": ["使用 Python 开发 AI Agent"],
                        "related_job_requirements": ["Python"],
                    },
                ],
                keyword_suggestions=[
                    {
                        "keyword": "Docker",
                        "status": "gap_do_not_add",
                        "evidence": None,
                        "guidance": "请先学习或实践，不要直接写入简历。",
                    }
                ],
                capability_gaps=["Docker"],
                warnings=["不要添加未掌握的技能。"],
            )

    initialize_session_state()
    candidate = CandidateProfile(
        skills={"programming_languages": ["Python"]},
        projects=[
            {"name": "TripMind", "highlights": ["使用 Python 开发 AI Agent"]}
        ],
    )
    job = JobProfile(
        job_title="AI 应用开发实习生",
        required_skills=["Python", "Docker"],
    )
    match = MatchResult(
        scores=MatchScoreBreakdown(overall_score=80, skills_score=50),
        matched_skills=[
            {
                "skill": "Python",
                "resume_evidence": "Python",
                "job_requirement": "Python",
                "match_type": "exact",
            }
        ],
        missing_skills=[
            {
                "skill": "Docker",
                "importance": "required",
                "reason": "当前简历中没有 Docker 证据。",
            }
        ],
    )
    resume_fp = "a" * 64
    job_fp = "b" * 64
    match_fp = match_result_fingerprint(resume_fp, job_fp)
    st.session_state.candidate_profile = candidate
    st.session_state.candidate_profile_fingerprint = resume_fp
    st.session_state.job_profile = job
    st.session_state.job_profile_fingerprint = job_fp
    st.session_state.match_fingerprint = match_fp
    st.session_state.match_result = match
    _render_matching_analysis(
        job,
        load_config(),
        optimization_service_factory=FakeOptimizationService,
    )


def test_optimization_runs_only_on_click_and_survives_rerun(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = AppTest.from_function(_optimization_app).run()

    assert not app.exception
    button = app.button(key="generate_targeted_resume_suggestions")
    assert button.label == "生成岗位定向建议"
    assert "fake_optimization_calls" not in app.session_state

    button.click().run()

    assert not app.exception
    assert app.session_state["fake_optimization_calls"] == 1
    headings = [item.value for item in app.markdown]
    for heading in ("#### 建议概述", "#### 无需修改", "#### 可选优化", "#### 建议修改", "#### 能力缺口"):
        assert heading in headings

    app.run()

    assert not app.exception
    assert app.session_state["fake_optimization_calls"] == 1


def test_optimization_copy_explains_no_forced_changes(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = AppTest.from_function(_optimization_app).run()

    captions = " ".join(item.value for item in app.caption)
    assert "只会在确有收益时建议修改" in captions
    assert "不会发送姓名、手机号、邮箱或原始 PDF 文本" in captions
