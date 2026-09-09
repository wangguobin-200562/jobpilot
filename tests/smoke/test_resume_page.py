from streamlit.testing.v1 import AppTest

from tests.fixtures.document_factory import make_docx


def test_resume_analysis_page_loads() -> None:
    def page_script() -> None:
        from jobpilot.ui.pages.resume_analysis import render_resume_analysis
        from jobpilot.ui.state import initialize_session_state

        initialize_session_state()
        render_resume_analysis()

    app = AppTest.from_function(page_script).run()

    assert not app.exception
    assert app.title[0].value == "简历分析"
    assert len(app.file_uploader) == 1
    assert len(app.button) == 0
    assert any(
        item.value == "请上传 PDF 或 DOCX 简历开始分析。" for item in app.info
    )
    assert any(
        "简历文件会先在本地完成文本提取" in item.value for item in app.caption
    )


def test_successful_local_parse_reveals_disabled_ai_section_without_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")

    def page_script() -> None:
        from jobpilot.ui.pages.resume_analysis import render_resume_analysis
        from jobpilot.ui.state import initialize_session_state

        initialize_session_state()
        render_resume_analysis()

    app = AppTest.from_function(page_script).run()
    resume_bytes = make_docx(paragraphs=("Jane Doe", "Python developer"))

    app.file_uploader(key="resume_upload").set_value(
        (
            "resume.docx",
            resume_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    ).run(timeout=10)

    assert not app.exception
    assert app.success[0].value == "简历解析成功"
    assert any(item.value == "AI 智能分析" for item in app.subheader)
    assert app.button(key="analyze_resume_with_ai").label == "开始 AI 分析"
    assert app.button(key="analyze_resume_with_ai").disabled is True


def test_parsed_resume_and_ai_profile_survive_returning_to_page(monkeypatch) -> None:
    """A removed file-uploader widget must not discard completed resume work."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")

    def page_script() -> None:
        import streamlit as st

        from jobpilot.models import CandidateProfile, ParsedResume, Skills
        from jobpilot.ui.pages.resume_analysis import render_resume_analysis
        from jobpilot.ui.state import initialize_session_state

        initialize_session_state()
        if st.session_state.get("seed_completed_resume"):
            st.session_state.resume_file_fingerprint = "resume-a"
            st.session_state.parsed_resume = ParsedResume(
                filename="retained-resume.pdf",
                file_type="pdf",
                file_size=1024,
                text="Candidate with Python experience",
                page_count=1,
                character_count=32,
                word_count=4,
            )
            st.session_state.resume_parse_error = None
            st.session_state.candidate_profile_fingerprint = "resume-a"
            st.session_state.candidate_profile = CandidateProfile(
                skills=Skills(programming_languages=["Python"])
            )
            st.session_state.candidate_profile_error = None
        render_resume_analysis()

    app = AppTest.from_function(page_script).run()
    app.session_state["seed_completed_resume"] = True
    app.run()

    assert not app.exception
    assert any("已保留当前简历" in item.value for item in app.info)
    assert any(item.value == "简历解析成功" for item in app.success)
    assert app.button(key="analyze_resume_with_ai").label == "重新分析"
    assert any(item.value == "候选人画像" for item in app.subheader)


def test_resume_business_state_survives_real_page_sequence_and_rerun(
    monkeypatch, tmp_path
) -> None:
    """Exercise the real page renderers in one Streamlit session without AI calls."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(tmp_path / "uat.db"))

    def app_script() -> None:
        import streamlit as st

        from jobpilot.models import CandidateProfile, ParsedResume, Skills
        from jobpilot.ui.pages.applications import render_applications
        from jobpilot.ui.pages.insights import render_insights
        from jobpilot.ui.pages.job_match import render_job_match
        from jobpilot.ui.pages.resume_analysis import render_resume_analysis
        from jobpilot.ui.state import initialize_session_state

        initialize_session_state()
        if not st.session_state.get("uat_resume_seeded"):
            st.session_state.uat_resume_seeded = True
            st.session_state.resume_file_fingerprint = "stable-resume-fingerprint"
            st.session_state.parsed_resume = ParsedResume(
                filename="retained-resume.pdf",
                file_type="pdf",
                file_size=1024,
                text="Candidate with Python experience",
                page_count=1,
                character_count=32,
                word_count=4,
            )
            st.session_state.candidate_profile_fingerprint = (
                "stable-resume-fingerprint"
            )
            st.session_state.candidate_profile = CandidateProfile(
                skills=Skills(programming_languages=["Python"])
            )
            st.session_state.uat_resume_ai_calls = 0

        page = st.session_state.get("uat_page", "resume")
        if page == "match":
            render_job_match()
        elif page == "applications":
            render_applications()
        elif page == "insights":
            render_insights()
        else:
            render_resume_analysis()

    app = AppTest.from_function(app_script, default_timeout=10).run()
    original_fingerprint = app.session_state["resume_file_fingerprint"]
    original_profile = app.session_state["candidate_profile"]

    for page in ("match", "applications", "insights", "resume"):
        app.session_state["uat_page"] = page
        app.run()
        assert not app.exception

    # A normal rerun with an empty uploader must keep application/business state.
    app.run()

    assert not app.exception
    assert app.session_state["resume_file_fingerprint"] == original_fingerprint
    assert app.session_state["candidate_profile"] == original_profile
    assert app.session_state["uat_resume_ai_calls"] == 0
    assert app.file_uploader(key="resume_upload").value is None
    assert any("已保留当前简历" in item.value for item in app.info)
    assert any(item.value == "候选人画像" for item in app.subheader)
    assert app.button(key="analyze_resume_with_ai").label == "重新分析"
