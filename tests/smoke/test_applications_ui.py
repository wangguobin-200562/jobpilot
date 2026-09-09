from streamlit.testing.v1 import AppTest

from jobpilot.models import JobProfile, MatchResult, MatchScoreBreakdown
from jobpilot.storage import ApplicationRepository


def _applications_app() -> None:
    from jobpilot.ui.pages.applications import render_applications
    from jobpilot.ui.state import initialize_session_state

    initialize_session_state()
    render_applications()


def _create_application(database, **updates):
    repository = ApplicationRepository(database)
    data = dict(
        company="示例科技",
        job_title="AI 应用开发实习生",
        location="深圳",
        jd_text="岗位职责：开发 AI Agent\n任职要求：Python",
        job_profile=JobProfile(
            company="示例科技",
            job_title="AI 应用开发实习生",
            location="深圳",
            responsibilities=["开发 AI Agent"],
            required_skills=["Python"],
            preferred_skills=["Docker"],
        ),
        match_score=86,
        match_result=MatchResult(scores=MatchScoreBreakdown(overall_score=86)),
    )
    data.update(updates)
    return repository.create_application(**data)


def test_applications_page_loads_with_empty_state(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))

    app = AppTest.from_function(_applications_app).run()

    assert not app.exception
    assert app.title[0].value == "求职进度"
    assert len(app.metric) == 6
    assert app.segmented_control(key="applications_mode").value == "求职进度"
    assert any(item.value == "当前没有对应岗位" for item in app.subheader)


def test_application_detail_status_notes_and_confirmed_delete(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    created = _create_application(database)
    repository = ApplicationRepository(database)
    app = AppTest.from_function(_applications_app).run()
    app.segmented_control(key="applications_mode").set_value("全部记录").run()

    app.button(key=f"view_application_{created.id}").click().run()

    assert not app.exception
    assert any(item.value == "岗位详情" for item in app.subheader)
    assert app.expander[0].label == "原始 JD"
    assert app.expander[0].proto.expanded is False

    app.selectbox(key=f"application_status_{created.id}").select("已投递").run()
    app.button(key=f"save_application_status_{created.id}").click().run()

    updated = repository.get_application_by_id(created.id)
    assert updated is not None
    assert updated.status.value == "applied"
    assert updated.applied_at is not None
    assert any("投递状态已更新" in item.value for item in app.success)

    app.text_area(key=f"application_notes_{created.id}").set_value(
        "HR 已联系，周五沟通。"
    ).run()
    app.button(key=f"save_application_notes_{created.id}").click().run()

    updated = repository.get_application_by_id(created.id)
    assert updated is not None
    assert updated.notes == "HR 已联系，周五沟通。"
    assert any("备注已保存" in item.value for item in app.success)

    app.button(key=f"delete_application_{created.id}").click().run()

    assert repository.get_application_by_id(created.id) is not None
    assert app.button(key=f"confirm_delete_application_{created.id}").label == "确认删除"
    assert app.button(key=f"cancel_delete_application_{created.id}").label == "取消"

    app.button(key=f"confirm_delete_application_{created.id}").click().run()

    assert not app.exception
    assert repository.get_application_by_id(created.id) is None
    assert any("岗位记录已删除" in item.value for item in app.success)


def test_application_status_filter_uses_repository(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    created = _create_application(database)
    ApplicationRepository(database).update_status(created.id, "interviewing")
    app = AppTest.from_function(_applications_app).run()
    app.segmented_control(key="applications_mode").set_value("全部记录").run()

    app.segmented_control(key="applications_status_filter").set_value("已投递").run()

    assert not app.exception
    assert len(app.button) == 0
    assert any(item.value == "暂无保存的岗位" for item in app.subheader)

    app.segmented_control(key="applications_status_filter").set_value("面试中").run()

    assert not app.exception
    assert app.button(key=f"view_application_{created.id}").label == "查看"


def test_contacted_record_appears_in_primary_progress_view(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    created = _create_application(database)
    updated = ApplicationRepository(database).update_status(created.id, "contacted")

    app = AppTest.from_function(_applications_app).run()

    assert not app.exception
    assert app.segmented_control(key="applications_mode").value == "求职进度"
    assert app.button(key=f"progress_view_{created.id}").label == "查看"
    assert updated.contacted_at is not None
    assert updated.applied_at is None


def test_queue_remains_available_as_secondary_view(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    created = _create_application(database)
    app = AppTest.from_function(_applications_app).run()
    app.segmented_control(key="applications_mode").set_value("投递队列").run()
    assert not app.exception
    assert app.segmented_control(key="applications_mode").value == "投递队列"
    assert {metric.label for metric in app.metric} == {
        "待投递", "可以投递", "建议先检查", "存在明显缺口"
    }
    assert app.button(key=f"queue_view_{created.id}").label == "查看详情"
    assert app.button(key=f"queue_apply_{created.id}").label == "标记已投递"


def test_queue_mark_applied_then_all_records_contains_item(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    created = _create_application(database)
    app = AppTest.from_function(_applications_app).run()
    app.segmented_control(key="applications_mode").set_value("投递队列").run()
    app.button(key=f"queue_apply_{created.id}").click().run()
    assert not app.exception
    assert ApplicationRepository(database).get_application_by_id(created.id).status.value == "applied"
    assert any("已标记为已投递" in item.value for item in app.success)
    app.segmented_control(key="applications_mode").set_value("全部记录").run()
    assert app.button(key=f"view_application_{created.id}").label == "查看"


def test_queue_defer_and_restore(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    created = _create_application(database)
    app = AppTest.from_function(_applications_app).run()
    app.segmented_control(key="applications_mode").set_value("投递队列").run()
    app.button(key=f"queue_defer_1_{created.id}").click().run()
    assert not app.exception
    assert ApplicationRepository(database).get_application_by_id(created.id).deferred_until is not None
    assert app.button(key=f"queue_restore_{created.id}").label == "提前恢复"
    app.button(key=f"queue_restore_{created.id}").click().run()
    assert ApplicationRepository(database).get_application_by_id(created.id).deferred_until is None
    assert app.button(key=f"queue_apply_{created.id}")


def test_queue_search_tier_filter_and_details_reuse(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    first = _create_application(database)
    second = _create_application(
        database, company="远方数据", job_title="数据岗位",
        jd_text="另一份虚构 JD", job_profile=JobProfile(job_title="数据岗位"),
        match_score=70,
        match_result=MatchResult(scores=MatchScoreBreakdown(overall_score=70)),
    )
    app = AppTest.from_function(_applications_app).run()
    app.segmented_control(key="applications_mode").set_value("投递队列").run()
    app.text_input(key="queue_search").set_value("远方").run()
    assert app.button(key=f"queue_view_{second.id}")
    assert not any(button.key == f"queue_view_{first.id}" for button in app.button)
    app.text_input(key="queue_search").set_value("").run()
    app.segmented_control(key="queue_filter").set_value("可以投").run()
    assert app.button(key=f"queue_view_{second.id}")
    app.button(key=f"queue_view_{second.id}").click().run()
    assert any(item.value == "岗位详情" for item in app.subheader)


def test_queue_renders_safe_external_link_without_http_or_ai_call(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    created = _create_application(database, source="manual", source_url="https://example.com/job/1")

    def forbidden(*args, **kwargs):
        raise AssertionError("Queue must not call external services")

    monkeypatch.setattr("jobpilot.llm.DeepSeekLLMClient.generate", forbidden)
    app = AppTest.from_function(_applications_app).run()
    app.segmented_control(key="applications_mode").set_value("投递队列").run()
    assert not app.exception
    assert app.get("link_button")
    assert app.button(key=f"queue_apply_{created.id}")
