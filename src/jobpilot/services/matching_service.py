"""Hybrid exact/semantic resume-to-job matching orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

from jobpilot.llm import LLMClient, ModelTier
from jobpilot.llm.structured_output import RequestTelemetry, generate_structured_output
from jobpilot.models import (
    CandidateProfile,
    ImprovementPriority,
    JobProfile,
    MatchedSkill,
    MatchEvidence,
    MatchResult,
    MissingSkill,
    PartialMatch,
    SemanticMatchAnalysis,
    SkillSemanticAnalysis,
)
from jobpilot.prompts.matching_analysis import (
    MATCHING_ANALYSIS_SYSTEM_PROMPT,
    build_matching_analysis_prompt,
)
from jobpilot.services.matching_score import calculate_score_breakdown


logger = logging.getLogger(__name__)
MATCHING_TEMPERATURE = 0.0
MATCHING_THINKING = False
MATCHING_MAX_TOKENS = 4000

_SKILL_ALIASES = {
    "python3": "python",
    "大模型api": "llmapi",
    "大语言模型api": "llmapi",
    "largelanguagemodelapi": "llmapi",
    "openai兼容api": "openaicompatibleapi",
    "prompt工程": "promptengineering",
}
_CLASSIFICATION_RANK = {"missing": 0, "partial": 1, "matched": 2}


@dataclass(frozen=True, slots=True)
class _SkillOutcome:
    skill: str
    importance: str
    classification: str
    evidence: str | None
    reason: str
    match_type: str | None


def normalize_skill(skill: str) -> str:
    """Normalize a skill for conservative exact matching."""
    normalized = re.sub(r"[^\w+#]", "", skill.casefold(), flags=re.UNICODE)
    return _SKILL_ALIASES.get(normalized, normalized)


def candidate_skill_evidence(profile: CandidateProfile) -> list[str]:
    """Collect explicitly named candidate capabilities for exact matching."""
    values = [
        *profile.skills.programming_languages,
        *profile.skills.frameworks,
        *profile.skills.tools,
        *profile.skills.databases,
        *profile.skills.other,
        *profile.certifications,
        *profile.languages,
    ]
    for experience in profile.experience:
        values.extend(experience.technologies)
    for project in profile.projects:
        values.extend(project.technologies)

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_skill(value)
        if key and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _exact_evidence(job_skill: str, candidate_skills: list[str]) -> str | None:
    job_key = normalize_skill(job_skill)
    return next(
        (value for value in candidate_skills if normalize_skill(value) == job_key),
        None,
    )


def _best_semantic_signal(
    job_skill: str, signals: list[SkillSemanticAnalysis]
) -> SkillSemanticAnalysis | None:
    matching = [
        signal
        for signal in signals
        if normalize_skill(signal.job_skill) == normalize_skill(job_skill)
    ]
    if not matching:
        return None
    return max(matching, key=lambda item: _CLASSIFICATION_RANK[item.classification])


def _safe_semantic_classification(
    job_skill: str, signal: SkillSemanticAnalysis
) -> str:
    """Apply small deterministic guardrails to known adjacent technologies."""
    if signal.classification == "missing" or not signal.candidate_evidence:
        return "missing"

    job_key = normalize_skill(job_skill)
    evidence_key = normalize_skill(signal.candidate_evidence)
    if job_key == "fastapi" and "streamlit" in evidence_key and "fastapi" not in evidence_key:
        return "missing"
    if job_key == "langgraph" and "langgraph" not in evidence_key:
        if "agentworkflow" in evidence_key or "agent工作流" in evidence_key:
            return "partial"
    return signal.classification


def _skill_outcomes(
    candidate: CandidateProfile,
    job: JobProfile,
    semantic: SemanticMatchAnalysis,
) -> list[_SkillOutcome]:
    candidate_skills = candidate_skill_evidence(candidate)
    outcomes: list[_SkillOutcome] = []
    for importance, job_skills in (
        ("required", job.required_skills),
        ("preferred", job.preferred_skills),
    ):
        for skill in job_skills:
            exact = _exact_evidence(skill, candidate_skills)
            if exact:
                outcomes.append(
                    _SkillOutcome(
                        skill=skill,
                        importance=importance,
                        classification="matched",
                        evidence=exact,
                        reason="简历中存在标准化后完全一致的技能证据。",
                        match_type="exact",
                    )
                )
                continue

            signal = _best_semantic_signal(skill, semantic.skill_analysis)
            if signal is None:
                outcomes.append(
                    _SkillOutcome(
                        skill=skill,
                        importance=importance,
                        classification="missing",
                        evidence=None,
                        reason=f"当前简历中未找到与“{skill}”相关的证据。",
                        match_type=None,
                    )
                )
                continue

            classification = _safe_semantic_classification(skill, signal)
            outcomes.append(
                _SkillOutcome(
                    skill=skill,
                    importance=importance,
                    classification=classification,
                    evidence=(
                        signal.candidate_evidence
                        if classification != "missing"
                        else None
                    ),
                    reason=signal.reason,
                    match_type=(
                        "semantic"
                        if classification == "matched"
                        else "partial" if classification == "partial" else None
                    ),
                )
            )
    return outcomes


def _candidate_prompt_data(profile: CandidateProfile) -> dict[str, Any]:
    """Exclude personal contact fields that cannot improve semantic matching."""
    return profile.model_dump(mode="json", exclude={"personal_info"})


def _job_other_requirements(job: JobProfile) -> list[str]:
    values: list[str] = []
    if job.education_requirements:
        values.append(job.education_requirements)
    values.extend(job.language_requirements)
    values.extend(job.other_requirements)
    return values


def _classification_for_requirement(
    requirement: str, semantic: SemanticMatchAnalysis
) -> tuple[str, str | None, str]:
    signal = next(
        (
            item
            for item in semantic.education_other_analysis
            if item.job_requirement.strip().casefold()
            == requirement.strip().casefold()
        ),
        None,
    )
    if signal is None or (
        signal.classification != "missing" and not signal.candidate_evidence
    ):
        return (
            "missing",
            None,
            f"当前简历中未找到与“{requirement}”相关的证据。",
        )
    return signal.classification, signal.candidate_evidence, signal.reason


def _unique_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    return result


class MatchingService:
    """Combine conservative Python matching, PRO signals, and fixed scoring."""

    MODEL_TIER = ModelTier.PRO

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def analyze(
        self,
        candidate: CandidateProfile,
        job: JobProfile,
        *,
        telemetry_callback: RequestTelemetry | None = None,
    ) -> MatchResult:
        candidate_skills = candidate_skill_evidence(candidate)
        all_job_skills = [*job.required_skills, *job.preferred_skills]
        exact_skills = [
            skill
            for skill in all_job_skills
            if _exact_evidence(skill, candidate_skills) is not None
        ]
        unresolved_skills = [
            skill for skill in all_job_skills if skill not in exact_skills
        ]
        candidate_data = _candidate_prompt_data(candidate)
        job_data = job.model_dump(mode="json")
        prompt = build_matching_analysis_prompt(
            candidate_data=candidate_data,
            job_data=job_data,
            exact_skills=exact_skills,
            unresolved_skills=unresolved_skills,
        )
        logger.info(
            "Matching analysis started: model_tier=PRO candidate_section_counts=%s "
            "job_section_counts=%s user_message_length=%d",
            {
                "education": len(candidate.education),
                "skills": len(candidate_skills),
                "experience": len(candidate.experience),
                "projects": len(candidate.projects),
            },
            {
                "responsibilities": len(job.responsibilities),
                "required_skills": len(job.required_skills),
                "preferred_skills": len(job.preferred_skills),
            },
            len(prompt),
        )
        semantic = generate_structured_output(
            self.client,
            system_prompt=MATCHING_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=prompt,
            model_type=SemanticMatchAnalysis,
            model_tier=self.MODEL_TIER,
            temperature=MATCHING_TEMPERATURE,
            thinking=MATCHING_THINKING,
            repair_with_original_input=False,
            repair_constraints=(
                "Do not add or change semantic classifications, relevance judgments, "
                "evidence, strengths, gaps, or priorities. Remove every numeric score "
                "or score field. If a field has no existing information, use null or []."
            ),
            repair_empty_response=False,
            telemetry_callback=telemetry_callback,
            max_tokens=MATCHING_MAX_TOKENS,
        )

        outcomes = _skill_outcomes(candidate, job, semantic)
        other_requirements = _job_other_requirements(job)
        other_assessments = [
            (requirement, *_classification_for_requirement(requirement, semantic))
            for requirement in other_requirements
        ]
        experience_applicable = bool(
            job.responsibilities or job.experience_requirements
        )
        projects_applicable = bool(
            job.responsibilities or job.required_skills or job.preferred_skills
        )
        scores = calculate_score_breakdown(
            required_classifications=[
                item.classification
                for item in outcomes
                if item.importance == "required"
            ],
            preferred_classifications=[
                item.classification
                for item in outcomes
                if item.importance == "preferred"
            ],
            experience_relevances=[
                item.relevance for item in semantic.experience_relevance
            ],
            project_relevances=[
                item.relevance for item in semantic.project_relevance
            ],
            education_other_classifications=[
                classification
                for _, classification, _, _ in other_assessments
            ],
            experience_applicable=experience_applicable,
            projects_applicable=projects_applicable,
            education_other_applicable=bool(other_requirements),
        )

        matched_skills = [
            MatchedSkill(
                skill=item.skill,
                resume_evidence=item.evidence or "",
                job_requirement=item.skill,
                match_type=item.match_type or "semantic",
            )
            for item in outcomes
            if item.classification == "matched"
        ]
        partial_matches = [
            PartialMatch(
                job_requirement=item.skill,
                resume_evidence=item.evidence or "当前简历中未找到直接证据",
                gap=item.reason,
            )
            for item in outcomes
            if item.classification == "partial"
        ]
        missing_skills = [
            MissingSkill(
                skill=item.skill,
                importance=item.importance,
                reason=(
                    item.reason
                    if "当前简历" in item.reason
                    else f"当前简历中未找到与“{item.skill}”直接对应的证据。"
                ),
            )
            for item in outcomes
            if item.classification == "missing"
        ]

        evidence = [
            MatchEvidence(
                category="技能",
                job_requirement=item.skill,
                resume_evidence=item.evidence or "未找到相关证据",
                assessment=item.reason,
            )
            for item in outcomes
        ]
        evidence.extend(
            MatchEvidence(
                category="工作经历",
                job_requirement=item.job_requirement,
                resume_evidence=item.candidate_evidence or "未找到相关证据",
                assessment=item.assessment,
            )
            for item in semantic.experience_relevance
        )
        evidence.extend(
            MatchEvidence(
                category="项目经历",
                job_requirement=item.job_requirement,
                resume_evidence=item.candidate_evidence or "未找到相关证据",
                assessment=item.assessment,
            )
            for item in semantic.project_relevance
        )
        evidence.extend(
            MatchEvidence(
                category="教育及其他",
                job_requirement=requirement,
                resume_evidence=candidate_evidence or "未找到相关证据",
                assessment=reason,
            )
            for requirement, _, candidate_evidence, reason in other_assessments
        )

        generated_gaps = [item.reason for item in missing_skills]
        generated_gaps.extend(item.gap for item in partial_matches)
        gaps = _unique_text([*semantic.gaps, *generated_gaps])

        priorities = list(semantic.improvement_priorities)
        existing_actions = {item.action.casefold() for item in priorities}
        for item in missing_skills:
            action = f"补充 {item.skill} 相关学习或实践证据"
            if action.casefold() not in existing_actions:
                priorities.append(
                    ImprovementPriority(
                        priority="high" if item.importance == "required" else "medium",
                        action=action,
                        reason=item.reason,
                    )
                )
                existing_actions.add(action.casefold())

        strengths = _unique_text(
            [
                *semantic.strengths,
                *[
                    f"简历中已体现 {item.skill} 相关能力"
                    for item in matched_skills
                ],
            ]
        )
        result = MatchResult(
            scores=scores,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            partial_matches=partial_matches,
            strengths=strengths,
            gaps=gaps,
            evidence=evidence,
            improvement_priorities=priorities,
            summary=semantic.summary,
        )
        logger.info(
            "Matching result scored: score_breakdown=%s",
            json.dumps(result.scores.model_dump(mode="json"), sort_keys=True),
        )
        return result
