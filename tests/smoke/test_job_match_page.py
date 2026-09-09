from streamlit.testing.v1 import AppTest


def _app() -> None:
    from jobpilot.ui.pages.job_match import render_job_match
    from jobpilot.ui.state import initialize_session_state
    initialize_session_state()
    render_job_match()


def test_job_match_page_uses_one_unified_flow_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = AppTest.from_function(_app).run()
    assert not app.exception
    assert app.title[0].value == "岗位匹配"
    assert not app.segmented_control
    assert next(button for button in app.button if button.label == "开始筛选").disabled


def test_raw_job_content_is_collapsed_under_manual_import() -> None:
    app = AppTest.from_function(_app).run()
    assert not app.exception
    assert any(expander.label == "手动导入或查看原始内容" for expander in app.expander)
    assert app.text_area(key="batch_job_input").label == "岗位原始内容"
