"""Evidence-bound, no-forced-rewrite resume optimization orchestration."""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
import logging
import re
from typing import Any, Iterable

from jobpilot.llm import LLMClient, ModelTier
from jobpilot.llm.structured_output import generate_structured_output
from jobpilot.models import (
    CandidateProfile,
    JobProfile,
    KeywordSuggestion,
    MatchResult,
    ResumeOptimizationResult,
    ResumeSuggestion,
)
from jobpilot.prompts.resume_optimization import (
    RESUME_OPTIMIZATION_SYSTEM_PROMPT,
    build_resume_optimization_prompt,
)
from jobpilot.services.matching_service import normalize_skill


logger = logging.getLogger(__name__)
OPTIMIZATION_TEMPERATURE = 0.0
OPTIMIZATION_THINKING = False
MAX_SUGGESTIONS_PER_CHANGE_DECISION = 5
MAX_KEEP_SUGGESTIONS = 5
_GENERIC_BENEFITS = (
    "更专业",
    "更清晰",
    "更高级",
    "更有吸引力",
    "提升简历质量",
    "优化表达",
    "增强可读性",
)


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            yield cleaned
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _compact(value: str) -> str:
    return re.sub(r"[^\w+#]", "", value.casefold(), flags=re.UNICODE)


def _texts_overlap(left: str, right: str) -> bool:
    left_key = _compact(left)
    right_key = _compact(right)
    return bool(left_key and right_key) and (
        left_key in right_key or right_key in left_key
    )


def _grounded(value: str, evidence_corpus: list[str]) -> bool:
    return any(_texts_overlap(value, evidence) for evidence in evidence_corpus)


def _privacy_safe_match_data(
    match: MatchResult, candidate: CandidateProfile
) -> dict[str, Any]:
    """Remove personal values even if an upstream evidence string repeated them."""
    private_values = {
        value.strip()
        for value in (
            candidate.personal_info.name,
            candidate.personal_info.email,
            candidate.personal_info.phone,
        )
        if value and value.strip()
    }

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value
            for private in private_values:
                cleaned = cleaned.replace(private, "[已移除]")
            return cleaned
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        return value

    return scrub(match.model_dump(mode="json"))


def _allowed_source_names(candidate: CandidateProfile) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    if candidate.summary:
        result["summary"].extend(["个人概述", "职业概述", "summary"])
    skill_values = list(_walk_strings(candidate.skills.model_dump(mode="json")))
    if skill_values:
        result["skills"].append("技能")
        result["skills"].extend(skill_values)
    if candidate.languages:
        result["languages"].append("语言能力")
        result["languages"].extend(candidate.languages)
    if candidate.certifications:
        result["certifications"].append("证书")
        result["certifications"].extend(candidate.certifications)
    for item in candidate.education:
        result["education"].extend(
            value for value in (item.institution, item.degree, item.major) if value
        )
    for item in candidate.experience:
        result["experience"].extend(
            value for value in (item.company, item.position) if value
        )
    for item in candidate.projects:
        if item.name:
            result["projects"].append(item.name)
    return result


def _source_exists(
    suggestion: ResumeSuggestion, allowed: dict[str, list[str]]
) -> bool:
    return any(
        _texts_overlap(suggestion.source_name, source)
        for source in allowed.get(suggestion.section, [])
    )


def _contains_skill(text: str, skill: str) -> bool:
    skill_key = normalize_skill(skill)
    text_key = normalize_skill(text)
    if not skill_key:
        return False
    if len(skill_key) <= 2:
        return bool(
            re.search(rf"(?<!\w){re.escape(skill.casefold())}(?!\w)", text.casefold())
        )
    return skill_key in text_key


def _introduces_new_number(suggestion: ResumeSuggestion) -> bool:
    if not suggestion.suggested:
        return False
    suggested_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", suggestion.suggested))
    supported_numbers = set(
        re.findall(
            r"\d+(?:\.\d+)?%?",
            " ".join([suggestion.original, *suggestion.supported_by]),
        )
    )
    return bool(suggested_numbers - supported_numbers)


def _benefit_is_specific(suggestion: ResumeSuggestion) -> bool:
    benefit = (suggestion.expected_benefit or "").strip()
    if len(benefit) < 8:
        return False
    if any(_compact(generic) == _compact(benefit) for generic in _GENERIC_BENEFITS):
        return False
    return bool(suggestion.related_job_requirements) or len(benefit) >= 16


def _is_near_synonym_rewrite(suggestion: ResumeSuggestion) -> bool:
    if not suggestion.suggested:
        return False
    original = _compact(suggestion.original)
    suggested = _compact(suggestion.suggested)
    return bool(original and suggested) and (
        SequenceMatcher(None, original, suggested).ratio() >= 0.9
    )


def _postprocess_suggestion(
    suggestion: ResumeSuggestion,
    *,
    allowed_sources: dict[str, list[str]],
    candidate_corpus: list[str],
    job_corpus: list[str],
    missing_skills: list[str],
) -> ResumeSuggestion | None:
    if not _source_exists(suggestion, allowed_sources):
        return None
    grounded_support = [
        value for value in suggestion.supported_by if _grounded(value, candidate_corpus)
    ]
    if not grounded_support:
        return None
    if suggestion.suggested and any(
        _contains_skill(suggestion.suggested, skill) for skill in missing_skills
    ):
        return None
    if _introduces_new_number(suggestion):
        return None

    data = suggestion.model_dump(mode="python")
    data["supported_by"] = grounded_support
    data["related_job_requirements"] = [
        value
        for value in suggestion.related_job_requirements
        if _grounded(value, job_corpus)
    ]
    if suggestion.decision == "keep":
        data["suggested"] = None
        data["expected_benefit"] = None
    elif _is_near_synonym_rewrite(suggestion) or not _benefit_is_specific(
        suggestion
    ):
        data["decision"] = "keep"
        data["suggested"] = None
        data["expected_benefit"] = None
    return ResumeSuggestion.model_validate(data)


def _candidate_skill_for(candidate: CandidateProfile, skill: str) -> str | None:
    values = [
        *candidate.skills.programming_languages,
        *candidate.skills.frameworks,
        *candidate.skills.tools,
        *candidate.skills.databases,
        *candidate.skills.other,
        *candidate.languages,
        *candidate.certifications,
    ]
    return next((value for value in values if _texts_overlap(value, skill)), None)


def _default_keep_suggestions(
    candidate: CandidateProfile, match: MatchResult
) -> list[ResumeSuggestion]:
    keeps: list[ResumeSuggestion] = []
    for matched in match.matched_skills:
        evidence = _candidate_skill_for(candidate, matched.skill)
        if not evidence:
            continue
        keeps.append(
            ResumeSuggestion(
                section="skills",
                source_name="技能",
                decision="keep",
                original=evidence,
                reason=f"该信息已清楚对应岗位的“{matched.job_requirement}”要求。",
                supported_by=[evidence],
                related_job_requirements=[matched.job_requirement],
            )
        )
    return keeps


def _normalize_keywords(
    keywords: list[KeywordSuggestion],
    *,
    candidate: CandidateProfile,
    match: MatchResult,
    candidate_corpus: list[str],
) -> list[KeywordSuggestion]:
    missing = {normalize_skill(item.skill): item.skill for item in match.missing_skills}
    matched = {
        normalize_skill(item.skill): item.resume_evidence for item in match.matched_skills
    }
    normalized: list[KeywordSuggestion] = []
    seen: set[str] = set()
    for item in keywords:
        key = normalize_skill(item.keyword)
        if not key or key in seen:
            continue
        if key in missing:
            normalized.append(
                KeywordSuggestion(
                    keyword=missing[key],
                    status="gap_do_not_add",
                    evidence=None,
                    guidance="当前缺少简历证据，请先学习或实践，不要直接写入简历。",
                )
            )
        elif item.status == "can_emphasize":
            if item.evidence and _grounded(item.evidence, candidate_corpus):
                normalized.append(item)
            else:
                evidence = matched.get(key) or _candidate_skill_for(candidate, item.keyword)
                if evidence and _grounded(evidence, candidate_corpus):
                    normalized.append(
                        KeywordSuggestion(
                            keyword=item.keyword,
                            status="covered",
                            evidence=evidence,
                            guidance="已覆盖，无需重复堆叠。",
                        )
                    )
        elif item.status == "covered":
            evidence = item.evidence or matched.get(key) or _candidate_skill_for(
                candidate, item.keyword
            )
            if evidence and _grounded(evidence, candidate_corpus):
                normalized.append(
                    KeywordSuggestion(
                        keyword=item.keyword,
                        status="covered",
                        evidence=evidence,
                        guidance="已覆盖，无需重复堆叠。",
                    )
                )
        else:
            normalized.append(
                KeywordSuggestion(
                    keyword=item.keyword,
                    status="gap_do_not_add",
                    evidence=None,
                    guidance="当前缺少简历证据，请先学习或实践，不要直接写入简历。",
                )
            )
        seen.add(key)

    for key, skill in missing.items():
        if key not in seen:
            normalized.append(
                KeywordSuggestion(
                    keyword=skill,
                    status="gap_do_not_add",
                    evidence=None,
                    guidance="当前缺少简历证据，请先学习或实践，不要直接写入简历。",
                )
            )
    return normalized


def normalize_optimization_result(
    raw: ResumeOptimizationResult,
    *,
    candidate: CandidateProfile,
    job: JobProfile,
    match: MatchResult,
) -> ResumeOptimizationResult:
    """Apply deterministic fact and no-forced-rewrite guardrails."""
    candidate_data = candidate.model_dump(mode="json", exclude={"personal_info"})
    candidate_corpus = list(_walk_strings(candidate_data))
    job_corpus = list(_walk_strings(job.model_dump(mode="json")))
    allowed_sources = _allowed_source_names(candidate)
    missing_skills = [item.skill for item in match.missing_skills]
    protected_gap_keywords = [
        item.keyword
        for item in raw.keyword_suggestions
        if item.status == "gap_do_not_add"
    ]

    grouped: dict[str, list[ResumeSuggestion]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for item in raw.suggestions:
        validated = _postprocess_suggestion(
            item,
            allowed_sources=allowed_sources,
            candidate_corpus=candidate_corpus,
            job_corpus=job_corpus,
            missing_skills=[*missing_skills, *protected_gap_keywords],
        )
        if validated is None:
            continue
        key = (
            validated.decision,
            _compact(validated.source_name),
            _compact(validated.original),
        )
        if key in seen:
            continue
        grouped[validated.decision].append(validated)
        seen.add(key)

    if len(grouped["keep"]) < 3:
        for keep in _default_keep_suggestions(candidate, match):
            key = (keep.decision, _compact(keep.source_name), _compact(keep.original))
            if key not in seen:
                grouped["keep"].append(keep)
                seen.add(key)
            if len(grouped["keep"]) >= 3:
                break

    suggestions = [
        *grouped["keep"][:MAX_KEEP_SUGGESTIONS],
        *grouped["optional"][:MAX_SUGGESTIONS_PER_CHANGE_DECISION],
        *grouped["recommended"][:MAX_SUGGESTIONS_PER_CHANGE_DECISION],
    ]
    keywords = _normalize_keywords(
        raw.keyword_suggestions,
        candidate=candidate,
        match=match,
        candidate_corpus=candidate_corpus,
    )
    gaps: list[str] = []
    for value in [*[item.skill for item in match.missing_skills], *match.gaps]:
        if value and value not in gaps:
            gaps.append(value)

    recommended_count = sum(item.decision == "recommended" for item in suggestions)
    optional_count = sum(item.decision == "optional" for item in suggestions)
    if recommended_count == 0:
        summary = "当前简历整体表达已经较成熟，无需大范围修改。"
        if optional_count:
            summary += f"另有 {optional_count} 项可选优化，可按需要采用。"
    else:
        summary = (
            f"建议优先处理 {recommended_count} 项有明确岗位收益的表达，"
            "其余清晰、真实且匹配的内容保持不变。"
        )

    return ResumeOptimizationResult(
        summary=summary,
        suggestions=suggestions,
        keyword_suggestions=keywords,
        capability_gaps=gaps,
        warnings=["不要添加未掌握的技能，也不要虚构经历、职责或成果。"],
    )


class ResumeOptimizationService:
    """Generate PRO suggestions, then enforce facts and safe keyword handling."""

    MODEL_TIER = ModelTier.PRO

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def analyze(
        self,
        candidate: CandidateProfile,
        job: JobProfile,
        match: MatchResult,
    ) -> ResumeOptimizationResult:
        prompt = build_resume_optimization_prompt(
            candidate_data=candidate.model_dump(
                mode="json", exclude={"personal_info"}
            ),
            job_data=job.model_dump(mode="json"),
            match_data=_privacy_safe_match_data(match, candidate),
        )
        logger.info(
            "Resume optimization started: model_tier=PRO suggestion_input_counts=%s "
            "user_message_length=%d",
            {
                "experience": len(candidate.experience),
                "projects": len(candidate.projects),
                "matched": len(match.matched_skills),
                "partial": len(match.partial_matches),
                "missing": len(match.missing_skills),
            },
            len(prompt),
        )
        raw = generate_structured_output(
            self.client,
            system_prompt=RESUME_OPTIMIZATION_SYSTEM_PROMPT,
            user_prompt=prompt,
            model_type=ResumeOptimizationResult,
            model_tier=self.MODEL_TIER,
            temperature=OPTIMIZATION_TEMPERATURE,
            thinking=OPTIMIZATION_THINKING,
            repair_with_original_input=False,
            repair_constraints=(
                "Repair format and schema only. Do not add or change suggestions, "
                "evidence, decisions, keywords, gaps, or judgments."
            ),
            repair_empty_response=False,
        )
        result = normalize_optimization_result(
            raw, candidate=candidate, job=job, match=match
        )
        logger.info(
            "Resume optimization completed: keep=%d optional=%d recommended=%d "
            "keywords=%d gaps=%d",
            sum(item.decision == "keep" for item in result.suggestions),
            sum(item.decision == "optional" for item in result.suggestions),
            sum(item.decision == "recommended" for item in result.suggestions),
            len(result.keyword_suggestions),
            len(result.capability_gaps),
        )
        return result
