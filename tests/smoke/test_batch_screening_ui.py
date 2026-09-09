import streamlit as st
from streamlit.testing.v1 import AppTest

from jobpilot.llm import LLMRequestError
from jobpilot.models import (
    CandidateProfile,
    JobProfile,
    MatchResult,
    MatchScoreBreakdown,
    Skills,
)
from jobpilot.storage import ApplicationRepository


BATCH_INPUT = """公司：高匹配公司（虚构）
岗位：HIGH AI 实习生
地点：广州
JD：HIGH 使用 Python 开发 AI 应用，负责模型 API 接入和服务开发。
---
公司：中匹配公司（虚构）
岗位：MID 数据实习生
地点：深圳
JD：MID 使用 SQL 和 Python 完成数据分析、报表制作和业务洞察。
---
公司：低匹配公司（虚构）
岗位：LOW 设计实习生
地点：上海
JD：LOW 负责视觉设计、品牌物料和用户界面设计工作。"""

FAILURE_INPUT = """公司：失败公司（虚构）
岗位：FAIL_ONCE 岗位
JD：FAIL_ONCE 这是一份会在测试中首次解析失败、随后重试成功的虚构岗位。
---
公司：正常公司（虚构）
岗位：MID 岗位
JD：MID 这是一份包含 SQL、Python 和数据分析职责的完整虚构岗位。"""

QUICK_INPUT = BATCH_INPUT.replace(
    "。\n---",
    "，同时需要完成需求分析、代码评审、测试验证以及项目文档整理工作。\n---",
).replace(
    "设计工作。",
    "设计工作，同时负责设计规范、交付检查、跨团队沟通以及项目复盘工作。",
)


def _candidate() -> CandidateProfile:
    return CandidateProfile(
        personal_info={
            "name": "虚构候选人",
            "email": "fictional@example.com",
            "phone": "00000000000",
        },
        skills=Skills(programming_languages=["Python"]),
    )


def _batch_app() -> None:
    import streamlit as st

    from jobpilot.llm import LLMRequestError
    from jobpilot.models import (
        AssessmentConfidence,
        FastRelevance,
        FastScreeningAssessment,
        JobProfile,
        MatchResult,
        MatchScoreBreakdown,
    )
    from jobpilot.ui.pages.job_match import render_job_match
    from jobpilot.ui.state import initialize_session_state

    class FakeAnalyzer:
        def analyze(self, jd_text: str) -> JobProfile:
            st.session_state["batch_fake_flash_calls"] = (
                st.session_state.get("batch_fake_flash_calls", 0) + 1
            )
            if "FAIL_ONCE" in jd_text and not st.session_state.get("batch_failed_once"):
                st.session_state["batch_failed_once"] = True
                raise LLMRequestError("private provider failure")
            marker = jd_text.split()[0]
            return JobProfile(
                company="模型公司",
                job_title=f"{marker} 岗位",
                responsibilities=[jd_text],
                required_skills=["Python"],
            )

    class FakeMatcher:
        def analyze(self, candidate, job) -> MatchResult:
            st.session_state["batch_fake_pro_calls"] = (
                st.session_state.get("batch_fake_pro_calls", 0) + 1
            )
            text = " ".join(job.responsibilities)
            score = 90 if "HIGH" in text else 70 if "MID" in text else 40
            missing = [] if score >= 65 else [
                {"skill": "视觉设计", "importance": "required", "reason": "当前简历无证据"}
            ]
            return MatchResult(
                scores=MatchScoreBreakdown(
                    overall_score=score,
                    skills_score=score,
                    experience_score=score,
                ),
                matched_skills=(
                    [{
                        "skill": "Python",
                        "resume_evidence": "Python",
                        "job_requirement": "Python",
                        "match_type": "exact",
                    }]
                    if score >= 65
                    else []
                ),
                missing_skills=missing,
                strengths=["具备虚构的 Python 项目证据"] if score >= 65 else [],
                gaps=[entry["reason"] for entry in missing],
            )

    class FakeFastScreening:
        def assess(self, candidate, job_input) -> FastScreeningAssessment:
            del candidate
            st.session_state["batch_fake_fast_calls"] = (
                st.session_state.get("batch_fake_fast_calls", 0) + 1
            )
            text = job_input.jd_text
            relevance = (
                FastRelevance.HIGH if "HIGH" in text
                else FastRelevance.MEDIUM if "MID" in text
                else FastRelevance.LOW
            )
            return FastScreeningAssessment(
                job_title=job_input.job_title,
                core_required_skills=["Python"],
                matched_core_skills=["Python"] if relevance is not FastRelevance.LOW else [],
                missing_core_skills=[] if relevance is not FastRelevance.LOW else ["视觉设计"],
                hard_requirement_risks=[],
                relevance=relevance,
                confidence=AssessmentConfidence.HIGH,
                reason="虚构的快速筛选理由。",
            )

    initialize_session_state()
    render_job_match(
        analyzer_factory=FakeAnalyzer,
        matching_service_factory=FakeMatcher,
        fast_screening_service_factory=FakeFastScreening,
    )


def _ready_app(monkeypatch, database) -> AppTest:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(database))
    app = AppTest.from_function(_batch_app)
    app.session_state["candidate_profile"] = _candidate()
    app.session_state["candidate_profile_fingerprint"] = "a" * 64
    app.run()
    return app


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_unified_screening_renders_without_mode_switches(tmp_path, monkeypatch) -> None:
    app = _ready_app(monkeypatch, tmp_path / "jobpilot.db")
    assert not app.exception
    assert app.title[0].value == "岗位匹配"
    assert app.text_area(key="batch_job_input").label == "岗位原始内容"
    assert _button(app, "开始筛选")
    assert not app.segmented_control


def test_quick_screening_is_the_only_default_flow(tmp_path, monkeypatch) -> None:
    app = _ready_app(monkeypatch, tmp_path / "jobpilot.db")
    app.text_area(key="batch_job_input").set_value(QUICK_INPUT).run()
    _button(app, "开始筛选").click().run(timeout=10)

    assert not app.exception
    result = app.session_state["batch_screening_result"]
    assert result.metrics.pro_provider_calls < result.metrics.flash_screened
    assert result.metrics.pro_provider_calls == 0
    assert "batch_fake_flash_calls" not in app.session_state
    assert app.session_state["batch_screening_mode_used"] == "quick"


def test_missing_candidate_disables_batch_analysis(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("JOBPILOT_DATABASE_PATH", str(tmp_path / "jobpilot.db"))
    app = AppTest.from_function(_batch_app).run()
    assert _button(app, "开始筛选").disabled is True
    assert any("请先在“简历分析”" in item.value for item in app.info)


def test_screening_cards_are_the_contact_selection_ui(tmp_path, monkeypatch) -> None:
    app = _ready_app(monkeypatch, tmp_path / "jobpilot.db")
    app.text_area(key="batch_job_input").set_value(QUICK_INPUT).run()
    _button(app, "开始筛选").click().run(timeout=10)

    assert not app.exception
    result = app.session_state["batch_screening_result"]
    assert len(result.items) == 3
    metric_values = {metric.label: metric.value for metric in app.metric}
    assert "建议沟通" in metric_values
    assert "可以沟通" in metric_values
    assert len(app.checkbox) == 3
    assert not [button for button in app.button if button.label == "保存到投递管理"]


def test_rerun_and_same_batch_submit_do_not_repeat_provider_calls(
    tmp_path, monkeypatch
) -> None:
    app = _ready_app(monkeypatch, tmp_path / "jobpilot.db")
    app.text_area(key="batch_job_input").set_value(QUICK_INPUT).run()
    _button(app, "开始筛选").click().run(timeout=10)
    first_result = app.session_state["batch_screening_result"]
    app.run()
    _button(app, "开始筛选").click().run(timeout=10)

    assert first_result.metrics.flash_provider_calls == 3
    repeated = app.session_state["batch_screening_result"]
    assert repeated.screening_batch_id == first_result.screening_batch_id
    assert repeated.metrics.flash_provider_calls == 3


def test_detailed_analysis_is_requested_from_one_result_card(tmp_path, monkeypatch) -> None:
    app = _ready_app(monkeypatch, tmp_path / "jobpilot.db")
    app.text_area(key="batch_job_input").set_value(QUICK_INPUT).run()
    _button(app, "开始筛选").click().run(timeout=10)

    _button(app, "详细分析").click().run(timeout=10)

    assert not app.exception
    result = app.session_state["batch_screening_result"]
    assert sum(item.deep_match for item in result.items) == 1
    assert app.session_state["selected_batch_item_index"] is not None
