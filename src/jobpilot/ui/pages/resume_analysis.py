"""Resume upload and local parsing page."""

from collections.abc import Callable

import streamlit as st

from jobpilot.config import AppConfig, load_config
from jobpilot.llm import (
    DeepSeekLLMClient,
    EmptyCandidateProfileError,
    LLMConfigurationError,
    LLMError,
    LLMRequestError,
    LLMTimeoutError,
    StructuredOutputError,
)
from jobpilot.models import CandidateProfile, ParsedResume
from jobpilot.parsers import (
    EmptyFileError,
    FileTooLargeError,
    NoReadableTextError,
    ResumeParseError,
    UnsupportedFileTypeError,
    parse_resume,
)
from jobpilot.parsers.resume_parser import MAX_RESUME_FILE_SIZE_MB
from jobpilot.services import ResumeAnalyzer, ensure_candidate_profile_has_core_data
from jobpilot.ui.candidate_profile_display import (
    classify_education_details,
    mask_email,
    mask_phone,
    masked_candidate_profile_data,
    normalize_candidate_profile_for_display,
)
from jobpilot.ui.state import (
    cached_candidate_profile,
    cached_resume_result,
    resume_fingerprint,
    store_candidate_profile,
    store_resume_result,
)


def _format_file_size(size_bytes: int) -> str:
    return f"{size_bytes / 1024:.1f} KB"


def _localized_parse_error(error: ResumeParseError) -> str:
    """Translate parser failures at the UI boundary without changing parser behavior."""
    if isinstance(error, UnsupportedFileTypeError):
        return "不支持该文件类型，请上传 PDF 或 DOCX 文件。"
    if isinstance(error, EmptyFileError):
        return "上传的文件为空，请重新选择简历文件。"
    if isinstance(error, FileTooLargeError):
        return f"文件超过 {MAX_RESUME_FILE_SIZE_MB} MB 限制，请压缩后重试。"
    if isinstance(error, NoReadableTextError):
        return "未能从文件中提取可读文本；当前暂不支持扫描版 PDF 的 OCR 识别。"
    return "简历解析失败，请确认文件完整后重试。"


def _localized_llm_error(error: LLMError) -> str:
    """Convert known LLM failures into safe Chinese UI messages."""
    if isinstance(error, LLMConfigurationError):
        return "AI 分析尚未配置，请完成 DeepSeek API Key 配置后重试。"
    if isinstance(error, EmptyCandidateProfileError):
        return "AI 未能从当前简历中提取有效信息，请重新分析。"
    if isinstance(error, LLMTimeoutError):
        return "AI 请求超时，请稍后重试。"
    if isinstance(error, StructuredOutputError):
        return "AI 返回结果无法转换为有效的候选人画像，请重新分析。"
    if isinstance(error, LLMRequestError):
        return "AI 服务暂时无法完成请求，请稍后重试。"
    return "AI 分析暂时无法完成，请稍后重试。"


def _render_result(result: ParsedResume) -> None:
    st.success("简历解析成功", icon=":material/check_circle:")

    file_columns = st.columns(3)
    file_columns[0].caption("文件名")
    file_columns[0].write(result.filename)
    file_columns[1].caption("文件类型")
    file_columns[1].write(result.file_type.upper())
    file_columns[2].caption("文件大小")
    file_columns[2].write(_format_file_size(result.file_size))

    metric_columns = st.columns(3)
    metric_columns[0].metric("页数", result.page_count or "—", border=True)
    metric_columns[1].metric("字符数", result.character_count, border=True)
    metric_columns[2].metric("词数", result.word_count, border=True)

    with st.expander("简历解析文本", expanded=True):
        st.text(result.text)


def _render_badges(values: list[str]) -> None:
    with st.container(horizontal=True, wrap=True, gap="small"):
        for value in values:
            st.badge(value, color="blue")


def _render_candidate_profile(profile: CandidateProfile) -> None:
    st.subheader("候选人画像")

    display_profile = normalize_candidate_profile_for_display(profile)
    personal = display_profile.personal_info
    basic_information = [
        (label, value)
        for label, value in (
            ("姓名", personal.name),
            ("邮箱", mask_email(personal.email)),
            ("手机号", mask_phone(personal.phone)),
            ("所在地", personal.location),
        )
        if value
    ]
    has_profile_content = bool(
        basic_information
        or display_profile.summary
        or display_profile.education
        or any(
            (
                display_profile.skills.programming_languages,
                display_profile.skills.frameworks,
                display_profile.skills.tools,
                display_profile.skills.databases,
                display_profile.skills.other,
            )
        )
        or display_profile.experience
        or display_profile.projects
        or display_profile.certifications
        or display_profile.languages
    )

    if not has_profile_content:
        st.info("简历中未识别到可展示的候选人信息。", icon=":material/info:")

    if basic_information:
        st.markdown("#### 基本信息")
        info_columns = st.columns(min(len(basic_information), 4))
        for column, (label, value) in zip(
            info_columns, basic_information, strict=True
        ):
            column.caption(label)
            column.write(value)

    if display_profile.summary:
        st.markdown("#### 个人概述")
        st.write(display_profile.summary)

    if display_profile.education:
        st.markdown("#### 教育经历")
        for item in display_profile.education:
            with st.container(border=True):
                heading = " · ".join(
                    filter(None, (item.institution, item.major, item.degree))
                )
                st.write(f"**{heading or '教育经历'}**")
                dates = " – ".join(filter(None, (item.start_date, item.end_date)))
                if dates:
                    st.caption(dates)
                gpa_details, course_details, other_details = (
                    classify_education_details(item.details)
                )
                if gpa_details:
                    st.caption("GPA")
                    for detail in gpa_details:
                        st.write(detail)
                if course_details:
                    st.caption("核心课程")
                    for detail in course_details:
                        st.write(detail)
                for detail in other_details:
                    st.caption(detail)

    skill_groups = {
        "编程语言": display_profile.skills.programming_languages,
        "框架": display_profile.skills.frameworks,
        "工具": display_profile.skills.tools,
        "数据库 / 查询": display_profile.skills.databases,
        "其他技能": display_profile.skills.other,
    }
    populated_skills = {name: values for name, values in skill_groups.items() if values}
    if populated_skills:
        st.markdown("#### 技能")
        for name, values in populated_skills.items():
            st.caption(name)
            _render_badges(values)

    if display_profile.experience:
        st.markdown("#### 实习 / 工作经历")
        for item in display_profile.experience:
            with st.container(border=True):
                heading = " · ".join(filter(None, (item.company, item.position)))
                st.write(f"**{heading or '工作经历'}**")
                dates = " – ".join(filter(None, (item.start_date, item.end_date)))
                if dates:
                    st.caption(dates)
                if item.description:
                    st.write(item.description)
                for highlight in item.highlights:
                    st.markdown(f"- {highlight}")
                if item.technologies:
                    st.caption("相关技术")
                    _render_badges(item.technologies)

    if display_profile.projects:
        st.markdown("#### 项目经历")
        for item in display_profile.projects:
            with st.container(border=True):
                heading = " · ".join(filter(None, (item.name, item.role)))
                st.write(f"**{heading or '项目经历'}**")
                if item.description:
                    st.write(item.description)
                for highlight in item.highlights:
                    st.markdown(f"- {highlight}")
                if item.technologies:
                    st.caption("相关技术")
                    _render_badges(item.technologies)

    if display_profile.certifications:
        st.markdown("#### 证书")
        _render_badges(display_profile.certifications)

    if display_profile.languages:
        st.markdown("#### 语言能力")
        _render_badges(display_profile.languages)

    with st.expander("高级信息", expanded=False):
        st.caption("以下为经过脱敏与展示归一化处理的结构化数据。")
        st.json(masked_candidate_profile_data(display_profile))


def _create_resume_analyzer(config: AppConfig) -> ResumeAnalyzer:
    return ResumeAnalyzer(DeepSeekLLMClient(config))


def _render_ai_analysis(
    result: ParsedResume,
    fingerprint: str,
    *,
    analyzer_factory: Callable[[], ResumeAnalyzer] | None = None,
) -> None:
    config = load_config()
    profile, error = cached_candidate_profile(fingerprint)
    if profile is not None:
        try:
            profile = ensure_candidate_profile_has_core_data(profile)
        except EmptyCandidateProfileError as exc:
            profile = None
            error = _localized_llm_error(exc)
            store_candidate_profile(fingerprint, profile, error)

    with st.container(border=True):
        st.subheader("AI 智能分析")
        st.caption("基于当前简历文本生成结构化候选人画像。")
        button_label = "重新分析" if profile is not None else "开始 AI 分析"
        requested = st.button(
            button_label,
            type="primary",
            disabled=not config.has_api_key,
            key="analyze_resume_with_ai",
            icon=":material/auto_awesome:",
        )

        if not config.has_api_key:
            st.info(
                "AI 分析尚未配置。请根据 .env.example 创建本地 .env，"
                "并配置 DeepSeek API Key。",
                icon=":material/info:",
            )

        if requested:
            factory = analyzer_factory or (lambda: _create_resume_analyzer(config))
            try:
                with st.spinner("正在分析简历..."):
                    profile = factory().analyze(result.text)
                    profile = ensure_candidate_profile_has_core_data(profile)
                error = None
            except LLMError as exc:
                profile = None
                error = _localized_llm_error(exc)
            store_candidate_profile(fingerprint, profile, error)

        if error:
            st.error(error, icon=":material/error:")
        elif profile is not None:
            _render_candidate_profile(profile)


def render_resume_analysis() -> None:
    """Render the local resume parser experience."""
    st.title("简历分析")
    st.caption("上传简历，系统会先在本地提取文本，并可进一步进行 AI 智能分析。")

    with st.container(border=True):
        st.subheader("上传简历")
        st.caption("支持格式：PDF、DOCX　·　最大文件大小：10 MB")
        uploaded_file = st.file_uploader(
            "选择简历文件",
            type=["pdf", "docx"],
            max_upload_size=MAX_RESUME_FILE_SIZE_MB,
            key="resume_upload",
            help="支持 PDF 或 DOCX，文件大小不超过 10 MB。",
            label_visibility="collapsed",
        )
        st.markdown("**本地解析**")
        st.caption("简历文件会先在本地完成文本提取。")
        st.markdown("**AI 智能分析**")
        st.caption(
            "只有在你主动点击“开始 AI 分析”后，解析出的简历文本才会发送到"
            "已配置的 DeepSeek API。"
        )

    if uploaded_file is None:
        # Streamlit removes a file uploader's widget value when its page is no
        # longer rendered. The parsed result and AI profile are application
        # state, however, and should remain available for this browser session.
        fingerprint = st.session_state.get("resume_file_fingerprint")
        result = st.session_state.get("parsed_resume")
        error = st.session_state.get("resume_parse_error")
        if not fingerprint or result is None:
            st.info("请上传 PDF 或 DOCX 简历开始分析。", icon=":material/info:")
            return
        st.info(
            f"已保留当前简历：{result.filename}。如需替换，请在上方重新上传。",
            icon=":material/check_circle:",
        )
    else:
        file_bytes = uploaded_file.getvalue()
        fingerprint = resume_fingerprint(uploaded_file.name, file_bytes)
        cached = cached_resume_result(fingerprint)
        if cached is None:
            try:
                result = parse_resume(uploaded_file.name, file_bytes)
                error = None
            except ResumeParseError as exc:
                result = None
                error = _localized_parse_error(exc)
            store_resume_result(fingerprint, result, error)
        else:
            result, error = cached

    if error:
        st.error(error, icon=":material/error:")
    elif result is not None:
        st.subheader("解析结果")
        _render_result(result)
        _render_ai_analysis(result, fingerprint)
