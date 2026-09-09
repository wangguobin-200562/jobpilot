"""Streamlit UI for bounded batch job screening."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import streamlit as st

from jobpilot.config import AppConfig
from jobpilot.browser import JobDiscoveryResult, discovery_items_to_batch_inputs
from jobpilot.llm import DeepSeekLLMClient
from jobpilot.models import (
    BatchJobInput,
    BatchJobStatus,
    BatchScreeningItem,
    BatchScreeningResult,
    CandidateProfile,
    FastScreeningItem,
    FastScreeningPipelineResult,
    FastScreeningProgress,
    FastScreeningStage,
    ScreeningMode,
    ScreeningTier,
)
from jobpilot.services import (
    BatchInputError,
    BatchScreeningService,
    FastScreeningPipeline,
    FastScreeningService,
    JobAnalyzer,
    LocalPreScreenService,
    MatchingService,
    batch_item_cache_key,
    build_batch_screening_result,
    build_completed_screening_item,
    parse_batch_job_input,
    save_batch_item,
    save_priority_items,
)
from jobpilot.storage import (
    ApplicationRepository,
    ApplicationRepositoryError,
    jd_text_fingerprint,
)
from jobpilot.ui.state import (
    handoff_batch_item_to_single,
    match_result_fingerprint,
    store_batch_screening_result,
    sync_batch_input_state,
)
from jobpilot.ui.site_discovery import (
    get_extension_bridge,
    mark_discovery_items_screened,
    render_site_discovery,
)
from jobpilot.ui.batch_apply import render_batch_apply_selection


BATCH_INPUT_EXAMPLE = """公司：星河智能（虚构）
岗位：AI 应用开发实习生
地点：广州
链接：https://example.com/job/1
JD：
负责大模型应用开发，要求熟悉 Python 和 LLM API。

---

公司：云启科技（虚构）
岗位：LLM 应用开发实习生
地点：深圳
JD：
参与 Agent Workflow 开发，要求熟悉 Python 和 Prompt Engineering。"""


def _format_discovered_jobs(result: JobDiscoveryResult) -> str:
    inputs = discovery_items_to_batch_inputs(result.items)
    blocks = []
    for job_input in inputs:
        lines = []
        if job_input.company:
            lines.append(f"公司：{job_input.company}")
        if job_input.job_title:
            lines.append(f"岗位：{job_input.job_title}")
        if job_input.location:
            lines.append(f"地点：{job_input.location}")
        if job_input.source_url:
            lines.append(f"链接：{job_input.source_url}")
        lines.extend(("JD：", job_input.jd_text))
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


TIER_LABELS = {
    ScreeningTier.PRIORITY: "建议沟通",
    ScreeningTier.RECOMMENDED: "可以沟通",
    ScreeningTier.CAUTION: "谨慎沟通",
    ScreeningTier.LOW_PRIORITY: "不建议沟通",
}

FAST_RELEVANCE_LABELS = {
    "high": "高匹配",
    "medium": "中等匹配",
    "low": "低匹配",
    "none": "不匹配",
}
TIER_COLORS = {
    ScreeningTier.PRIORITY: "blue",
    ScreeningTier.RECOMMENDED: "green",
    ScreeningTier.CAUTION: "orange",
    ScreeningTier.LOW_PRIORITY: "gray",
}


def _major_gaps(item: BatchScreeningItem) -> str:
    if item.match_result is None:
        return "—"
    names = [missing.skill for missing in item.match_result.missing_skills]
    if not names:
        return "暂无明显技能缺口"
    shown = "、".join(names[:2])
    return f"{shown} 等 {len(names)} 项" if len(names) > 2 else shown


def _seed_single_job_cache(
    inputs: list[BatchJobInput],
    resume_fingerprint: str,
    cache: dict[str, BatchScreeningItem],
) -> None:
    job_fingerprint = st.session_state.get("job_profile_fingerprint")
    profile = st.session_state.get("job_profile")
    match_result = st.session_state.get("match_result")
    match_fingerprint = st.session_state.get("match_fingerprint")
    if not job_fingerprint or profile is None or match_result is None:
        return
    expected_match_fingerprint = match_result_fingerprint(
        resume_fingerprint, job_fingerprint
    )
    if match_fingerprint != expected_match_fingerprint:
        return
    for job_input in inputs:
        key = batch_item_cache_key(resume_fingerprint, job_fingerprint)
        if batch_item_cache_key(
            resume_fingerprint, jd_text_fingerprint(job_input.jd_text)
        ) != key:
            continue
        cache[key] = build_completed_screening_item(
            job_input,
            profile,
            match_result,
            is_cached=True,
            cache_source="single",
        )


def _render_tier_counts(result: BatchScreeningResult) -> None:
    counts = {
        tier: sum(item.screening_tier is tier for item in result.items)
        for tier in ScreeningTier
    }
    with st.container(horizontal=True, wrap=True):
        for tier in ScreeningTier:
            st.metric(TIER_LABELS[tier], counts[tier], border=True)
        st.metric("失败", result.failed_count, border=True)


def _render_match_details(item: BatchScreeningItem) -> None:
    if item.match_result is None:
        return
    result = item.match_result
    st.divider()
    st.subheader("批量筛选详情")
    st.write(f"**{item.company or '未提供公司'} · {item.job_title or '未命名岗位'}**")
    scores = result.scores
    with st.container(horizontal=True, wrap=True):
        for label, score in (
            ("综合匹配度", scores.overall_score),
            ("技能", scores.skills_score),
            ("经历", scores.experience_score),
            ("项目", scores.projects_score),
            ("教育及其他", scores.education_other_score),
        ):
            st.metric(label, "N/A" if score is None else f"{score:.0f} 分", border=True)

    sections = (
        ("匹配技能", [entry.skill for entry in result.matched_skills]),
        (
            "部分匹配",
            [entry.job_requirement for entry in result.partial_matches],
        ),
        (
            "缺失必备技能",
            [entry.skill for entry in result.missing_skills if entry.importance == "required"],
        ),
        (
            "缺失加分技能",
            [entry.skill for entry in result.missing_skills if entry.importance == "preferred"],
        ),
        ("优势", result.strengths),
        ("能力差距", result.gaps),
    )
    for title, values in sections:
        if values:
            st.markdown(f"#### {title}")
            for value in values:
                st.markdown(f"- {value}")


def _quick_as_completed(item: FastScreeningItem) -> BatchScreeningItem | None:
    if not item.deep_match or item.job_profile is None or item.match_result is None:
        return None
    return build_completed_screening_item(
        item.job_input,
        item.job_profile,
        item.match_result,
        is_cached=item.is_cached,
        cache_source="fast-pipeline" if item.is_cached else None,
    )


def _render_fast_metrics(result: FastScreeningPipelineResult) -> None:
    metrics = result.metrics
    with st.expander("高级设置 · 开发者诊断", expanded=False):
        st.caption(
            f"岗位 {metrics.total_jobs} · 本地筛除 {metrics.local_filtered} · "
            f"快速分析 {metrics.flash_screened} · 深度分析 {metrics.pro_analyzed} · "
            f"缓存 {metrics.cache_hits}"
        )
        st.caption(
            f"总耗时 {metrics.timing.total_elapsed_seconds:.1f}s · "
            f"首个结果 {metrics.timing.time_to_first_result_seconds:.1f}s · "
            f"JD 清洗 {metrics.jd_parse_calls} · 快速请求 {metrics.flash_provider_calls} · "
            f"深度请求 {metrics.pro_provider_calls} · 修复 {metrics.repair_calls}"
        )
        st.dataframe(
            [
                {
                    "阶段": item.stage,
                    "岗位序号": item.job_index,
                    "开始（秒）": round(item.start_seconds, 3),
                    "结束（秒）": round(item.end_seconds, 3),
                    "耗时（秒）": round(item.duration_seconds, 3),
                    "缓存": "命中" if item.cache_hit else "未命中",
                }
                for item in metrics.timeline
            ],
            hide_index=True,
            width="stretch",
        )


def _render_fast_results(
    result: FastScreeningPipelineResult,
    resume_fingerprint: str,
    repository_factory: Callable[[], ApplicationRepository],
    detail_callback: Callable[[int], None] | None = None,
) -> None:
    st.subheader("筛选结果")
    counts = {
        tier: sum(item.screening_tier is tier for item in result.items)
        for tier in ScreeningTier
    }
    with st.container(horizontal=True, wrap=True):
        for tier in ScreeningTier:
            st.metric(TIER_LABELS[tier], counts[tier], border=True)
    _render_fast_metrics(result)
    st.caption("勾选希望联系的岗位；只有已完成详细分析的岗位才显示精确分数。")
    render_batch_apply_selection(
        result,
        repository_factory=repository_factory,
        detail_callback=detail_callback,
    )
    selected_index = st.session_state.get("selected_batch_item_index")
    selected = next(
        (
            completed
            for entry in result.items
            if entry.job_input.index == selected_index
            if (completed := _quick_as_completed(entry)) is not None
        ),
        None,
    )
    if selected is not None:
        _render_match_details(selected)


def _save_feedback(outcome: str) -> None:
    if outcome == "saved":
        st.success("岗位已保存到投递管理，当前状态为待投递。")
    elif outcome == "duplicate":
        st.info("该岗位已存在于投递管理中，本次已跳过。")
    else:
        st.error("岗位暂时无法保存，请稍后重试。")


def _render_results(
    result: BatchScreeningResult,
    service: BatchScreeningService,
    candidate: CandidateProfile,
    resume_fingerprint: str,
    repository_factory: Callable[[], ApplicationRepository],
) -> None:
    st.subheader("筛选结果")
    _render_tier_counts(result)
    st.caption(
        f"本次岗位数：{result.total_count}　·　"
        f"新分析：{result.newly_analyzed_count}　·　缓存复用：{result.cached_count}"
    )
    st.info("筛选结果仅用于安排投递优先级，不代表招聘成功概率或 Offer 概率。")

    priority_count = sum(
        item.screening_tier is ScreeningTier.PRIORITY for item in result.items
    )
    if priority_count and st.button(
        "保存所有优先投岗位",
        key="save_all_priority_batch_items",
        icon=":material/bookmarks:",
    ):
        try:
            summary = save_priority_items(repository_factory(), result.items)
        except ApplicationRepositoryError:
            st.error("批量保存暂时无法完成，请稍后重试。")
        else:
            st.success(
                f"成功保存 {summary.saved_count} 个，已存在 {summary.duplicate_count} 个，"
                f"失败 {summary.failed_count} 个。"
            )

    for item in result.items:
        key_suffix = f"{item.index}_{item.jd_fingerprint[:10]}"
        with st.container(border=True):
            if item.status is BatchJobStatus.FAILED:
                st.badge("分析失败", color="red")
                st.write(
                    f"**{item.company or '未提供公司'} · {item.job_title or f'岗位 {item.index}'}**"
                )
                st.error(item.error_message or "该岗位分析失败。")
                if st.button(
                    "重新分析",
                    key=f"retry_batch_{key_suffix}",
                    icon=":material/refresh:",
                ):
                    with st.spinner("正在重新分析该岗位..."):
                        retried = service.retry_item(
                            candidate, resume_fingerprint, item
                        )
                    updated = [
                        retried if existing.index == item.index else existing
                        for existing in result.items
                    ]
                    store_batch_screening_result(
                        build_batch_screening_result(updated), None
                    )
                    st.rerun()
                continue

            tier = item.screening_tier
            with st.container(horizontal=True, wrap=True, gap="small"):
                st.badge(TIER_LABELS[tier], color=TIER_COLORS[tier])
                if item.is_cached:
                    st.badge("缓存复用", color="gray")
            st.write(
                f"**{item.company or '未提供公司'} · {item.job_title or '未命名岗位'}**"
            )
            st.caption(f"地点：{item.location or '—'}　·　状态：已完成")
            with st.container(horizontal=True, wrap=True):
                st.metric("匹配度", f"{item.match_score:.0f} 分", border=True)
                st.metric("必备技能缺口", item.required_missing_count, border=True)
            st.write(item.screening_reason)
            st.caption(f"主要缺口：{_major_gaps(item)}")
            if item.source_url:
                st.caption("已记录岗位链接；JobPilot 不会自动访问该网址。")
            with st.container(horizontal=True, wrap=True):
                if st.button(
                    "查看详情",
                    key=f"batch_details_{key_suffix}",
                    icon=":material/visibility:",
                ):
                    st.session_state.selected_batch_item_index = item.index
                st.button(
                    "查看完整分析",
                    key=f"batch_handoff_{key_suffix}",
                    icon=":material/open_in_new:",
                    on_click=handoff_batch_item_to_single,
                    args=(item, resume_fingerprint),
                )
                if st.button(
                    "保存到投递管理",
                    key=f"batch_save_{key_suffix}",
                    icon=":material/bookmark_add:",
                ):
                    try:
                        outcome = save_batch_item(repository_factory(), item)
                    except ApplicationRepositoryError:
                        outcome = "failed"
                    _save_feedback(outcome)

    selected_index = st.session_state.get("selected_batch_item_index")
    selected = next(
        (
            item
            for item in result.items
            if item.index == selected_index
            and item.status is BatchJobStatus.COMPLETED
        ),
        None,
    )
    if selected is not None:
        _render_match_details(selected)


def render_batch_screening(
    config: AppConfig,
    *,
    job_analyzer_factory: Callable[[], JobAnalyzer] | None = None,
    matching_service_factory: Callable[[], MatchingService] | None = None,
    fast_screening_service_factory: Callable[[], FastScreeningService] | None = None,
    repository_factory: Callable[[], ApplicationRepository] = ApplicationRepository,
    extension_bridge_factory: Callable[[], object] = get_extension_bridge,
) -> None:
    """Render batch input, bounded sequential processing, and reusable results."""
    st.caption("一次筛选 1–20 个岗位，JobPilot 会基于当前简历给出沟通建议。")
    st.caption(
        "批量岗位分析会将岗位 JD 以及必要的结构化简历信息发送至 AI 服务；"
        "不会发送手机号或邮箱。"
    )
    render_site_discovery(bridge_factory=extension_bridge_factory)
    discovery_result: JobDiscoveryResult | None = st.session_state.get(
        "boss_discovery_result"
    )
    if discovery_result is not None and discovery_result.discovered_count:
        discovered_raw = _format_discovered_jobs(discovery_result)
        if st.session_state.get("boss_import_fingerprint") != discovered_raw:
            st.session_state.batch_job_input = discovered_raw
            st.session_state.boss_import_fingerprint = discovered_raw
        st.success(f"已导入 {discovery_result.discovered_count} 个岗位。")
        with st.container(border=True):
            for item in discovery_result.items:
                st.write(f"**{item.company or '未提供公司'} · {item.job_title or '未命名岗位'}**")
                st.caption(item.location or "地点未提供")

    with st.expander("手动导入或查看原始内容", expanded=False):
        st.caption("没有使用扩展时，可粘贴 1–20 个岗位；多个岗位用单独一行 --- 分隔。")
        raw_input = st.text_area(
            "岗位原始内容",
            height=280,
            placeholder="公司、岗位、地点、链接和 JD",
            key="batch_job_input",
            persist_state="session",
        )
    raw_input = st.session_state.get("batch_job_input", "")
    input_fingerprint = sync_batch_input_state(raw_input)
    screening_mode = ScreeningMode.QUICK
    explicitly_deep_indices: set[int] = set()

    candidate: CandidateProfile | None = st.session_state.get("candidate_profile")
    resume_fingerprint = st.session_state.get("candidate_profile_fingerprint")
    can_analyze = bool(candidate is not None and resume_fingerprint and config.has_api_key)
    requested = st.button(
        "开始筛选",
        type="primary",
        disabled=not can_analyze,
        key="start_batch_screening",
        icon=":material/filter_alt:",
    )
    if candidate is None or not resume_fingerprint:
        st.info(
            "请先在“简历分析”中完成简历解析和 AI 分析，再进行批量岗位筛选。"
        )
        st.caption("请使用左侧导航前往“简历分析”。")
    elif not config.has_api_key:
        st.info("AI 分析尚未配置，请完成 DeepSeek API Key 配置后重试。")

    result = st.session_state.get("batch_screening_result")
    request_key = (
        f"{resume_fingerprint}:{input_fingerprint}:quick"
        if resume_fingerprint and input_fingerprint
        else None
    )
    if (
        requested
        and result is not None
        and request_key is not None
        and st.session_state.get("screening_request_key") == request_key
    ):
        requested = False
        st.info("当前岗位批次已经完成筛选，已复用现有结果。")
    if requested:
        screening_batch_id = f"screening-{uuid4().hex}"
        st.session_state.screening_in_progress = True
        try:
            inputs = parse_batch_job_input(raw_input)
            repository = repository_factory()
            cache = st.session_state.batch_item_cache
            _seed_single_job_cache(inputs, resume_fingerprint, cache)
            analyzer = (
                job_analyzer_factory()
                if job_analyzer_factory
                else JobAnalyzer(DeepSeekLLMClient(config))
            )
            matcher = (
                matching_service_factory()
                if matching_service_factory
                else MatchingService(DeepSeekLLMClient(config))
            )
            service = BatchScreeningService(
                analyzer,
                matcher,
                repository=repository,
                item_cache=cache,
            )
            progress = st.progress(0, text=f"准备筛选 {len(inputs)} 个岗位")
            live_results = st.empty()
            if True:
                fast_service = (
                    fast_screening_service_factory()
                    if fast_screening_service_factory
                    else FastScreeningService(DeepSeekLLMClient(config))
                )
                pipeline = FastScreeningPipeline(
                    LocalPreScreenService(),
                    fast_service,
                    matcher,
                    deep_service=service,
                    local_cache=st.session_state.fast_local_cache,
                    fast_cache=st.session_state.fast_assessment_cache,
                    deep_cache=cache,
                    trimmed_jd_cache=st.session_state.fast_trimmed_jd_cache,
                    compact_summary_cache=st.session_state.fast_candidate_summary_cache,
                    job_profile_cache=st.session_state.fast_job_profile_cache,
                )

                def update_fast_progress(
                    event: FastScreeningProgress,
                    snapshot: list[FastScreeningItem],
                ) -> None:
                    stage_labels = {
                        FastScreeningStage.LOCAL: "本地预筛完成",
                        FastScreeningStage.FLASH: "FLASH 快筛",
                        FastScreeningStage.PRO: "PRO 深度分析",
                        FastScreeningStage.COMPLETED: "筛选完成",
                    }
                    if event.stage is FastScreeningStage.LOCAL:
                        fraction = 0.2
                    elif event.stage is FastScreeningStage.FLASH:
                        fraction = 0.2 + 0.4 * event.completed / max(event.total, 1)
                    elif event.stage is FastScreeningStage.PRO:
                        fraction = 0.6 + 0.35 * event.completed / max(event.total, 1)
                    else:
                        fraction = 1.0
                    progress.progress(
                        min(fraction, 1.0),
                        text=f"{stage_labels[event.stage]} · {event.completed} / {event.total}",
                    )
                    preview = snapshot[:5]
                    live_results.markdown(
                        "**实时结果**　"
                        + "　|　".join(
                            f"{entry.job_input.job_title or f'岗位 {entry.job_input.index}'}："
                            f"{TIER_LABELS[entry.screening_tier]}"
                            for entry in preview
                        )
                    )

                result = pipeline.process(
                    candidate,
                    resume_fingerprint,
                    inputs,
                    mode=ScreeningMode.QUICK,
                    explicitly_deep_indices=explicitly_deep_indices,
                    progress_callback=update_fast_progress,
                    screening_batch_id=screening_batch_id,
                )
            progress.progress(1.0, text=f"已完成 {len(inputs)} 个岗位的批量处理")
            st.session_state.batch_screening_mode_used = ScreeningMode.QUICK.value
            mark_discovery_items_screened(inputs)
            store_batch_screening_result(result, None)
            st.session_state.screening_request_key = request_key
        except BatchInputError as exc:
            store_batch_screening_result(None, str(exc))
            result = None
        except ApplicationRepositoryError:
            store_batch_screening_result(None, "本地岗位数据暂时无法读取，请稍后重试。")
            result = None
        finally:
            st.session_state.screening_in_progress = False

    error = st.session_state.get("batch_input_error")
    if error:
        st.error(error)
    if result is not None and candidate is not None and resume_fingerprint:
        if isinstance(result, FastScreeningPipelineResult):
            def run_detail_analysis(item_index: int) -> None:
                inputs = parse_batch_job_input(raw_input)
                repository = repository_factory()
                analyzer = (
                    job_analyzer_factory()
                    if job_analyzer_factory
                    else JobAnalyzer(DeepSeekLLMClient(config))
                )
                matcher = (
                    matching_service_factory()
                    if matching_service_factory
                    else MatchingService(DeepSeekLLMClient(config))
                )
                deep_service = BatchScreeningService(
                    analyzer,
                    matcher,
                    repository=repository,
                    item_cache=st.session_state.batch_item_cache,
                )
                fast_service = (
                    fast_screening_service_factory()
                    if fast_screening_service_factory
                    else FastScreeningService(DeepSeekLLMClient(config))
                )
                pipeline = FastScreeningPipeline(
                    LocalPreScreenService(),
                    fast_service,
                    matcher,
                    deep_service=deep_service,
                    local_cache=st.session_state.fast_local_cache,
                    fast_cache=st.session_state.fast_assessment_cache,
                    deep_cache=st.session_state.batch_item_cache,
                    trimmed_jd_cache=st.session_state.fast_trimmed_jd_cache,
                    compact_summary_cache=st.session_state.fast_candidate_summary_cache,
                    job_profile_cache=st.session_state.fast_job_profile_cache,
                )
                with st.spinner("正在生成该岗位的详细分析……"):
                    detailed = pipeline.process(
                        candidate,
                        resume_fingerprint,
                        inputs,
                        mode=ScreeningMode.QUICK,
                        explicitly_deep_indices={item_index},
                    )
                detailed = detailed.model_copy(
                    update={"screening_batch_id": result.screening_batch_id}
                )
                store_batch_screening_result(detailed, None)
                st.session_state.selected_batch_item_index = item_index

            _render_fast_results(
                result,
                resume_fingerprint,
                repository_factory,
                detail_callback=run_detail_analysis,
            )
            return
        try:
            repository = repository_factory()
        except ApplicationRepositoryError:
            st.error("本地岗位数据暂时无法读取，请稍后重试。")
            return
        analyzer = (
            job_analyzer_factory()
            if job_analyzer_factory
            else JobAnalyzer(DeepSeekLLMClient(config))
        )
        matcher = (
            matching_service_factory()
            if matching_service_factory
            else MatchingService(DeepSeekLLMClient(config))
        )
        service = BatchScreeningService(
            analyzer,
            matcher,
            repository=repository,
            item_cache=st.session_state.batch_item_cache,
        )
        _render_results(
            result,
            service,
            candidate,
            resume_fingerprint,
            repository_factory,
        )
