from streamlit.testing.v1 import AppTest


def _ai_section_app() -> None:
    import streamlit as st

    from jobpilot.models import CandidateProfile, ParsedResume
    from jobpilot.ui.pages.resume_analysis import _render_ai_analysis
    from jobpilot.ui.state import initialize_session_state

    class FakeAnalyzer:
        def analyze(self, resume_text: str) -> CandidateProfile:
            st.session_state["fake_analysis_calls"] = (
                st.session_state.get("fake_analysis_calls", 0) + 1
            )
            return CandidateProfile(
                personal_info={"name": "Jane Doe"},
                skills={"programming_languages": ["Python"]},
            )

    initialize_session_state()
    st.session_state.resume_file_fingerprint = "resume-a"
    result = ParsedResume(
        filename="resume.pdf",
        file_type="pdf",
        file_size=100,
        text="Jane Doe\nPython",
        character_count=15,
        word_count=3,
        page_count=1,
    )
    _render_ai_analysis(result, "resume-a", analyzer_factory=FakeAnalyzer)


def test_ai_button_exists_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")

    app = AppTest.from_function(_ai_section_app).run()

    assert not app.exception
    assert len(app.button) == 1
    assert app.button[0].label == "开始 AI 分析"
    assert app.button[0].disabled is True


def test_candidate_profile_renders_and_rerun_does_not_repeat_request(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = AppTest.from_function(_ai_section_app).run()

    app.button(key="analyze_resume_with_ai").click().run()

    assert not app.exception
    assert app.session_state["fake_analysis_calls"] == 1
    assert any(item.value == "候选人画像" for item in app.subheader)
    assert any("Jane Doe" in item.value for item in app.markdown)

    app.run()

    assert not app.exception
    assert app.session_state["fake_analysis_calls"] == 1

    app.button(key="analyze_resume_with_ai").click().run()

    assert not app.exception
    assert app.session_state["fake_analysis_calls"] == 2


def test_empty_candidate_profile_renders_without_empty_values() -> None:
    def profile_app() -> None:
        from jobpilot.models import CandidateProfile
        from jobpilot.ui.pages.resume_analysis import _render_candidate_profile

        _render_candidate_profile(CandidateProfile())

    app = AppTest.from_function(profile_app).run()

    assert not app.exception
    assert any("未识别到可展示的候选人信息" in item.value for item in app.info)
    visible_text = " ".join(item.value for item in app.markdown)
    assert "None" not in visible_text
    assert "null" not in visible_text


def test_profile_ui_masks_contacts_and_collapses_safe_advanced_information() -> None:
    import json

    def profile_app() -> None:
        from jobpilot.models import CandidateProfile
        from jobpilot.ui.pages.resume_analysis import _render_candidate_profile

        _render_candidate_profile(
            CandidateProfile(
                personal_info={
                    "name": "测试用户",
                    "email": "candidate@example.com",
                    "phone": "00000000000",
                },
                education=[
                    {
                        "institution": "示例大学",
                        "degree": "本科",
                        "major": "计算机科学",
                        "start_date": "2021",
                        "end_date": "2025",
                        "details": [
                            "GPA 3.8/4.0",
                            "核心课程：数据结构",
                            "CET-4",
                            "校级奖学金",
                        ],
                    }
                ],
                skills={
                    "programming_languages": ["Python", "SQL"],
                    "other": ["英语CET-4", "精通粤语"],
                },
                languages=["英语", "粤语"],
            )
        )

    app = AppTest.from_function(profile_app).run()

    assert not app.exception
    assert len(app.expander) == 1
    assert app.expander[0].label == "高级信息"
    assert app.expander[0].proto.expanded is False

    frontend_values = " ".join(
        str(element.value)
        for collection in (app.markdown, app.caption, app.json)
        for element in collection
    )
    assert "00000000000" not in frontend_values
    assert "candidate@example.com" not in frontend_values
    assert "000****0000" in frontend_values
    assert "cand****@example.com" in frontend_values
    assert "英语CET-4" not in frontend_values
    assert "精通粤语" not in frontend_values
    advanced_data = json.loads(app.json[0].value)
    assert advanced_data["skills"]["programming_languages"] == ["Python"]
    assert advanced_data["skills"]["databases"] == ["SQL"]
    assert advanced_data["languages"] == ["英语（CET-4）", "粤语（精通）"]

    captions = [caption.value for caption in app.caption]
    assert "数据库 / 查询" in captions
    assert "GPA" in captions
    assert "核心课程" in captions
    assert "校级奖学金" in captions


def test_structured_output_error_is_shown_as_safe_chinese_message(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def error_app() -> None:
        import streamlit as st

        from jobpilot.llm import StructuredOutputError
        from jobpilot.models import ParsedResume
        from jobpilot.ui.pages.resume_analysis import _render_ai_analysis
        from jobpilot.ui.state import initialize_session_state

        class FailingAnalyzer:
            def analyze(self, resume_text: str):
                raise StructuredOutputError("raw provider response")

        initialize_session_state()
        st.session_state.resume_file_fingerprint = "resume-a"
        result = ParsedResume(
            filename="resume.pdf",
            file_type="pdf",
            file_size=100,
            text="Jane Doe",
            character_count=8,
            word_count=2,
            page_count=1,
        )
        _render_ai_analysis(result, "resume-a", analyzer_factory=FailingAnalyzer)

    app = AppTest.from_function(error_app).run()
    app.button(key="analyze_resume_with_ai").click().run()

    assert not app.exception
    assert app.error[0].value == (
        "AI 返回结果无法转换为有效的候选人画像，请重新分析。"
    )
    assert "raw provider response" not in app.error[0].value


def test_empty_profile_is_not_saved_or_rendered_as_success(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def empty_profile_app() -> None:
        import streamlit as st

        from jobpilot.models import CandidateProfile, ParsedResume
        from jobpilot.ui.pages.resume_analysis import _render_ai_analysis
        from jobpilot.ui.state import initialize_session_state

        class EmptyAnalyzer:
            def analyze(self, resume_text: str) -> CandidateProfile:
                return CandidateProfile()

        initialize_session_state()
        st.session_state.resume_file_fingerprint = "resume-a"
        result = ParsedResume(
            filename="resume.pdf",
            file_type="pdf",
            file_size=100,
            text="Jane Doe\nPython",
            character_count=15,
            word_count=3,
            page_count=1,
        )
        _render_ai_analysis(result, "resume-a", analyzer_factory=EmptyAnalyzer)

    app = AppTest.from_function(empty_profile_app).run()
    app.button(key="analyze_resume_with_ai").click().run()

    assert not app.exception
    assert app.error[0].value == "AI 未能从当前简历中提取有效信息，请重新分析。"
    assert app.session_state["candidate_profile"] is None
    assert not any(item.value == "候选人画像" for item in app.subheader)


def test_stale_empty_profile_is_cleared_from_session_state(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def stale_profile_app() -> None:
        import streamlit as st

        from jobpilot.models import CandidateProfile, ParsedResume
        from jobpilot.ui.pages.resume_analysis import _render_ai_analysis
        from jobpilot.ui.state import initialize_session_state

        initialize_session_state()
        st.session_state.resume_file_fingerprint = "resume-a"
        st.session_state.candidate_profile_fingerprint = "resume-a"
        st.session_state.candidate_profile = CandidateProfile()
        result = ParsedResume(
            filename="resume.pdf",
            file_type="pdf",
            file_size=100,
            text="Jane Doe\nPython",
            character_count=15,
            word_count=3,
            page_count=1,
        )
        _render_ai_analysis(result, "resume-a")

    app = AppTest.from_function(stale_profile_app).run()

    assert not app.exception
    assert app.session_state["candidate_profile"] is None
    assert app.error[0].value == "AI 未能从当前简历中提取有效信息，请重新分析。"
    assert not any(item.value == "候选人画像" for item in app.subheader)
