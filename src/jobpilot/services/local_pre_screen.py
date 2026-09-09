"""Conservative, deterministic rejection of only clearly unsuitable jobs."""

from __future__ import annotations

import re

from jobpilot.models import BatchJobInput, CandidateProfile
from jobpilot.models.fast_screening import LocalPreScreenResult, LocalScreeningDecision
from jobpilot.services.job_analyzer import MIN_JOB_DESCRIPTION_CHARACTERS, normalize_job_description


_EARLY_CAREER = re.compile(r"实习|intern|应届|在校|student|graduate", re.IGNORECASE)
_SENIOR_REQUIREMENT = re.compile(
    r"(?:[3-9]|[1-9]\d)\s*(?:\+|年以上|年及以上|年经验)|资深|高级工程师|senior|staff engineer|lead engineer",
    re.IGNORECASE,
)
_STACKS = {
    "java_spring": ({"java", "spring", "spring boot", "springboot"}, 2),
    "frontend": ({"javascript", "typescript", "react", "vue", "前端"}, 2),
    "design": ({"figma", "photoshop", "illustrator", "视觉设计", "ui设计"}, 2),
    "embedded": ({"c++", "嵌入式", "stm32", "rtos"}, 2),
}
_CERTIFICATES = ("注册会计师", "法律职业资格", "医师资格", "教师资格证")


def _candidate_text(candidate: CandidateProfile) -> str:
    values: list[str] = []
    skills = candidate.skills
    values.extend(
        [
            *skills.programming_languages,
            *skills.frameworks,
            *skills.tools,
            *skills.databases,
            *skills.other,
            *candidate.certifications,
        ]
    )
    for item in candidate.experience:
        values.extend(filter(None, [item.position, item.description, *item.highlights, *item.technologies]))
    for item in candidate.projects:
        values.extend(filter(None, [item.name, item.description, *item.highlights, *item.technologies]))
    return " ".join(values).casefold()


def _is_early_career(candidate: CandidateProfile) -> bool:
    if not candidate.experience:
        return True
    experience_text = " ".join(
        filter(None, (item.position for item in candidate.experience))
    )
    return bool(experience_text) and bool(_EARLY_CAREER.search(experience_text))


class LocalPreScreenService:
    """Reject only invalid JDs and explicit, evidenced hard mismatches."""

    def assess(
        self, candidate: CandidateProfile, job_input: BatchJobInput
    ) -> LocalPreScreenResult:
        jd = normalize_job_description(job_input.jd_text)
        if len(jd) < MIN_JOB_DESCRIPTION_CHARACTERS:
            return LocalPreScreenResult(
                decision=LocalScreeningDecision.REJECT,
                reason="岗位描述过短，无法形成可靠判断。",
                hard_requirement_risks=["JD 信息不足"],
            )

        candidate_text = _candidate_text(candidate)
        jd_lower = jd.casefold()
        if _is_early_career(candidate) and _SENIOR_REQUIREMENT.search(jd):
            return LocalPreScreenResult(
                decision=LocalScreeningDecision.REJECT,
                reason="岗位明确要求资深或三年以上经验，与当前早期职业阶段明显不符。",
                hard_requirement_risks=["工作年限硬门槛"],
            )

        for stack_name, (markers, minimum) in _STACKS.items():
            required = [marker for marker in markers if marker in jd_lower]
            evidence = [marker for marker in markers if marker in candidate_text]
            if len(required) >= minimum and not evidence:
                return LocalPreScreenResult(
                    decision=LocalScreeningDecision.REJECT,
                    reason=f"岗位以 {stack_name.replace('_', '/')} 为核心，简历中没有相关方向证据。",
                    hard_requirement_risks=["核心技术方向明显不同"],
                )

        for certificate in _CERTIFICATES:
            explicit_certificate = re.search(
                rf"(?:必须|持有|具备).{{0,12}}{re.escape(certificate)}|"
                rf"{re.escape(certificate)}.{{0,8}}(?:必须|硬性|证书)",
                jd,
            )
            if explicit_certificate:
                if certificate.casefold() not in candidate_text:
                    return LocalPreScreenResult(
                        decision=LocalScreeningDecision.REJECT,
                        reason=f"岗位明确要求{certificate}，简历中未找到对应证据。",
                        hard_requirement_risks=[f"缺少{certificate}"],
                    )

        if re.search(r"必须|硬性|仅限|要求", jd) and not any(
            skill in candidate_text for skill in ("python", "java", "sql", "javascript", "c++")
        ):
            return LocalPreScreenResult(
                decision=LocalScreeningDecision.UNCERTAIN,
                reason="岗位包含硬性要求，但本地规则无法可靠确认是否满足。",
                hard_requirement_risks=[],
            )
        return LocalPreScreenResult(
            decision=LocalScreeningDecision.PASS,
            reason="未发现足以直接淘汰的明确硬门槛。",
            hard_requirement_risks=[],
        )
