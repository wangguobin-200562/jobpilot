"""Job intelligence, matching, and targeted resume suggestions page."""

from collections.abc import Callable

import streamlit as st

from jobpilot.config import AppConfig, load_config
from jobpilot.llm import (
    DeepSeekLLMClient,
    EmptyJobProfileError,
    LLMConfigurationError,
    LLMError,
    LLMRequestError,
    LLMTimeoutError,
    StructuredOutputError,
)
from jobpilot.models import (
    CandidateProfile,
    JobProfile,
    MatchResult,
    ResumeOptimizationResult,
    ResumeSuggestion,
)
from jobpilot.services import (
    MAX_JOB_DESCRIPTION_CHARACTERS,
    MIN_JOB_DESCRIPTION_CHARACTERS,
    EmptyJobDescriptionError,
    JobAnalyzer,
    JobDescriptionValidationError,
    LongJobDescriptionError,
    MatchingService,
    ResumeOptimizationService,
    ShortJobDescriptionError,
    ensure_job_profile_has_core_data,
    validate_job_description,
)
from jobpilot.storage import (
    ApplicationRepository,
    ApplicationRepositoryError,
    DuplicateApplicationError,
)
from jobpilot.ui.state import (
    cached_job_profile,
    cached_match_result,
    cached_optimization_result,
    job_description_fingerprint,
    match_result_fingerprint,
    optimization_result_fingerprint,
    store_job_profile,
    store_match_result,
    store_optimization_result,
    sync_job_description_state,
    sync_match_result_state,
    sync_optimization_result_state,
)


def _localized_job_input_error(error: JobDescriptionValidationError) -> str:
    if isinstance(error, EmptyJobDescriptionError):
        return "请先粘贴岗位描述。"
    if isinstance(error, ShortJobDescriptionError):
        return "岗位描述内容过短，请粘贴更完整的 JD 后再分析。"
    if isinstance(error, LongJobDescriptionError):
        return "岗位描述内容过长，请精简至 20,000 个字符以内后再分析。"
    return "岗位描述内容无效，请检查后重试。"


def _localized_job_llm_error(error: LLMError) -> str:
    if isinstance(error, LLMConfigurationError):
        return "AI 分析尚未配置，请完成 DeepSeek API Key 配置后重试。"
    if isinstance(error, EmptyJobProfileError):
        return "AI 未能从当前岗位描述中提取有效信息，请检查 JD 后重新分析。"
    if isinstance(error, LLMTimeoutError):
        return "AI 请求超时，请稍后重试。"
    if isinstance(error, StructuredOutputError):
        return "AI 返回结果无法转换为有效的岗位画像，请重新分析。"
    if isinstance(error, LLMRequestError):
        return "AI 服务暂时无法完成请求，请稍后重试。"
    return "AI 分析暂时无法完成，请稍后重试。"


def _localized_matching_error(error: LLMError) -> str:
    if isinstance(error, LLMConfigurationError):
        return "AI 分析尚未配置，请完成 DeepSeek API Key 配置后重试。"
    if isinstance(error, LLMTimeoutError):
        return "岗位匹配分析请求超时，请稍后重试。"
    if isinstance(error, StructuredOutputError):
        return "AI 返回的匹配分析结果无法解析，请重新分析。"
    if isinstance(error, LLMRequestError):
        return "AI 服务暂时无法完成岗位匹配分析，请稍后重试。"
    return "岗位匹配分析暂时无法完成，请稍后重试。"


def _localized_optimization_error(error: LLMError) -> str:
    if isinstance(error, LLMConfigurationError):
        return "AI 建议尚未配置，请完成 DeepSeek API Key 配置后重试。"
    if isinstance(error, LLMTimeoutError):
        return "岗位定向建议生成超时，请稍后重试。"
    if isinstance(error, StructuredOutputError):
        return "AI 返回的岗位定向建议无法解析，请重新生成。"
    if isinstance(error, LLMRequestError):
        return "AI 服务暂时无法生成岗位定向建议，请稍后重试。"
    return "岗位定向建议暂时无法生成，请稍后重试。"


def _render_badges(values: list[str], *, color: str = "blue") -> None:
    with st.container(horizontal=True, wrap=True, gap="small"):
        for value in values:
            st.badge(value, color=color)


def _render_list_section(title: str, values: list[str]) -> None:
    if not values:
        return
    st.markdown(f"#### {title}")
    for value in values:
        st.markdown(f"- {value}")


def _render_job_profile(profile: JobProfile) -> None:
    st.subheader("岗位画像")

    basic_information = [
        (label, value)
        for label, value in (
            ("岗位名称", profile.job_title),
            ("公司", profile.company),
            ("地点", profile.location),
            ("用工类型", profile.employment_type),
            ("薪资", profile.salary_range),
        )
        if value
    ]
    if basic_information:
        st.markdown("#### 基本信息")
        for start in range(0, len(basic_information), 4):
            row = basic_information[start : start + 4]
            columns = st.columns(len(row))
            for column, (label, value) in zip(columns, row, strict=True):
                column.caption(label)
                column.write(value)

    _render_list_section("岗位职责", profile.responsibilities)

    if profile.required_skills:
        st.markdown("#### 必备技能")
        _render_badges(profile.required_skills, color="blue")
    if profile.preferred_skills:
        st.markdown("#### 加分技能")
        _render_badges(profile.preferred_skills, color="violet")
    if profile.tools_and_technologies:
        st.markdown("#### 工具与技术")
        _render_badges(profile.tools_and_technologies, color="gray")

    requirement_fields = [
        ("经验要求", profile.experience_requirements),
        ("学历要求", profile.education_requirements),
    ]
    populated_requirements = [item for item in requirement_fields if item[1]]
    if populated_requirements:
        st.markdown("#### 任职要求")
        columns = st.columns(len(populated_requirements))
        for column, (label, value) in zip(
            columns, populated_requirements, strict=True
        ):
            with column.container(border=True):
                st.caption(label)
                st.write(value)

    if profile.language_requirements:
        st.markdown("#### 语言要求")
        _render_badges(profile.language_requirements, color="gray")
    if profile.keywords:
        st.markdown("#### 岗位关键词")
        _render_badges(profile.keywords, color="blue")

    _render_list_section("福利待遇", profile.benefits)
    _render_list_section("其他要求", profile.other_requirements)

    with st.expander("高级信息", expanded=False):
        st.caption("以下仅展示岗位画像结构化数据。")
        st.json(profile.model_dump(mode="json"))


def _create_job_analyzer(config: AppConfig) -> JobAnalyzer:
    return JobAnalyzer(DeepSeekLLMClient(config))


def _create_matching_service(config: AppConfig) -> MatchingService:
    return MatchingService(DeepSeekLLMClient(config))


def _create_resume_optimization_service(
    config: AppConfig,
) -> ResumeOptimizationService:
    return ResumeOptimizationService(DeepSeekLLMClient(config))


def _format_score(score: float | None) -> str:
    return "不适用" if score is None else f"{score:.0f}%"


def _render_match_result(result: MatchResult) -> None:
    st.subheader("匹配结果")
    scores = result.scores
    overall = st.container(border=True)
    overall.metric("岗位匹配度", _format_score(scores.overall_score))
    overall.progress(
        int(round(scores.overall_score)),
        text="基于适用维度动态加权计算",
    )

    score_columns = st.columns(4)
    for column, (label, score) in zip(
        score_columns,
        (
            ("技能匹配", scores.skills_score),
            ("经历匹配", scores.experience_score),
            ("项目匹配", scores.projects_score),
            ("教育及其他", scores.education_other_score),
        ),
        strict=True,
    ):
        column.metric(label, _format_score(score), border=True)

    if result.summary:
        st.markdown("#### 匹配概述")
        st.write(result.summary)

    if result.strengths:
        st.markdown("#### 你的优势")
        for strength in result.strengths:
            st.markdown(f"- {strength}")

    if result.matched_skills:
        st.markdown("#### 已匹配技能")
        for item in result.matched_skills:
            with st.container(border=True):
                st.badge(
                    "完全匹配" if item.match_type == "exact" else "语义匹配",
                    color="green",
                )
                st.write(f"**{item.skill}**")
                st.caption(f"简历证据：{item.resume_evidence}")

    if result.partial_matches:
        st.markdown("#### 部分匹配")
        for item in result.partial_matches:
            with st.container(border=True):
                st.badge("部分匹配", color="orange")
                st.write(f"**岗位要求：{item.job_requirement}**")
                st.caption(f"简历证据：{item.resume_evidence}")
                st.write(item.gap)

    if result.missing_skills:
        st.markdown("#### 缺失技能")
        for importance, label in (("required", "缺失必备"), ("preferred", "缺失加分")):
            values = [
                item for item in result.missing_skills if item.importance == importance
            ]
            if values:
                st.caption(label)
                for item in values:
                    with st.container(border=True):
                        st.badge(
                            "必备" if importance == "required" else "加分",
                            color="red" if importance == "required" else "orange",
                        )
                        st.write(f"**{item.skill}**")
                        st.caption(item.reason)

    if result.evidence:
        st.markdown("#### 匹配证据")
        for item in result.evidence:
            with st.container(border=True):
                st.caption(item.category)
                st.write(f"**岗位要求：** {item.job_requirement}")
                st.write(f"**简历证据：** {item.resume_evidence}")
                st.caption(item.assessment)

    if result.gaps:
        st.markdown("#### 能力差距")
        for gap in result.gaps:
            st.markdown(f"- {gap}")

    if result.improvement_priorities:
        st.markdown("#### 提升优先级")
        priority_labels = {"high": "高", "medium": "中", "low": "低"}
        priority_colors = {"high": "red", "medium": "orange", "low": "gray"}
        for item in result.improvement_priorities:
            with st.container(border=True):
                st.badge(
                    priority_labels[item.priority],
                    color=priority_colors[item.priority],
                )
                st.write(f"**{item.action}**")
                st.caption(item.reason)


def _render_suggestion_cards(
    title: str,
    suggestions: list[ResumeSuggestion],
    *,
    badge_label: str,
    badge_color: str,
) -> None:
    section_labels = {
        "summary": "个人概述",
        "education": "教育经历",
        "experience": "工作经历",
        "projects": "项目经历",
        "skills": "技能",
        "certifications": "证书",
        "languages": "语言能力",
    }
    st.markdown(f"#### {title}")
    if not suggestions:
        st.caption("当前没有此类建议。")
        return
    for item in suggestions:
        with st.container(border=True):
            with st.container(horizontal=True, wrap=True, gap="small"):
                st.badge(badge_label, color=badge_color)
                st.caption(f"{section_labels[item.section]} · {item.source_name}")
            if item.decision == "keep":
                st.write(item.original)
                st.caption(item.reason)
                continue
            original_column, suggestion_column = st.columns(2)
            with original_column:
                st.caption("当前表达")
                st.write(item.original)
            with suggestion_column:
                st.caption("建议表达")
                st.write(item.suggested or "—")
            st.write(f"**原因：** {item.reason}")
            if item.expected_benefit:
                st.caption(f"预期收益：{item.expected_benefit}")


def _render_optimization_result(result: ResumeOptimizationResult) -> None:
    st.markdown("#### 建议概述")
    st.write(result.summary)

    keeps = [item for item in result.suggestions if item.decision == "keep"]
    optional = [item for item in result.suggestions if item.decision == "optional"]
    recommended = [
        item for item in result.suggestions if item.decision == "recommended"
    ]
    _render_suggestion_cards(
        "无需修改", keeps, badge_label="保留", badge_color="green"
    )
    _render_suggestion_cards(
        "可选优化", optional, badge_label="可选", badge_color="blue"
    )
    _render_suggestion_cards(
        "建议修改", recommended, badge_label="建议", badge_color="orange"
    )

    if result.keyword_suggestions:
        st.markdown("#### 岗位关键词")
        status_labels = {
            "covered": ("已覆盖", "green"),
            "can_emphasize": ("可突出", "blue"),
            "gap_do_not_add": ("能力缺口", "red"),
        }
        for item in result.keyword_suggestions:
            label, color = status_labels[item.status]
            with st.container(border=True):
                st.badge(label, color=color)
                st.write(f"**{item.keyword}**")
                st.caption(item.guidance)

    st.markdown("#### 能力缺口")
    if result.capability_gaps:
        for gap in result.capability_gaps:
            st.markdown(f"- {gap}")
    else:
        st.caption("当前匹配结果中没有需要额外提示的能力缺口。")
    for warning in result.warnings:
        st.warning(warning, icon=":material/warning:")


def _render_resume_optimization(
    candidate: CandidateProfile,
    job_profile: JobProfile,
    match_result: MatchResult,
    *,
    resume_fingerprint_value: str,
    job_fingerprint_value: str,
    match_fingerprint_value: str,
    config: AppConfig,
    optimization_service_factory: Callable[[], ResumeOptimizationService] | None,
) -> None:
    st.divider()
    st.subheader("岗位定向简历建议")
    st.caption(
        "系统只会在确有收益时建议修改。如果当前表达已经清楚且适合目标岗位，"
        "会直接建议保留。"
    )

    fingerprint = optimization_result_fingerprint(
        resume_fingerprint_value,
        job_fingerprint_value,
        match_fingerprint_value,
    )
    sync_optimization_result_state(fingerprint)
    result, error = cached_optimization_result(fingerprint)
    requested = st.button(
        "生成岗位定向建议",
        type="primary",
        disabled=not config.has_api_key,
        key="generate_targeted_resume_suggestions",
        icon=":material/edit_note:",
    )
    st.caption(
        "仅发送结构化候选人画像、岗位画像和匹配结果；不会发送姓名、手机号、"
        "邮箱或原始 PDF 文本。"
    )
    if requested:
        factory = optimization_service_factory or (
            lambda: _create_resume_optimization_service(config)
        )
        try:
            with st.spinner("正在生成岗位定向建议..."):
                result = factory().analyze(candidate, job_profile, match_result)
            error = None
        except LLMError as exc:
            result = None
            error = _localized_optimization_error(exc)
        store_optimization_result(fingerprint, result, error)

    if error:
        st.error(error, icon=":material/error:")
    elif result is not None:
        _render_optimization_result(result)


def _render_save_application(
    job_profile: JobProfile,
    jd_text: str,
    *,
    repository_factory: Callable[[], ApplicationRepository],
) -> None:
    st.divider()
    st.subheader("保存岗位")
    st.caption("将当前岗位及已有分析结果保存到本地投递管理。")
    if not st.button(
        "保存到投递管理",
        key="save_job_application",
        icon=":material/bookmark_add:",
    ):
        return

    company = job_profile.company or "未提供公司"
    job_title = job_profile.job_title or "未命名岗位"
    match_result: MatchResult | None = st.session_state.get("match_result")
    optimization_result: ResumeOptimizationResult | None = st.session_state.get(
        "optimization_result"
    )
    try:
        repository = repository_factory()
        duplicate = repository.find_duplicate(
            company=company,
            job_title=job_title,
            jd_text=jd_text,
        )
        if duplicate is not None:
            st.info("该岗位已经存在于投递管理中。", icon=":material/info:")
            return
        repository.create_application(
            company=company,
            job_title=job_title,
            location=job_profile.location,
            jd_text=jd_text,
            job_profile=job_profile,
            match_score=(
                match_result.scores.overall_score if match_result is not None else None
            ),
            match_result=match_result,
            optimization_result=optimization_result,
        )
        st.success("岗位已保存到投递管理。", icon=":material/check_circle:")
    except DuplicateApplicationError:
        st.info("该岗位已经存在于投递管理中。", icon=":material/info:")
    except (ApplicationRepositoryError, OSError):
        st.error("数据暂时无法保存，请稍后重试。", icon=":material/error:")


def _render_matching_analysis(
    job_profile: JobProfile | None,
    config: AppConfig,
    *,
    matching_service_factory: Callable[[], MatchingService] | None = None,
    optimization_service_factory: Callable[[], ResumeOptimizationService] | None = None,
) -> None:
    st.divider()
    st.subheader("匹配分析")
    st.caption("结合候选人画像与岗位要求，生成可解释的匹配结果和能力差距。")

    candidate: CandidateProfile | None = st.session_state.candidate_profile
    resume_fingerprint_value = st.session_state.candidate_profile_fingerprint
    job_fingerprint_value = st.session_state.job_profile_fingerprint

    if candidate is None or not resume_fingerprint_value:
        sync_match_result_state(None)
        st.info(
            "请先前往“简历分析”完成简历 AI 分析。",
            icon=":material/info:",
        )
    if job_profile is None or not job_fingerprint_value:
        sync_match_result_state(None)
        st.info("请先完成当前岗位 JD 分析。", icon=":material/info:")
    if (
        candidate is None
        or not resume_fingerprint_value
        or job_profile is None
        or not job_fingerprint_value
    ):
        return

    fingerprint = match_result_fingerprint(
        resume_fingerprint_value, job_fingerprint_value
    )
    sync_match_result_state(fingerprint)
    result, error = cached_match_result(fingerprint)

    requested = st.button(
        "开始匹配分析",
        type="primary",
        disabled=not config.has_api_key,
        key="analyze_resume_job_match",
        icon=":material/compare_arrows:",
    )
    st.caption(
        "点击“开始匹配分析”后，结构化候选人信息与岗位画像将发送到"
        "已配置的 DeepSeek API 进行语义匹配分析。"
    )
    if not config.has_api_key:
        st.info(
            "AI 分析尚未配置，请完成 DeepSeek API Key 配置后重试。",
            icon=":material/info:",
        )

    if requested:
        factory = matching_service_factory or (
            lambda: _create_matching_service(config)
        )
        try:
            with st.spinner("正在进行岗位匹配分析..."):
                result = factory().analyze(candidate, job_profile)
            error = None
        except LLMError as exc:
            result = None
            error = _localized_matching_error(exc)
        store_match_result(fingerprint, result, error)

    if error:
        st.error(error, icon=":material/error:")
    elif result is not None:
        _render_match_result(result)
        _render_resume_optimization(
            candidate,
            job_profile,
            result,
            resume_fingerprint_value=resume_fingerprint_value,
            job_fingerprint_value=job_fingerprint_value,
            match_fingerprint_value=fingerprint,
            config=config,
            optimization_service_factory=optimization_service_factory,
        )


def _render_single_job_match(
    *,
    analyzer_factory: Callable[[], JobAnalyzer] | None = None,
    matching_service_factory: Callable[[], MatchingService] | None = None,
    optimization_service_factory: Callable[[], ResumeOptimizationService] | None = None,
    application_repository_factory: Callable[
        [], ApplicationRepository
    ] = ApplicationRepository,
) -> None:
    """Render the complete JD analysis and resume-matching workflow."""
    config = load_config()
    with st.container(border=True):
        st.subheader("岗位 JD")
        st.caption("请粘贴完整岗位描述，包含岗位职责和任职要求。")
        job_description = st.text_area(
            "粘贴岗位 JD",
            height=300,
            placeholder="在此粘贴岗位名称、岗位职责、任职要求、技能要求等完整信息……",
            key="job_description_input",
            persist_state="session",
        )
        st.caption(
            f"建议至少 {MIN_JOB_DESCRIPTION_CHARACTERS} 个字符，"
            f"最多 {MAX_JOB_DESCRIPTION_CHARACTERS:,} 个字符。"
        )
        requested = st.button(
            "开始岗位分析",
            type="primary",
            disabled=not config.has_api_key,
            key="analyze_job_with_ai",
            icon=":material/auto_awesome:",
        )
        st.caption(
            "岗位 JD 只会在你点击“开始岗位分析”后发送到已配置的 DeepSeek API。"
        )

        if not config.has_api_key:
            st.info(
                "AI 分析尚未配置，请完成 DeepSeek API Key 配置后重试。",
                icon=":material/info:",
            )

    fingerprint = job_description_fingerprint(job_description)
    if fingerprint is None and not requested:
        st.info("请粘贴目标岗位 JD。", icon=":material/info:")
    sync_job_description_state(fingerprint)
    profile, error = cached_job_profile(fingerprint)
    if profile is not None:
        try:
            profile = ensure_job_profile_has_core_data(profile)
        except EmptyJobProfileError as exc:
            profile = None
            error = _localized_job_llm_error(exc)
            if fingerprint is not None:
                store_job_profile(fingerprint, profile, error)

    local_error: str | None = None
    if requested:
        try:
            validated_description = validate_job_description(job_description)
        except JobDescriptionValidationError as exc:
            local_error = _localized_job_input_error(exc)
        else:
            if fingerprint is None:
                local_error = "请先粘贴岗位描述。"
            else:
                factory = analyzer_factory or (
                    lambda: _create_job_analyzer(config)
                )
                try:
                    with st.spinner("正在分析岗位描述..."):
                        profile = factory().analyze(validated_description)
                        profile = ensure_job_profile_has_core_data(profile)
                    error = None
                except LLMError as exc:
                    profile = None
                    error = _localized_job_llm_error(exc)
                store_job_profile(fingerprint, profile, error)

    if local_error:
        st.error(local_error, icon=":material/error:")
    elif error:
        st.error(error, icon=":material/error:")
    elif profile is not None:
        _render_job_profile(profile)

    _render_matching_analysis(
        profile,
        config,
        matching_service_factory=matching_service_factory,
        optimization_service_factory=optimization_service_factory,
    )
    if profile is not None:
        _render_save_application(
            profile,
            job_description,
            repository_factory=application_repository_factory,
        )


def render_job_match(
    *,
    analyzer_factory: Callable[[], JobAnalyzer] | None = None,
    matching_service_factory: Callable[[], MatchingService] | None = None,
    fast_screening_service_factory=None,
    optimization_service_factory: Callable[[], ResumeOptimizationService] | None = None,
    application_repository_factory: Callable[
        [], ApplicationRepository
    ] = ApplicationRepository,
    extension_bridge_factory=None,
) -> None:
    """Render the unified 1–20 job screening flow."""
    st.title("岗位匹配")
    st.caption("从 BOSS 连续采集岗位，统一筛选并选择希望沟通的机会。")
    from jobpilot.ui.batch_screening import render_batch_screening

    kwargs = {
        "job_analyzer_factory": analyzer_factory,
        "matching_service_factory": matching_service_factory,
        "fast_screening_service_factory": fast_screening_service_factory,
        "repository_factory": application_repository_factory,
    }
    if extension_bridge_factory is not None:
        kwargs["extension_bridge_factory"] = extension_bridge_factory
    render_batch_screening(load_config(), **kwargs)
