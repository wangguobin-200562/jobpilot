from __future__ import annotations

from streamlit.testing.v1 import AppTest

from jobpilot.models import (
    AssessmentConfidence,
    BatchJobInput,
    FastRelevance,
    FastScreeningAssessment,
    FastScreeningItem,
    FastScreeningPipelineResult,
    LocalPreScreenResult,
    LocalScreeningDecision,
    ScreeningMetrics,
    ScreeningTier,
    ScreeningTiming,
)


def _item(index: int, tier: ScreeningTier) -> FastScreeningItem:
    job = BatchJobInput(
        index=index,
        company=f"虚构公司{index}",
        job_title=f"虚构岗位{index}",
        source_url=f"https://www.zhipin.com/job_detail/ui-fake-{index}.html",
        jd_text=f"第 {index} 份虚构岗位描述，仅用于界面测试。",
        raw_block=f"第 {index} 份虚构岗位描述，仅用于界面测试。",
    )
    relevance = {
        ScreeningTier.PRIORITY: FastRelevance.HIGH,
        ScreeningTier.RECOMMENDED: FastRelevance.MEDIUM,
        ScreeningTier.CAUTION: FastRelevance.MEDIUM,
        ScreeningTier.LOW_PRIORITY: FastRelevance.LOW,
    }[tier]
    assessment = FastScreeningAssessment(
        job_title=job.job_title,
        core_required_skills=["Python"],
        matched_core_skills=["Python"],
        missing_core_skills=["Docker"] if tier is ScreeningTier.CAUTION else [],
        hard_requirement_risks=[],
        relevance=relevance,
        confidence=AssessmentConfidence.HIGH,
        reason="虚构的快速筛选依据。",
    )
    return FastScreeningItem(
        job_input=job,
        local_result=LocalPreScreenResult(
            decision=LocalScreeningDecision.PASS,
            reason="虚构本地规则通过。",
        ),
        assessment=assessment,
        screening_tier=tier,
        screening_reason="虚构的主要推荐理由。",
        core_gaps=assessment.missing_core_skills,
    )


def _result(suffix: str = "") -> FastScreeningPipelineResult:
    tiers = [
        *([ScreeningTier.PRIORITY] * 4),
        *([ScreeningTier.RECOMMENDED] * 2),
        *([ScreeningTier.CAUTION] * 2),
        *([ScreeningTier.LOW_PRIORITY] * 2),
    ]
    items = [_item(index, tier) for index, tier in enumerate(tiers, start=1)]
    if suffix:
        first = items[0]
        first.job_input.job_title += suffix
    return FastScreeningPipelineResult(
        items=items,
        metrics=ScreeningMetrics(
            total_jobs=10,
            local_filtered=0,
            flash_screened=10,
            pro_analyzed=0,
            cache_hits=0,
            flash_provider_calls=0,
            pro_provider_calls=0,
            timing=ScreeningTiming(
                local_seconds=0,
                flash_seconds=0,
                pro_seconds=0,
                total_elapsed_seconds=0,
                avg_seconds_per_job=0,
            ),
        ),
    )


def _app() -> None:
    import streamlit as st

    from jobpilot.ui.batch_apply import render_batch_apply_selection
    from jobpilot.ui.state import initialize_session_state

    class EmptyRepository:
        def list_applications(self):
            return []

    initialize_session_state()
    render_batch_apply_selection(
        st.session_state["test_screening_result"],
        repository_factory=EmptyRepository,
    )


def _batch_input_state_app() -> None:
    import streamlit as st

    from jobpilot.ui.state import initialize_session_state, sync_batch_input_state

    initialize_session_state()
    sync_batch_input_state(st.session_state["test_batch_input"])


def _ready_app(result=None) -> AppTest:
    app = AppTest.from_function(_app)
    app.session_state["test_screening_result"] = result or _result()
    return app.run()


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_defaults_and_rerun_preserve_user_selection() -> None:
    app = _ready_app()
    assert not app.exception
    assert [box.value for box in app.checkbox] == [
        True, True, True, True, True, True, False, False, False, False
    ]

    app.checkbox[0].uncheck().run()
    app.checkbox[6].check().run()
    app.run()

    assert app.checkbox[0].value is False
    assert app.checkbox[6].value is True
    assert _button(app, "开始沟通 6 个")


def test_quick_selection_actions() -> None:
    app = _ready_app()

    _button(app, "全选建议沟通").click().run()
    assert [box.value for box in app.checkbox] == [
        True, True, True, True, False, False, False, False, False, False
    ]

    _button(app, "全选建议沟通 + 可以沟通").click().run()
    assert [box.value for box in app.checkbox] == [
        True, True, True, True, True, True, False, False, False, False
    ]

    _button(app, "清空选择").click().run()
    assert all(not box.value for box in app.checkbox)
    assert _button(app, "开始沟通 0 个").disabled is True


def test_selection_immediately_creates_privacy_minimal_plan() -> None:
    app = _ready_app()

    assert not app.exception
    plan = app.session_state["batch_apply_plan"]
    assert plan.selected_count == 6
    assert plan.total_count == 10
    serialized = str(plan.model_dump(mode="json")).casefold()
    assert "jd_text" not in serialized
    assert "resume" not in serialized
    assert "phone" not in serialized
    assert "email" not in serialized


def test_changed_screening_result_clears_old_plan_and_reseeds_defaults() -> None:
    app = _ready_app()
    app.checkbox[0].uncheck().run()
    assert app.session_state["batch_apply_plan"] is not None

    app.session_state["test_screening_result"] = _result("（已变化）")
    app.run()

    assert app.session_state["batch_apply_plan"] is not None
    assert [box.value for box in app.checkbox[:6]] == [True] * 6


def test_changed_batch_input_clears_apply_plan() -> None:
    app = AppTest.from_function(_batch_input_state_app)
    app.session_state["test_batch_input"] = "第一批虚构岗位"
    app.run()
    app.session_state["batch_apply_plan"] = "old-plan"

    app.session_state["test_batch_input"] = "第二批虚构岗位"
    app.run()

    assert app.session_state["batch_apply_plan"] is None
