from streamlit.testing.v1 import AppTest


def _boss_batch_app() -> None:
    import streamlit as st

    from jobpilot.browser import JobDiscoveryItem, JobDiscoveryResult
    from jobpilot.ui.pages.job_match import render_job_match
    from jobpilot.ui.state import initialize_session_state

    class FakeInbox:
        def snapshot(self):
            return 1, [
                JobDiscoveryItem(
                    company=f"虚构公司{i}", job_title=f"AI 岗位{i}", location="广州",
                    salary="10-15K", source="boss",
                    source_url=f"https://www.zhipin.com/job_detail/fake-{i}.html",
                    jd_text=f"第 {i} 份完整虚构 JD，要求 Python 与 AI 应用开发。",
                ) for i in (1, 2)
            ]

    class FakeBridge:
        host = "127.0.0.1"
        token = "test-bridge-token"
        inbox = FakeInbox()

        @property
        def running(self):
            return st.session_state.get("fake_bridge_running", False)

        def start(self):
            st.session_state["fake_bridge_running"] = True
            return self

        def rotate_token(self):
            self.token = "rotated-test-bridge-token"
            return self.token

    initialize_session_state()
    render_job_match(extension_bridge_factory=FakeBridge)


def _unified_page(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    app = AppTest.from_function(_boss_batch_app).run()
    return app


def test_boss_discovery_entry_is_inside_unified_flow(monkeypatch) -> None:
    app = _unified_page(monkeypatch)
    assert not app.exception
    assert any(expander.label == "从招聘网站获取岗位" for expander in app.expander)
    assert any("本地连接已自动启动" in item.value for item in app.success)


def test_extension_discovery_imports_existing_batch_format_without_analysis(monkeypatch) -> None:
    app = _unified_page(monkeypatch)
    app.run()
    assert any("已获取 2 个岗位" in item.value or "已导入 2 个岗位" in item.value for item in app.success)
    value = app.text_area(key="batch_job_input").value
    assert "公司：虚构公司1" in value
    assert "https://www.zhipin.com/job_detail/fake-2.html" in value
    assert "\n\n---\n\n" in value
    assert app.session_state["batch_screening_result"] is None


def test_bridge_token_can_be_rotated_explicitly(monkeypatch) -> None:
    app = _unified_page(monkeypatch)
    app.button(key="extension_bridge_rotate_token").click().run()
    assert not app.exception
    assert app.button(key="extension_bridge_rotate_token")
