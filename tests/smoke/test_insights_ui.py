from streamlit.testing.v1 import AppTest

from jobpilot.models import JobProfile, MatchResult, MatchScoreBreakdown
from jobpilot.storage import ApplicationRepository


def _insights_app() -> None:
    from jobpilot.ui.pages.insights import render_insights

    render_insights()


def _match(required=(), preferred=()) -> MatchResult:
    return MatchResult(
        scores=MatchScoreBreakdown(overall_score=75),
        missing_skills=[
            *[
                {"skill": skill, "importance": "required", "reason": "尚无项目证据"}
                for skill in required
            ],
            *[
                {"skill": skill, "importance": "preferred", "reason": "尚无项目证据"}
                for skill in preferred
            ],
        ],
    )


def _create_rich_dataset(database) -> None:
    repository = ApplicationRepository(database)
    definitions = [
        ("星云科技", "AI 应用实习生", 91, "contacted", ["Python", "FastAPI"], ["Docker"], ["Git"]),
        ("远景数据", "数据实习生", 82, "interviewing", ["Python", "SQL"], ["Docker"], ["Git"]),
        ("未来智能", "Agent 实习生", 68, "offer", ["Python", "LLM"], ["RAG"], ["Linux"]),
    ]
    for index, (company, role, score, status, required, preferred, tools) in enumerate(
        definitions, 1
    ):
        created = repository.create_application(
            company=company,
            job_title=role,
            jd_text=f"虚构岗位说明 {index}",
            job_profile=JobProfile(
                company=company,
                job_title=role,
                required_skills=required,
                preferred_skills=preferred,
                tools_and_technologies=tools,
            ),
            match_score=score,
            match_result=_match(required=["Docker"], preferred=["云平台"]),
        )
        repository.update_status(created.id, "applied")
        repository.update_status(created.id, status)


def test_insights_page_has_empty_state_without_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(tmp_path / "jobpilot.db"))

    app = AppTest.from_function(_insights_app).run()

    assert not app.exception
    assert app.title[0].value == "求职洞察"
    assert any(item.value == "暂无可分析的岗位" for item in app.subheader)
    assert len(app.metric) == 0


def test_insights_page_warns_when_sample_is_small(tmp_path, monkeypatch) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    ApplicationRepository(database).create_application(
        company="虚构公司",
        job_title="虚构岗位",
        jd_text="虚构岗位说明",
        job_profile=JobProfile(company="虚构公司", job_title="虚构岗位"),
    )

    app = AppTest.from_function(_insights_app).run()

    assert not app.exception
    assert any("当前数据较少" in item.value for item in app.info)
    assert any("至少保存 3 个包含匹配结果" in item.value for item in app.info)
    assert any(metric.label == "沟通率" and metric.value == "—" for metric in app.metric)


def test_insights_page_renders_all_sections_with_sufficient_data(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "jobpilot.db"
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    _create_rich_dataset(database)

    app = AppTest.from_function(_insights_app).run(timeout=10)

    assert not app.exception
    headings = [item.value for item in app.subheader]
    assert headings == [
        "核心数据",
        "求职漏斗",
        "能力缺口",
        "目标岗位技能趋势",
        "匹配度分布",
        "最匹配岗位",
        "最近求职活动",
    ]
    labels = {metric.label for metric in app.metric}
    assert {
        "全部岗位",
        "平均匹配度",
        "已投递",
        "面试中",
        "Offer",
        "沟通率",
        "面试率",
        "Offer 率",
        "近 7 天新增岗位",
    } <= labels
    assert any(metric.label == "平均匹配度" and metric.value == "80.3 分" for metric in app.metric)
    assert any(metric.label == "面试率" and metric.value == "66.7%" for metric in app.metric)
    assert len(app.dataframe) == 1
    assert len(app.dataframe[0].value) == 3
