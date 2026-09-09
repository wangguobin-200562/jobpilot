"""User-controlled selection and confirmation for BOSS initial contact."""

from __future__ import annotations

from hashlib import sha256
from collections.abc import Callable

import streamlit as st

from jobpilot.models import ApplyReadiness, FastScreeningPipelineResult, ScreeningTier
from jobpilot.services import (
    BatchApplyService,
    apply_item_identity,
    screening_result_fingerprint,
)
from jobpilot.storage import ApplicationRepository, ApplicationRepositoryError
from jobpilot.ui.state import sync_batch_apply_state
from jobpilot.ui.batch_apply_execution import render_batch_apply_execution


TIER_LABELS = {
    ScreeningTier.PRIORITY: "建议沟通",
    ScreeningTier.RECOMMENDED: "可以沟通",
    ScreeningTier.CAUTION: "谨慎沟通",
    ScreeningTier.LOW_PRIORITY: "不建议沟通",
}
READINESS_LABELS = {
    ApplyReadiness.READY: "准备沟通",
    ApplyReadiness.REVIEW_REQUIRED: "需要确认",
    ApplyReadiness.UNSUPPORTED: "暂不支持",
}
READINESS_COLORS = {
    ApplyReadiness.READY: "green",
    ApplyReadiness.REVIEW_REQUIRED: "orange",
    ApplyReadiness.UNSUPPORTED: "gray",
}


class _EmptyRepository:
    def list_applications(self):
        return []


def _widget_key(identity: str) -> str:
    return "batch_apply_checkbox_" + sha256(identity.encode("utf-8")).hexdigest()[:16]


def _selectable(item) -> bool:
    return (
        item.apply_readiness is not ApplyReadiness.UNSUPPORTED
        and item.exclusion_reason is None
    )


def chinese_display_reason(reason: str, tier: ScreeningTier) -> str:
    """Keep internal model text intact while preventing English-only UI output."""
    value = (reason or "").strip()
    chinese_count = sum("\u4e00" <= char <= "\u9fff" for char in value)
    if chinese_count >= 4:
        return value
    fallbacks = {
        ScreeningTier.PRIORITY: "核心能力与岗位要求高度匹配，建议优先沟通。",
        ScreeningTier.RECOMMENDED: "主要能力与岗位方向匹配，可以进一步沟通。",
        ScreeningTier.CAUTION: "岗位方向有一定匹配，但关键要求仍需确认。",
        ScreeningTier.LOW_PRIORITY: "当前简历与岗位核心要求的匹配较弱。",
    }
    return fallbacks[tier]


def _apply_quick_selection(items, allowed_tiers: set[ScreeningTier]) -> None:
    selections = {}
    for item in items:
        identity = apply_item_identity(item)
        selected = _selectable(item) and item.screening_tier in allowed_tiers
        selections[identity] = selected
        st.session_state[_widget_key(identity)] = selected
    st.session_state.batch_apply_selections = selections
    st.session_state.batch_apply_plan = None
    st.session_state.batch_apply_feedback = None


def render_batch_apply_selection(
    result: FastScreeningPipelineResult,
    *,
    repository_factory=ApplicationRepository,
    detail_callback: Callable[[int], None] | None = None,
) -> None:
    """Render a confirmation-only plan; this function performs no browser or AI work."""
    st.caption("默认选择“建议沟通”和“可以沟通”，你可以直接调整。")
    try:
        repository = repository_factory()
    except ApplicationRepositoryError:
        repository = _EmptyRepository()
        st.warning("暂时无法读取历史投递记录，重复状态保护可能不完整。")
    service = BatchApplyService(repository)
    items = service.build_selection_items(result)
    fingerprint = screening_result_fingerprint(result)
    defaults = {apply_item_identity(item): item.selected for item in items}
    sync_batch_apply_state(fingerprint, defaults, result.screening_batch_id)

    with st.container(horizontal=True, wrap=True):
        if st.button("全选建议沟通", key="batch_apply_select_priority"):
            _apply_quick_selection(items, {ScreeningTier.PRIORITY})
        if st.button("全选建议沟通 + 可以沟通", key="batch_apply_select_recommended"):
            _apply_quick_selection(
                items, {ScreeningTier.PRIORITY, ScreeningTier.RECOMMENDED}
            )
        if st.button("清空选择", key="batch_apply_clear_selection"):
            _apply_quick_selection(items, set())

    selections = dict(st.session_state.batch_apply_selections)
    for item, screening in zip(items, result.items, strict=True):
        identity = apply_item_identity(item)
        key = _widget_key(identity)
        if _selectable(item):
            st.session_state.setdefault(
                key, bool(selections.get(identity, item.selected))
            )
        else:
            # A repository status may change while the screening result stays the
            # same. Never leave a newly excluded row visually selected.
            st.session_state[key] = False
        with st.container(border=True):
            with st.container(horizontal=True, wrap=True, gap="small"):
                st.badge(TIER_LABELS[item.screening_tier], color="blue")
                st.badge(
                    READINESS_LABELS[item.apply_readiness],
                    color=READINESS_COLORS[item.apply_readiness],
                )
            st.write(f"**{item.company} · {item.job_title}**")
            if item.match_score is not None:
                st.caption(f"深度匹配：{item.match_score:.0f} 分")
            elif item.fast_relevance is not None:
                st.caption(f"快速判断：{item.fast_relevance.value}")
            st.write(chinese_display_reason(item.main_reason, item.screening_tier))
            st.caption(
                "主要缺口：" + ("、".join(item.main_gaps[:3]) if item.main_gaps else "暂无明显核心缺口")
            )
            if item.exclusion_reason:
                st.warning(item.exclusion_reason)
            if detail_callback is not None:
                label = "查看详细分析" if screening.deep_match else "详细分析"
                if st.button(label, key=f"detail_screening_{screening.job_input.index}"):
                    detail_callback(screening.job_input.index)
                    st.rerun()
            selected = st.checkbox(
                TIER_LABELS[item.screening_tier],
                key=key,
                disabled=not _selectable(item),
                persist_state="session",
            )
            if selections.get(identity) != selected:
                st.session_state.batch_apply_plan = None
                st.session_state.batch_apply_feedback = None
            selections[identity] = selected
    st.session_state.batch_apply_selections = selections

    selected_count = sum(
        bool(selections.get(apply_item_identity(item))) and _selectable(item)
        for item in items
    )
    plan = service.create_plan(
        items,
        selections,
        screening_batch_id=result.screening_batch_id,
    )
    st.session_state.batch_apply_plan = plan
    st.caption(f"已选择 {selected_count} 个岗位")
    render_batch_apply_execution(plan, repository_factory=repository_factory)
